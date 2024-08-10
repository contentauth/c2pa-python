//go:build (darwin && cgo) || (dragonfly && cgo) || (freebsd && cgo) || (linux && cgo) || (netbsd && cgo) || (openbsd && cgo)

package c2pa

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"os"
	"path/filepath"

	rustC2PA "git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/c2pa"
	"git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/manifeststore"
)

// #cgo LDFLAGS: -L../../target/release -lc2pa -lm
// #cgo darwin LDFLAGS: -framework Security
import "C"

type Reader interface {
	GetManifest(label string) *manifeststore.Manifest
	GetActiveManifest() *manifeststore.Manifest
}

func FromStream(target io.ReadWriteSeeker, mType string) (Reader, error) {
	stream := C2PAStream{target}
	r := rustC2PA.NewReader()
	r.FromStream(mType, &stream)
	ret, err := r.Json()
	if err != nil {
		return nil, err
	}
	var store manifeststore.ManifestStoreSchemaJson
	err = json.Unmarshal([]byte(ret), &store)
	if err != nil {
		return nil, err
	}
	return &C2PAReader{store: &store}, nil
}

func FromFile(fname string) (Reader, error) {
	mType := mime.TypeByExtension(filepath.Ext(fname))
	if mType == "" {
		return nil, fmt.Errorf("couldn't find MIME type for filename %s", fname)
	}
	f, err := os.Open(fname)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return FromStream(f, mType)
}

type C2PAReader struct {
	store *manifeststore.ManifestStoreSchemaJson
}

func (r *C2PAReader) GetManifest(label string) *manifeststore.Manifest {
	m, ok := r.store.Manifests[label]
	if !ok {
		return nil
	}
	return &m
}

func (r *C2PAReader) GetActiveManifest() *manifeststore.Manifest {
	if r.store.ActiveManifest == nil {
		return nil
	}
	return r.GetManifest(*r.store.ActiveManifest)
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
