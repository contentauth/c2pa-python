package c2pa

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"encoding/pem"
	"errors"
	"fmt"
	"reflect"

	"github.com/decred/dcrd/dcrec/secp256k1"
)

func MakeStaticSigner(keybs []byte) (crypto.Signer, error) {
	block, _ := pem.Decode(keybs)

	if block == nil {
		return nil, fmt.Errorf("failed to parse PEM block containing the private key")
	}
	key, err := parsePrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("parsePrivateKey failed: %s", err.Error())
	}
	return key, nil
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
