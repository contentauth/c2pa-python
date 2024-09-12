package c2pa

import (
	"crypto"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"os"
	"path/filepath"

	rustC2PA "git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/c2pa"
	"git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/manifestdefinition"
	"git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/manifeststore"
)

// #cgo LDFLAGS: -L../../target/release -lc2pa -lm
// #cgo darwin LDFLAGS: -framework Security
import "C"

type Reader interface {
	GetManifest(label string) *manifeststore.Manifest
	GetActiveManifest() *manifeststore.Manifest
	GetProvenanceCertChain() string
}

func FromStream(target io.ReadSeeker, mType string) (Reader, error) {
	stream := C2PAStreamReader{target}
	r := rustC2PA.NewReader()
	r.FromStream(mType, &stream)
	ret, err := r.Json()
	if err != nil {
		return nil, err
	}
	certs, err := r.GetProvenanceCertChain()
	if err != nil {
		return nil, err
	}
	var store manifeststore.ManifestStoreSchemaJson
	err = json.Unmarshal([]byte(ret), &store)
	if err != nil {
		return nil, err
	}
	if len(store.ValidationStatus) > 0 {
		errBs, err := json.Marshal(store.ValidationStatus)
		if err != nil {
			return nil, err
		}
		return &C2PAReader{store: &store, certs: certs}, fmt.Errorf("validation error: %s", string(errBs))
	}
	return &C2PAReader{store: &store, certs: certs}, nil
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
	certs string
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

func (r *C2PAReader) GetProvenanceCertChain() string {
	return r.certs
}

type Builder interface {
	Sign(input io.ReadSeeker, output io.ReadWriteSeeker, mimeType string) error
	SignFile(infile, outfile string) error
}

type BuilderParams struct {
	Cert      []byte
	Signer    crypto.Signer
	TAURL     string
	Algorithm *SigningAlgorithm
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

func (b *C2PABuilder) Sign(input io.ReadSeeker, output io.ReadWriteSeeker, mimeType string) error {
	mySigner := &C2PACallbackSigner{
		signer:    b.params.Signer,
		algorithm: *b.params.Algorithm,
	}
	signer := rustC2PA.NewCallbackSigner(mySigner, b.params.Algorithm.RustC2PAType, b.params.Cert, &b.params.TAURL)
	_, err := b.builder.Sign(mimeType, &C2PAStreamReader{input}, &C2PAStreamWriter{output}, signer)
	if err != nil {
		return err
	}
	_, err = FromStream(output, mimeType)
	if err != nil {
		return fmt.Errorf("unable to validate newly-signed file: %w", err)
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
