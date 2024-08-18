package c2pa

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/rsa"
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
	"reflect"

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
	stream := C2PAStreamReader{target}
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

type Builder interface {
	Sign(input io.ReadSeeker, output io.ReadWriteSeeker, mimeType string) error
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

var algMap = map[string]rustC2PA.SigningAlg{
	"es256":   rustC2PA.SigningAlgEs256,
	"es256k":  rustC2PA.SigningAlgEs256k,
	"es384":   rustC2PA.SigningAlgEs384,
	"es512":   rustC2PA.SigningAlgEs512,
	"ed25519": rustC2PA.SigningAlgEd25519,
	"ps256":   rustC2PA.SigningAlgPs256,
	"ps384":   rustC2PA.SigningAlgPs384,
	"ps512":   rustC2PA.SigningAlgPs512,
}

var hashMap = map[string]crypto.Hash{
	"es256":   crypto.SHA256,
	"es256k":  crypto.SHA256,
	"es384":   crypto.SHA384,
	"es512":   crypto.SHA512,
	"ed25519": crypto.Hash(0),
	"ps256":   crypto.SHA256,
	"ps384":   crypto.SHA384,
	"ps512":   crypto.SHA512,
}

func (b *C2PABuilder) Sign(input io.ReadSeeker, output io.ReadWriteSeeker, mimeType string) error {
	mySigner := &C2PACallbackSigner{
		params: b.params,
	}
	alg, ok := algMap[b.params.Algorithm]
	if !ok {
		return fmt.Errorf("unknown algorithm: %s", b.params.Algorithm)
	}
	signer := rustC2PA.NewCallbackSigner(mySigner, alg, b.params.Cert, &b.params.TAURL)
	_, err := b.builder.Sign(mimeType, &C2PAStreamReader{input}, &C2PAStreamWriter{output}, signer)
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

type ecPrivateKey struct {
	Version       int
	PrivateKey    []byte
	NamedCurveOID asn1.ObjectIdentifier `asn1:"optional,explicit,tag:0"`
	PublicKey     asn1.BitString        `asn1:"optional,explicit,tag:1"`
}

func (s *C2PACallbackSigner) Sign(data []byte) ([]byte, *rustC2PA.Error) {
	bs, err := s._sign(data)
	if err != nil {
		return []byte{}, rustC2PA.NewErrorOther(err.Error())
	}
	return bs, nil
}

type C2PASignerOpts struct{}

func (s *C2PACallbackSigner) _sign(data []byte) ([]byte, error) {
	block, _ := pem.Decode(s.params.Key)

	if block == nil {
		return []byte{}, fmt.Errorf("failed to parse PEM block containing the private key")
	}
	key, err := parsePrivateKey(block.Bytes)
	if err != nil {
		return []byte{}, fmt.Errorf("parsePrivateKey failed: %s", err.Error())
	}

	var opts crypto.SignerOpts
	var digest []byte

	hash, ok := hashMap[s.params.Algorithm]
	if !ok {
		return []byte{}, fmt.Errorf("hash not found for %s", s.params.Algorithm)
	}

	switch key.(type) {
	case *ed25519.PrivateKey:
		// ed25519 handles its own hashing
		opts = hash
		digest = data
	case *rsa.PrivateKey:
		h := hash.New()
		h.Write(data)
		digest = h.Sum(nil)
		opts = &rsa.PSSOptions{
			Hash:       hash,
			SaltLength: rsa.PSSSaltLengthEqualsHash,
		}
	default:
		h := hash.New()
		h.Write(data)
		digest = h.Sum(nil)
		opts = hash
	}

	bs, err := key.Sign(rand.Reader, digest, opts)

	if err != nil {
		return []byte{}, fmt.Errorf("ecdsa.SignASN1 failed: %s", err.Error())
	}
	return bs, nil
}

func parsePrivateKey(der []byte) (crypto.Signer, error) {
	if key, err := x509.ParsePKCS1PrivateKey(der); err == nil {
		return key, nil
	}

	if key, err := x509.ParseECPrivateKey(der); err == nil {
		return key, nil
	}

	key, err := x509.ParsePKCS8PrivateKey(der)
	if err == nil {
		switch key := key.(type) {
		case *rsa.PrivateKey:
			return key, nil
		case *ecdsa.PrivateKey:
			return key, nil
		case ed25519.PrivateKey:
			return &key, nil
		default:
			return nil, errors.New("crypto/tls: found unknown private key type in PKCS#8 wrapping")
		}
	}

	// Last resort... handle some key types Go doesn't know about.
	return parsePKCS8PrivateKey(der)
}

var OID_RSA_PSS asn1.ObjectIdentifier = []int{1, 2, 840, 113549, 1, 1, 10}
var OID_EC asn1.ObjectIdentifier = []int{1, 2, 840, 10045, 2, 1}
var OID_SECP256K1 asn1.ObjectIdentifier = []int{1, 3, 132, 0, 10}

func parsePKCS8PrivateKey(der []byte) (crypto.Signer, error) {
	var privKey pkcs8
	_, err := asn1.Unmarshal(der, &privKey)
	if err != nil {
		return nil, fmt.Errorf("asn1.Unmarshal failed: %s", err.Error())
	}
	if reflect.DeepEqual(privKey.Algo.Algorithm, OID_RSA_PSS) {
		return x509.ParsePKCS1PrivateKey(privKey.PrivateKey)
	} else if reflect.DeepEqual(privKey.Algo.Algorithm, OID_EC) {
		return parseES256KPrivateKey(privKey)
	} else {
		return nil, fmt.Errorf("unknown pkcs8 OID: %s", privKey.Algo.Algorithm)
	}
}

func parseES256KPrivateKey(privKey pkcs8) (crypto.Signer, error) {
	var namedCurveOID asn1.ObjectIdentifier
	if _, err := asn1.Unmarshal(privKey.Algo.Parameters.FullBytes, &namedCurveOID); err != nil {
		return nil, fmt.Errorf("asn1.Unmarshal for oid failed: %w", err)
	}
	if !reflect.DeepEqual(namedCurveOID, OID_SECP256K1) {
		return nil, fmt.Errorf("unknown named curve OID: %s", namedCurveOID.String())
	}
	var curveKey ecPrivateKey
	_, err := asn1.Unmarshal(privKey.PrivateKey, &curveKey)
	if err != nil {
		return nil, fmt.Errorf("asn1.Unmarshal for private key failed: %w", err)
	}
	key, _ := secp256k1.PrivKeyFromBytes(curveKey.PrivateKey)
	return key.ToECDSA(), nil
}
