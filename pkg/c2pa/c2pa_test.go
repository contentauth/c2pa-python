package c2pa

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"os"

	"github.com/stretchr/testify/require"
)

func getFixtures() string {
	_, filename, _, _ := runtime.Caller(0)
	dir := filepath.Dir(filename)
	return filepath.Join(dir, "..", "..", "tests", "fixtures")
}

func getPair(name string) ([]byte, []byte, error) {
	fixtures := getFixtures()

	certBytes, err := os.ReadFile(filepath.Join(fixtures, fmt.Sprintf("%s_certs.pem", name)))
	if err != nil {
		return nil, nil, err
	}
	keyBytes, err := os.ReadFile(filepath.Join(fixtures, fmt.Sprintf("%s_private.key", name)))
	if err != nil {
		return nil, nil, err
	}
	return certBytes, keyBytes, nil
}

func TestSigning(t *testing.T) {
	tests := []struct {
		name string
	}{
		{"es256"},
		{"es256k"},
	}

	dname, err := os.MkdirTemp("", "c2pa-go-test")
	require.NoError(t, err)
	defer os.RemoveAll(dname)

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			certBytes, keyBytes, err := getPair(test.name)
			require.NoError(t, err)
			manifestBs := []byte(`
				{
					"title": "Image File",
					"assertions": [
						{
							"label": "c2pa.actions",
							"data": { "actions": [{ "action": "c2pa.published" }] }
						}
					]
				}
			`)
			var manifest ManifestDefinition
			err = json.Unmarshal(manifestBs, &manifest)
			require.NoError(t, err)
			b, err := NewBuilder(&manifest, &BuilderParams{
				Cert:      certBytes,
				Key:       keyBytes,
				Algorithm: test.name,
				TAURL:     "http://timestamp.digicert.com",
			})
			require.NoError(t, err)

			fixtures := getFixtures()
			input := filepath.Join(fixtures, "A.jpg")
			output := filepath.Join(dname, fmt.Sprintf("A-signed-%s.jpg", test.name))

			err = b.SignFile(input, output)
			require.NoError(t, err)

			err = c2patool(output)
			require.NoError(t, err)
		})
	}
}

type C2PAToolOutput struct {
	ActiveManifest string `json:"active_manifest"`
	Manifests      struct {
		UrnUUID struct {
			ClaimGenerator     string `json:"claim_generator"`
			ClaimGeneratorInfo []struct {
				Name    string `json:"name"`
				Version string `json:"version"`
			} `json:"claim_generator_info"`
			Title       string `json:"title"`
			Format      string `json:"format"`
			InstanceID  string `json:"instance_id"`
			Ingredients []any  `json:"ingredients"`
			Assertions  []struct {
				Label string `json:"label"`
				Data  struct {
					Actions []struct {
						Action string `json:"action"`
					} `json:"actions"`
				} `json:"data"`
			} `json:"assertions"`
			SignatureInfo struct {
				Alg              string    `json:"alg"`
				Issuer           string    `json:"issuer"`
				CertSerialNumber string    `json:"cert_serial_number"`
				Time             time.Time `json:"time"`
			} `json:"signature_info"`
			Label string `json:"label"`
		} `json:"urn:uuid"`
	} `json:"manifests"`
	ValidationStatus []struct {
		Code        string `json:"code"`
		URL         string `json:"url"`
		Explanation string `json:"explanation"`
	} `json:"validation_status"`
}

// validate a file with c2patool
func c2patool(file string) error {
	outbs, err := exec.Command("c2patool", file).Output()
	if err != nil {
		return err
	}
	var out C2PAToolOutput
	err = json.Unmarshal(outbs, &out)
	if err != nil {
		return err
	}
	if len(out.ValidationStatus) > 0 {
		errbs, err := json.Marshal(out.ValidationStatus)
		if err != nil {
			panic("validation status testing error")
		}
		return fmt.Errorf(string(errbs))
	}
	return nil
}

func TestC2PATool(t *testing.T) {
	fixtures := getFixtures()
	err := c2patool(filepath.Join(fixtures, "C.jpg"))
	require.NoError(t, err)
	err = c2patool(filepath.Join(fixtures, "screenshot-signed-badsig.jpg"))
	require.Error(t, err)
}
