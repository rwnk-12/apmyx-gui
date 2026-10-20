package lyrics

import "sync"

var rawMu sync.Mutex
var rawID, rawText string

func rememberRaw(id, text string) {
	rawMu.Lock()
	defer rawMu.Unlock()
	rawID, rawText = id, text
}

func LatestTTML(id string) string {
	rawMu.Lock()
	defer rawMu.Unlock()
	if id == rawID {
		return rawText
	}
	return ""
}
