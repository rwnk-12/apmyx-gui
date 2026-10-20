package mp4tag

import ( 
	"path/filepath"
	"time"
	"os"
	"io"
	"strings"
	"fmt"
)

func containsRune(items []rune, value rune) bool {
	for _, item := range items {
		if item == value {
			return true
		}
	}
	return false
}

func containsOnlyNums(str string) bool {
	for _, r := range str {
		if !containsRune(numbers, r) {
			return false
		}
	}
	return true
}

func strArrToLower(arr []string) []string {
	var lowerArr []string
	for _, str := range arr {
		lowerArr = append(lowerArr, strings.ToLower(str))
	}
	return lowerArr
}

func containsStr(arr []string, val string) bool {
	for _, str := range arr {
		if str == val {
			return true
		}
	}
	return false	
}

func getTempPath(path string) string {
	fname := filepath.Base(path)
	unix := time.Now().UnixMilli()
	tempPath := filepath.Join(
		os.TempDir(), fmt.Sprintf("%s_tmp_%d", fname, unix))
	return tempPath
}

func getPos(f *os.File) (int64, error) {
	return f.Seek(0, io.SeekCurrent)
}

func moveMP4(srcPath, destPath string) error {
    inFile, err := os.Open(srcPath)
    if err != nil {
        return err
    }
    outFile, err := os.Create(destPath)
    if err != nil {
        inFile.Close()
        return err
    }
    defer outFile.Close()
    _, err = io.Copy(outFile, inFile)
    if err != nil {
        return err
    }
    inFile.Close()
    err = os.Remove(srcPath)
    return err
}