package bridgeio

import (
	"os"
	"strconv"
	"sync"
	"time"
)

var Sink func(map[string]any)
var outputLock sync.Mutex
var streamIndex, streamCount = 1, 1

func SetStream(index, count int) {
	outputLock.Lock()
	defer outputLock.Unlock()
	streamIndex, streamCount = index, count
}

func Emit(data map[string]any) {
	if Sink == nil {
		return
	}
	outputLock.Lock()
	defer outputLock.Unlock()
	if _, ok := data["phase"]; ok && streamCount > 1 {
		data["stream_index"], data["stream_count"] = streamIndex, streamCount
	}
	Sink(data)
}

func Interval() time.Duration {
	value, err := strconv.Atoi(os.Getenv("APMYX_PROGRESS_INTERVAL_MS"))
	if err != nil || value < 1 || value > 1000 {
		value = 50
	}
	return time.Duration(value) * time.Millisecond
}

type Counter struct {
	phase string
	total int64
	done  int64
	last  time.Time
	mu    sync.Mutex
}

func New(phase string, total int64) *Counter {
	counter := &Counter{phase: phase, total: total}
	counter.Set(0)
	return counter
}

func (c *Counter) send(finish bool) {
	if Sink == nil {
		return
	}
	if !finish && !c.last.IsZero() && time.Since(c.last) < Interval() {
		return
	}
	var percent any
	if c.total > 0 {
		percent = float64(c.done) / float64(c.total) * 100
	}
	if finish {
		percent = 100.0
	}
	data := map[string]any{"type": "track_progress", "phase": c.phase, "phase_percent": percent}
	if c.phase == "downloading" {
		data["downloaded_bytes"] = c.done
		if c.total > 0 {
			data["total_bytes"] = c.total
		}
	}
	Emit(data)
	c.last = time.Now()
}

func (c *Counter) Set(done int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.done = done
	c.send(c.total > 0 && c.done >= c.total)
}

func (c *Counter) Add(done int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.done += done
	c.send(c.total > 0 && c.done >= c.total)
}

func (c *Counter) Finish() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.send(true)
}

func (c *Counter) Write(data []byte) (int, error) {
	c.Add(int64(len(data)))
	return len(data), nil
}
