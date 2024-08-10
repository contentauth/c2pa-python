package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"mime"
	"os"
	"path/filepath"

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
	f, err := os.Open(fname)
	if err != nil {
		return err
	}
	defer f.Close()
	mType := mime.TypeByExtension(filepath.Ext(fname))
	if mType == "" {
		return fmt.Errorf("couldn't find MIME type for filename %s", fname)
	}
	manifest, err := c2pa.GetManifest(f, mType)
	if err != nil {
		return err
	}

	bs, err := json.MarshalIndent(manifest, "", "  ")
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
