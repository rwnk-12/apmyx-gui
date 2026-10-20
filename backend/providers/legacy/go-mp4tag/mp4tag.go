package mp4tag

import (
	"bytes"
	"fmt"
	"io"
	"os"
)

func (mp4 *MP4) UpperCustom(b bool) { 
	mp4.upperCustom = b
}

func (mp4 *MP4) Close() error { 
	return mp4.f.Close()
}

func (mp4 *MP4) Read() (*MP4Tags, error) {
	tags, _, err := mp4.actualRead()
	return tags, err
}

func (mp4 *MP4) Write(tags *MP4Tags, delStrings []string) error {
	if tags == nil && len(delStrings) == 0 {
		return nil
	}
	err := mp4.actualWrite(tags, delStrings)
	return err
}

func (mp4 *MP4) checkHeader() error {
	buf := make([]byte, 8)
	_, err := mp4.f.Seek(4, io.SeekStart)
	if err != nil {
		return err
	}
	_, err = io.ReadFull(mp4.f, buf)
	if err != nil {
		return err
	}

	if !bytes.Equal(buf[:4], []byte{0x66, 0x74, 0x79, 0x70}) {
		return &ErrInvalidMagic{}
	}
	for _, ftyp := range ftyps {
		if bytes.Equal(buf[4:], ftyp) {
			return nil
		}
	}
	return &ErrUnsupportedFtyp{
		Msg: "unsupported ftyp: " + fmt.Sprintf("%x", buf[4:]),
	}
}

func Open(trackPath string) (*MP4, error) {
	f, err := os.Open(trackPath)
	if err != nil {
		return nil, err
	}
	stat, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}

	mp4 := &MP4{
		f: f,
		size : stat.Size(),
		path: trackPath,
		upperCustom: true,
	}
	err = mp4.checkHeader()
	if err != nil {
		f.Close()
		return nil, err
	}
	return mp4, nil
}