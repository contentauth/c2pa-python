package c2pa

import (
	"errors"
	"fmt"
	"io"

	rustC2PA "git.stream.place/streamplace/c2pa-go/pkg/c2pa/generated/c2pa"
)

// Wrapped io.ReadSeeker for passing to Rust. Doesn't write.
type C2PAStreamReader struct {
	io.ReadSeeker
}

func (s *C2PAStreamReader) ReadStream(length uint64) ([]byte, *rustC2PA.Error) {
	return readStream(s.ReadSeeker, length)
}

func (s *C2PAStreamReader) SeekStream(pos int64, mode rustC2PA.SeekMode) (uint64, *rustC2PA.Error) {
	return seekStream(s.ReadSeeker, pos, mode)
}

func (s *C2PAStreamReader) WriteStream(data []byte) (uint64, *rustC2PA.Error) {
	return 0, rustC2PA.NewErrorIo("Writing is not implemented for C2PAStreamReader")
}

// Wrapped io.Writer for passing to Rust.
type C2PAStreamWriter struct {
	io.ReadWriteSeeker
}

func (s *C2PAStreamWriter) ReadStream(length uint64) ([]byte, *rustC2PA.Error) {
	return readStream(s.ReadWriteSeeker, length)
}

func (s *C2PAStreamWriter) SeekStream(pos int64, mode rustC2PA.SeekMode) (uint64, *rustC2PA.Error) {
	return seekStream(s.ReadWriteSeeker, pos, mode)
}

func (s *C2PAStreamWriter) WriteStream(data []byte) (uint64, *rustC2PA.Error) {
	return writeStream(s.ReadWriteSeeker, data)
}

func readStream(r io.ReadSeeker, length uint64) ([]byte, *rustC2PA.Error) {
	// fmt.Printf("read length=%d\n", length)
	bs := make([]byte, length)
	read, err := r.Read(bs)
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
		partial := bs[:read]
		// fmt.Printf("read returning partial read=%d len=%d\n", read, len(partial))
		return partial, nil
	}
	// fmt.Printf("read returning full read=%d len=%d\n", read, len(bs))
	return bs, nil
}

func seekStream(r io.ReadSeeker, pos int64, mode rustC2PA.SeekMode) (uint64, *rustC2PA.Error) {
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
	newPos, err := r.Seek(pos, seekMode)
	if err != nil {
		return 0, rustC2PA.NewErrorIo(err.Error())
	}
	return uint64(newPos), nil
}

func writeStream(w io.ReadWriteSeeker, data []byte) (uint64, *rustC2PA.Error) {
	wrote, err := w.Write(data)
	if err != nil {
		return uint64(wrote), rustC2PA.NewErrorIo(err.Error())
	}
	return uint64(wrote), nil
}
