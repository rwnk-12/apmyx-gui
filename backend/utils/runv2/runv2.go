package runv2

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"main/utils/structs"
	"net"
	"net/http"
	"net/url"
	"os"
	// "strings" // REMOVED: Unused import
	"time"

	"github.com/Eyevinn/mp4ff/mp4"
	"github.com/grafov/m3u8"
	"github.com/schollz/progressbar/v3"
)

const prefetchKey = "skd://itunes.apple.com/P000000000/s1/e1"
var ErrTimeout = errors.New("response timed out")

type TimedResponseBody struct {
	timeout   time.Duration
	timer     *time.Timer
	threshold int
	body      io.Reader
}

func (b *TimedResponseBody) Read(p []byte) (int, error) {
	n, err := b.body.Read(p)
	if err != nil {
		return n, err
	}
	if n >= b.threshold {
		b.timer.Reset(b.timeout)
	}
	return n, err
}

func Run(adamId string, playlistUrl string, outfile string, Config structs.ConfigSet) error {
	var err error
	var optstimeout uint = 0
	timeout := time.Duration(optstimeout * uint(time.Millisecond))
	header := make(http.Header)

	req, err := http.NewRequest("GET", playlistUrl, nil)
	if err != nil {
		return err
	}
	req.Header = header
	do, err := (&http.Client{Timeout: timeout}).Do(req)
	if err != nil {
		return err
	}

	segments, err := parseMediaPlaylist(do.Body)
	if err != nil {
		return err
	}
	if len(segments) == 0 || segments[0] == nil {
		return errors.New("no segments extracted from playlist")
	}
	if segments[0].Limit <= 0 {
		return errors.New("non-byterange playlists are currently unsupported")
	}

	parsedUrl, err := url.Parse(playlistUrl)
	if err != nil {
		return err
	}
	fileUrl, err := parsedUrl.Parse(segments[0].URI)
	if err != nil {
		return err
	}

	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)
	req, err = http.NewRequestWithContext(ctx, "GET", fileUrl.String(), nil)
	if err != nil {
		return err
	}
	req.Header = header

	var body io.Reader
	client := &http.Client{Timeout: timeout}
	
	do, err = client.Do(req)
	if err != nil {
		return err
	}
	defer do.Body.Close()
	
	if do.ContentLength > 0 && do.ContentLength < int64(Config.MaxMemoryLimit*1024*1024) {
		var buffer bytes.Buffer
		bar := progressbar.NewOptions64(
			do.ContentLength,
			progressbar.OptionSetDescription("Downloading..."),
			progressbar.OptionShowBytes(true),
			progressbar.OptionClearOnFinish(),
		)
		io.Copy(io.MultiWriter(&buffer, bar), do.Body)
		body = &buffer
		fmt.Print("Downloaded\n")
	} else {
		body = do.Body
	}

	var totalLen int64 = do.ContentLength
	addr := Config.DecryptM3u8Port
	if addr == "" {
		return errors.New("decryption service address (decrypt-m3u8-port) is not configured")
	}
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		return err
	}
	defer Close(conn)

	err = downloadAndDecryptFile(conn, body, outfile, adamId, segments, totalLen, Config)
	if err != nil {
		return err
	}
	fmt.Print("Decrypted\n")
	return nil
}

func downloadAndDecryptFile(conn io.ReadWriter, in io.Reader, outfile string,
	adamId string, playlistSegments []*m3u8.MediaSegment, totalLen int64, Config structs.ConfigSet) error {
	var buffer bytes.Buffer
	var outBuf *bufio.Writer
	MaxMemorySize := int64(Config.MaxMemoryLimit * 1024 * 1024)
	inBuf := bufio.NewReader(in)
	if totalLen > 0 && totalLen <= MaxMemorySize {
		outBuf = bufio.NewWriter(&buffer)
	} else {
		ofh, err := os.Create(outfile)
		if err != nil { return err }
		defer ofh.Close()
		outBuf = bufio.NewWriter(ofh)
	}
	init, offset, err := ReadInitSegment(inBuf)
	if err != nil { return err }
	if init == nil { return errors.New("no init segment found") }

	tracks, err := TransformInit(init)
	if err != nil { return err }
	sanitizeInit(init)
	init.Encode(outBuf)

	bar := progressbar.NewOptions64(totalLen,
		progressbar.OptionSetDescription("Decrypting..."),
		progressbar.OptionShowBytes(true),
		progressbar.OptionClearOnFinish(),
	)
	bar.Add64(int64(offset))
	rw := bufio.NewReadWriter(bufio.NewReader(conn), bufio.NewWriter(conn))
	for i := 0; ; i++ {
		frag, newOffset, err := ReadNextFragment(inBuf, offset)
		if err == io.EOF { break }
		if err != nil { return err }
		
		rawoffset := newOffset - offset
		offset = newOffset
		
		if i >= len(playlistSegments) { return errors.New("mp4 fragment count exceeds playlist segment count") }
		segment := playlistSegments[i]
		if segment.Key != nil {
			if i != 0 {
				SwitchKeys(rw)
			}
			if segment.Key.URI == prefetchKey {
				SendString(rw, "0")
			} else {
				SendString(rw, adamId)
			}
			SendString(rw, segment.Key.URI)
			
			// FIX: Correctly flush the bufio.ReadWriter
			if err := rw.Flush(); err != nil {
				return err
			}
		}
		
		err = DecryptFragment(frag, tracks, rw)
		if err != nil { return fmt.Errorf("decryptFragment: %w", err) }
		
		err = frag.Encode(outBuf)
		if err != nil { return err }
		
		bar.Add64(int64(rawoffset))
	}
	outBuf.Flush()
	if totalLen > 0 && totalLen <= MaxMemorySize {
		ofh, err := os.Create(outfile)
		if err != nil { return err }
		defer ofh.Close()
		_, err = ofh.Write(buffer.Bytes())
		if err != nil { return err }
	}
	return nil
}

func sanitizeInit(init *mp4.InitSegment) error {
	traks := init.Moov.Traks
	if len(traks) > 1 { return errors.New("more than 1 track found") }
	stsd := traks[0].Mdia.Minf.Stbl.Stsd
	if stsd.SampleCount <= 1 { return nil }
	if stsd.SampleCount > 2 { return fmt.Errorf("expected 1 or 2 entries in stsd, got %d", stsd.SampleCount) }
	children := stsd.Children
	if children[0].Type() != children[1].Type() { return errors.New("children in stsd are not of the same type") }
	stsd.Children = children[:1]
	stsd.SampleCount = 1
	return nil
}

func filterResponse(f io.Reader) (*bytes.Buffer, error) {
	buf := &bytes.Buffer{}
	scanner := bufio.NewScanner(f)
	prefix := []byte("#EXT-X-KEY:")
	keyFormat := []byte("streamingkeydelivery")
	for scanner.Scan() {
		lineBytes := scanner.Bytes()
		if bytes.HasPrefix(lineBytes, prefix) && !bytes.Contains(lineBytes, keyFormat) {
			continue
		}
		buf.Write(lineBytes)
		buf.WriteString("\n")
	}
	return buf, scanner.Err()
}

func parseMediaPlaylist(r io.ReadCloser) ([]*m3u8.MediaSegment, error) {
	defer r.Close()
	playlistBuf, err := filterResponse(r)
	if err != nil { return nil, err }
	playlist, listType, err := m3u8.Decode(*playlistBuf, true)
	if err != nil { return nil, err }
	if listType != m3u8.MEDIA { return nil, errors.New("m3u8 not of media type") }
	mediaPlaylist := playlist.(*m3u8.MediaPlaylist)
	return mediaPlaylist.Segments, nil
}

func ReadInitSegment(r io.Reader) (*mp4.InitSegment, uint64, error) {
	var offset uint64 = 0
	init := mp4.NewMP4Init()
	for i := 0; i < 2; i++ {
		box, err := mp4.DecodeBox(offset, r)
		if err != nil { return nil, offset, err }
		boxType := box.Type()
		if boxType != "ftyp" && boxType != "moov" { return nil, offset, fmt.Errorf("unexpected box type %s", boxType) }
		init.AddChild(box)
		offset += box.Size()
	}
	return init, offset, nil
}

func ReadNextFragment(r io.Reader, offset uint64) (*mp4.Fragment, uint64, error) {
	frag := mp4.NewFragment()
	for {
		box, err := mp4.DecodeBox(offset, r)
		if err == io.EOF { return nil, offset, io.EOF }
		if err != nil { return nil, offset, err }
		boxType := box.Type()
		offset += box.Size()
		if boxType == "moof" || boxType == "emsg" || boxType == "prft" {
			frag.AddChild(box)
			continue
		}
		if boxType == "mdat" {
			frag.AddChild(box)
			break
		}
	}
	if frag.Moof == nil { return nil, offset, errors.New("mdat box found without preceding moof box") }
	return frag, offset, nil
}

func FilterSbgpSgpd(children []mp4.Box) ([]mp4.Box, uint64) {
	var bytesRemoved uint64 = 0
	remainingChildren := make([]mp4.Box, 0, len(children))
	for _, child := range children {
		switch box := child.(type) {
		case *mp4.SbgpBox:
			if box.GroupingType == "seam" || box.GroupingType == "seig" { bytesRemoved += child.Size(); continue }
		case *mp4.SgpdBox:
			if box.GroupingType == "seam" || box.GroupingType == "seig" { bytesRemoved += child.Size(); continue }
		}
		remainingChildren = append(remainingChildren, child)
	}
	return remainingChildren, bytesRemoved
}

func TransformInit(init *mp4.InitSegment) (map[uint32]mp4.DecryptTrackInfo, error) {
	di, err := mp4.DecryptInit(init)
	if err != nil { return nil, err }
	tracks := make(map[uint32]mp4.DecryptTrackInfo, len(di.TrackInfos))
	for _, ti := range di.TrackInfos { tracks[ti.TrackID] = ti }
	for _, trak := range init.Moov.Traks {
		stbl := trak.Mdia.Minf.Stbl
		stbl.Children, _ = FilterSbgpSgpd(stbl.Children)
	}
	return tracks, nil
}

func Close(conn io.WriteCloser) error {
	defer conn.Close()
	_, err := conn.Write([]byte{0, 0, 0, 0, 0})
	return err
}

func SwitchKeys(conn io.Writer) error {
	_, err := conn.Write([]byte{0, 0, 0, 0})
	return err
}

func SendString(conn io.Writer, uri string) error {
	if _, err := conn.Write([]byte{byte(len(uri))}); err != nil { return err }
	_, err := io.WriteString(conn, uri)
	return err
}

func cbcsFullSubsampleDecrypt(data []byte, conn *bufio.ReadWriter) error {
	truncatedLen := len(data) & ^0xf
	if truncatedLen == 0 { return nil }
	err := binary.Write(conn, binary.LittleEndian, uint32(truncatedLen))
	if err != nil { return err }
	_, err = conn.Write(data[:truncatedLen])
	if err != nil { return err }
	err = conn.Flush()
	if err != nil { return err }
	_, err = io.ReadFull(conn, data[:truncatedLen])
	return err
}

func cbcsStripeDecrypt(data []byte, conn *bufio.ReadWriter, decryptBlockLen, skipBlockLen int) error {
	size := len(data)
	if size < decryptBlockLen { return nil }
	count := ((size - decryptBlockLen) / (decryptBlockLen + skipBlockLen)) + 1
	totalLen := count * decryptBlockLen
	err := binary.Write(conn, binary.LittleEndian, uint32(totalLen))
	if err != nil { return err }
	pos := 0
	for {
		if size-pos < decryptBlockLen { break }
		_, err = conn.Write(data[pos : pos+decryptBlockLen])
		if err != nil { return err }
		pos += decryptBlockLen
		if size-pos < skipBlockLen { break }
		pos += skipBlockLen
	}
	err = conn.Flush()
	if err != nil { return err }
	pos = 0
	for {
		if size-pos < decryptBlockLen { break }
		_, err = io.ReadFull(conn, data[pos:pos+decryptBlockLen])
		if err != nil { return err }
		pos += decryptBlockLen
		if size-pos < skipBlockLen { break }
		pos += skipBlockLen
	}
	return nil
}

func cbcsDecryptRaw(data []byte, conn *bufio.ReadWriter, decryptBlockLen, skipBlockLen int) error {
	if skipBlockLen == 0 {
		return cbcsFullSubsampleDecrypt(data, conn)
	}
	return cbcsStripeDecrypt(data, conn, decryptBlockLen, skipBlockLen)
}

func cbcsDecryptSample(sample []byte, conn *bufio.ReadWriter, subSamplePatterns []mp4.SubSamplePattern, tenc *mp4.TencBox) error {
	decryptBlockLen := int(tenc.DefaultCryptByteBlock) * 16
	skipBlockLen := int(tenc.DefaultSkipByteBlock) * 16
	var pos uint32 = 0
	if len(subSamplePatterns) == 0 {
		return cbcsDecryptRaw(sample, conn, decryptBlockLen, skipBlockLen)
	}
	for _, ss := range subSamplePatterns {
		pos += uint32(ss.BytesOfClearData)
		if ss.BytesOfProtectedData > 0 {
			err := cbcsDecryptRaw(sample[pos:pos+ss.BytesOfProtectedData], conn, decryptBlockLen, skipBlockLen)
			if err != nil { return err }
			pos += ss.BytesOfProtectedData
		}
	}
	return nil
}

func cbcsDecryptSamples(samples []mp4.FullSample, conn *bufio.ReadWriter, tenc *mp4.TencBox, senc *mp4.SencBox) error {
	for i := range samples {
		var subSamplePatterns []mp4.SubSamplePattern
		if len(senc.SubSamples) != 0 {
			subSamplePatterns = senc.SubSamples[i]
		}
		err := cbcsDecryptSample(samples[i].Data, conn, subSamplePatterns, tenc)
		if err != nil { return err }
	}
	return nil
}

func DecryptFragment(frag *mp4.Fragment, tracks map[uint32]mp4.DecryptTrackInfo, conn *bufio.ReadWriter) error {
	moof := frag.Moof
	var bytesRemoved uint64 = 0
	for _, traf := range moof.Trafs {
		ti, ok := tracks[traf.Tfhd.TrackID]
		if !ok { return fmt.Errorf("could not find decryption info for track %d", traf.Tfhd.TrackID) }
		if ti.Sinf == nil { continue }
		if ti.Sinf.Schm.SchemeType != "cbcs" { return fmt.Errorf("scheme type %s not supported", ti.Sinf.Schm.SchemeType) }
		hasSenc, isParsed := traf.ContainsSencBox()
		if !hasSenc { return errors.New("no senc box in traf") }
		var senc *mp4.SencBox
		if traf.Senc != nil { senc = traf.Senc } else { senc = traf.UUIDSenc.Senc }
		if !isParsed {
			err := senc.ParseReadBox(ti.Sinf.Schi.Tenc.DefaultPerSampleIVSize, traf.Saiz)
			if err != nil { return err }
		}
		samples, err := frag.GetFullSamples(ti.Trex)
		if err != nil { return err }
		err = cbcsDecryptSamples(samples, conn, ti.Sinf.Schi.Tenc, senc)
		if err != nil { return err }
		
		removed := traf.RemoveEncryptionBoxes()
		var newChildren []mp4.Box
		for _, child := range traf.Children {
			if child != nil {
				newChildren = append(newChildren, child)
			}
		}
		traf.Children = newChildren
		bytesRemoved += removed
		
		filteredChildren, sxxxRemoved := FilterSbgpSgpd(traf.Children)
		traf.Children = filteredChildren
		bytesRemoved += sxxxRemoved
	}
	_, psshBytesRemoved := moof.RemovePsshs()
	bytesRemoved += psshBytesRemoved
	for _, traf := range moof.Trafs {
		for _, trun := range traf.Truns {
			trun.DataOffset -= int32(bytesRemoved)
		}
	}
	return nil
}