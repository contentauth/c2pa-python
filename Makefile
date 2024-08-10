
.PHONY: all
all: rust types go

.PHONY: rust
rust:
	cargo install uniffi-bindgen-go --git https://github.com/NordSecurity/uniffi-bindgen-go --tag v0.2.1+v0.25.0
	cargo build --release

.PHONY: types
types:
	go install github.com/atombender/go-jsonschema@latest
	cargo install --git https://github.com/aquareum-tv/c2pa-rs export_schema
	go-jsonschema -p manifeststore ./target/schema/ManifestStore.schema.json -o pkg/c2pa/generated/manifeststore/manifeststore.go
	go-jsonschema -p manifestdefinition ./target/schema/ManifestDefinition.schema.json -o pkg/c2pa/generated/manifestdefinition/manifestdefinition.go
	go-jsonschema -p settings ./target/schema/Settings.schema.json -o pkg/c2pa/generated/settings/settings.go

.PHONY: go
go:
	mkdir -p dist
	uniffi-bindgen-go src/c2pa.udl --out-dir pkg/c2pa/generated
	go build -o ./dist/go-demo ./pkg/c2pa/demo/...