package c2pa

import (
	"crypto"
	"crypto/rand"

	rustC2PA "git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa/generated/c2pa"
)

type C2PACallbackSigner struct {
	signer    crypto.Signer
	algorithm SigningAlgorithm
}

func (s *C2PACallbackSigner) Sign(data []byte) ([]byte, *rustC2PA.Error) {
	bs, err := s._sign(data)
	if err != nil {
		return nil, rustC2PA.NewErrorSignature(err.Error())
	}
	return bs, nil
}

func (s *C2PACallbackSigner) _sign(data []byte) ([]byte, error) {
	digest, opts, err := s.algorithm.Digest(data)
	if err != nil {
		return nil, err
	}

	return s.signer.Sign(rand.Reader, digest, opts)
}
