//go:build (darwin && cgo) || (dragonfly && cgo) || (freebsd && cgo) || (linux && cgo) || (netbsd && cgo) || (openbsd && cgo)

package c2pa

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"mime"
	"os"
	"path/filepath"

	rustC2PA "git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/c2pa"
	"git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/manifestdefinition"
	"git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/manifeststore"
	"github.com/decred/dcrd/dcrec/secp256k1"
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
	fmt.Println(ret)
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
	wrote, err := s.ReadWriteSeeker.Write(data)
	if err != nil {
		return uint64(wrote), rustC2PA.NewErrorIo(err.Error())
	}
	return uint64(wrote), nil
}

type Builder interface {
	Sign(input, output io.ReadWriteSeeker, mimeType string) error
	SignFile(infile, outfile string) error
}

type BuilderParams struct {
	Cert      []byte
	Key       []byte
	TAURL     string
	Algorithm string
}

type C2PABuilder struct {
	builder  *rustC2PA.Builder
	manifest *ManifestDefinition
	params   *BuilderParams
}

type ManifestDefinition manifestdefinition.ManifestDefinitionSchemaJson

func NewBuilder(manifest *ManifestDefinition, params *BuilderParams) (Builder, error) {
	b := rustC2PA.NewBuilder()
	bs, err := json.Marshal(manifest)
	if err != nil {
		return nil, err
	}
	err = b.WithJson(string(bs))
	if err != nil {
		return nil, err
	}

	return &C2PABuilder{builder: b, manifest: manifest, params: params}, nil
}

func (b *C2PABuilder) Sign(input, output io.ReadWriteSeeker, mimeType string) error {
	mySigner := &C2PACallbackSigner{
		params: b.params,
	}
	signer := rustC2PA.NewCallbackSigner(mySigner, rustC2PA.SigningAlgEs256k, b.params.Cert, &b.params.TAURL)
	_, err := b.builder.Sign(mimeType, &C2PAStream{input}, &C2PAStream{output}, signer)
	if err != nil {
		return err
	}
	return nil
}

// helper function for operating on files
func (b *C2PABuilder) SignFile(infile, outfile string) error {
	mimeType := mime.TypeByExtension(filepath.Ext(infile))
	if mimeType == "" {
		return fmt.Errorf("couldn't find MIME type for filename %s", infile)
	}
	input, err := os.Open(infile)
	if err != nil {
		return err
	}
	defer input.Close()

	output, err := os.Create(outfile)
	if err != nil {
		return err
	}
	defer output.Close()
	return b.Sign(input, output, mimeType)
}

type C2PACallbackSigner struct {
	params *BuilderParams
}

type pkcs8 struct {
	Version    int
	Algo       pkix.AlgorithmIdentifier
	PrivateKey []byte
}

func (s *C2PACallbackSigner) Sign(data []byte) ([]byte, *rustC2PA.Error) {
	h := sha256.New()

	h.Write(data)

	hashbs := h.Sum(nil)
	block, _ := pem.Decode(s.params.Key)

	if block == nil {
		return []byte{}, rustC2PA.NewErrorOther("failed to parse PEM block containing the private key")
	}
	if s.params.Algorithm == "es256k" {
		var privKey pkcs8
		_, err := asn1.Unmarshal(block.Bytes, &privKey)
		if err != nil {
			return nil, rustC2PA.NewErrorOther(fmt.Sprintf("asn1.Unmarshal failed: %s", err.Error()))
		}
		var curvePrivateKey []byte
		asn1.Unmarshal(privKey.PrivateKey, &curvePrivateKey)
		if err != nil {
			return nil, rustC2PA.NewErrorOther(fmt.Sprintf("asn1.Unmarshal for private key failed: %s", err.Error()))
		}
		priv, _ := secp256k1.PrivKeyFromBytes(curvePrivateKey)
		bs, err := ecdsa.SignASN1(rand.Reader, priv.ToECDSA(), hashbs)
		if err != nil {
			return []byte{}, rustC2PA.NewErrorOther(fmt.Sprintf("ecdsa.SignASN1 failed: %s", err.Error()))
		}
		return bs, nil
	}
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return []byte{}, rustC2PA.NewErrorOther(fmt.Sprintf("x509.ParsePKCS8PrivateKey failed: %s", err.Error()))
	}

	bs, err := ecdsa.SignASN1(rand.Reader, key.(*ecdsa.PrivateKey), hashbs)
	if err != nil {
		return []byte{}, rustC2PA.NewErrorOther(fmt.Sprintf("ecdsa.SignASN1 failed: %s", err.Error()))
	}
	return bs, nil
}

func parsePrivateKey(der []byte) (crypto.Signer, error) {
	if key, err := x509.ParsePKCS1PrivateKey(der); err == nil {
		return key, nil
	}
	if key, err := x509.ParsePKCS8PrivateKey(der); err == nil {
		switch key := key.(type) {
		case *rsa.PrivateKey:
			return key, nil
		case *ecdsa.PrivateKey:
			return key, nil
		default:
			return nil, errors.New("crypto/tls: found unknown private key type in PKCS#8 wrapping")
		}
	}
	if key, err := x509.ParseECPrivateKey(der); err == nil {
		return key, nil
	}

	return nil, errors.New("crypto/tls: failed to parse private key")
}
