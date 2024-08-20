package c2pa

import (
	"crypto"
	"crypto/rsa"
	"fmt"

	rustC2PA "git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/c2pa"
)

type SigningAlgorithmName string

const (
	ED25519 SigningAlgorithmName = "ed25519"
	ES256   SigningAlgorithmName = "es256"
	ES256K  SigningAlgorithmName = "es256k"
	ES384   SigningAlgorithmName = "es384"
	ES512   SigningAlgorithmName = "es512"
	PS256   SigningAlgorithmName = "ps256"
	PS384   SigningAlgorithmName = "ps384"
	PS512   SigningAlgorithmName = "ps512"
)

type SigningAlgorithm struct {
	Name         SigningAlgorithmName
	RustC2PAType rustC2PA.SigningAlg
	Hash         crypto.Hash
}

func GetSigningAlgorithm(algStr string) (*SigningAlgorithm, error) {
	alg := SigningAlgorithmName(algStr)
	switch alg {
	case ED25519:
		return &SigningAlgorithm{ED25519, rustC2PA.SigningAlgEd25519, crypto.Hash(0)}, nil
	case ES256:
		return &SigningAlgorithm{ES256, rustC2PA.SigningAlgEs256, crypto.SHA256}, nil
	case ES256K:
		return &SigningAlgorithm{ES256K, rustC2PA.SigningAlgEs256k, crypto.SHA256}, nil
	case ES384:
		return &SigningAlgorithm{ES384, rustC2PA.SigningAlgEs384, crypto.SHA384}, nil
	case ES512:
		return &SigningAlgorithm{ES512, rustC2PA.SigningAlgEs512, crypto.SHA512}, nil
	case PS256:
		return &SigningAlgorithm{PS256, rustC2PA.SigningAlgPs256, crypto.SHA256}, nil
	case PS384:
		return &SigningAlgorithm{PS384, rustC2PA.SigningAlgPs384, crypto.SHA384}, nil
	case PS512:
		return &SigningAlgorithm{PS512, rustC2PA.SigningAlgPs512, crypto.SHA512}, nil
	default:
		return nil, fmt.Errorf("algorithm not found: %s", alg)
	}
}

// get digest and crypto options for passing to the actual signer
func (alg *SigningAlgorithm) Digest(data []byte) ([]byte, crypto.SignerOpts, error) {
	switch alg.Name {
	case ED25519:
		// ed25519 handles its own hashing
		return data, alg.Hash, nil
	case ES256, ES256K, ES384, ES512:
		h := alg.Hash.New()
		h.Write(data)
		digest := h.Sum(nil)
		return digest, alg.Hash, nil
	case PS256, PS384, PS512:
		h := alg.Hash.New()
		h.Write(data)
		digest := h.Sum(nil)
		opts := &rsa.PSSOptions{
			Hash:       alg.Hash,
			SaltLength: rsa.PSSSaltLengthEqualsHash,
		}
		return digest, opts, nil
	}
	return nil, nil, fmt.Errorf("unknown algorithm: %s", alg.Name)
}
