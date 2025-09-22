# Copyright 2025 Adobe. All rights reserved.
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

# This example shows how to sign an image with a C2PA manifest
# using a callback signer and read the metadata added to the image.

import os
import c2pa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

# Note: Builder, Reader, and Signer support being used as context managers
# (with 'with' statements), but this example shows manual usage which requires
# explicitly calling the close() function to clean up resources.

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# Ensure the output directory exists
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

print("c2pa version:")
version = c2pa.sdk_version()
print(version)


# Load certificates and private key (here from the test fixtures).
# This is OK for development, but in production you should use a
# secure way to load the certificates and private key.
with open(fixtures_dir + "es256_certs.pem", "rb") as cert_file:
    certs = cert_file.read()
with open(fixtures_dir + "es256_private.key", "rb") as key_file:
    key = key_file.read()

# Define a callback signer function
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

# Create a manifest definition as a dictionary.
# This manifest follows the V2 manifest format.
manifest_definition = {
    "claim_generator": "python_example",
    "claim_generator_info": [{
        "name": "python_example",
        "version": "0.0.1",
    }],
    # Claims version 2 is the default, so the version
    # number can be omitted.
    # "claim_version": 2,
    "format": "image/jpeg",
    "title": "Python Example Image",
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

# Sign the image with the signer created above,
# which will use the callback signer
print("\nSigning the image file...")

with c2pa.Signer.from_callback(
    callback=callback_signer_es256,
    alg=c2pa.C2paSigningAlg.ES256,
    certs=certs.decode('utf-8'),
    tsa_url="http://timestamp.digicert.com"
) as signer:
    with c2pa.Builder(manifest_definition) as builder:
        builder.sign_file(
            source_path=fixtures_dir + "A.jpg",
            dest_path=output_dir + "A_signed.jpg",
            signer=signer
        )

# Re-Read the signed image to verify
print("\nReading signed image metadata:")
with open(output_dir + "A_signed.jpg", "rb") as file:
    with c2pa.Reader("image/jpeg", file) as reader:
        print(reader.json())

print("\nExample completed successfully!")

