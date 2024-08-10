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
	output := fs.String("output", "", "output file for signing")
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
		c2pa.NewBuilder()
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
