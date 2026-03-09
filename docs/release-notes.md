# Release notes

## Version 0.6.0

<!-- Get features and updates -->

See [Release tag 0.6.0](https://github.com/contentauth/c2pa-python/releases/tag/v0.6.0).

### Breaking changes

The signature of the `c2pa.sign_ps256()` method changed.  Previously, the argument was a file path but now its the PEM certificate string. 

## Version 0.5.2

New features:

- Allow EC signatures in DER format from signers and verify signature format during validation.
- Fix bug in signing audio and video files in ISO Base Media File Format (BMFF).
- Add the ability to verify PDF files (but not to sign them).
- Increase speed of `sign_file` by 2x or more, when using file paths (uses native Rust file I/O).
- Fixes for RIFF and GIF formats.

## Version 0.5.0

New features in this release:

- Rewrites the API to be stream-based using a Builder / Reader model.
- The functions now support throwing `c2pa.Error` values, caught with `try`/`except`.
- Instead of `c2pa.read_file` you now call `c2pa_api.Reader.from_file` and `reader.json`.
- Read thumbnails and other resources use `reader.resource_to_stream` or `reader.resource.to_file`.
- Instead of `c2pa.sign_file` use `c2pa_api.Builder.from_json` and `builder.sign` or `builder.sign_file`.
- Add thumbnails or other resources with `builder.add_resource` or `builder.add_resource_file`.
- Add Ingredients with `builder.add_ingredient` or `builder.add_ingredient_file`.
- You can archive a `Builder` using `builder.to_archive` and reconstruct it with `builder.from_archive`.
- Signers can be constructed with `c2pa_api.create_signer`.
- The signer now requires a signing function to keep private keys private.
- Example signing functions are provided in c2pa_api.py

## Version 0.4.0

This release:

- Changes the name of the import from `c2pa-python` to `c2pa`.
- Supports pre-built platform wheels for macOS, Windows and [manylinux](https://github.com/pypa/manylinux).

## Version 0.3.0

This release includes some breaking changes to align with future APIs:

- `C2paSignerInfo` moves the `alg` to the first parameter from the 3rd.
- `c2pa.verify_from_file_json` is now `c2pa.read_file`.
- `c2pa.ingredient_from_file_json` is now `c2pa.read_ingredient_file`.
- `c2pa.add_manifest_to_file_json` is now `c2pa.sign_file`.
- There are many more specific errors types now, and Error messages always start with the name of the error i.e (str(err.value).startswith("ManifestNotFound")).
- The ingredient thumbnail identifier may be jumbf uri reference if a valid thumb already exists in the active manifest.
- Extracted file paths for read_file now use a folder structure and different naming conventions.
