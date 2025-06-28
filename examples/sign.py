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
# and read the metadata added to the image.

import os
import c2pa

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# ensure the output directory exists
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

print("c2pa version:")
version = c2pa.sdk_version()
print(version)

# Read existing C2PA metadata from the file
print("\nReading existing C2PA metadata:")
with open(fixtures_dir + "C.jpg", "rb") as file:
    reader = c2pa.Reader("image/jpeg", file)
    print(reader.json())

# Create a signer from certificate and key files
certs = open(fixtures_dir + "es256_certs.pem", "rb").read()
key = open(fixtures_dir + "es256_private.key", "rb").read()

signer_info = c2pa.C2paSignerInfo(
    alg=b"es256",  # Use bytes instead of encoded string
    sign_cert=certs,
    private_key=key,
    ta_url=b"http://timestamp.digicert.com"  # Use bytes and add timestamp URL
)

signer = c2pa.Signer.from_info(signer_info)

# Create a manifest definition as a dictionary
manifest_definition = {
    "claim_generator": "python_example",
    "claim_generator_info": [{
        "name": "python_example",
        "version": "0.0.1",
    }],
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
                        "parameters": {
                            # could hold additional information about this step
                        }
                    }
                ]
            }
        }
    ]
}

builder = c2pa.Builder(manifest_definition)

# Sign the image
print("\nSigning the image...")
with open(fixtures_dir + "C.jpg", "rb") as source:
    with open(output_dir + "C_signed.jpg", "wb") as dest:
        result = builder.sign(signer, "image/jpeg", source, dest)

# Read the signed image to verify
print("\nReading signed image metadata:")
with open(output_dir + "C_signed.jpg", "rb") as file:
    reader = c2pa.Reader("image/jpeg", file)
    print(reader.json())

print("\nExample completed successfully!")

