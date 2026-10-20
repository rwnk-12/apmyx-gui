package mp4tag

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
)

const BufSize = 4096*1024

func overwriteTags(mergedTags, tags *MP4Tags, delStrings []string) *MP4Tags{
	if containsStr(delStrings, "alltags") {
		mergedPics := mergedTags.Pictures
		mergedTags = &MP4Tags{}
		mergedTags.Pictures = mergedPics
	} else if containsStr(delStrings, "allcustom") {
		mergedTags.Custom = map[string]string{}
	}
	if containsStr(delStrings, "allothercustom") {
		mergedTags.OtherCustom = map[string][]string{}
	}

	if mergedTags.Custom == nil {
		mergedTags.Custom = map[string]string{}
	}
	if mergedTags.OtherCustom == nil {
		mergedTags.OtherCustom = map[string][]string{}
	}

	if containsStr(delStrings,  "album") {
		mergedTags.Album = ""
	}

	if containsStr(delStrings,  "albumartist") {
		mergedTags.AlbumArtist = ""
	}

	if containsStr(delStrings,  "albumartistsort") {
		mergedTags.AlbumArtistSort = ""
	}

	if containsStr(delStrings,  "albumsort") {
		mergedTags.AlbumSort = ""
	}

	if containsStr(delStrings,  "artist") {
		mergedTags.Artist = ""
	}

	if containsStr(delStrings,  "artistsort") {
		mergedTags.ArtistSort = ""
	}

	if containsStr(delStrings,  "bpm") {
		mergedTags.BPM = 0
	}

	if containsStr(delStrings,  "comment") {
		mergedTags.Comment = ""
	}

	if containsStr(delStrings,  "composer") {
		mergedTags.Composer = ""
	}

	if containsStr(delStrings,  "composersort") {
		mergedTags.ComposerSort = ""
	}

	if containsStr(delStrings,  "conductor") {
		mergedTags.Conductor = ""
	}

	if containsStr(delStrings,  "copyright") {
		mergedTags.Copyright = ""
	}

	if containsStr(delStrings,  "customgenre") {
		mergedTags.CustomGenre = ""
	}

	if containsStr(delStrings,  "date") {
		mergedTags.Date = ""
	}

	if containsStr(delStrings,  "description") {
		mergedTags.Description = ""
	}

	if containsStr(delStrings,  "director") {
		mergedTags.Director = ""
	}

	if containsStr(delStrings,  "discnumber") || containsStr(delStrings,  "disknumber") {
		mergedTags.DiscNumber = 0
	}

	if containsStr(delStrings,  "disctotal") || containsStr(delStrings,  "disktotal") {
		mergedTags.DiscTotal = 0
	}

	if containsStr(delStrings,  "genre") {
		mergedTags.Genre = GenreNone
	}

	if containsStr(delStrings,  "itunesadvisory") {
		mergedTags.ItunesAdvisory = ItunesAdvisoryNone
	}

	if containsStr(delStrings,  "itunesalbumid") {
		mergedTags.ItunesAlbumID = 0
	}	

	if containsStr(delStrings,  "itunesartistid") {
		mergedTags.ItunesArtistID = 0
	}

	if containsStr(delStrings,  "lyrics") {
		mergedTags.Lyrics = ""
	}

	if containsStr(delStrings,  "narrator") {
		mergedTags.Narrator = ""
	}

	if containsStr(delStrings,  "publisher") {
		mergedTags.Publisher = ""
	}

	if containsStr(delStrings,  "title") {
		mergedTags.Title = ""
	}

	if containsStr(delStrings,  "titlesort") {
		mergedTags.TitleSort = ""
	}

	if containsStr(delStrings,  "tracknumber") {
		mergedTags.TrackNumber = 0
	}

	if containsStr(delStrings,  "tracktotal") {
		mergedTags.TrackTotal = 0
	}

	if containsStr(delStrings,  "year") {
		mergedTags.Year = 0
	}

	if containsStr(delStrings, "allpictures") {
		mergedTags.Pictures = []*MP4Picture{}
	}

	if tags.Album != "" {
		mergedTags.Album = tags.Album
	}

	if tags.AlbumSort != "" {
		mergedTags.AlbumSort = tags.AlbumSort
	}

	if tags.AlbumArtist != "" {
		mergedTags.AlbumArtist = tags.AlbumArtist
	}

	if tags.AlbumArtistSort != "" {
		mergedTags.AlbumArtistSort = tags.AlbumArtistSort
	}

	if tags.Artist != "" {
		mergedTags.Artist = tags.Artist
	}

	if tags.ArtistSort != "" {
		mergedTags.ArtistSort = tags.ArtistSort
	}

	if tags.BPM > 0 {
		mergedTags.BPM = tags.BPM
	}

	if tags.Comment != "" {
		mergedTags.Comment = tags.Comment
	}

	if tags.Composer != "" {
		mergedTags.Composer = tags.Composer
	}

	if tags.ComposerSort != "" {
		mergedTags.ComposerSort = tags.ComposerSort
	}
	if tags.Conductor != "" {
		mergedTags.Conductor = tags.Conductor
	}

	if tags.Copyright != "" {
		mergedTags.Copyright = tags.Copyright
	}

	if tags.CustomGenre != "" {
		mergedTags.CustomGenre = tags.CustomGenre
	}

	if tags.Date != "" {
		mergedTags.Date = tags.Date
	}

	if tags.Description != "" {
		mergedTags.Description = tags.Description
	}

	if tags.Director != "" {
		mergedTags.Director = tags.Director
	}

	if tags.DiscNumber > 0 {
		mergedTags.DiscNumber = tags.DiscNumber
	}

	if tags.DiscTotal > 0 {
		mergedTags.DiscTotal = tags.DiscTotal
	}

	if tags.ItunesAdvisory != ItunesAdvisoryNone {
		mergedTags.ItunesAdvisory = tags.ItunesAdvisory
	}

	if tags.ItunesAlbumID > 0 {
		mergedTags.ItunesAlbumID = tags.ItunesAlbumID
	}

	if tags.ItunesArtistID > 0 {
		mergedTags.ItunesArtistID = tags.ItunesArtistID
	}

	if tags.Lyrics != "" {
		mergedTags.Lyrics = tags.Lyrics
	}

	if tags.Narrator != "" {
		mergedTags.Narrator = tags.Narrator
	}

	if tags.Publisher != "" {
		mergedTags.Publisher = tags.Publisher
	}

	if tags.Title != "" {
		mergedTags.Title = tags.Title
	}

	if tags.TitleSort != "" {
		mergedTags.TitleSort = tags.TitleSort
	}

	if tags.TrackNumber > 0 {
		mergedTags.TrackNumber = tags.TrackNumber
	}

	if tags.TrackTotal > 0 {
		mergedTags.TrackTotal = tags.TrackTotal
	}

	if tags.Year > 0 {
		mergedTags.Year = tags.Year
	}	

	if tags.Genre != GenreNone {
		mergedTags.Genre = tags.Genre
	}

	for k, v := range tags.Custom {
		if containsStr(delStrings, "custom:"+k) {
			continue
		}
		if v != "" {
			mergedTags.Custom[k] = v
		}
	}

	for k, v := range tags.OtherCustom {
		if containsStr(delStrings, "custom:"+k) || len(v) < 1 {
			continue
		}
		_, ok := mergedTags.OtherCustom[k]
		if ok {
			mergedTags.OtherCustom[k] = append(mergedTags.OtherCustom[k], v...)
		} else {
			mergedTags.OtherCustom[k] = v
		}

	}

	var filteredPics []*MP4Picture

	for idx, p := range mergedTags.Pictures {
		if !containsStr(delStrings,  fmt.Sprintf("picture:%d", idx+1)) {
			filteredPics = append(filteredPics, p)
		}
	}

	for _, p := range tags.Pictures {
		filteredPics = append(filteredPics, p)
	}

	mergedTags.Pictures = filteredPics
	return mergedTags
}

func putI16BE(n int16) []byte {
	buf := make([]byte, 2)

	binary.BigEndian.PutUint16(buf, uint16(n))
	return buf
}

func putI32BE(n int32) []byte {
	buf := make([]byte, 4)
	binary.BigEndian.PutUint32(buf, uint32(n))
	return buf
}

func putI64BE(n int64) []byte {
	buf := make([]byte, 8)
	binary.BigEndian.PutUint64(buf, uint64(n))
	return buf
}

func (mp4 MP4) updateChunkOffsets(outF *os.File, boxes MP4Boxes, oldIlistSize, newIlistSize int64) error {
	stco := boxes.getBoxByPath("moov.trak.mdia.minf.stbl.stco")
	_, err := mp4.f.Seek(stco.StartOffset+12, io.SeekStart)
	if err != nil {
		return err
	}
	_, err = outF.Seek(stco.StartOffset+16, io.SeekStart)
	if err != nil {
		return err
	}
	count, err := mp4.readI32BE()
	if err != nil {
		return err
	}
    if stco.BoxSize != int64(count) * 4 + 16 {
    	return &ErrInvalidStcoSize{}
    }

    for i := int32(1);  i<=count; i++ {
    	offset, err  := mp4.readI32BE()
    	if err != nil {
    		return err
    	}
    	offsetBytes := putI32BE(offset-int32(oldIlistSize)+int32(newIlistSize))
    	_, err = outF.Write(offsetBytes)
    	if err != nil {
    		return err
    	}
    }

    return nil
}

func (mp4 MP4) readToOffset(f *os.File, startOffset int64) error {
	_, err := mp4.f.Seek(0, io.SeekStart)
	if err != nil {
		return err
	}
	buf := make([]byte, BufSize)
	var totalRead int64

	for {
		read, err := mp4.f.Read(buf)
		if err != nil { 
			if err == io.EOF {
                break
            }
            return err
		}
		readI64 := int64(read)
		totalRead += readI64
		if totalRead > startOffset {
			_, err = f.Write(buf[:readI64+startOffset-totalRead])
			if err != nil {
				return err
			}
			break
		}
		_, err = f.Write(buf)
		if err != nil {
			return err
		}
	}
	return nil
}


func writeRegular(f *os.File, boxName, val string, prefix bool) error {
	// boxSize := utf8.RuneCountInString(val) + 24
	valBytes := []byte(val)
	boxSize := len(valBytes) + 24
	boxSizeI32 := int32(boxSize)
	boxSizeBytes := putI32BE(boxSizeI32)
	_, err := f.Write(boxSizeBytes)
	if err != nil {
		return err
	}
	if prefix {
		_, err = f.Write([]byte{0xA9})
		if err != nil {
			return err
		}
	}
	_, err = f.WriteString(boxName)
	if err != nil {
		return err
	}
	boxSizeBytes = putI32BE(boxSizeI32-8)
	_, err = f.Write(boxSizeBytes)
	if err != nil {
		return err
	}	
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}

	_, err = f.Write(
		[]byte{0x0, 0x0, 0x0, 0x01, 0x0, 0x0, 0x0, 0x0})
	if err != nil {
		return err
	}

	_, err = f.Write(valBytes)
	return err
}

func writeGenre(f *os.File, genre Genre) error {
	_, err := f.Write([]byte{0x0, 0x0, 0x0, 0x1A})
	if err != nil {
		return err
	}
	_, err = f.WriteString("gnre")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x12})
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}
	_, err = f.Write(bytes.Repeat([]byte{0x0}, 9))
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{byte(genre)})
	return err
}

func writeTrknDisc(f *os.File, n, total int16, isTrkn bool) error {
	var boxSize int32 = 30
	if n < 0 {
		n = 0
	}
	if total < 0 {
		total = 0
	}
	if isTrkn {
		boxSize += 2
	}
	boxSizeBytes := putI32BE(boxSize)
	_, err := f.Write(boxSizeBytes)
	if err != nil {
		return err
	}
	if isTrkn {
		_, err = f.WriteString("trkn")
	} else {
		_, err = f.WriteString("disk")
	}
	if err != nil {
		return err
	}
	boxSizeBytes = putI32BE(boxSize-8)
	if err != nil {
		return err
	}
	_, err = f.Write(boxSizeBytes)
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")	
	if err != nil {
		return err
	}
	_, err = f.Write(bytes.Repeat([]byte{0x0}, 10))
	if err != nil {
		return err
	}

	nBytes := putI16BE(n)
	_, err = f.Write(nBytes)
	if err != nil {
		return err
	}
	totalBytes := putI16BE(total)
	_, err = f.Write(totalBytes)
	if err != nil {
		return err
	}
	if isTrkn {
		_, err = f.Write([]byte{0x0, 0x0})
		return err
	}
	return nil
}

func writeBPM(f *os.File, bpm int16) error {
	_, err := f.Write([]byte{0x0, 0x0, 0x0, 0x1A})
	if err != nil {
		return err
	}
	_, err = f.WriteString("tmpo")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x12})
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}
	_, err = f.Write(
		[]byte{0x0, 0x0, 0x0, 0x15, 0x0, 0x0, 0x0, 0x0})
	if err != nil {
		return err
	}
	bpmBytes := putI16BE(bpm)
	_, err = f.Write(bpmBytes)
	return err
}

func writeAdvisory(f *os.File, advisory ItunesAdvisory) error {
	_, err := f.Write([]byte{0x0, 0x0, 0x0, 0x19})
	if err != nil {
		return err
	}
	_, err = f.WriteString("rtng")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x11})
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x15, 0x0, 0x0, 0x0, 0x0})
	if err != nil {
		return err
	}	
	_, err = f.Write([]byte{byte(advisory)})
	return err
}

func writeItunesAlbumID(f *os.File, albumID int64) error {
	_, err := f.Write([]byte{0x0, 0x0, 0x0, 0x20})
	if err != nil {
		return err
	}	
	_, err = f.WriteString("plID")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x18})
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}
	_, err = f.Write(
		[]byte{0x0, 0x0, 0x0, 0x15, 0x0, 0x0, 0x0, 0x0})
	if err != nil {
		return err
	}
	albumIDBytes := putI64BE(albumID)
	_, err = f.Write(albumIDBytes)
	return err
}

func writeItunesArtistID(f *os.File, artistID int64) error {
	_, err := f.Write([]byte{0x0, 0x0, 0x0, 0x20})
	if err != nil {
		return err
	}	
	_, err = f.WriteString("atID")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x18})
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}
	_, err = f.Write(
		[]byte{0x0, 0x0, 0x0, 0x15, 0x0, 0x0, 0x0, 0x0})
	if err != nil {
		return err
	}
	artistIDBytes := putI64BE(artistID)
	_, err = f.Write(artistIDBytes)
	return err
}

func writeCustom(f *os.File, name, value string, upper bool, others map[string][]string) error {	
	valueBytes := []byte(value)
	valueSize := len(valueBytes)

	if upper {
		name = strings.ToUpper(name)
	}
	nameUpperBytes := []byte(name)
	nameSize := len(nameUpperBytes)

	totalSize := nameSize+valueSize+64
	otherCust, _ := others[name]

	for _, other := range otherCust {
		totalSize += len([]byte(other)) + 16
	}

	// 48
	sizeBytes := putI32BE(int32(totalSize))
	_, err := f.Write(sizeBytes)
	if err != nil {
		return err
	}
	_, err = f.WriteString("----")
	if err != nil {
		return err
	}
	_, err = f.Write([]byte{0x0, 0x0, 0x0, 0x1C})
	if err != nil {
		return err
	}	
	_, err = f.WriteString("mean")
	if err != nil {
		return err
	}
	_, err = f.Write(bytes.Repeat([]byte{0x0}, 4))
	if err != nil {
		return err
	}
	_, err = f.WriteString("com.apple.iTunes")
	if err != nil {
		return err
	}
	sizeBytes = putI32BE(int32(nameSize)+12)
	_, err = f.Write(sizeBytes)
	if err != nil {
		return err
	}
	_, err = f.WriteString("name")
	if err != nil {
		return err
	}
	_, err = f.Write(bytes.Repeat([]byte{0x0}, 4))
	if err != nil {
		return err
	}
	_, err = f.Write(nameUpperBytes)
	if err != nil {
		return err
	}
	sizeBytes = putI32BE(int32(valueSize)+16)
	_, err = f.Write(sizeBytes)
	if err != nil {
		return err
	}
	_, err = f.WriteString("data")
	if err != nil {
		return err
	}
	_, err = f.Write(
		[]byte{0x0, 0x0, 0x0, 0x01, 0x0, 0x0, 0x0, 0x0})
	if err != nil {
		return err
	}
	_, err = f.Write(valueBytes)
	if err != nil {
		return err
	}


	for _, v := range otherCust {
		valueBytes = []byte(v)
		valueSize = len(valueBytes)
		sizeBytes = putI32BE(int32(valueSize)+16)
		_, err = f.Write(sizeBytes)
		if err != nil {
			return err
		}
		_, err = f.WriteString("data")
		if err != nil {
			return err
		}
		_, err = f.Write(
			[]byte{0x0, 0x0, 0x0, 0x01, 0x0, 0x0, 0x0, 0x0})
		if err != nil {
			return err
		}
		_, err = f.Write(valueBytes)
		if err != nil {
			return err
		}
	}

	return nil
}

func getPicFormat(imageType ImageType, magic []byte) uint8 {
	if imageType == ImageTypeAuto {
		if bytes.Equal(magic, []byte{0x89, 0x50, 0x4E, 0x47}) {
			return 0xE
		}
	}
	if imageType == ImageTypePNG {
		return 0xE
	}
	return 0x0D
}

func writePics(f *os.File, pics []*MP4Picture) error {
	var boxSize int32 = 8
	for _, pic := range pics {
		dataSize := len(pic.Data)
		if dataSize < 1 {
			continue
		}
		boxSize += int32(dataSize + 16)
	}
	if boxSize == 8 {
		return nil
	}

	boxSizeBytes := putI32BE(boxSize)
	_, err := f.Write(boxSizeBytes)
	if err != nil {
		return err
	}
	_, err = f.WriteString("covr")
	if err != nil {
		return err
	}

	for _, pic := range pics {
		dataSize := len(pic.Data)
		if dataSize < 1 {
			continue
		}
		boxSizeBytes = putI32BE(int32(dataSize+16))
		_, err = f.Write(boxSizeBytes)
		if err != nil {
			return err
		}
		_, err = f.WriteString("data")
		if err != nil {
			return err
		}

		format := getPicFormat(pic.Format, pic.Data[:4])
		_, err = f.Write([]byte{0x0, 0x0, 0x0, format, 0x0, 0x0, 0x0, 0x0})
		if err != nil {
			return err
		}
		_, err = f.Write(pic.Data)
		if err != nil {
			return err
		}
	}

	return nil
}

func resizeBoxes(f *os.File, boxes MP4Boxes, oldIlstSize, newIlistSize int64) error {
	moov := boxes.getBoxByPath("moov")
	udta := boxes.getBoxByPath("moov.udta")
	meta := boxes.getBoxByPath("moov.udta.meta")

	sizeBytes := putI32BE(int32(newIlistSize))
	_, err := f.Write(sizeBytes)
	if err != nil {
		return err
	}

	_, err = f.Seek(moov.StartOffset, io.SeekStart)
	if err != nil {
		return err
	}
	newMoovSize := moov.BoxSize - oldIlstSize + newIlistSize
	sizeBytes = putI32BE(int32(newMoovSize))
	_, err = f.Write(sizeBytes)
	if err != nil {
		return err
	}

	_, err = f.Seek(udta.StartOffset, io.SeekStart)
	if err != nil {
		return err
	}
	newUdtaSize := udta.BoxSize - oldIlstSize + newIlistSize
	sizeBytes = putI32BE(int32(newUdtaSize))
	_, err = f.Write(sizeBytes)
	if err != nil {
		return err
	}

	_, err = f.Seek(meta.StartOffset, io.SeekStart)
	if err != nil {
		return err
	}
	newMetaSize := meta.BoxSize - oldIlstSize + newIlistSize
	sizeBytes = putI32BE(int32(newMetaSize))
	_, err = f.Write(sizeBytes)
	return err
}

func (mp4 MP4) writeRemaining(f *os.File) error {
	buf := make([]byte, BufSize)
	for {
		read, err := mp4.f.Read(buf)
		if err != nil {
			if err == io.EOF {
                break
            }
			return err
		}
		if read < BufSize {
			_, err := f.Write(buf[:read])
			if err != nil {
				return err
			}
		} else {
			_, err = f.Write(buf)
			if err != nil {
				return err
			}
		}
	}
	return nil
}

func (mp4 MP4) writeTags(boxes MP4Boxes, tags *MP4Tags, tempPath string) error {
	ilst := boxes.getBoxByPath("moov.udta.meta.ilst")
    oldIlstSize := ilst.BoxSize
    f, err := os.OpenFile(tempPath, os.O_CREATE|os.O_WRONLY, 0644)
    if err != nil {
    	return err
    }
    defer f.Close()
    err = mp4.readToOffset(f, ilst.StartOffset)
    if err != nil {
    	return err
    }
    ilstStartOffset, err := getPos(f)
    if err != nil {
    	return err
    }

   	_, err = f.Write(bytes.Repeat([]byte{0x0}, 4))
	if err != nil {
		return err
	}
	_, err = f.WriteString("ilst")
	if err != nil {
		return err
	}
	if tags.Title != "" {
		err = writeRegular(f, "nam", tags.Title, true)
		if err != nil {
			return err
		}
	}
	if tags.TitleSort != "" {
		err = writeRegular(f, "sonm", tags.TitleSort, false)
		if err != nil {
			return err
		}
	}
	if tags.Album != "" {
		err = writeRegular(f, "alb", tags.Album, true)
		if err != nil {
			return err
		}
	}
	if tags.AlbumSort != "" {
		err = writeRegular(f, "soal", tags.AlbumSort, false)
		if err != nil {
			return err
		}
	}

	if tags.AlbumArtist != "" {
		err = writeRegular(f, "aART", tags.AlbumArtist, false)
		if err != nil {
			return err
		}
	}

	if tags.AlbumArtistSort != "" {
		err = writeRegular(f, "soaa", tags.AlbumArtistSort, false)
		if err != nil {
			return err
		}
	}

	if tags.Artist != "" {
		err = writeRegular(f, "ART", tags.Artist, true)
		if err != nil {
			return err
		}
	}

	if tags.ArtistSort != "" {
		err = writeRegular(f, "soar", tags.ArtistSort, false)
		if err != nil {
			return err
		}
	}

	if tags.Comment != "" {
		err = writeRegular(f, "cmt", tags.Comment, true)
		if err != nil {
			return err
		}
	}

	if tags.Composer != "" {
		err = writeRegular(f, "wrt", tags.Composer, true)
		if err != nil {
			return err
		}
	}

	if tags.ComposerSort != "" {
		err = writeRegular(f, "soco", tags.ComposerSort, false)
		if err != nil {
			return err
		}
	}

	if tags.Copyright != "" {
		err = writeRegular(f, "cprt", tags.Copyright, false)
		if err != nil {
			return err
		}
	}

	if tags.Lyrics != "" {
		err = writeRegular(f, "lyr", tags.Lyrics, true)
		if err != nil {
			return err
		}
	}

	if tags.CustomGenre != "" {
		err = writeRegular(f, "gen", tags.CustomGenre, true)
		if err != nil {
			return err
		}
	}

	if tags.Description != "" {
		err = writeRegular(f, "desc", tags.Description, false)
		if err != nil {
			return err
		}
	}

	if tags.Publisher != "" {
		err = writeRegular(f, "pub", tags.Publisher, true)
		if err != nil {
			return err
		}
	}	

	if tags.Conductor != "" {
		err = writeRegular(f, "con", tags.Conductor, true)
		if err != nil {
			return err
		}
	}

	if tags.ItunesAdvisory != ItunesAdvisoryNone {
		err = writeAdvisory(f, tags.ItunesAdvisory)
		if err != nil {
			return err
		}
	}

	if tags.ItunesAlbumID > 0  {
		err = writeItunesAlbumID(f, tags.ItunesAlbumID)
		if err != nil {
			return err
		}
	}

	if tags.ItunesArtistID > 0  {
		err = writeItunesArtistID(f, tags.ItunesArtistID)
		if err != nil {
			return err
		}
	}

	if tags.TrackNumber > 0 || tags.TrackTotal > 0 {
		err = writeTrknDisc(f, tags.TrackNumber, tags.TrackTotal, true)
		if err != nil {
			return err
		}		
	}

	if tags.DiscNumber > 0 || tags.DiscTotal > 0 {
		err = writeTrknDisc(f, tags.DiscNumber, tags.DiscTotal, false)
		if err != nil {
			return err
		}		
	}
	
	if tags.BPM > 0 {
		err = writeBPM(f, tags.BPM)
		if err != nil {
			return err
		}		
	}

	if tags.Year > 0 {
		err = writeRegular(f, "day", strconv.Itoa(int(tags.Year)), true)
		if err != nil {
			return err
		}
	} else if tags.Date != "" {
		err = writeRegular(f, "day", tags.Date, true)
		if err != nil {
			return err
		}	
	}

	if tags.Genre != GenreNone {
		err = writeGenre(f, tags.Genre)
		if err != nil {
			return err
		}		
	}
	
	for k, v := range tags.Custom {
		err = writeCustom(f, k, v, mp4.upperCustom, tags.OtherCustom)
		if err != nil {
			return err
		}
	}

	err = writePics(f, tags.Pictures)
	if err != nil {
		return err
	}

	newIlstEndOffset, err := getPos(f)	
	if err != nil {
		return err
	}
	newIlstSize := newIlstEndOffset - ilstStartOffset
	_, err = f.Seek(ilstStartOffset, io.SeekStart)
	if err != nil {
		return err
	}

	err = resizeBoxes(f, boxes, oldIlstSize, newIlstSize)
	if err != nil {
		return err
	}

	mdat := boxes.getBoxByPath("mdat")
	if mdat.StartOffset > ilstStartOffset && oldIlstSize != newIlstSize {
		err = mp4.updateChunkOffsets(f, boxes, oldIlstSize, newIlstSize)
		if err != nil {
			return err
		}	
	}

	_, err = f.Seek(newIlstEndOffset, io.SeekStart)
	if err != nil {
		return err
	}
	_, err = mp4.f.Seek(ilst.EndOffset, io.SeekStart)
	if err != nil {
		return err
	}
	err = mp4.writeRemaining(f)
	return err
}

func (mp4 *MP4) actualWrite(tags *MP4Tags, _delStrings []string) error {
	delStrings := strArrToLower(_delStrings)

	mergedTags, boxes, err := mp4.actualRead()
	if err != nil {
		return err
	}
	if boxes.getBoxByPath("moov.udta.meta.ilst") == nil {
		return &ErrBoxNotPresent{Msg: "ilst box not present, implement me"}
	}
	mergedTags = overwriteTags(mergedTags, tags, delStrings)
   	tempPath := getTempPath(mp4.path)
   	err = mp4.writeTags(boxes, mergedTags, tempPath)
	if err != nil {
		return err
	}
	mp4.Close()
	err = moveMP4(tempPath, mp4.path)
	if err != nil {
		return err
	}

	m, err := Open(mp4.path)
	if err != nil {
		return err
	}
	mp4.f = m.f
	mp4.size = m.size
	return nil
}

