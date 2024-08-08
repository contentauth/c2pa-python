//go:build (darwin && cgo) || (dragonfly && cgo) || (freebsd && cgo) || (linux && cgo) || (netbsd && cgo) || (openbsd && cgo)

package c2pa

import (
	"errors"
	"fmt"
	"io"

	rustC2PA "git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/c2pa"
)

// #cgo LDFLAGS: -L../../target/release -lc2pa -lm
import "C"

func GetManifest(target io.ReadWriteSeeker, mType string) (string, error) {
	stream := C2PAStream{target}
	r := rustC2PA.NewReader()
	r.FromStream("image/jpeg", &stream)
	ret, err := r.Json()
	if err != nil {
		return "", err
	}
	return ret, nil
}

type C2PAStream struct {
	io.ReadWriteSeeker
}

func (s *C2PAStream) ReadStream(length uint64) ([]byte, *rustC2PA.Error) {
	// fmt.Printf("read length=%d\n", length)
	bs := make([]byte, length)
	read, err := s.ReadWriteSeeker.Read(bs)
	if err != nil {
		if errors.Is(err, io.EOF) {
			if read == 0 {
				// fmt.Printf("read EOF read=%d returning empty?", read)
				return []byte{}, nil
			}
			// partial := bs[read:]
			// return partial, nil
		}
		// fmt.Printf("io error=%s\n", err)
		return []byte{}, rustC2PA.NewErrorIo(err.Error())
	}
	if uint64(read) < length {
		partial := bs[read:]
		// fmt.Printf("read returning partial read=%d len=%d\n", read, len(partial))
		return partial, nil
	}
	// fmt.Printf("read returning full read=%d len=%d\n", read, len(bs))
	return bs, nil
}

func (s *C2PAStream) SeekStream(pos int64, mode rustC2PA.SeekMode) (uint64, *rustC2PA.Error) {
	// fmt.Printf("seek pos=%d\n", pos)
	var seekMode int
	if mode == rustC2PA.SeekModeCurrent {
		seekMode = io.SeekCurrent
	} else if mode == rustC2PA.SeekModeStart {
		seekMode = io.SeekStart
	} else if mode == rustC2PA.SeekModeEnd {
		seekMode = io.SeekEnd
	} else {
		// fmt.Printf("seek mode unsupported mode=%d\n", mode)
		return 0, rustC2PA.NewErrorNotSupported(fmt.Sprintf("unknown seek mode: %d", mode))
	}
	newPos, err := s.ReadWriteSeeker.Seek(pos, seekMode)
	if err != nil {
		return 0, rustC2PA.NewErrorIo(err.Error())
	}
	return uint64(newPos), nil
}

func (s *C2PAStream) WriteStream(data []byte) (uint64, *rustC2PA.Error) {
	panic("not implemented")
	return 0, nil
}
