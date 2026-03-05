# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.
# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

# Shows how to use Context+Settings API to control
# thumbnails added to the manifest.
#
# This example uses Settings to explicitly turn off
# thumbnail addition when signing.

import json
import os
import c2pa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# Ensure the output directory exists.
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Load certificates and private key (here from the unit test fixtures).
with open(fixtures_dir + "es256_certs.pem", "rb") as cert_file:
    certs = cert_file.read()
with open(fixtures_dir + "es256_private.key", "rb") as key_file:
    key = key_file.read()

# Define a callback signer function.
def callback_signer_es256(data: bytes) -> bytes:
    """Callback function that signs data using ES256 algorithm."""
    private_key = serialization.load_pem_private_key(
        key,
        password=None,
        backend=default_backend()
    )
    signature = private_key.sign(
        data,
        ec.ECDSA(hashes.SHA256())
    )
    return signature

# Create a manifest definition.
manifest_definition = {
    "claim_generator_info": [{
        "name": "python_no_thumbnail_example",
        "version": "0.1.0",
    }],
    "format": "image/jpeg",
    "title": "No Thumbnail Example",
    "ingredients": [],
    "assertions": [
        {
            "label": "c2pa.actions",
            "data": {
                "actions": [
                    {
                        "action": "c2pa.created",
                        "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                    }
                ]
            }
        }
    ]
}

# Use Settings to disable thumbnail generation,
# Settings are JSON matching the C2PA SDK settings schema
settings = c2pa.Settings.from_dict({
    "builder": {
        "thumbnail": {"enabled": False}
    }
})

print("Signing image with thumbnails disabled through settings...")
context = c2pa.Context(settings=settings)
with c2pa.Signer.from_callback(
    callback=callback_signer_es256,
    alg=c2pa.C2paSigningAlg.ES256,
    certs=certs.decode('utf-8'),
    tsa_url="http://timestamp.digicert.com"
) as signer:
    with c2pa.Builder(manifest_definition, context=context) as builder:
        builder.sign_file(
            source_path=fixtures_dir + "A.jpg",
            dest_path=output_dir + "A_no_thumbnail.jpg",
            signer=signer
        )

# Read the signed image and verify no thumbnail is present.
with c2pa.Reader(output_dir + "A_no_thumbnail.jpg", context=context) as reader:
    manifest_store = json.loads(reader.json())
    manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

    if manifest.get("thumbnail") is None:
        print("No thumbnail in the manifest as per settings.")
    else:
        print("Thumbnail found in the manifest.")

# TODO-TMN: use with context here
context.close()

print("\nExample completed successfully!")
