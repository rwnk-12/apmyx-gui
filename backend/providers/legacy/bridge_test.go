package main

import (
	"apmyx/legacy/utils/task"
	"bufio"
	"bytes"
	"encoding/json"
	"strings"
	"sync"
	"testing"
)

func TestSharedTaggingEmitsRawMetadataWithoutOpeningOutput(t *testing.T) {
	t.Setenv("APMYX_BRIDGE", "1")
	t.Setenv("APMYX_SHARED_TAGGING", "1")
	var output bytes.Buffer
	previous := progressWriter
	progressWriter = bufio.NewWriter(&output)
	defer func() { progressWriter = previous }()
	track := &task.Track{ID: "7", SavePath: "not-created.m4a"}
	track.Resp.Attributes.Name = "Title"
	if err := writeMP4Tags(track, "Lyrics", nil); err != nil {
		t.Fatal(err)
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(strings.TrimPrefix(output.String(), "AMDL_ARTIFACT::"))), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["path"] != "not-created.m4a" || payload["lyrics"] != "Lyrics" {
		t.Fatal("artifact payload lost metadata")
	}
}

func TestBridgeSelectionSkipsWithoutChangingCounters(t *testing.T) {
	t.Setenv("APMYX_TRACK_IDS", "2")
	before := counter
	ripTrack(&task.Track{ID: "3"}, "", "", nil)
	if counter != before {
		t.Fatal("unselected track affected counters")
	}
}

func TestBridgeConcurrentProgressAndArtifactsStayValid(t *testing.T) {
	var output bytes.Buffer
	previous := progressWriter
	progressWriter = bufio.NewWriter(&output)
	defer func() { progressWriter = previous }()
	var workers sync.WaitGroup
	for index := 0; index < 20; index++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			emitProgress(map[string]any{"type": "track_progress", "name": "Title \"quoted\" 日本"})
			if err := bridgeArtifact("output.m4a", map[string]any{"name": strings.Repeat("日本", 3000)}, nil, nil, 1, 1, 1, "", ""); err != nil {
				t.Error(err)
			}
		}()
	}
	workers.Wait()
	lines := strings.Split(strings.TrimSpace(output.String()), "\n")
	if len(lines) != 40 {
		t.Fatalf("got %d events, want 40", len(lines))
	}
	for _, line := range lines {
		parts := strings.SplitN(line, "::", 2)
		if len(parts) != 2 || !json.Valid([]byte(parts[1])) {
			t.Fatal("concurrent writes corrupted a machine event")
		}
	}
}
