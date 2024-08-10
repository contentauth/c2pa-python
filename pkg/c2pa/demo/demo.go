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
	fs.Parse(os.Args)
	args := fs.Args()
	if len(args) != 2 {
		fmt.Printf("usage: %s [target-file]\n", os.Args[0])
		return nil
	}
	fname := args[1]
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
