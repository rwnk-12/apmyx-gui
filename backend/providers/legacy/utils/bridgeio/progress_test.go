package bridgeio

import "testing"

func TestProgressBoundariesAndUnknownTotals(t *testing.T) {
	var records []map[string]any
	Sink = func(data map[string]any) { records = append(records, data) }
	defer func() { Sink = nil }()
	counter := New("downloading", 100)
	counter.Add(25)
	counter.Finish()
	if records[0]["phase_percent"] != float64(0) || records[len(records)-1]["phase_percent"] != float64(100) {
		t.Fatal("phase boundaries were buffered")
	}
	records = nil
	unknown := New("processing", -1)
	unknown.Add(1)
	if records[0]["phase_percent"] != nil {
		t.Fatal("unknown total produced a false percentage")
	}
}
