
.PHONY: all
all: rust types go

.PHONY: rust
rust:
	cargo install uniffi-bindgen-go --git https://github.com/NordSecurity/uniffi-bindgen-go --tag v0.3.0+v0.28.3
	cargo build --release

.PHONY: types
types:
	go install github.com/atombender/go-jsonschema@v0.17.0
	cargo install --git https://github.com/aquareum-tv/c2pa-rs export_schema
	export_schema
	go-jsonschema --only-models -p manifeststore ./target/schema/ManifestStore.schema.json -o pkg/c2pa/generated/manifeststore/manifeststore.go
	go-jsonschema --only-models -p manifestdefinition ./target/schema/ManifestDefinition.schema.json -o pkg/c2pa/generated/manifestdefinition/manifestdefinition.go
	go-jsonschema --only-models -p settings ./target/schema/Settings.schema.json -o pkg/c2pa/generated/settings/settings.go

.PHONY: go
go:
	mkdir -p dist
	uniffi-bindgen-go src/c2pa.udl --out-dir pkg/c2pa/generated
	go build -a -o ./dist/go-demo ./pkg/c2pa/demo/...

# need es256k-enabled c2patool
.PHONY: test
test:
	cargo install --git https://git.stream.place/aquareum-tv/c2patool.git
	go test ./pkg/...