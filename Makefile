
.PHONY: all
all: rust go

.PHONY: rust
rust:
	cargo install uniffi-bindgen-go --git https://github.com/NordSecurity/uniffi-bindgen-go --tag v0.2.1+v0.25.0
	cargo build --release

.PHONY: go
go:
	mkdir -p dist
	uniffi-bindgen-go src/c2pa.udl --out-dir pkg/c2pa/generated
	go build -o ./dist/go-demo ./pkg/c2pa/demo/...
