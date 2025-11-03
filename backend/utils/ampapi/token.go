package ampapi

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
)

const CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"


func findJwtInText(text string) string {
	
	jwtRegex := regexp.MustCompile(`eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+`)
	return jwtRegex.FindString(text)
}

func toAbs(u string) string {
	if strings.HasPrefix(u, "http://") || strings.HasPrefix(u, "https://") {
		return u
	}
	if strings.HasPrefix(u, "/") {
		return "https://music.apple.com" + u
	}
	return "https://music.apple.com/" + u
}


func collectCandidates(html string) []string {
	uniqueUrls := make(map[string]struct{})

	regexes := []*regexp.Regexp{
		regexp.MustCompile(`(?:src|href|data-src)=["'](/assets/index~[a-z0-9]+\.js)["']`),
		regexp.MustCompile(`(?:src|href|data-src)=["'](/assets/index-legacy~[a-z0-9]+\.js)["']`),
		regexp.MustCompile(`(?:src|href|data-src)=["'](/assets/[A-Za-z0-9/_\-.]+\.js)["']`),
	}

	for _, rx := range regexes {
		matches := rx.FindAllStringSubmatch(html, -1)
		for _, match := range matches {
			if len(match) > 1 {
				uniqueUrls[match[1]] = struct{}{}
			}
		}
	}

	var candidates []string
	for url := range uniqueUrls {
		candidates = append(candidates, toAbs(url))
	}

	return candidates
}


func score(s string) int {
	n := strings.ToLower(s)
	if strings.Contains(n, "index-legacy~") {
		return 0
	}
	if strings.Contains(n, "index~") {
		return 1
	}
	if strings.Contains(n, "app~") || strings.Contains(n, "main~") || strings.Contains(n, "bootstrap~") {
		return 2
	}
	return 3
}


func GetToken() (string, error) {

	jwtRegex := regexp.MustCompile(`^eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$`)
	envToken := os.Getenv("APPLE_DEV_TOKEN")
	if envToken == "" {
		envToken = os.Getenv("DEV_TOKEN")
	}
	if envToken != "" && jwtRegex.MatchString(envToken) {
		return envToken, nil
	}


	homeUrls := []string{
		"https://music.apple.com/us/browse",
		"https://music.apple.com/ca/home",
	}
	var homepageHtml string
	var lastErr error

	for _, u := range homeUrls {
		req, reqErr := http.NewRequest("GET", u, nil)
		if reqErr != nil {
			continue 
		}
		req.Header.Set("User-Agent", CHROME_USER_AGENT)
		req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
		req.Header.Set("Accept-Language", "en-US,en;q=0.9")
		req.Header.Set("Cache-Control", "no-cache")

		resp, doErr := http.DefaultClient.Do(req)
		if doErr != nil {
			lastErr = doErr
			continue
		}

		if resp.StatusCode == http.StatusOK {
			body, readErr := io.ReadAll(resp.Body)
			resp.Body.Close()
			if readErr != nil {
				lastErr = readErr
				continue
			}
			homepageHtml = string(body)
			if homepageHtml != "" {
				lastErr = nil
				break
			}
		} else {
			resp.Body.Close()
			lastErr = fmt.Errorf("received status code %d from %s", resp.StatusCode, u)
		}
	}

	if homepageHtml == "" {
		return "", fmt.Errorf("failed to load Apple Music homepage for token discovery: %w", lastErr)
	}


	if inlineToken := findJwtInText(homepageHtml); inlineToken != "" {
		return inlineToken, nil
	}


	candidates := collectCandidates(homepageHtml)
	sort.Slice(candidates, func(i, j int) bool {
		return score(candidates[i]) < score(candidates[j])
	})


	limit := 12
	if len(candidates) < limit {
		limit = len(candidates)
	}
	topCandidates := candidates[:limit]

	for _, url := range topCandidates {
		req, reqErr := http.NewRequest("GET", url, nil)
		if reqErr != nil {
			continue
		}
		req.Header.Set("User-Agent", CHROME_USER_AGENT)

		resp, doErr := http.DefaultClient.Do(req)
		if doErr != nil {
			continue
		}

		if resp.StatusCode == http.StatusOK {
			jsBody, readErr := io.ReadAll(resp.Body)
			resp.Body.Close()
			if readErr != nil {
				continue
			}
			if token := findJwtInText(string(jsBody)); token != "" {
				return token, nil
			}
		} else {
			resp.Body.Close()
		}
	}

	return "", errors.New("developer token not found in current assets; set APPLE_DEV_TOKEN/DEV_TOKEN to bypass scraping")
}