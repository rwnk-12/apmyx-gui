package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"main/utils/ampapi"
	"main/utils/lyrics"
	"main/utils/runv2"
	"main/utils/runv3"
	"main/utils/structs"
	"main/utils/task"

	"github.com/grafov/m3u8"
	"github.com/zhaarey/go-mp4tag"
	"gopkg.in/yaml.v2"
)

var (
	forbiddenNames    = regexp.MustCompile(`[/\\<>:"|?*]`)
	codecPreference   string
	dl_song           bool
	dl_mv             bool
	json_output       bool
	resolve_artist    string
	Config            structs.ConfigSet
	counter           structs.Counter
	okDict            = make(map[string][]int)
	progressWriter    *bufio.Writer
	httpClient        *http.Client
	makeCuratorFolder = flag.Bool("make-curator-folder", false, "Create curator folder structure")
)

type ArtistMediaItem struct {
	ID         string          `json:"id"`
	Type       string          `json:"type"`
	Href       string          `json:"href"`
	Attributes AlbumAttributes `json:"attributes"`
}

type MusicVideoItem struct {
	ID         string               `json:"id"`
	Type       string               `json:"type"`
	Href       string               `json:"href"`
	Attributes MusicVideoAttributes `json:"attributes"`
}

type AlbumAttributes struct {
	ArtistName    string `json:"artistName"`
	Artwork       struct {
		URL string `json:"url"`
	} `json:"artwork"`
	IsCompilation bool   `json:"isCompilation"`
	Name          string `json:"name"`
	ReleaseDate   string `json:"releaseDate"`
	TrackCount    int    `json:"trackCount"`
	URL           string `json:"url"`
	IsSingle      bool   `json:"isSingle"`
}

type MusicVideoAttributes struct {
	ArtistName       string `json:"artistName"`
	Artwork          struct {
		URL string `json:"url"`
	} `json:"artwork"`
	Name             string `json:"name"`
	ReleaseDate      string `json:"releaseDate"`
	URL              string `json:"url"`
	DurationInMillis int    `json:"durationInMillis"`
}

type QualityInfo struct {
	Codec    string `json:"codec"`
	URL      string `json:"url"`
	Quality  string `json:"quality"`
	Group    string `json:"group"`
	Selected bool   `json:"selected"`
}
type TrackProbe struct {
	Index              int                  `json:"-"`
	TrackData          ampapi.TrackRespData `json:"trackData"`
	AvailableQualities []QualityInfo        `json:"availableQualities"`
	AvailableCodecs    []string             `json:"availableCodecs"`
}

type ProbeJob struct {
	Track      ampapi.TrackRespData
	Index      int
	Storefront string
	Language   string
	Token      string
}

func emitStreamInfo(trackNum int, totalTracks int, trackName string, streamGroup string) {
	// DEBUG: Print to console to see if this is being called
	fmt.Printf("DEBUG: emitStreamInfo called - track %d/%d, streamGroup='%s'\n", trackNum, totalTracks, streamGroup)

	if streamGroup == "" {
		fmt.Printf("DEBUG: streamGroup is empty, not emitting\n")
		return
	}

	progressData := map[string]interface{}{
		"type":        "trackstream",
		"tracknum":    trackNum,
		"totaltracks": totalTracks,
		"name":        trackName,
		"streamgroup": streamGroup,
	}

	jsonData, err := json.Marshal(progressData)
	if err == nil {
		fmt.Printf("DEBUG: Emitting JSON: AMDL_PROGRESS::%s\n", string(jsonData))
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", string(jsonData))
		progressWriter.Flush()
	} else {
		fmt.Printf("DEBUG: JSON marshal error: %v\n", err)
	}
}

func probeWorker(jobs <-chan ProbeJob, results chan<- TrackProbe, wg *sync.WaitGroup) {
	defer wg.Done()
	for job := range jobs {
		probeTrack(job.Track, job.Index, job.Storefront, job.Language, job.Token, results)
	}
}

func loadConfig() error {
	exePath, err := os.Executable()
	if err != nil {
		return err
	}
	configPath := filepath.Join(filepath.Dir(exePath), "config.yaml")

	data, err := os.ReadFile(configPath)
	if err != nil {
		data, err = os.ReadFile("config.yaml")
		if err != nil {
			return err
		}
	}

	err = yaml.Unmarshal(data, &Config)
	if err != nil {
		return err
	}
	if len(Config.Storefront) != 2 {
		Config.Storefront = "us"
	}
	if strings.TrimSpace(Config.MvSaveFolder) == "" {
		Config.MvSaveFolder = filepath.Join(Config.AlacSaveFolder, "Music Videos")
	}
	if reflect.ValueOf(Config.TagOptions).IsZero() {
		o := &Config.TagOptions
		o.WriteTitle = true
		o.WriteArtist = true
		o.WriteArtistSort = false
		o.WriteAlbum = true
		o.WriteAlbumSort = false
		o.WriteAlbumArtist = true
		o.WriteAlbumArtistSort = false
		o.WriteComposer = true
		o.WriteComposerSort = false
		o.WriteGenre = true
		o.WriteISRC = true
		o.WriteUPC = true
		o.WriteDate = true
		o.WriteCopyright = true
		o.WritePublisher = true
		o.WriteDiscTrack = true
		o.WriteLyrics = Config.EmbedLrc || Config.SaveLrcFile
		o.WriteCover = Config.EmbedCover
		o.DeleteSortOnWrite = true
		o.UseMp4BoxArtist = false
	}
	return nil
}

func LimitString(s string) string {
	if len([]rune(s)) > Config.LimitMax {
		return string([]rune(s)[:Config.LimitMax])
	}
	return s
}

func fileExists(path string) (bool, error) {
	f, err := os.Stat(path)
	if err == nil {
		return !f.IsDir(), nil
	} else if os.IsNotExist(err) {
		return false, nil
	}
	return false, err
}

func checkUrl(url string) (string, string) {
	pat := regexp.MustCompile(`^(?:https:\/\/(?:beta\.music|music|classical\.music)\.apple\.com\/(\w{2})(?:\/album|\/album\/.+))\/(?:id)?(\d[^\D]+)(?:$|\?)`)
	matches := pat.FindAllStringSubmatch(url, -1)
	if matches == nil {
		return "", ""
	}
	return matches[0][1], matches[0][2]
}

func checkUrlMv(url string) (string, string) {
	pat := regexp.MustCompile(`^(?:https:\/\/(?:beta\.music|music)\.apple\.com\/(\w{2})(?:\/music-video|\/music-video\/.+))\/(?:id)?(\d[^\D]+)(?:$|\?)`)
	matches := pat.FindAllStringSubmatch(url, -1)

	if matches == nil {
		return "", ""
	} else {
		return matches[0][1], matches[0][2]
	}
}

func checkUrlSong(url string) (string, string) {
	pat := regexp.MustCompile(`^(?:https:\/\/(?:beta\.music|music|classical\.music)\.apple\.com\/(\w{2})(?:\/song|\/song\/.+))\/(?:id)?(\d[^\D]+)(?:$|\?)`)
	matches := pat.FindAllStringSubmatch(url, -1)
	if matches == nil {
		return "", ""
	}
	return matches[0][1], matches[0][2]
}

func checkUrlArtist(url string) (string, string) {
	pat := regexp.MustCompile(`^(?:https:\/\/(?:beta\.music|music|classical\.music)\.apple\.com\/(\w{2})(?:\/artist|\/artist\/.+))\/(?:id)?(\d[^\D]+)(?:$|\?)`)
	matches := pat.FindAllStringSubmatch(url, -1)
	if matches == nil {
		return "", ""
	}
	return matches[0][1], matches[0][2]
}

func checkUrlPlaylist(url string) (string, string) {
	// First, try the original pattern for backwards compatibility
	originalPat := regexp.MustCompile(`^(?:https:\/\/(?:beta\.music|music|classical\.music)\.apple\.com\/(?:(\w{2})\/playlist|library\/playlist))\/(?:id)?((?:p|pl)\.[\w-]+)(?:$|\?)`)
	matches := originalPat.FindAllStringSubmatch(url, -1)
	if matches != nil {
		storefront := matches[0][1]
		if storefront == "" {
			storefront = Config.Storefront
		}
		return storefront, matches[0][2]
	}

	// If original pattern fails, try the new pattern for playlists with names
	newPat := regexp.MustCompile(`^(?:https:\/\/(?:beta\.music|music|classical\.music)\.apple\.com\/(\w{2})\/playlist\/[^\/]+\/)(?:id)?(pl\.[\w.-]+)(?:$|\?)`)
	matches = newPat.FindAllStringSubmatch(url, -1)
	if matches != nil {
		return matches[0][1], matches[0][2]
	}

	return "", ""
}

func getUrlSong(songUrl string, token string) (string, error) {
	storefront, songId := checkUrlSong(songUrl)
	manifest, err := ampapi.GetSongResp(storefront, songId, Config.Language, token)
	if err != nil {
		return "", err
	}
	albumId := manifest.Data[0].Relationships.Albums.Data[0].ID
	songAlbumUrl := fmt.Sprintf("https://music.apple.com/%s/album/1/%s?i=%s", storefront, albumId, songId)
	return songAlbumUrl, nil
}

func resolveArtistToJSON(artistUrl string, token string) (string, error) {
	storefront, artistId := checkUrlArtist(artistUrl)
	if storefront == "" || artistId == "" {
		return "", errors.New("invalid artist URL format")
	}

	var wg sync.WaitGroup
	var albumIDs, mvIDs []string
	var errAlbums, errMVs error

	wg.Add(2)

	go func() {
		defer wg.Done()
		albumIDs, errAlbums = fetchArtistRelationshipIDs(storefront, artistId, "albums", token)
	}()

	go func() {
		defer wg.Done()
		mvIDs, errMVs = fetchArtistRelationshipIDs(storefront, artistId, "music-videos", token)
	}()

	wg.Wait()

	if errAlbums != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not fetch albums for artist %s: %v\n", artistId, errAlbums)
	}
	if errMVs != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not fetch music videos for artist %s: %v\n", artistId, errMVs)
	}

	var albums, musicVideos []ArtistMediaItem
	var errFetchAlbums, errFetchMVs error

	wg.Add(2)

	go func() {
		defer wg.Done()
		albums, errFetchAlbums = fetchFullAlbumDetails(storefront, albumIDs, token)
	}()

	go func() {
		defer wg.Done()
		musicVideos, errFetchMVs = fetchFullMusicVideoDetails(storefront, mvIDs, token)
	}()

	wg.Wait()

	if errFetchAlbums != nil {
		return "", fmt.Errorf("failed to fetch full album details: %w", errFetchAlbums)
	}
	if errFetchMVs != nil {
		return "", fmt.Errorf("failed to fetch full music video details: %w", errFetchMVs)
	}

	combinedMedia := append(albums, musicVideos...)

	jsonBytes, err := json.Marshal(combinedMedia)
	if err != nil {
		return "", fmt.Errorf("failed to marshal artist media to JSON: %w", err)
	}

	return string(jsonBytes), nil
}

func fetchArtistRelationshipIDs(storefront, artistId, relationship, token string) ([]string, error) {
	var resultIDs []string
	offset := 0
	limit := 100

	for {
		apiURL := fmt.Sprintf("https://amp-api.music.apple.com/v1/catalog/%s/artists/%s/%s?limit=%d&offset=%d", storefront, artistId, relationship, limit, offset)
		req, err := http.NewRequest("GET", apiURL, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))
		req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
		req.Header.Set("Origin", "https://music.apple.com")

		resp, err := httpClient.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("API request failed with status: %s", resp.Status)
		}

		var pageData struct {
			Data []struct {
				ID string `json:"id"`
			} `json:"data"`
			Next string `json:"next"`
		}

		if err := json.NewDecoder(resp.Body).Decode(&pageData); err != nil {
			return nil, err
		}

		for _, item := range pageData.Data {
			resultIDs = append(resultIDs, item.ID)
		}

		if pageData.Next == "" {
			break
		}
		offset += limit
	}
	return resultIDs, nil
}

func fetchFullAlbumDetails(storefront string, albumIDs []string, token string) ([]ArtistMediaItem, error) {
	var allAlbums []ArtistMediaItem
	if len(albumIDs) == 0 {
		return allAlbums, nil
	}

	chunkSize := 100
	for i := 0; i < len(albumIDs); i += chunkSize {
		end := i + chunkSize
		if end > len(albumIDs) {
			end = len(albumIDs)
		}
		chunk := albumIDs[i:end]

		idsParam := strings.Join(chunk, ",")
		apiURL := fmt.Sprintf("https://amp-api.music.apple.com/v1/catalog/%s/albums?ids=%s", storefront, idsParam)

		req, err := http.NewRequest("GET", apiURL, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))
		req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
		req.Header.Set("Origin", "https://music.apple.com")

		resp, err := httpClient.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("batch album API request failed with status: %s", resp.Status)
		}

		var resultData struct {
			Data []ArtistMediaItem `json:"data"`
		}

		if err := json.NewDecoder(resp.Body).Decode(&resultData); err != nil {
			return nil, err
		}
		allAlbums = append(allAlbums, resultData.Data...)
	}

	return allAlbums, nil
}

func fetchFullMusicVideoDetails(storefront string, mvIDs []string, token string) ([]ArtistMediaItem, error) {
	var allMVs []ArtistMediaItem
	if len(mvIDs) == 0 {
		return allMVs, nil
	}

	chunkSize := 100
	for i := 0; i < len(mvIDs); i += chunkSize {
		end := i + chunkSize
		if end > len(mvIDs) {
			end = len(mvIDs)
		}
		chunk := mvIDs[i:end]

		idsParam := strings.Join(chunk, ",")
		apiURL := fmt.Sprintf("https://amp-api.music.apple.com/v1/catalog/%s/music-videos?ids=%s", storefront, idsParam)

		req, err := http.NewRequest("GET", apiURL, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))
		req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
		req.Header.Set("Origin", "https://music.apple.com")

		resp, err := httpClient.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("batch music video API request failed with status: %s", resp.Status)
		}

		var resultData struct {
			Data []MusicVideoItem `json:"data"`
		}

		if err := json.NewDecoder(resp.Body).Decode(&resultData); err != nil {
			return nil, err
		}

		for _, mv := range resultData.Data {
			adaptedItem := ArtistMediaItem{
				ID:   mv.ID,
				Type: mv.Type,
				Href: mv.Href,
				Attributes: AlbumAttributes{
					ArtistName:  mv.Attributes.ArtistName,
					Artwork:     mv.Attributes.Artwork,
					Name:        mv.Attributes.Name,
					ReleaseDate: mv.Attributes.ReleaseDate,
					URL:         mv.Attributes.URL,
					TrackCount:  1,
					IsSingle:    true,
				},
			}
			allMVs = append(allMVs, adaptedItem)
		}
	}

	return allMVs, nil
}

func writeCover(sanAlbumFolder, name string, url string) (string, error) {
	covPath := filepath.Join(sanAlbumFolder, name+"."+Config.CoverFormat)
	if Config.CoverFormat == "original" {
		ext := strings.Split(url, "/")[len(strings.Split(url, "/"))-2]
		ext = ext[strings.LastIndex(ext, ".")+1:]
		covPath = filepath.Join(sanAlbumFolder, name+"."+ext)
	}
	exists, err := fileExists(covPath)
	if err != nil {
		fmt.Println("Failed to check if cover exists.")
		return "", err
	}
	if exists {
		_ = os.Remove(covPath)
	}
	if Config.CoverFormat == "png" {
		re := regexp.MustCompile(`\{w\}x\{h\}`)
		parts := re.Split(url, 2)
		url = parts[0] + "{w}x{h}" + strings.Replace(parts[1], ".jpg", ".png", 1)
	}
	url = strings.Replace(url, "{w}x{h}", Config.CoverSize, 1)
	if Config.CoverFormat == "original" {
		url = strings.Replace(url, "is1-ssl.mzstatic.com/image/thumb", "a5.mzstatic.com/us/r1000/0", 1)
		url = url[:strings.LastIndex(url, "/")]
	}
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
	do, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer do.Body.Close()
	if do.StatusCode != http.StatusOK {
		return "", errors.New(do.Status)
	}
	f, err := os.Create(covPath)
	if err != nil {
		return "", err
	}
	defer f.Close()
	_, err = io.Copy(f, do.Body)
	if err != nil {
		return "", err
	}
	return covPath, nil
}

func writeLyrics(sanAlbumFolder, filename string, lrc string) error {
	lyricspath := filepath.Join(sanAlbumFolder, filename)
	f, err := os.Create(lyricspath)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(lrc)
	if err != nil {
		return err
	}
	return nil
}

func contains(slice []string, item string) bool {
	for _, v := range slice {
		if v == item {
			return true
		}
	}
	return false
}

func preferredCodec() string {
	if codecPreference != "" {
		up := strings.ToUpper(codecPreference)
		switch up {
		case "ATMOS":
			return "ATMOS"
		case "ALAC", "LOSSLESS", "HIRES", "HI-RES", "HIRES-LOSSLESS":
			return "ALAC"
		case "AAC", "AAC-LC", "AAC_STEREO", "AAC-STEREO", "AAC-BINAURAL", "AAC_DOWNMIX", "AAC-DOWNMIX":
			return "AAC"
		}
	}
	return "ALAC"
}

func isUserPlaylist(playlistId string) bool {
	return strings.HasPrefix(playlistId, "pl.u-")
}

func ripTrack(track *task.Track, token string, mediaUserToken string) {
	var err error
	counter.Total++

	if track.PreType == "playlists" && Config.UseSongInfoForPlaylist {
		err = track.GetAlbumData(token)
		if err != nil {
			fmt.Println("Warning: Failed to get original album data:", err)
			// Continue with playlist metadata instead of failing
		}
	}

	if track.Type == "music-videos" {
		if len(mediaUserToken) <= 50 {
			fmt.Fprintln(os.Stderr, "media-user-token is not set, skip MV dl")
			counter.Success++
			return
		}
		if _, err := exec.LookPath("mp4decrypt"); err != nil {
			fmt.Fprintln(os.Stderr, "mp4decrypt is not found, skip MV dl")
			counter.Success++
			return
		}

		artistFolderName := filepath.Base(filepath.Dir(track.SaveDir))
		if strings.TrimSpace(artistFolderName) == "" {
			artistFolderName = forbiddenNames.ReplaceAllString(track.Resp.Attributes.ArtistName, "_")
		}
		saveDir := filepath.Join(Config.MvSaveFolder, forbiddenNames.ReplaceAllString(artistFolderName, "_"))
		os.MkdirAll(saveDir, os.ModePerm)

		err := mvDownloader(track.ID, saveDir, token, track.Storefront, mediaUserToken, track, progressWriter)
		if err != nil {
			fmt.Fprintf(os.Stderr, "\u26A0 Failed to dl MV: %v\n", err)
			counter.Error++
			return
		}
		counter.Success++
		return
	}

	trackM3u8Url, actualCodec, streamGroup, err := getStreamForCodec(track.M3u8, preferredCodec())
	if err != nil {
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(`{"type": "track_skip", "name": "%s", "reason": "Not available in %s"}`, track.Resp.Attributes.Name, preferredCodec()))
		progressWriter.Flush()
		counter.Unavailable++
		return
	}
	track.Codec = actualCodec

	runner := "runv2"
	if actualCodec == "AAC" {
		isLC := strings.EqualFold(Config.AacType, "aac-lc") || strings.EqualFold(Config.AacType, "aac")
		if isLC {
			runner = "runv3"
		}
	}

	var totalBytes int64 = 0
	bandwidth, err := getBandwidthForStream(track.M3u8, actualCodec, streamGroup)
	if err == nil && track.Resp.Attributes.DurationInMillis > 0 {
		durationSeconds := float64(track.Resp.Attributes.DurationInMillis) / 1000.0
		totalBytes = int64((float64(bandwidth) / 8.0) * durationSeconds)
	}

	progressData := map[string]interface{}{
		"type":         "track_start",
		"track_num":    track.TaskNum,
		"total_tracks": track.TaskTotal,
		"name":         track.Resp.Attributes.Name,
		"codec":        actualCodec,
		"runner":       runner,
		"total_bytes":  totalBytes,
	}
	if track.PreType == "playlists" && track.IsUserPlaylist {
		progressData["isUserPlaylist"] = true
	}
	jsonData, _ := json.Marshal(progressData)
	fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", string(jsonData))
	progressWriter.Flush()

	if track.PreType == "playlists" && Config.UseSongInfoForPlaylist {
		track.GetAlbumData(token)
	}

	baseSaveFolder := ""
	switch actualCodec {
	case "ATMOS":
		baseSaveFolder = Config.AtmosSaveFolder
	case "AAC":
		baseSaveFolder = Config.AacSaveFolder
	default:
		baseSaveFolder = Config.AlacSaveFolder
	}
	albumFolderName := filepath.Base(track.SaveDir)
	artistFolderName := filepath.Base(filepath.Dir(track.SaveDir))
	track.SaveDir = filepath.Join(baseSaveFolder, artistFolderName, albumFolderName)
	os.MkdirAll(track.SaveDir, os.ModePerm)

	var Quality string
	if strings.Contains(Config.SongFileFormat, "Quality") {
		_, Quality, err = extractMedia(track.M3u8, true)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to extract quality from manifest.\n %v\n", err)
		}
	}
	track.Quality = Quality

	stringsToJoin := []string{}
	if track.Resp.Attributes.IsAppleDigitalMaster {
		if Config.AppleMasterChoice != "" {
			stringsToJoin = append(stringsToJoin, Config.AppleMasterChoice)
		}
	}
	if track.Resp.Attributes.ContentRating == "explicit" {
		if Config.ExplicitChoice != "" {
			stringsToJoin = append(stringsToJoin, Config.ExplicitChoice)
		}
	}
	if track.Resp.Attributes.ContentRating == "clean" {
		if Config.CleanChoice != "" {
			stringsToJoin = append(stringsToJoin, Config.CleanChoice)
		}
	}
	Tag_string := strings.Join(stringsToJoin, " ")

	songName := strings.NewReplacer(
		"{SongId}", track.ID,
		"{SongNumber}", fmt.Sprintf("%02d", track.TaskNum),
		"{SongName}", LimitString(track.Resp.Attributes.Name),
		"{DiscNumber}", fmt.Sprintf("%0d", track.Resp.Attributes.DiscNumber),
		"{TrackNumber}", fmt.Sprintf("%0d", track.Resp.Attributes.TrackNumber),
		"{Quality}", Quality,
		"{Tag}", Tag_string,
		"{Codec}", track.Codec,
	).Replace(Config.SongFileFormat)

	filename := fmt.Sprintf("%s.m4a", forbiddenNames.ReplaceAllString(songName, "_"))
	track.SaveName = filename
	trackPath := filepath.Join(track.SaveDir, track.SaveName)
	lrcFilename := fmt.Sprintf("%s.%s", forbiddenNames.ReplaceAllString(songName, "_"), Config.LrcFormat)

	var lrc string = ""
	if Config.EmbedLrc || Config.SaveLrcFile {
		lrcStr, err := lyrics.Get(track.Storefront, track.ID, Config.LrcType, Config.Language, Config.LrcFormat, token, mediaUserToken)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
		} else {
			if Config.SaveLrcFile {
				err := writeLyrics(track.SaveDir, lrcFilename, lrcStr)
				if err != nil {
					fmt.Fprintln(os.Stderr, "Failed to write lyrics")
				}
			}
			if Config.EmbedLrc {
				lrc = lrcStr
			}
		}
	}

	exists, err := fileExists(trackPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Failed to check if track exists.")
	}
	if exists {
		fmt.Fprintln(os.Stderr, "Track already exists locally.")
		counter.Success++
		okDict[track.PreID] = append(okDict[track.PreID], track.TaskNum)
		return
	}

	if runner == "runv3" {
		_, err = runv3.Run(track.ID, trackPath, token, mediaUserToken, false)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to run v3: %v\n", err)
			counter.Error++
			return
		}
	} else {
		err = runv2.Run(track.ID, trackM3u8Url, trackPath, Config)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to run v2: %v\n", err)
			counter.Error++
			return
		}
	}

	tags := []string{
		"tool=",
	}
	if Config.TagOptions.UseMp4BoxArtist && Config.TagOptions.WriteArtist {
		tags = append(tags, fmt.Sprintf("artist=%s", track.Resp.Attributes.ArtistName))
	}
	if Config.TagOptions.WriteCover && Config.EmbedCover {
		if (strings.Contains(track.PreID, "pl.") || strings.Contains(track.PreID, "ra.")) && Config.DlAlbumcoverForPlaylist {
			track.CoverPath, err = writeCover(track.SaveDir, track.ID, track.Resp.Attributes.Artwork.URL)
			if err != nil {
				fmt.Fprintln(os.Stderr, "Failed to write cover.")
			}
		}
		tags = append(tags, fmt.Sprintf("cover=%s", track.CoverPath))
	}
	tagsString := strings.Join(tags, ":")
	cmd := exec.Command("MP4Box", "-itags", tagsString, trackPath)
	if err := cmd.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Embed failed: %v\n", err)
		counter.Error++
		return
	}
	if (strings.Contains(track.PreID, "pl.") || strings.Contains(track.PreID, "ra.")) && Config.DlAlbumcoverForPlaylist {
		if err := os.Remove(track.CoverPath); err != nil {
			fmt.Fprintf(os.Stderr, "Error deleting file: %s\n", track.CoverPath)
			counter.Error++
			return
		}
	}
	track.SavePath = trackPath
	err = writeMP4Tags(track, lrc)
	if err != nil {
		fmt.Fprintf(os.Stderr, "\u26A0 Failed to write tags in media: %v\n", err)
		counter.Unavailable++
		return
	}

	fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(
		`{"type":"track_complete","track_num":%d,"total_tracks":%d,"name":"%s"}`,
		track.TaskNum, track.TaskTotal, track.Resp.Attributes.Name,
	))
	progressWriter.Flush()

	counter.Success++
	okDict[track.PreID] = append(okDict[track.PreID], track.TaskNum)
}

func probeTrack(track ampapi.TrackRespData, index int, storefront, language, token string, resultsChan chan<- TrackProbe) {
	m3u8Url := ""
	manifest, err := ampapi.GetSongResp(storefront, track.ID, language, token)
	if err == nil && len(manifest.Data) > 0 && manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls != "" {
		m3u8Url = manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls
	}

	qualities := []QualityInfo{}
	codecs := []string{}
	if m3u8Url != "" {
		masterUrl, _ := url.Parse(m3u8Url)
		resp, err := httpClient.Get(m3u8Url)
		if err == nil && resp.StatusCode == http.StatusOK {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			from, listType, _ := m3u8.DecodeFrom(strings.NewReader(string(body)), true)
			if listType == m3u8.MASTER {
				master := from.(*m3u8.MasterPlaylist)
				sort.Slice(master.Variants, func(i, j int) bool { return master.Variants[i].AverageBandwidth > master.Variants[j].AverageBandwidth })
				bestByCodec := make(map[string]QualityInfo)
				for _, v := range master.Variants {
					abs := masterUrl.ResolveReference(&url.URL{Path: v.URI})
					codecLabel, qualityText := "", ""
					switch {
					case v.Codecs == "ec-3" && strings.Contains(v.Audio, "atmos"):
						codecLabel, qualityText = "ATMOS", fmt.Sprintf("%dKbps", v.Bandwidth/1000)
					case v.Codecs == "alac":
						codecLabel = "ALAC"
						parts := strings.Split(v.Audio, "-")
						if len(parts) >= 3 {
							sr, _ := strconv.Atoi(parts[len(parts)-2])
							bd := parts[len(parts)-1]
							qualityText = fmt.Sprintf("%s-bit/%dkHz", bd, sr/1000)
						}
					case v.Codecs == "mp4a.40.2":
						codecLabel, qualityText = "AAC", fmt.Sprintf("%dKbps", v.Bandwidth/1000)
					}
					if codecLabel != "" {
						if _, ok := bestByCodec[codecLabel]; !ok {
							bestByCodec[codecLabel] = QualityInfo{
								Codec:    codecLabel,
								URL:      abs.String(),
								Quality:  qualityText,
								Group:    v.Audio,
								Selected: false,
							}
						}
					}
				}
				order := []string{"ATMOS", "ALAC", "AAC"}
				prefCodec := preferredCodec()
				for _, k := range order {
					if q, ok := bestByCodec[k]; ok {
						if q.Codec == prefCodec {
							if q.Codec == "AAC" {
								aacregex := regexp.MustCompile(`audio-stereo-\d+`)
								normalizedGroup := aacregex.ReplaceAllString(q.Group, "aac")
								if strings.EqualFold(normalizedGroup, Config.AacType) {
									q.Selected = true
								}
							} else {
								q.Selected = true
							}
						}
						qualities = append(qualities, q)
						codecs = append(codecs, k)
					}
				}
			}
		}
	}
	resultsChan <- TrackProbe{
		Index:              index,
		TrackData:          track,
		AvailableQualities: qualities,
		AvailableCodecs:    codecs,
	}
}

func ripPlaylist(playlistId string, token string, storefront string, mediaUserToken string) error {
	playlist := task.NewPlaylist(storefront, playlistId)
	err := playlist.GetResp(token, Config.Language)
	if err != nil {
		return fmt.Errorf("failed to get playlist response: %w", err)
	}
	meta := playlist.Resp

	// Detect if this is a user playlist for better progress tracking
	isUserPL := isUserPlaylist(playlistId)

	if json_output {
		type TempPlaylistAttributes struct {
			Name        string `json:"name"`
			CuratorName string `json:"curatorName"`
			URL         string `json:"url"`
			Artwork     struct {
				URL string `json:"url"`
			} `json:"artwork"`
		}
		type TempPlaylistData struct {
			Attributes TempPlaylistAttributes `json:"attributes"`
		}
		type TempPlaylistResponse struct {
			Data []TempPlaylistData `json:"data"`
		}

		apiURL := fmt.Sprintf("https://amp-api.music.apple.com/v1/catalog/%s/playlists/%s?l=%s", storefront, playlistId, Config.Language)
		req, _ := http.NewRequest("GET", apiURL, nil)
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))
		req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
		req.Header.Set("Origin", "https://music.apple.com")
		resp, err := httpClient.Do(req)
		if err != nil || resp.StatusCode != http.StatusOK {
			return fmt.Errorf("failed to fetch playlist metadata directly")
		}
		defer resp.Body.Close()

		var playlistMeta TempPlaylistResponse
		if err := json.NewDecoder(resp.Body).Decode(&playlistMeta); err != nil || len(playlistMeta.Data) == 0 {
			return fmt.Errorf("failed to decode playlist metadata")
		}

		type AlbumProbe struct {
			AlbumData interface{}  `json:"albumData"`
			Tracks    []TrackProbe `json:"tracks"`
		}
		type AlbumAttributesForJSON struct {
			Name       string `json:"name"`
			ArtistName string `json:"artistName"`
			URL        string `json:"url"`
			Artwork    struct {
				URL string `json:"url"`
			} `json:"artwork"`
		}
		type AlbumDataForJSON struct {
			Type       string                 `json:"type"`
			ID         string                 `json:"id"`
			Attributes AlbumAttributesForJSON `json:"attributes"`
		}

		albumData := AlbumDataForJSON{
			Type: "playlists",
			ID:   playlistId,
			Attributes: AlbumAttributesForJSON{
				Name:       playlistMeta.Data[0].Attributes.Name,
				ArtistName: playlistMeta.Data[0].Attributes.CuratorName,
				URL:        playlistMeta.Data[0].Attributes.URL,
				Artwork:    playlistMeta.Data[0].Attributes.Artwork,
			},
		}

		tracks := meta.Data[0].Relationships.Tracks.Data
		totalTracks := len(tracks)
		jobs := make(chan ProbeJob, totalTracks)
		results := make(chan TrackProbe, totalTracks)
		var wg sync.WaitGroup

		numWorkers := 20
		for i := 0; i < numWorkers; i++ {
			wg.Add(1)
			go probeWorker(jobs, results, &wg)
		}

		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(`{"type": "probe_start", "total": %d}`, totalTracks))
		progressWriter.Flush()

		for i, track := range tracks {
			jobs <- ProbeJob{Track: track, Index: i, Storefront: storefront, Language: playlist.Language, Token: token}
		}
		close(jobs)

		probedTracks := make([]TrackProbe, 0, totalTracks)
		for i := 0; i < totalTracks; i++ {
			result := <-results
			probedTracks = append(probedTracks, result)
			fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(`{"type": "probe_progress", "current": %d, "total": %d}`, i+1, totalTracks))
			progressWriter.Flush()
		}
		wg.Wait()

		sort.Slice(probedTracks, func(i, j int) bool {
			return probedTracks[i].Index < probedTracks[j].Index
		})

		hasMatchingTrack := false
		for _, track := range probedTracks {
			if contains(track.AvailableCodecs, preferredCodec()) {
				hasMatchingTrack = true
				break
			}
		}
		if !hasMatchingTrack {
			return fmt.Errorf("This playlist is not available in the selected quality (%s)", preferredCodec())
		}

		probe := AlbumProbe{AlbumData: albumData, Tracks: probedTracks}
		jsonBytes, _ := json.Marshal(probe)
		fmt.Println("AMDL_JSON_START")
		fmt.Println(string(jsonBytes))
		fmt.Println("AMDL_JSON_END")
		return nil
	}

	Codec := preferredCodec()
	playlist.Codec = Codec

	var baseSaveFolder string
	switch Codec {
	case "ATMOS":
		baseSaveFolder = Config.AtmosSaveFolder
	case "AAC":
		baseSaveFolder = Config.AacSaveFolder
	default:
		baseSaveFolder = Config.AlacSaveFolder
	}

	var curatorFolderPath string
	if *makeCuratorFolder {
		var curatorFolderName string
		if Config.ArtistFolderFormat != "" {
			curatorFolderName = strings.NewReplacer(
				"{ArtistName}", "Apple Music",
				"{ArtistId}", "",
				"{UrlArtistName}", "Apple Music",
			).Replace(Config.ArtistFolderFormat)
			if strings.HasSuffix(curatorFolderName, ".") {
				curatorFolderName = strings.ReplaceAll(curatorFolderName, ".", "")
			}
			curatorFolderName = strings.TrimSpace(curatorFolderName)
		}
		curatorFolderPath = filepath.Join(baseSaveFolder, forbiddenNames.ReplaceAllString(curatorFolderName, "_"))
	} else {
		curatorFolderPath = baseSaveFolder
	}
	os.MkdirAll(curatorFolderPath, os.ModePerm)
	playlist.SaveDir = curatorFolderPath

	playlistFolder := strings.NewReplacer(
		"{ArtistName}", "Apple Music",
		"{PlaylistName}", LimitString(meta.Data[0].Attributes.Name),
		"{PlaylistId}", playlistId,
		"{Quality}", "",
		"{Codec}", Codec,
		"{Tag}", "",
	).Replace(Config.PlaylistFolderFormat)
	if strings.HasSuffix(playlistFolder, ".") {
		playlistFolder = strings.ReplaceAll(playlistFolder, ".", "")
	}
	playlistFolder = strings.TrimSpace(playlistFolder)
	playlistFolderPath := filepath.Join(curatorFolderPath, forbiddenNames.ReplaceAllString(playlistFolder, "_"))
	os.MkdirAll(playlistFolderPath, os.ModePerm)
	playlist.SaveName = playlistFolder

	covPath, err := writeCover(playlistFolderPath, "cover", meta.Data[0].Attributes.Artwork.URL)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Failed to write cover.")
	}

	totalTracksInPlaylist := len(playlist.Tracks)
	for i := range playlist.Tracks {
		playlist.Tracks[i].TaskNum = i + 1
		playlist.Tracks[i].TaskTotal = totalTracksInPlaylist
		playlist.Tracks[i].CoverPath = covPath
		playlist.Tracks[i].SaveDir = playlistFolderPath
		playlist.Tracks[i].Codec = Codec
		playlist.Tracks[i].IsUserPlaylist = isUserPL
	}

	for i := range playlist.Tracks {
		trackNum := i + 1
		totalTracks := len(playlist.Tracks)

		// GET PROPER M3U8 URL (same as ripTrack does)
		manifest, err := ampapi.GetSongResp(storefront, playlist.Tracks[i].ID, playlist.Language, token)
		if err != nil {
			continue
		}

		var m3u8Url string
		if manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls != "" {
			m3u8Url = manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls
		}

		// GET STREAM INFO (same method as ripTrack)
		_, _, streamGroup, err := getStreamForCodec(m3u8Url, preferredCodec())
		if err == nil && streamGroup != "" {
			// EMIT STREAM INFO FOR GUI
			emitStreamInfo(trackNum, totalTracks, playlist.Tracks[i].Resp.Attributes.Name, streamGroup)
		}

		// Store M3U8 for ripTrack to avoid double-fetching
		playlist.Tracks[i].M3u8 = m3u8Url

		// THEN DOWNLOAD THE TRACK
		ripTrack(&playlist.Tracks[i], token, mediaUserToken)
	}
	return nil
}

func ripAlbum(albumId string, token string, storefront string, mediaUserToken string, urlArg_i string) error {
	album := task.NewAlbum(storefront, albumId)
	err := album.GetResp(token, Config.Language)
	if err != nil {
		return err
	}
	meta := album.Resp
	if json_output {
		type AlbumProbe struct {
			AlbumData interface{}  `json:"albumData"`
			Tracks    []TrackProbe `json:"tracks"`
		}

		var tracksToProbe []ampapi.TrackRespData
		if dl_song && urlArg_i != "" {
			
			for _, track := range meta.Data[0].Relationships.Tracks.Data {
				if track.ID == urlArg_i {
					tracksToProbe = append(tracksToProbe, track)
					break
				}
			}
		} else {
			
			tracksToProbe = meta.Data[0].Relationships.Tracks.Data
		}

		totalTracks := len(tracksToProbe)
		if totalTracks == 0 {
	
			probe := AlbumProbe{AlbumData: meta.Data[0], Tracks: []TrackProbe{}}
			jsonBytes, _ := json.Marshal(probe)
			fmt.Println("AMDL_JSON_START")
			fmt.Println(string(jsonBytes))
			fmt.Println("AMDL_JSON_END")
			return nil
		}

		jobs := make(chan ProbeJob, totalTracks)
		results := make(chan TrackProbe, totalTracks)
		var wg sync.WaitGroup

		numWorkers := 20
		if totalTracks < numWorkers {
			numWorkers = totalTracks
		}
		for i := 0; i < numWorkers; i++ {
			wg.Add(1)
			go probeWorker(jobs, results, &wg)
		}

		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(`{"type": "probe_start", "total": %d}`, totalTracks))
		progressWriter.Flush()

		for i, track := range tracksToProbe {
			jobs <- ProbeJob{Track: track, Index: i, Storefront: storefront, Language: album.Language, Token: token}
		}
		close(jobs)

		probedTracks := make([]TrackProbe, 0, totalTracks)
		for i := 0; i < totalTracks; i++ {
			result := <-results
			probedTracks = append(probedTracks, result)
			fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(`{"type": "probe_progress", "current": %d, "total": %d}`, i+1, totalTracks))
			progressWriter.Flush()
		}
		wg.Wait()

		sort.Slice(probedTracks, func(i, j int) bool {
			return probedTracks[i].Index < probedTracks[j].Index
		})

		hasMatchingTrack := false
		for _, track := range probedTracks {
			if contains(track.AvailableCodecs, preferredCodec()) {
				hasMatchingTrack = true
				break
			}
		}
		if !hasMatchingTrack && !dl_song { 
			return fmt.Errorf("This album is not available in the selected quality (%s)", preferredCodec())
		}

		probe := AlbumProbe{AlbumData: meta.Data[0], Tracks: probedTracks}
		jsonBytes, err := json.Marshal(probe)
		if err != nil {
			log.Fatalf("FATAL: Failed to marshal album probe to JSON: %v", err)
			return err
		}
		fmt.Println("AMDL_JSON_START")
		fmt.Println(string(jsonBytes))
		fmt.Println("AMDL_JSON_END")
		return nil
	}
	Codec := preferredCodec()
	album.Codec = Codec
	var singerFoldername string
	if Config.ArtistFolderFormat != "" {
		if len(meta.Data[0].Relationships.Artists.Data) > 0 {
			singerFoldername = strings.NewReplacer(
				"{UrlArtistName}", LimitString(meta.Data[0].Attributes.ArtistName),
				"{ArtistName}", LimitString(meta.Data[0].Attributes.ArtistName),
				"{ArtistId}", meta.Data[0].Relationships.Artists.Data[0].ID,
			).Replace(Config.ArtistFolderFormat)
		} else {
			singerFoldername = strings.NewReplacer(
				"{UrlArtistName}", LimitString(meta.Data[0].Attributes.ArtistName),
				"{ArtistName}", LimitString(meta.Data[0].Attributes.ArtistName),
				"{ArtistId}", "",
			).Replace(Config.ArtistFolderFormat)
		}
		if strings.HasSuffix(singerFoldername, ".") {
			singerFoldername = strings.ReplaceAll(singerFoldername, ".", "")
		}
		singerFoldername = strings.TrimSpace(singerFoldername)
	}
	singerFolder := filepath.Join(Config.AlacSaveFolder, forbiddenNames.ReplaceAllString(singerFoldername, "_"))
	if Codec == "ATMOS" {
		singerFolder = filepath.Join(Config.AtmosSaveFolder, forbiddenNames.ReplaceAllString(singerFoldername, "_"))
	}
	if Codec == "AAC" {
		singerFolder = filepath.Join(Config.AacSaveFolder, forbiddenNames.ReplaceAllString(singerFoldername, "_"))
	}
	os.MkdirAll(singerFolder, os.ModePerm)
	album.SaveDir = singerFolder
	var Quality string
	if strings.Contains(Config.AlbumFolderFormat, "Quality") {
		if Codec == "ATMOS" {
			Quality = fmt.Sprintf("%dKbps", Config.AtmosMax-2000)
		} else if Codec == "AAC" && Config.AacType == "aac-lc" {
			Quality = "256Kbps"
		} else {
			manifest1, err := ampapi.GetSongResp(storefront, meta.Data[0].Relationships.Tracks.Data[0].ID, album.Language, token)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Failed to get manifest.\n %v\n", err)
			} else {
				if manifest1.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls == "" {
					Codec = "AAC"
					Quality = "256Kbps"
				} else {
					_, Quality, err = extractMedia(manifest1.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls, true)
					if err != nil {
						fmt.Fprintf(os.Stderr, "Failed to extract quality from manifest.\n %v\n", err)
					}
				}
			}
		}
	}
	stringsToJoin := []string{}
	if meta.Data[0].Attributes.IsAppleDigitalMaster || meta.Data[0].Attributes.IsMasteredForItunes {
		if Config.AppleMasterChoice != "" {
			stringsToJoin = append(stringsToJoin, Config.AppleMasterChoice)
		}
	}
	if meta.Data[0].Attributes.ContentRating == "explicit" {
		if Config.ExplicitChoice != "" {
			stringsToJoin = append(stringsToJoin, Config.ExplicitChoice)
		}
	}
	if meta.Data[0].Attributes.ContentRating == "clean" {
		if Config.CleanChoice != "" {
			stringsToJoin = append(stringsToJoin, Config.CleanChoice)
		}
	}
	Tag_string := strings.Join(stringsToJoin, " ")
	var albumFolderName string
	albumFolderName = strings.NewReplacer(
		"{ReleaseDate}", meta.Data[0].Attributes.ReleaseDate,
		"{ReleaseYear}", meta.Data[0].Attributes.ReleaseDate[:4],
		"{ArtistName}", LimitString(meta.Data[0].Attributes.ArtistName),
		"{AlbumName}", LimitString(meta.Data[0].Attributes.Name),
		"{UPC}", meta.Data[0].Attributes.Upc,
		"{RecordLabel}", meta.Data[0].Attributes.RecordLabel,
		"{Copyright}", meta.Data[0].Attributes.Copyright,
		"{AlbumId}", albumId,
		"{Quality}", Quality,
		"{Codec}", Codec,
		"{Tag}", Tag_string,
	).Replace(Config.AlbumFolderFormat)

	if strings.HasSuffix(albumFolderName, ".") {
		albumFolderName = strings.ReplaceAll(albumFolderName, ".", "")
	}
	albumFolderName = strings.TrimSpace(albumFolderName)
	albumFolderPath := filepath.Join(singerFolder, forbiddenNames.ReplaceAllString(albumFolderName, "_"))
	os.MkdirAll(albumFolderPath, os.ModePerm)
	album.SaveName = albumFolderName

	if Config.SaveArtistCover {
		if len(meta.Data[0].Relationships.Artists.Data) > 0 {
			_, err = writeCover(singerFolder, "folder", meta.Data[0].Relationships.Artists.Data[0].Attributes.Artwork.Url)
			if err != nil {
				fmt.Fprintln(os.Stderr, "Failed to write artist cover.")
			}
		}
	}
	covPath, err := writeCover(albumFolderPath, "cover", meta.Data[0].Attributes.Artwork.URL)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Failed to write cover.")
	}
	if Config.SaveAnimatedArtwork && meta.Data[0].Attributes.EditorialVideo.MotionDetailSquare.Video != "" {
		motionvideoUrlSquare, err := extractVideo(meta.Data[0].Attributes.EditorialVideo.MotionDetailSquare.Video)
		if err == nil {
			exists, _ := fileExists(filepath.Join(albumFolderPath, "square_animated_artwork.mp4"))
			if !exists {
				cmd := exec.Command("ffmpeg", "-loglevel", "quiet", "-y", "-i", motionvideoUrlSquare, "-c", "copy", filepath.Join(albumFolderPath, "square_animated_artwork.mp4"))
				cmd.Run()
			}
		}
	}
	for i := range album.Tracks {
		album.Tracks[i].CoverPath = covPath
		album.Tracks[i].SaveDir = albumFolderPath
		album.Tracks[i].Codec = Codec
	}

	if dl_song {
		if urlArg_i != "" {
			for i := range album.Tracks {
				if urlArg_i == album.Tracks[i].ID {
					album.Tracks[i].TaskNum = album.Tracks[i].Resp.Attributes.TrackNumber
					album.Tracks[i].TaskTotal = meta.Data[0].Attributes.TrackCount
					
					// GET STREAM INFO (same as full album does)
					manifest, err := ampapi.GetSongResp(storefront, album.Tracks[i].ID, album.Language, token)
					if err == nil {
						var m3u8Url string
						if manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls != "" {
							m3u8Url = manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls
						}
						
						// EMIT STREAM INFO FOR GUI
						_, _, streamGroup, err := getStreamForCodec(m3u8Url, preferredCodec())
						if err == nil && streamGroup != "" {
							emitStreamInfo(album.Tracks[i].TaskNum, album.Tracks[i].TaskTotal, album.Tracks[i].Resp.Attributes.Name, streamGroup)
						}
						
						// Store M3U8 to avoid double-fetching in ripTrack
						album.Tracks[i].M3u8 = m3u8Url
					}
					
					ripTrack(&album.Tracks[i], token, mediaUserToken)
					return nil
				}
			}
		}
		return nil
	}

	for i := range album.Tracks {
		trackNum := i + 1
		totalTracks := len(album.Tracks)

		// GET PROPER M3U8 URL (same as ripTrack does)
		manifest, err := ampapi.GetSongResp(storefront, album.Tracks[i].ID, album.Language, token)
		if err != nil {
			continue
		}

		var m3u8Url string
		if manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls != "" {
			m3u8Url = manifest.Data[0].Attributes.ExtendedAssetUrls.EnhancedHls
		}

		// GET STREAM INFO (same method as ripTrack)
		_, _, streamGroup, err := getStreamForCodec(m3u8Url, preferredCodec())
		if err == nil && streamGroup != "" {
			// EMIT STREAM INFO FOR GUI
			emitStreamInfo(trackNum, totalTracks, album.Tracks[i].Resp.Attributes.Name, streamGroup)
		}

		// Store M3U8 for ripTrack to avoid double-fetching
		album.Tracks[i].M3u8 = m3u8Url

		// THEN DOWNLOAD THE TRACK
		ripTrack(&album.Tracks[i], token, mediaUserToken)
	}
	return nil
}

func getStreamForCodec(m3u8Url, codec string) (string, string, string, error) {
	masterUrl, err := url.Parse(m3u8Url)
	if err != nil {
		return "", "", "", err
	}
	resp, err := httpClient.Get(m3u8Url)
	if err != nil {
		return "", "", "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", "", "", errors.New(resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", "", err
	}
	playlist, listType, err := m3u8.DecodeFrom(strings.NewReader(string(body)), true)
	if err != nil || listType != m3u8.MASTER {
		return "", "", "", errors.New("m3u8 not of master type")
	}
	master := playlist.(*m3u8.MasterPlaylist)
	sort.Slice(master.Variants, func(i, j int) bool { return master.Variants[i].AverageBandwidth > master.Variants[j].AverageBandwidth })

	if codec == "ATMOS" {
		for _, v := range master.Variants {
			if v.Codecs == "ec-3" && strings.Contains(v.Audio, "atmos") {
				u := masterUrl.ResolveReference(&url.URL{Path: v.URI})
				return u.String(), "ATMOS", v.Audio, nil
			}
		}
		return "", "", "", fmt.Errorf("codec %s not found", codec)
	}
	if codec == "ALAC" {
		for _, v := range master.Variants {
			if v.Codecs == "alac" {
				u := masterUrl.ResolveReference(&url.URL{Path: v.URI})
				return u.String(), "ALAC", v.Audio, nil
			}
		}
		return "", "", "", fmt.Errorf("codec %s not found", codec)
	}

	if codec == "AAC" {
		pref := strings.ToLower(Config.AacType)
		var chosen *m3u8.Variant
		sort.Slice(master.Variants, func(i, j int) bool {
			return master.Variants[i].AverageBandwidth > master.Variants[j].AverageBandwidth
		})

		for _, v := range master.Variants {
			if v.Codecs != "mp4a.40.2" {
				continue
			}
			g := strings.ToLower(v.Audio)
			match := false
			switch pref {
			case "aac-lc", "aac":
				if !strings.Contains(g, "binaural") && !strings.Contains(g, "downmix") {
					match = true
				}
			case "aac-binaural":
				if strings.Contains(g, "binaural") {
					match = true
				}
			case "aac-downmix":
				if strings.Contains(g, "downmix") {
					match = true
				}
			default:
				return "", "", "", fmt.Errorf("unsupported AacType: %s", Config.AacType)
			}
			if match {
				chosen = v
				break
			}
		}

		if chosen == nil {
			return "", "", "", fmt.Errorf("requested AAC type (%s) not available", Config.AacType)
		}
		u := masterUrl.ResolveReference(&url.URL{Path: chosen.URI})
		return u.String(), "AAC", chosen.Audio, nil
	}

	return "", "", "", fmt.Errorf("unsupported codec preference: %s", codec)
}

func getBandwidthForStream(m3u8Url, codec, streamGroup string) (uint32, error) {
	resp, err := httpClient.Get(m3u8Url)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, errors.New(resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, err
	}
	playlist, listType, err := m3u8.DecodeFrom(strings.NewReader(string(body)), true)
	if err != nil || listType != m3u8.MASTER {
		return 0, errors.New("m3u8 not of master type")
	}
	master := playlist.(*m3u8.MasterPlaylist)

	for _, v := range master.Variants {
		if v.Audio == streamGroup {
			return v.Bandwidth, nil
		}
	}

	return 0, errors.New("stream group not found in manifest")
}

// Helper function to check if album data is valid
func hasValidAlbumData(track *task.Track) bool {
	// Check for nil FIRST before accessing fields
	return !reflect.ValueOf(track.AlbumData).IsZero() &&
		track.AlbumData.ID != "" &&
		!reflect.ValueOf(track.AlbumData.Attributes).IsZero() &&
		track.AlbumData.Attributes.Name != ""
}

func writeMP4Tags(track *task.Track, lrc string) error {
	t := &mp4tag.MP4Tags{
		Custom: make(map[string]string),
	}

	if Config.TagOptions.WriteTitle {
		t.Title = track.Resp.Attributes.Name
	}
	if Config.TagOptions.WriteArtist {
		t.Artist = track.Resp.Attributes.ArtistName
		t.Custom["PERFORMER"] = track.Resp.Attributes.ArtistName
	}
	if Config.TagOptions.WriteArtistSort {
		t.ArtistSort = track.Resp.Attributes.ArtistName
	}
	if Config.TagOptions.WriteAlbum {
		t.Album = track.Resp.Attributes.AlbumName
	}
	if Config.TagOptions.WriteAlbumSort {
		t.AlbumSort = track.Resp.Attributes.AlbumName
	}
	if Config.TagOptions.WriteGenre && len(track.Resp.Attributes.GenreNames) > 0 {
		t.CustomGenre = track.Resp.Attributes.GenreNames[0]
	}
	if Config.TagOptions.WriteComposer {
		t.Composer = track.Resp.Attributes.ComposerName
	}
	if Config.TagOptions.WriteComposerSort {
		t.ComposerSort = track.Resp.Attributes.ComposerName
	}
	if Config.TagOptions.WriteDiscTrack {
		t.TrackNumber = int16(track.Resp.Attributes.TrackNumber)
		t.DiscNumber = int16(track.Resp.Attributes.DiscNumber)
	}
	if Config.TagOptions.WriteISRC {
		t.Custom["ISRC"] = track.Resp.Attributes.Isrc
	}
	if Config.TagOptions.WriteDate {
		t.Custom["RELEASETIME"] = track.Resp.Attributes.ReleaseDate
	}
	if Config.TagOptions.WriteLyrics {
		t.Lyrics = lrc
	}

	if track.PreType == "albums" {
		albumID, err := strconv.ParseUint(track.PreID, 10, 32)
		if err == nil {
			t.ItunesAlbumID = int32(albumID)
		}
	}

	if len(track.Resp.Relationships.Artists.Data) > 0 {
		artistID, err := strconv.ParseUint(track.Resp.Relationships.Artists.Data[0].ID, 10, 32)
		if err == nil {
			t.ItunesArtistID = int32(artistID)
		}
	}

	if (track.PreType == "playlists" || track.PreType == "stations") && !Config.UseSongInfoForPlaylist {
		if Config.TagOptions.WriteDiscTrack {
			t.DiscNumber = 1
			t.DiscTotal = 1
			t.TrackNumber = int16(track.TaskNum)
			t.TrackTotal = int16(track.TaskTotal)
		}
		if Config.TagOptions.WriteAlbum {
			t.Album = track.PlaylistData.Attributes.Name
		}
		if Config.TagOptions.WriteAlbumSort {
			t.AlbumSort = track.PlaylistData.Attributes.Name
		}
		if Config.TagOptions.WriteAlbumArtist {
			t.AlbumArtist = track.PlaylistData.Attributes.ArtistName
			t.AlbumArtistSort = track.PlaylistData.Attributes.ArtistName
		}
	} else if (track.PreType == "playlists" || track.PreType == "stations") && Config.UseSongInfoForPlaylist {
		if hasValidAlbumData(track) {
			if Config.TagOptions.WriteDiscTrack {
				t.DiscTotal = int16(track.DiscTotal)
				t.TrackTotal = int16(track.AlbumData.Attributes.TrackCount)
			}
			if Config.TagOptions.WriteAlbum {
				t.Album = track.AlbumData.Attributes.Name
			}
			if Config.TagOptions.WriteAlbumSort {
				t.AlbumSort = track.AlbumData.Attributes.Name
			}
			if Config.TagOptions.WriteAlbumArtist {
				t.AlbumArtist = track.AlbumData.Attributes.ArtistName
				t.AlbumArtistSort = track.AlbumData.Attributes.ArtistName
			}
			if Config.TagOptions.WriteUPC {
				t.Custom["UPC"] = track.AlbumData.Attributes.Upc
			}
			if Config.TagOptions.WritePublisher {
				t.Publisher = track.AlbumData.Attributes.RecordLabel
			}
			if Config.TagOptions.WriteDate {
				t.Date = track.AlbumData.Attributes.ReleaseDate
			}
			if Config.TagOptions.WriteCopyright {
				t.Copyright = track.AlbumData.Attributes.Copyright
			}
		} else {
			fmt.Println("Warning: Album data not available, using playlist metadata as fallback.")
			if Config.TagOptions.WriteDiscTrack {
				t.DiscNumber = 1
				t.DiscTotal = 1
				t.TrackNumber = int16(track.TaskNum)
				t.TrackTotal = int16(track.TaskTotal)
			}
			if Config.TagOptions.WriteAlbum {
				t.Album = track.PlaylistData.Attributes.Name
			}
			if Config.TagOptions.WriteAlbumSort {
				t.AlbumSort = track.PlaylistData.Attributes.Name
			}
			if Config.TagOptions.WriteAlbumArtist {
				t.AlbumArtist = track.PlaylistData.Attributes.ArtistName
				t.AlbumArtistSort = track.PlaylistData.Attributes.ArtistName
			}
		}
	} else { // Regular album
		if hasValidAlbumData(track) {
			if Config.TagOptions.WriteDiscTrack {
				t.DiscTotal = int16(track.DiscTotal)
				t.TrackTotal = int16(track.AlbumData.Attributes.TrackCount)
			}
			if Config.TagOptions.WriteAlbumArtist {
				t.AlbumArtist = track.AlbumData.Attributes.ArtistName
			}
			if Config.TagOptions.WriteAlbumArtistSort {
				t.AlbumArtistSort = track.AlbumData.Attributes.ArtistName
			}
			if Config.TagOptions.WriteUPC {
				t.Custom["UPC"] = track.AlbumData.Attributes.Upc
			}
			if Config.TagOptions.WriteDate {
				t.Date = track.AlbumData.Attributes.ReleaseDate
			}
			if Config.TagOptions.WriteCopyright {
				t.Copyright = track.AlbumData.Attributes.Copyright
			}
			if Config.TagOptions.WritePublisher {
				t.Publisher = track.AlbumData.Attributes.RecordLabel
			}
		}
	}

	if track.Resp.Attributes.ContentRating == "explicit" {
		t.ItunesAdvisory = mp4tag.ItunesAdvisoryExplicit
	} else if track.Resp.Attributes.ContentRating == "clean" {
		t.ItunesAdvisory = mp4tag.ItunesAdvisoryClean
	} else {
		t.ItunesAdvisory = mp4tag.ItunesAdvisoryNone
	}

	del := []string{}
	if Config.TagOptions.DeleteSortOnWrite {
		del = append(del, "artist_sort", "album_sort", "album_artist_sort", "title_sort", "composer_sort")
	}

	mp4, err := mp4tag.Open(track.SavePath)
	if err != nil {
		return err
	}
	defer mp4.Close()
	err = mp4.Write(t, del)
	if err != nil {
		return err
	}
	return nil
}

func mvDownloader(adamID string, saveDir string, token string, storefront string, mediaUserToken string, track *task.Track, progressWriter *bufio.Writer) error {
	MVInfo, err := ampapi.GetMusicVideoResp(storefront, adamID, Config.Language, token)
	if err != nil {
		fmt.Fprintf(os.Stderr, "\u26A0 Failed to get MV manifest: %v\n", err)
		return nil
	}

	if track != nil && progressWriter != nil {
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(
			`{"type":"track_start","track_num":%d,"total_tracks":%d,"name":"%s","codec":"H.264/AAC","runner":"runv3"}`,
			track.TaskNum, track.TaskTotal, MVInfo.Data[0].Attributes.Name,
		))
		progressWriter.Flush()
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(
			`{"type":"track_stream","track_num":%d,"total_tracks":%d,"name":"%s","stream_group":"Music Video"}`,
			track.TaskNum, track.TaskTotal, MVInfo.Data[0].Attributes.Name))
		progressWriter.Flush()
	}

	if strings.HasSuffix(saveDir, ".") {
		saveDir = strings.ReplaceAll(saveDir, ".", "")
	}
	saveDir = strings.TrimSpace(saveDir)

	vidPath := filepath.Join(saveDir, fmt.Sprintf("%s_vid.mp4", adamID))
	audPath := filepath.Join(saveDir, fmt.Sprintf("%s_aud.mp4", adamID))
	artistName := forbiddenNames.ReplaceAllString(MVInfo.Data[0].Attributes.ArtistName, "_")
	videoName := forbiddenNames.ReplaceAllString(MVInfo.Data[0].Attributes.Name, "_")
	mvSaveName := fmt.Sprintf("%s - %s", artistName, videoName)

	mvOutPath := filepath.Join(saveDir, fmt.Sprintf("%s.mp4", forbiddenNames.ReplaceAllString(mvSaveName, "_")))

	exists, _ := fileExists(mvOutPath)
	if exists {
		fmt.Fprintln(os.Stderr, "MV already exists locally.")
		return nil
	}

	mvm3u8url, _, _ := runv3.GetWebplayback(adamID, token, mediaUserToken, true)
	if mvm3u8url == "" {
		return errors.New("media-user-token may wrong or expired")
	}

	os.MkdirAll(saveDir, os.ModePerm)

	var videoBytesDownloaded, audioBytesDownloaded atomic.Int64
	var totalVideoBytes, totalAudioBytes atomic.Int64

	videom3u8url, _ := extractVideo(mvm3u8url)
	videokeyAndUrls, _ := runv3.Run(adamID, videom3u8url, token, mediaUserToken, true)

	audiom3u8url, _ := extractMvAudio(mvm3u8url)
	audiokeyAndUrls, _ := runv3.Run(adamID, audiom3u8url, token, mediaUserToken, true)

	var wg sync.WaitGroup
	done := make(chan struct{})
	var lastFlush time.Time
	var progressSent bool
	wg.Add(1)
	go runv3.ProgressAggregator(&wg, done, &videoBytesDownloaded, &audioBytesDownloaded, &totalVideoBytes, &totalAudioBytes, func(percent float64) {
		downloaded := videoBytesDownloaded.Load() + audioBytesDownloaded.Load()
		total := totalVideoBytes.Load() + totalAudioBytes.Load()

		// Emit size event once when total becomes known
		if !progressSent && total > 0 {
			fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n",
				fmt.Sprintf(`{"type":"size","total_bytes":%d}`, total))
			progressSent = true
		}

		// Emit bytes on every tick
		if total > 0 {
			fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n",
				fmt.Sprintf(`{"type":"bytes","downloaded_bytes":%d,"total_bytes":%d}`, downloaded, total))
		}

		// Keep existing track_progress percent emission for the progress bar itself
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n",
			fmt.Sprintf(`{"type":"track_progress","track_num":%d,"total_tracks":%d,"name":"%s","percent":%d}`,
				track.TaskNum, track.TaskTotal, MVInfo.Data[0].Attributes.Name, int(percent*100)))

		// Use a throttled flush
		now := time.Now()
		if now.Sub(lastFlush) >= 1*time.Second {
			progressWriter.Flush()
			lastFlush = now
		}
	})

	_ = runv3.ExtMvData(videokeyAndUrls, vidPath, &videoBytesDownloaded, &totalVideoBytes)
	_ = runv3.ExtMvData(audiokeyAndUrls, audPath, &audioBytesDownloaded, &totalAudioBytes)

	close(done)
	wg.Wait()

	// Send 90% progress - downloads complete
	if track != nil && progressWriter != nil {
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(
			`{"type":"track_progress","track_num":%d,"total_tracks":%d,"name":"%s","percent":90}`,
			track.TaskNum, track.TaskTotal, MVInfo.Data[0].Attributes.Name))
		progressWriter.Flush()
	}

	tags := []string{
		"tool=",
	}
	if Config.TagOptions.UseMp4BoxArtist {
		tags = append(tags, fmt.Sprintf("artist=%s", MVInfo.Data[0].Attributes.ArtistName))
	}
	if Config.TagOptions.WriteCover {
		var covPath string
		thumbURL := MVInfo.Data[0].Attributes.Artwork.URL
		baseThumbName := forbiddenNames.ReplaceAllString(mvSaveName, "_") + "_thumbnail"
		covPath, err = writeCover(saveDir, baseThumbName, thumbURL)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to save MV thumbnail: %v\n", err)
		} else {
			tags = append(tags, fmt.Sprintf("cover=%s", covPath))
			defer os.Remove(covPath)
		}
	}

	tagsString := strings.Join(tags, ":")
	fmt.Fprintln(os.Stderr, "MV Remuxing...")

	// Run MP4Box in goroutine with progress simulation (90-99%)
	remuxDone := make(chan error, 1)
	go func() {
		muxCmd := exec.Command("MP4Box", "-itags", tagsString, "-quiet", "-add", vidPath, "-add", audPath, "-keep-utc", "-new", mvOutPath)
		remuxDone <- muxCmd.Run()
	}()

	// Increment progress during remuxing
	progressTicker := time.NewTicker(1 * time.Second)
	defer progressTicker.Stop()
	currentProgress := 90

remuxLoop:
	for {
		select {
		case err := <-remuxDone:
			if err != nil {
				fmt.Fprintf(os.Stderr, "MV mux failed: %v\n", err)
				return err
			}
			break remuxLoop
		case <-progressTicker.C:
			currentProgress++
			if currentProgress > 99 {
				currentProgress = 99 // Cap at 99% until actual completion
			}
			if track != nil && progressWriter != nil {
				fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(
					`{"type":"track_progress","track_num":%d,"total_tracks":%d,"name":"%s","percent":%d}`,
					track.TaskNum, track.TaskTotal, MVInfo.Data[0].Attributes.Name, currentProgress))
				progressWriter.Flush()
			}
		}
	}

	fmt.Fprintln(os.Stderr, "MV Remuxed.")
	defer os.Remove(vidPath)
	defer os.Remove(audPath)

	if track != nil && progressWriter != nil {
		fmt.Fprintf(progressWriter, "AMDL_PROGRESS::%s\n", fmt.Sprintf(
			`{"type":"track_complete","track_num":%d,"total_tracks":%d,"name":"%s"}`,
			track.TaskNum, track.TaskTotal, MVInfo.Data[0].Attributes.Name,
		))
		progressWriter.Flush()
	}

	return nil
}

func extractMvAudio(c string) (string, error) {
	MediaUrl, err := url.Parse(c)
	if err != nil {
		return "", err
	}

	resp, err := httpClient.Get(c)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", errors.New(resp.Status)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	audioString := string(body)
	from, listType, err := m3u8.DecodeFrom(strings.NewReader(audioString), true)
	if err != nil || listType != m3u8.MASTER {
		return "", errors.New("m3u8 not of media type")
	}

	audio := from.(*m3u8.MasterPlaylist)

	var audioPriority = []string{"audio-atmos", "audio-ac3", "audio-stereo-256"}
	if Config.MVAudioType == "ac3" {
		audioPriority = []string{"audio-ac3", "audio-stereo-256"}
	} else if Config.MVAudioType == "aac" {
		audioPriority = []string{"audio-stereo-256"}
	}

	re := regexp.MustCompile(`_gr(\d+)_`)

	type AudioStream struct {
		URL     string
		Rank    int
		GroupID string
	}
	var audioStreams []AudioStream

	for _, variant := range audio.Variants {
		for _, audiov := range variant.Alternatives {
			if audiov.URI != "" {
				for _, priority := range audioPriority {
					if audiov.GroupId == priority {
						matches := re.FindStringSubmatch(audiov.URI)
						if len(matches) == 2 {
							var rank int
							fmt.Sscanf(matches[1], "%d", &rank)
							streamUrl, _ := MediaUrl.Parse(audiov.URI)
							audioStreams = append(audioStreams, AudioStream{
								URL:     streamUrl.String(),
								Rank:    rank,
								GroupID: audiov.GroupId,
							})
						}
					}
				}
			}
		}
	}

	if len(audioStreams) == 0 {
		return "", errors.New("no suitable audio stream found")
	}

	sort.Slice(audioStreams, func(i, j int) bool {
		return audioStreams[i].Rank > audioStreams[j].Rank
	})
	return audioStreams[0].URL, nil
}

func extractMedia(b string, more_mode bool) (string, string, error) {
	masterUrl, err := url.Parse(b)
	if err != nil {
		return "", "", err
	}
	resp, err := httpClient.Get(b)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", "", errors.New(resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", err
	}
	masterString := string(body)
	from, listType, err := m3u8.DecodeFrom(strings.NewReader(masterString), true)
	if err != nil {
		return "", "", err
	}
	if listType != m3u8.MASTER {
		if listType == m3u8.MEDIA {
			return b, "Unknown", nil
		}
		return "", "", errors.New("m3u8 not of master type")
	}
	master := from.(*m3u8.MasterPlaylist)
	var streamUrl *url.URL
	sort.Slice(master.Variants, func(i, j int) bool {
		return master.Variants[i].AverageBandwidth > master.Variants[j].AverageBandwidth
	})

	var Quality string
	var bestVariant *m3u8.Variant
	switch preferredCodec() {
	case "ATMOS":
		for _, variant := range master.Variants {
			if (variant.Codecs == "ec-3" && strings.Contains(variant.Audio, "atmos")) || variant.Codecs == "ac-3" {
				bestVariant = variant
				break
			}
		}
	case "AAC":
		for _, variant := range master.Variants {
			if variant.Codecs == "mp4a.40.2" {
				aacregex := regexp.MustCompile(`audio-stereo-\d+`)
				replaced := aacregex.ReplaceAllString(variant.Audio, "aac")
				if replaced == Config.AacType {
					bestVariant = variant
					break
				}
			}
		}
	default:
		for _, variant := range master.Variants {
			if variant.Codecs == "alac" {
				split := strings.Split(variant.Audio, "-")
				if len(split) >= 3 {
					sampleRate, _ := strconv.Atoi(split[len(split)-2])
					if sampleRate <= Config.AlacMax {
						bestVariant = variant
						break
					}
				}
			}
		}
	}

	if bestVariant == nil {
		return "", "", errors.New("no variants found in playlist")
	}

	streamUrl = masterUrl.ResolveReference(&url.URL{Path: bestVariant.URI})

	if bestVariant.Codecs == "alac" {
		split := strings.Split(bestVariant.Audio, "-")
		if len(split) >= 3 {
			sr, _ := strconv.Atoi(split[len(split)-2])
			Quality = fmt.Sprintf("%sB-%.1fkHz", split[len(split)-1], float64(sr)/1000.0)
		}
	} else {
		Quality = fmt.Sprintf("%dKbps", bestVariant.Bandwidth/1000)
	}

	return streamUrl.String(), Quality, nil
}

func extractVideo(c string) (string, error) {
	MediaUrl, err := url.Parse(c)
	if err != nil {
		return "", err
	}

	resp, err := httpClient.Get(c)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", errors.New(resp.Status)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	videoString := string(body)

	from, listType, err := m3u8.DecodeFrom(strings.NewReader(videoString), true)
	if err != nil || listType != m3u8.MASTER {
		return "", errors.New("m3u8 not of media type")
	}

	video := from.(*m3u8.MasterPlaylist)

	re := regexp.MustCompile(`_(\d+)x(\d+)`)

	var streamUrl *url.URL
	sort.Slice(video.Variants, func(i, j int) bool {
		return video.Variants[i].AverageBandwidth > video.Variants[j].AverageBandwidth
	})

	maxHeight := Config.MVMax

	for _, variant := range video.Variants {
		matches := re.FindStringSubmatch(variant.URI)
		if len(matches) == 3 {
			height := matches[2]
			var h int
			_, err := fmt.Sscanf(height, "%d", &h)
			if err != nil {
				continue
			}
			if h <= maxHeight {
				streamUrl, err = MediaUrl.Parse(variant.URI)
				if err != nil {
					return "", err
				}
				break
			}
		}
	}

	if streamUrl == nil {
		return "", errors.New("no suitable video stream found")
	}

	return streamUrl.String(), nil
}

func main() {
	progressWriter = bufio.NewWriter(os.Stdout)
	defer progressWriter.Flush()

	
	transport := &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 100,
		IdleConnTimeout:     90 * time.Second,
	}
	httpClient = &http.Client{Transport: transport}

	err := loadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "load Config failed: %v\n", err)
		return
	}
	token, err := ampapi.GetToken()
	if err != nil {
		if Config.AuthorizationToken != "" && Config.AuthorizationToken != "your-authorization-token" {
			token = strings.Replace(Config.AuthorizationToken, "Bearer ", "", -1)
		} else {
			fmt.Fprintln(os.Stderr, "Failed to get token.")
			return
		}
	}

	
	codecPreferenceFlag := flag.String("codec-preference", "", "Codec preference")
	songFlag := flag.Bool("song", false, "Download a single song")
	mvFlag := flag.Bool("music-video", false, "Download a music video")
	jsonOutputFlag := flag.Bool("json-output", false, "Output metadata as JSON")
	resolveArtistFlag := flag.String("resolve-artist", "", "Resolve artist discography")

	
	flag.StringVar(&Config.AlacSaveFolder, "alac-save-folder", Config.AlacSaveFolder, "Overrides alac-save-folder from config")
	flag.StringVar(&Config.AtmosSaveFolder, "atmos-save-folder", Config.AtmosSaveFolder, "Overrides atmos-save-folder from config")
	flag.StringVar(&Config.AacSaveFolder, "aac-save-folder", Config.AacSaveFolder, "Overrides aac-save-folder from config")
	flag.StringVar(&Config.MvSaveFolder, "mv-save-folder", Config.MvSaveFolder, "Overrides mv-save-folder from config")
	flag.StringVar(&Config.LrcType, "lrc-type", Config.LrcType, "Lyrics type")
	flag.StringVar(&Config.LrcFormat, "lrc-format", Config.LrcFormat, "Lyrics format")
	flag.BoolVar(&Config.EmbedLrc, "embed-lrc", Config.EmbedLrc, "Embed lyrics")
	flag.BoolVar(&Config.SaveLrcFile, "save-lrc-file", Config.SaveLrcFile, "Save lyrics file")
	flag.BoolVar(&Config.EmbedCover, "embed-cover", Config.EmbedCover, "Embed cover art")
	flag.StringVar(&Config.CoverSize, "cover-size", Config.CoverSize, "Cover art size")
	flag.StringVar(&Config.CoverFormat, "cover-format", Config.CoverFormat, "Cover art format")
	flag.IntVar(&Config.AlacMax, "alac-max", Config.AlacMax, "Max sample rate for ALAC")
	flag.IntVar(&Config.AtmosMax, "atmos-max", Config.AtmosMax, "Max bitrate for Atmos")
	flag.StringVar(&Config.AacType, "aac-type", Config.AacType, "AAC type")
	flag.StringVar(&Config.MVAudioType, "mv-audio-type", Config.MVAudioType, "Music video audio type")
	flag.IntVar(&Config.MVMax, "mv-max", Config.MVMax, "Max resolution for music videos")
	flag.StringVar(&Config.AlbumFolderFormat, "album-folder-format", Config.AlbumFolderFormat, "Album folder format")
	flag.StringVar(&Config.PlaylistFolderFormat, "playlist-folder-format", Config.PlaylistFolderFormat, "Playlist folder format")
	flag.StringVar(&Config.SongFileFormat, "song-file-format", Config.SongFileFormat, "Song file format")
	flag.StringVar(&Config.ArtistFolderFormat, "artist-folder-format", Config.ArtistFolderFormat, "Artist folder format")
	flag.StringVar(&Config.MediaUserToken, "media-user-token", Config.MediaUserToken, "Media user token")
	flag.StringVar(&Config.AuthorizationToken, "authorization-token", Config.AuthorizationToken, "Authorization token")
	flag.StringVar(&Config.Language, "language", Config.Language, "Language")
	flag.BoolVar(&Config.SaveArtistCover, "save-artist-cover", Config.SaveArtistCover, "Save artist cover")
	flag.BoolVar(&Config.SaveAnimatedArtwork, "save-animated-artwork", Config.SaveAnimatedArtwork, "Save animated artwork")
	flag.BoolVar(&Config.EmbyAnimatedArtwork, "emby-animated-artwork", Config.EmbyAnimatedArtwork, "Save animated artwork for Emby")
	flag.IntVar(&Config.MaxMemoryLimit, "max-memory-limit", Config.MaxMemoryLimit, "Max memory limit")
	flag.StringVar(&Config.DecryptM3u8Port, "decrypt-m3u8-port", Config.DecryptM3u8Port, "Decrypt M3U8 port")
	flag.StringVar(&Config.GetM3u8Port, "get-m3u8-port", Config.GetM3u8Port, "Get M3U8 port")
	flag.BoolVar(&Config.GetM3u8FromDevice, "get-m3u8-from-device", Config.GetM3u8FromDevice, "Get M3U8 from device")
	flag.StringVar(&Config.GetM3u8Mode, "get-m3u8-mode", Config.GetM3u8Mode, "Get M3U8 mode")
	flag.IntVar(&Config.LimitMax, "limit-max", Config.LimitMax, "Limit max characters in filename")
	flag.StringVar(&Config.ExplicitChoice, "explicit-choice", Config.ExplicitChoice, "Explicit tag")
	flag.StringVar(&Config.CleanChoice, "clean-choice", Config.CleanChoice, "Clean tag")
	flag.StringVar(&Config.AppleMasterChoice, "apple-master-choice", Config.AppleMasterChoice, "Apple Master tag")
	flag.BoolVar(&Config.UseSongInfoForPlaylist, "use-songinfo-for-playlist", Config.UseSongInfoForPlaylist, "Use song info for playlist")
	flag.BoolVar(&Config.DlAlbumcoverForPlaylist, "dl-albumcover-for-playlist", Config.DlAlbumcoverForPlaylist, "Download album cover for playlist")
	flag.StringVar(&Config.Storefront, "storefront", Config.Storefront, "Storefront")

	flag.Parse() 

	
	codecPreference = *codecPreferenceFlag
	dl_song = *songFlag
	dl_mv = *mvFlag
	json_output = *jsonOutputFlag
	resolve_artist = *resolveArtistFlag


	args := flag.Args()

	if resolve_artist != "" {
		if !json_output {
			fmt.Fprintln(os.Stderr, "Error: --resolve-artist requires --json-output flag.")
			os.Exit(1)
		}
		jsonResult, err := resolveArtistToJSON(resolve_artist, token)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error resolving artist: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("AMDL_JSON_START")
		fmt.Println(jsonResult)
		fmt.Println("AMDL_JSON_END")
		return
	}

	if len(args) == 0 {
		return
	}

	urlRaw := args[0]
	mediaUserToken := Config.MediaUserToken

	if strings.Contains(urlRaw, "/song/") {
		var err error
		urlRaw, err = getUrlSong(urlRaw, token)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to resolve song URL to album URL: %v\n", err)
			return
		}
		dl_song = true
	}

	parse, err := url.Parse(urlRaw)
	if err != nil {
		log.Printf("Invalid URL: %v\n", err)
		return
	}
	urlArg_i := parse.Query().Get("i")

	if strings.Contains(urlRaw, "/music-video/") {
		storefront, mvId := checkUrlMv(urlRaw)
		if mvId == "" {
			fmt.Fprintf(os.Stderr, "Invalid music video URL\n")
			return
		}

		if json_output {
			mvInfo, err := ampapi.GetMusicVideoResp(storefront, mvId, Config.Language, token)
			if err != nil || len(mvInfo.Data) == 0 {
				fmt.Fprintf(os.Stderr, "Failed to get MV info: %v\n", err)
				return
			}

			albumData := map[string]interface{}{
				"id":   mvInfo.Data[0].ID,
				"type": "music-videos",
				"attributes": map[string]interface{}{
					"name":       mvInfo.Data[0].Attributes.Name,
					"artistName": mvInfo.Data[0].Attributes.ArtistName,
					"artwork":    mvInfo.Data[0].Attributes.Artwork,
					"url":        mvInfo.Data[0].Attributes.URL,
				},
			}

			var trackData ampapi.TrackRespData
			mvAttrs := mvInfo.Data[0].Attributes
			trackData.ID = mvInfo.Data[0].ID
			trackData.Type = "music-videos"
			trackData.Attributes.Name = mvAttrs.Name
			trackData.Attributes.ArtistName = mvAttrs.ArtistName
			trackData.Attributes.URL = mvAttrs.URL
			trackData.Attributes.Artwork.URL = mvAttrs.Artwork.URL
			trackData.Attributes.Artwork.Width = mvAttrs.Artwork.Width
			trackData.Attributes.Artwork.Height = mvAttrs.Artwork.Height

			trackProbe := TrackProbe{
				TrackData: trackData,
			}

			probe := map[string]interface{}{
				"albumData": albumData,
				"tracks":    []TrackProbe{trackProbe},
			}

			jsonBytes, err := json.Marshal(probe)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Failed to marshal music video data: %v\n", err)
				return
			}

			fmt.Println("AMDL_JSON_START")
			fmt.Println(string(jsonBytes))
			fmt.Println("AMDL_JSON_END")
			return
		}

		if dl_mv {
			mvInfo, err := ampapi.GetMusicVideoResp(storefront, mvId, Config.Language, token)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Failed to get MV info: %v\n", err)
				return
			}
			artistName := mvInfo.Data[0].Attributes.ArtistName
			var singerFoldername string
			if Config.ArtistFolderFormat != "" {
				singerFoldername = strings.NewReplacer(
					"{UrlArtistName}", LimitString(artistName),
					"{ArtistName}", LimitString(artistName),
					"{ArtistId}", "",
				).Replace(Config.ArtistFolderFormat)
			}
			saveDir := filepath.Join(Config.MvSaveFolder, forbiddenNames.ReplaceAllString(singerFoldername, "_"))
			os.MkdirAll(saveDir, os.ModePerm)

			dummyTrack := &task.Track{
				TaskNum:   1,
				TaskTotal: 1,
			}

			err = mvDownloader(mvId, saveDir, token, storefront, mediaUserToken, dummyTrack, progressWriter)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Failed to process music video %s: %v\n", mvId, err)
			}
		}
	} else if strings.Contains(urlRaw, "/album/") {
		storefront, albumId := checkUrl(urlRaw)
		if albumId != "" {
			err := ripAlbum(albumId, token, storefront, mediaUserToken, urlArg_i)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Failed to process album %s: %v\n", albumId, err)
			}
		}
	} else if strings.Contains(urlRaw, "/playlist/") {
		storefront, playlistId := checkUrlPlaylist(urlRaw)
		if playlistId != "" {
			err := ripPlaylist(playlistId, token, storefront, mediaUserToken)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Failed to process playlist %s: %v\n", playlistId, err)
			}
		}
	} else {
		fmt.Fprintf(os.Stderr, "URL type not supported by this bridge: %s\n", urlRaw)
	}
}