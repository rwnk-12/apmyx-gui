package main

import (
	"apmyx/legacy/utils/ampapi"
	"apmyx/legacy/utils/bridgeio"
	lyricscache "apmyx/legacy/utils/lyrics"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sync"
)

var machineOutput io.Writer = os.Stdout
var machineMutex sync.Mutex

func bridgeMetadata(value string) {
	machineMutex.Lock()
	defer machineMutex.Unlock()
	fmt.Fprintln(machineOutput, "AMDL_JSON_START")
	fmt.Fprintln(machineOutput, value)
	fmt.Fprintln(machineOutput, "AMDL_JSON_END")
}

func bridgeSummary(value any) {
	machineMutex.Lock()
	defer machineMutex.Unlock()
	data, err := json.Marshal(value)
	if err == nil {
		fmt.Fprintf(machineOutput, "AMDL_SUMMARY::%s\n", data)
	}
}

func initializeBridgeProgress() {
	if os.Getenv("APMYX_BRIDGE") != "1" {
		return
	}
	bridgeio.Sink = emitProgress
}

func emitProgress(data map[string]any) {
	machineMutex.Lock()
	defer machineMutex.Unlock()
	value, err := json.Marshal(data)
	if err == nil && progressWriter != nil {
		_, _ = progressWriter.WriteString("AMDL_PROGRESS::" + string(value) + "\n")
		_ = progressWriter.Flush()
	}
}

func sharedTagging() bool {
	return os.Getenv("APMYX_BRIDGE") == "1" && os.Getenv("APMYX_SHARED_TAGGING") == "1"
}

func bridgeArtifact(path string, track, album, playlist any, position, total, discTotal int, lyrics, coverPath string) error {
	payload := map[string]any{"version": 1, "path": path, "track": track, "album": album, "playlist": playlist, "position": position, "total": total, "disc_total": discTotal, "lyrics": lyrics}
	if value, ok := track.(ampapi.TrackRespData); ok {
		payload["lyrics_ttml"] = lyricscache.LatestTTML(value.ID)
	}
	if cover, err := os.ReadFile(coverPath); err == nil {
		payload["cover"] = base64.StdEncoding.EncodeToString(cover)
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	machineMutex.Lock()
	defer machineMutex.Unlock()
	if _, err = progressWriter.WriteString("AMDL_ARTIFACT::" + string(data) + "\n"); err != nil {
		return err
	}
	return progressWriter.Flush()
}
