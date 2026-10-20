package mp4tag

import "os"

type ErrBoxNotPresent struct {
    Msg  string
}

type ErrUnsupportedFtyp struct {
    Msg  string
}

type ErrInvalidStcoSize struct {}

type ErrInvalidMagic struct {}


func (e *ErrBoxNotPresent) Error() string { 
    return e.Msg
}

func (e *ErrUnsupportedFtyp) Error() string { 
    return e.Msg
}

func (_ *ErrInvalidStcoSize) Error() string {
	return "stco size is invalid"
}

func (_ *ErrInvalidMagic) Error() string {
	return "file header is corrupted or not an mp4 file"
}

var ftyps = [8][]byte{
	{0x4D, 0x34, 0x41, 0x20}, // M4A
	{0x4D, 0x34, 0x42, 0x20}, // M4B
	{0x64, 0x61, 0x73, 0x68}, // dash
	{0x6D, 0x70, 0x34, 0x31}, // mp41
	{0x6D, 0x70, 0x34, 0x32}, // mp42
	{0x69, 0x73, 0x6F, 0x6D}, // isom
	{0x69, 0x73, 0x6F, 0x32}, // iso2
	{0x61, 0x76, 0x63, 0x31}, // avc1
}

var containers = []string{
  "moov", "udta", "meta", "ilst", "----", "(c)alb",
  "aART", "(c)art", "(c)nam", "(c)cmt", "(c)gen", "gnre",
  "(c)wrt", "(c)con", "cprt", "desc", "(c)lyr", "(c)nrt",
  "(c)pub", "trkn", "covr", "(c)day", "disk", "(c)too",
  "trak", "mdia", "minf", "stbl", "rtng", "plID",
  "atID", "tmpo", "sonm", "soal", "soar", "soco",
  "soaa",
}

// 0-9
var numbers = []rune{
	0x30, 0x31, 0x32, 0x33, 0x34,
	0x35, 0x36, 0x37, 0x38, 0x39,
}

type MP4 struct {
	f *os.File
	path string
	size int64
	upperCustom bool
}

type MP4Box struct {
	StartOffset int64
	EndOffset   int64
	BoxSize     int64
	Path        string
}

type MP4Boxes struct {
	Boxes []*MP4Box
}

type ImageType int8
const (
	ImageTypeJPEG ImageType = iota + 13
	ImageTypePNG
	ImageTypeAuto
)

var resolveImageType = map[uint8]ImageType{
	13: ImageTypeJPEG,
	14: ImageTypePNG,
}

type ItunesAdvisory int8
const (
	ItunesAdvisoryNone ItunesAdvisory = iota
	ItunesAdvisoryExplicit
	ItunesAdvisoryClean
)

var resolveItunesAdvisory = map[uint8]ItunesAdvisory{
	1: ItunesAdvisoryExplicit,
	2: ItunesAdvisoryClean,
}

// GenreNone
type Genre int8
const (
	GenreNone Genre = iota
	GenreBlues
	GenreClassicRock
	GenreCountry
	GenreDance
	GenreDisco
	GenreFunk
	GenreGrunge
	GenreHipHop
	GenreJazz
	GenreMetal
	GenreNewAge
	GenreOldies
	GenreOther
	GenrePop
	GenreRhythmAndBlues
	GenreRap
	GenreReggae
	GenreRock
	GenreTechno
	GenreIndustrial
	GenreAlternative
	GenreSka
	GenreDeathMetal
	GenrePranks
	GenreSoundtrack
	GenreEurotechno
	GenreAmbient
	GenreTripHop
	GenreVocal
	GenreJassAndFunk
	GenreFusion
	GenreTrance
	GenreClassical
	GenreInstrumental
	GenreAcid
	GenreHouse
	GenreGame
	GenreSoundClip
	GenreGospel
	GenreNoise
	GenreAlternativeRock
	GenreBass
	GenreSoul
	GenrePunk
	GenreSpace
	GenreMeditative
	GenreInstrumentalPop
	GenreInstrumentalRock
	GenreEthnic
	GenreGothic
	GenreDarkwave
	GenreTechnoindustrial
	GenreElectronic
	GenrePopFolk
	GenreEurodance
	GenreSouthernRock
	GenreComedy
	GenreCull
	GenreGangsta
	GenreTop40
	GenreChristianRap
	GenrePopSlashFunk
	GenreJungleMusic
	GenreNativeUS
	GenreCabaret
	GenreNewWave
	GenrePsychedelic
	GenreRave
	GenreShowtunes
	GenreTrailer
	GenreLofi
	GenreTribal
	GenreAcidPunk
	GenreAcidJazz
	GenrePolka
	GenreRetro
	GenreMusical
	GenreRockNRoll
	GenreHardRock
)

var resolveGenre = map[uint8]Genre{
	1: GenreBlues,
	2: GenreClassicRock,
	3: GenreCountry,
	4: GenreDance,
	5: GenreDisco,
	6: GenreFunk,
	7: GenreGrunge,
	8: GenreHipHop,
	9: GenreJazz,
	10: GenreMetal,
	11: GenreNewAge,
	12: GenreOldies,
	13: GenreOther,
	14: GenrePop,
	15: GenreRhythmAndBlues,
	16: GenreRap,
	17: GenreReggae,
	18: GenreRock,
	19: GenreTechno,
	20: GenreIndustrial,
	21: GenreAlternative,
	22: GenreSka,
	23: GenreDeathMetal,
	24: GenrePranks,
	25: GenreSoundtrack,
	26: GenreEurotechno,
	27: GenreAmbient,
	28: GenreTripHop,
	29: GenreVocal,
	30: GenreJassAndFunk,
	31: GenreFusion,
	32: GenreTrance,
	33: GenreClassical,
	34: GenreInstrumental,
	35: GenreAcid,
	36: GenreHouse,
	37: GenreGame,
	38: GenreSoundClip,
	39: GenreGospel,
	40: GenreNoise,
	41: GenreAlternativeRock,
	42: GenreBass,
	43: GenreSoul,
	44: GenrePunk,
	45: GenreSpace,
	46: GenreMeditative,
	47: GenreInstrumentalPop,
	48: GenreInstrumentalRock,
	49: GenreEthnic,
	50: GenreGothic,
	51: GenreDarkwave,
	52: GenreTechnoindustrial,
	53: GenreElectronic,
	54: GenrePopFolk,
	55: GenreEurodance,
	56: GenreSouthernRock,
	57: GenreComedy,
	58: GenreCull,
	59: GenreGangsta,
	60: GenreTop40,
	61: GenreChristianRap,
	62: GenrePopSlashFunk,
	63: GenreJungleMusic,
	64: GenreNativeUS,
	65: GenreCabaret,
	66: GenreNewWave,
	67: GenrePsychedelic,
	68: GenreRave,
	69: GenreShowtunes,
	70: GenreTrailer,
	71: GenreLofi,
	72: GenreTribal,
	73: GenreAcidPunk,
	74: GenreAcidJazz,
	75: GenrePolka,
	76: GenreRetro,
	77: GenreMusical,
	78: GenreRockNRoll,
	79: GenreHardRock,
}

type MP4Picture struct {
	Format ImageType
	Data []byte
}

type MP4Tags struct {
	Album string
	AlbumSort string 
	AlbumArtist string
	AlbumArtistSort string
	Artist string
	ArtistSort string
	BPM int16
	Comment string
	Composer string
	ComposerSort string
	Conductor string
	Copyright string
	Custom map[string]string
	CustomGenre string
	Date string
	Description string
	Director string
	DiscNumber int16
	DiscTotal int16
	Genre Genre
	ItunesAdvisory ItunesAdvisory
	ItunesAlbumID int64
	ItunesArtistID int64
	Lyrics string
	Narrator string
	OtherCustom map[string][]string
	Pictures []*MP4Picture
	Publisher string
	Title string
	TitleSort string
	TrackNumber int16
	TrackTotal int16
	Year int32
}