//go:build (darwin && cgo) || (dragonfly && cgo) || (freebsd && cgo) || (linux && cgo) || (netbsd && cgo) || (openbsd && cgo)

package c2pa

import (
	"crypto/ecdsa"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
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
	GetManifest(label string) *manifeststore.Manifest
	GetActiveManifest() *manifeststore.Manifest
}

type C2PABuilder struct {
	builder *rustC2PA.Builder
}

var certs = []byte(`-----BEGIN CERTIFICATE-----
MIIChzCCAi6gAwIBAgIUcCTmJHYF8dZfG0d1UdT6/LXtkeYwCgYIKoZIzj0EAwIw
gYwxCzAJBgNVBAYTAlVTMQswCQYDVQQIDAJDQTESMBAGA1UEBwwJU29tZXdoZXJl
MScwJQYDVQQKDB5DMlBBIFRlc3QgSW50ZXJtZWRpYXRlIFJvb3QgQ0ExGTAXBgNV
BAsMEEZPUiBURVNUSU5HX09OTFkxGDAWBgNVBAMMD0ludGVybWVkaWF0ZSBDQTAe
Fw0yMjA2MTAxODQ2NDBaFw0zMDA4MjYxODQ2NDBaMIGAMQswCQYDVQQGEwJVUzEL
MAkGA1UECAwCQ0ExEjAQBgNVBAcMCVNvbWV3aGVyZTEfMB0GA1UECgwWQzJQQSBU
ZXN0IFNpZ25pbmcgQ2VydDEZMBcGA1UECwwQRk9SIFRFU1RJTkdfT05MWTEUMBIG
A1UEAwwLQzJQQSBTaWduZXIwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQPaL6R
kAkYkKU4+IryBSYxJM3h77sFiMrbvbI8fG7w2Bbl9otNG/cch3DAw5rGAPV7NWky
l3QGuV/wt0MrAPDoo3gwdjAMBgNVHRMBAf8EAjAAMBYGA1UdJQEB/wQMMAoGCCsG
AQUFBwMEMA4GA1UdDwEB/wQEAwIGwDAdBgNVHQ4EFgQUFznP0y83joiNOCedQkxT
tAMyNcowHwYDVR0jBBgwFoAUDnyNcma/osnlAJTvtW6A4rYOL2swCgYIKoZIzj0E
AwIDRwAwRAIgOY/2szXjslg/MyJFZ2y7OH8giPYTsvS7UPRP9GI9NgICIDQPMKrE
LQUJEtipZ0TqvI/4mieoyRCeIiQtyuS0LACz
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIICajCCAg+gAwIBAgIUfXDXHH+6GtA2QEBX2IvJ2YnGMnUwCgYIKoZIzj0EAwIw
dzELMAkGA1UEBhMCVVMxCzAJBgNVBAgMAkNBMRIwEAYDVQQHDAlTb21ld2hlcmUx
GjAYBgNVBAoMEUMyUEEgVGVzdCBSb290IENBMRkwFwYDVQQLDBBGT1IgVEVTVElO
R19PTkxZMRAwDgYDVQQDDAdSb290IENBMB4XDTIyMDYxMDE4NDY0MFoXDTMwMDgy
NzE4NDY0MFowgYwxCzAJBgNVBAYTAlVTMQswCQYDVQQIDAJDQTESMBAGA1UEBwwJ
U29tZXdoZXJlMScwJQYDVQQKDB5DMlBBIFRlc3QgSW50ZXJtZWRpYXRlIFJvb3Qg
Q0ExGTAXBgNVBAsMEEZPUiBURVNUSU5HX09OTFkxGDAWBgNVBAMMD0ludGVybWVk
aWF0ZSBDQTBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABHllI4O7a0EkpTYAWfPM
D6Rnfk9iqhEmCQKMOR6J47Rvh2GGjUw4CS+aLT89ySukPTnzGsMQ4jK9d3V4Aq4Q
LsOjYzBhMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMB0GA1UdDgQW
BBQOfI1yZr+iyeUAlO+1boDitg4vazAfBgNVHSMEGDAWgBRembiG4Xgb2VcVWnUA
UrYpDsuojDAKBggqhkjOPQQDAgNJADBGAiEAtdZ3+05CzFo90fWeZ4woeJcNQC4B
84Ill3YeZVvR8ZECIQDVRdha1xEDKuNTAManY0zthSosfXcvLnZui1A/y/DYeg==
-----END CERTIFICATE-----
`)

var priv = []byte(`-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgfNJBsaRLSeHizv0m
GL+gcn78QmtfLSm+n+qG9veC2W2hRANCAAQPaL6RkAkYkKU4+IryBSYxJM3h77sF
iMrbvbI8fG7w2Bbl9otNG/cch3DAw5rGAPV7NWkyl3QGuV/wt0MrAPDo
-----END PRIVATE KEY-----
`)

func NewBuilder() *C2PABuilder {
	b := rustC2PA.NewBuilder()
	str := `{
		"alg": "ES256",
		"private_key": "/home/iameli/testvids/cert.key",
		"sign_cert": "/home/iameli/testvids/cert.crt",
		"ta_url": "http://timestamp.digicert.com",
		"claim_generator": "Aquareum",
		"title": "Image File",
		"assertions": [
			{
				"label": "c2pa.actions",
				"data": { "actions": [{ "action": "c2pa.published" }] }
			}
		]
	}`
	err := b.WithJson(str)
	if err != nil {
		panic(err)
	}
	infile, err := os.Open("/home/iameli/testvids/screenshot.jpg")
	if err != nil {
		panic(err)
	}
	outfile, err := os.Create("/home/iameli/code/c2pa-go/screenshot-signed-go.jpg")
	if err != nil {
		panic(err)
	}
	mySigner := &C2PASigner{}
	taUrl := "http://timestamp.digicert.com"
	signer := rustC2PA.NewCallbackSigner(mySigner, rustC2PA.SigningAlgEs256, certs, &taUrl)
	bs, err := b.Sign("image/jpeg", &C2PAStream{infile}, &C2PAStream{outfile}, signer)
	if err != nil {
		panic(err)
	}
	fmt.Printf("got %d bytes\n", len(bs))
	return &C2PABuilder{b}
}

type C2PASigner struct{}

func (s *C2PASigner) Sign(data []byte) ([]byte, *rustC2PA.Error) {
	// fmt.Printf("Sign called len(data)=%d\n", len(data))
	block, _ := pem.Decode(priv)
	if block == nil {
		return []byte{}, rustC2PA.NewErrorOther("failed to parse PEM block containing the private key")
	}
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		fmt.Println(err.Error())
		return []byte{}, rustC2PA.NewErrorOther(err.Error())
	}

	h := sha256.New()

	h.Write(data)

	hashbs := h.Sum(nil)
	// fmt.Printf("len(hashbs)=%d\n", len(hashbs))

	bs, err := ecdsa.SignASN1(rand.Reader, key.(*ecdsa.PrivateKey), hashbs)
	if err != nil {
		fmt.Println(err.Error())
		return []byte{}, rustC2PA.NewErrorOther(err.Error())
	}
	return bs, nil
}
