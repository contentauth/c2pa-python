package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"git.aquareum.tv/aquareum-tv/c2pa-go/pkg/c2pa"
)

func Start() error {
	fs := flag.NewFlagSet("c2pa-go-demo", flag.ExitOnError)
	manifest := fs.String("manifest", "", "manifest file for signing")
	cert := fs.String("cert", "", "certificate file to use")
	key := fs.String("key", "", "private key file to use")
	input := fs.String("input", "", "input file for signing")
	output := fs.String("output", "", "output file for signing")
	alg := fs.String("alg", "", "algorithm to use to sign (es256, es256k, es384, es512, ps256, ps384, ps512, ed25519)")
	pass := os.Args[1:]
	err := fs.Parse(pass)
	if err != nil {
		return err
	}
	if *manifest != "" || *output != "" {
		if *manifest == "" {
			return fmt.Errorf("missing --manifest")
		}
		if *output == "" {
			return fmt.Errorf("missing --output")
		}
		if *input == "" {
			return fmt.Errorf("missing --input")
		}
		if *cert == "" {
			return fmt.Errorf("missing --cert")
		}
		if *key == "" {
			return fmt.Errorf("missing --key")
		}
		if *alg == "" {
			return fmt.Errorf("missing --alg")
		}
		certBytes, err := os.ReadFile(*cert)
		if err != nil {
			return err
		}
		keyBytes, err := os.ReadFile(*key)
		if err != nil {
			return err
		}
		manifestBytes, err := os.ReadFile(*manifest)
		if err != nil {
			return err
		}
		var manifest c2pa.ManifestDefinition
		err = json.Unmarshal(manifestBytes, &manifest)
		if err != nil {
			return err
		}
		b, err := c2pa.NewBuilder(&manifest, &c2pa.BuilderParams{
			Cert:      certBytes,
			Key:       keyBytes,
			Algorithm: *alg,
			TAURL:     "http://timestamp.digicert.com",
		})
		if err != nil {
			return err
		}
		err = b.SignFile(*input, *output)
		if err != nil {
			return err
		}
		return nil
	}
	args := fs.Args()
	if len(args) != 1 {
		fs.Usage()
		fmt.Printf("usage: %s [target-file]\n", os.Args[0])
		return nil
	}
	fname := args[0]
	reader, err := c2pa.FromFile(fname)
	if err != nil {
		return err
	}

	activeManifest := reader.GetActiveManifest()
	if activeManifest == nil {
		return fmt.Errorf("could not find active manifest")
	}

	bs, err := json.MarshalIndent(activeManifest, "", "  ")
	if err != nil {
		return err
	}

	fmt.Println(string(bs))
	return nil
}

func main() {
	err := Start()
	if err != nil {
		panic(err)
	}
}
