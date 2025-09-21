# Copyright 2023 Adobe. All rights reserved.
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

# This example shows how to add a do not train assertion to an asset and then verify it
# We use python crypto to sign the data using openssl with Ps256 here

import json
import os

# Example of using python crypto to sign data using openssl with Ps256
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import c2pa

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# Ensure the output directory exists
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Set up paths to the files we we are using
testFile = os.path.join(fixtures_dir, "A.jpg")
pemFile = os.path.join(fixtures_dir, "ps256.pub")
keyFile = os.path.join(fixtures_dir, "ps256.pem")
testOutputFile = os.path.join(output_dir, "dnt.jpg")

# A little helper function to get a value from a nested dictionary
from functools import reduce
import operator
def getitem(d, key):
    return reduce(operator.getitem, key, d)

# First create an asset with a do not train assertion
# Define a manifest with the do not train assertion
manifest_json = {
    "claim_generator_info": [{
        "name": "python_test",
        "version": "0.1"
    }],
    "title": "Do Not Train Example",
    "thumbnail": {
        "format": "image/jpeg",
        "identifier": "thumbnail"
    },
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
        },
        {
            "label": "cawg.training-mining",
            "data": {
                "entries": {
                    "cawg.ai_inference": {
                        "use": "notAllowed"
                    },
                    "cawg.ai_generative_training": {
                        "use": "notAllowed"
                    }
                }
            }
        }
    ]
}

ingredient_json = {
    "title": "A.jpg",
    "relationship": "parentOf",
    "thumbnail": {
        "identifier": "thumbnail",
        "format": "image/jpeg"
    }
}

# V2 signing API example
try:
    # Read the private key and certificate files
    with open(keyFile, "rb") as key_file:
        key = key_file.read()
    with open(pemFile, "rb") as cert_file:
        certs = cert_file.read()

    # Create a signer using the new API
    signer_info = c2pa.C2paSignerInfo(
        alg=b"ps256",
        sign_cert=certs,
        private_key=key,
        ta_url=b"http://timestamp.digicert.com"
    )

    with c2pa.Signer.from_info(signer_info) as signer:
        with c2pa.Builder(manifest_json) as builder:
            # Add the thumbnail resource using a stream
            with open(fixtures_dir + "A_thumbnail.jpg", "rb") as thumbnail_file:
                builder.add_resource("thumbnail", thumbnail_file)

            # Add the ingredient using the correct method
            with open(fixtures_dir + "A_thumbnail.jpg", "rb") as ingredient_file:
                builder.add_ingredient(json.dumps(ingredient_json), "image/jpeg", ingredient_file)

            if os.path.exists(testOutputFile):
                os.remove(testOutputFile)

            # Sign the file using the stream-based sign method
            with open(testFile, "rb") as source_file:
                with open(testOutputFile, "w+b") as dest_file:
                    result = builder.sign(signer, "image/jpeg", source_file, dest_file)

            # As an alternative, you can also use file paths directly during signing:
            # builder.sign_file(testFile, testOutputFile, signer)

except Exception as err:
    print(f"Exception during signing: {err}")

print(f"\nSuccessfully added do not train manifest to file {testOutputFile}")

# now verify the asset and check the manifest for a do not train assertion...

allowed = True # opt out model, assume training is ok if the assertion doesn't exist
try:
    # Create reader using the Reader API
    with c2pa.Reader(testOutputFile) as reader:
        # Retrieve the manifest store
        manifest_store = json.loads(reader.json())

        # Look at data in the active manifest
        manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
        for assertion in manifest["assertions"]:
            if assertion["label"] == "cawg.training-mining":
                if getitem(assertion, ("data","entries","cawg.ai_generative_training","use")) == "notAllowed":
                    allowed = False

        # Get the ingredient thumbnail and save it to a file using resource_to_stream
        uri = getitem(manifest,("ingredients", 0, "thumbnail", "identifier"))
        with open(output_dir + "thumbnail_v2.jpg", "wb") as thumbnail_output:
            reader.resource_to_stream(uri, thumbnail_output)

except Exception as err:
    print(f"Exception during assertions reading: {err}")

if allowed:
    print("Training is allowed")
else:
    print("Training is not allowed")
