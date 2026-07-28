import json
import os
import sys
import urllib.error
import urllib.request

import c2pa

# This example shows how to intercept every HTTP request the C2PA SDK makes,
# by attaching a custom HTTP resolver to a Context. The resolver logs the
# method and URL of each request and the status code of each response, while
# delegating the actual transfer to urllib from the standard library.
#
# A resolver sees all SDK HTTP traffic: remote manifest fetches, OCSP
# requests, RFC 3161 timestamp requests, and CAWG did:web resolution.
#
# This example needs internet access: tests/fixtures/cloud.jpg carries no
# embedded manifest, only a remote one that has to be fetched.

fixtures_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures") + os.sep
output_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output") + os.sep


class DebugHttpResolver:
    """Logs every SDK HTTP request and response status.

    The actual transfer is delegated to urllib, which also gives us redirect
    handling for free: the SDK itself does not follow redirects, so a
    hand-rolled resolver would have to implement that.
    """

    def __init__(self, timeout=10.0):
        self._timeout = timeout

    def resolve(self, request):
        print(f"[http] {request.method} {request.url}", flush=True)

        # Timestamp requests POST a body; manifest fetches send none.
        data = request.body or None
        req = urllib.request.Request(
            request.url,
            data=data,
            method=request.method,
            headers=request.headers)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
                print(f"[http]   -> {resp.status} ({len(body)} bytes)",
                      flush=True)
                return c2pa.HttpResponse(resp.status, body)
        except urllib.error.HTTPError as e:
            # A 4xx/5xx is still a real response. Pass the status through and
            # let the SDK turn it into its own typed error: a remote manifest
            # fetch only accepts 200.
            body = e.read()
            print(f"[http]   -> {e.code}", flush=True)
            return c2pa.HttpResponse(e.code, body)
        # urllib.error.URLError (DNS failure, connection refused, timeout) is
        # deliberately not caught: raising marks the request as a hard
        # resolver failure, which surfaces as a typed C2paError.


def read_with_resolver():
    """Read an asset whose manifest lives at a remote URL."""
    print("\n--- Reading cloud.jpg (manifest is remote):")

    resolver = DebugHttpResolver()
    with c2pa.Context.builder().with_resolver(resolver).build() as context:
        with open(fixtures_dir + "cloud.jpg", "rb") as f:
            with c2pa.Reader("image/jpeg", f, context=context) as reader:
                print(f"validation state: {reader.get_validation_state()}")
                print(f"embedded manifest: {reader.is_embedded()}")
                print(f"remote URL: {reader.get_remote_url()}")


def sign_with_resolver():
    """Sign an asset, adding an ingredient whose manifest is remote."""
    print("\n--- Signing A.jpg with a remote-manifest ingredient:")

    with open(fixtures_dir + "es256_certs.pem", "rb") as f:
        certs = f.read()
    with open(fixtures_dir + "es256_private.key", "rb") as f:
        key = f.read()

    # ta_url is None, meaning "no timestamp authority". An empty string is
    # treated as a URL and fails signing.
    signer_info = c2pa.C2paSignerInfo(
        alg=b"es256", sign_cert=certs, private_key=key, ta_url=None)

    manifest_definition = {
        "claim_generator": "http_resolver_debug",
        "claim_generator_info": [
            {"name": "http_resolver_debug", "version": "0.1"}],
        "format": "image/jpeg",
        "title": "Signed with a debug HTTP resolver",
        "assertions": [],
    }

    resolver = DebugHttpResolver()
    context = (c2pa.Context.builder()
               .with_resolver(resolver)
               .with_signer(c2pa.Signer.from_info(signer_info))
               .build())
    try:
        builder = c2pa.Builder(manifest_definition, context=context)

        # Adding this ingredient fetches its remote manifest through the
        # resolver, so one GET shows up in the log.
        with open(fixtures_dir + "cloud.jpg", "rb") as ingredient:
            builder.add_ingredient(
                {"title": "cloud.jpg"}, "image/jpeg", ingredient)

        os.makedirs(output_dir, exist_ok=True)
        output_path = output_dir + "A_signed_resolver.jpg"
        with open(fixtures_dir + "A.jpg", "rb") as source:
            with open(output_path, "wb") as dest:
                builder.sign(
                    c2pa.Signer.from_info(signer_info),
                    "image/jpeg", source, dest)
        print(f"signed asset written to {output_path}")

        # Reading the signed file back uses its embedded manifest,
        # so this makes no HTTP requests at all.
        print("\n--- Reading the signed asset (no HTTP expected): ")
        with open(output_path, "rb") as f:
            with c2pa.Reader("image/jpeg", f) as reader:
                store = json.loads(reader.json())
                manifest = store["manifests"][store["active_manifest"]]
                for ingredient in manifest.get("ingredients", []):
                    print(f"ingredient: {ingredient.get('title')}")
    finally:
        context.close()


def main():
    try:
        read_with_resolver()
        sign_with_resolver()
    except c2pa.C2paError as e:
        message = str(e)
        if "fetch" in message or "resolver" in message:
            print(f"\nError: {e}")
            print("This example needs internet access to fetch the remote "
                  "manifest for tests/fixtures/cloud.jpg.")
            sys.exit(1)
        raise

    print("\nNote: with a ta_url set on the signer, the log above would also "
          "show the RFC 3161 timestamp POST.")


if __name__ == "__main__":
    main()
