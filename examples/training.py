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
import sys

# Example of using python crypto to sign data using openssl with Ps256
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from c2pa import *

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# set up paths to the files we we are using
testFile = os.path.join(fixtures_dir, "A.jpg")
pemFile = os.path.join(fixtures_dir, "ps256.pub")
keyFile = os.path.join(fixtures_dir, "ps256.pem")
testOutputFile = os.path.join(output_dir, "dnt.jpg")

# a little helper function to get a value from a nested dictionary
from functools import reduce
import operator
def getitem(d, key):
    return reduce(operator.getitem, key, d)


# This function signs data with PS256 using a private key
def sign_ps256(data: bytes, key: bytes) -> bytes:
    private_key = serialization.load_pem_private_key(
        key,
        password=None,
    )
    signature = private_key.sign(
        data,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature

# first create an asset with a do not train assertion

# define a manifest with the do not train assertion
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
      "label": "c2pa.training-mining",
      "data": {
        "entries": {
          "c2pa.ai_generative_training": { "use": "notAllowed" },
          "c2pa.ai_inference": { "use": "notAllowed" },
          "c2pa.ai_training": { "use": "notAllowed" },
          "c2pa.data_mining": { "use": "notAllowed" }
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

# V2 signing api
try:
    # This could be implemented on a server using an HSM
    key = open(keyFile,"rb").read()
    def sign(data: bytes) -> bytes:
        print("data len = ", len(data))
        #return ed25519_sign(data, key)
        return sign_ps256(data, key)

    certs = open(pemFile,"rb").read()

    import traceback
    # Create a signer from a certificate pem file
    try:
        signer = create_signer(sign, C2paSigningAlg.PS256, certs, "http://timestamp.digicert.com")
    except Exception as e:
        print("An error occurred:")
        traceback.print_exc()
    builder = Builder(manifest_json)

    builder.add_resource_file("thumbnail", fixtures_dir + "A_thumbnail.jpg")

    builder.add_ingredient_file(ingredient_json, fixtures_dir + "A_thumbnail.jpg")

    if os.path.exists(testOutputFile):
        os.remove(testOutputFile)
        
    result = builder.sign_file(signer, testFile, testOutputFile)

except Exception as err:
    sys.exit(err)

print("V2: successfully added do not train manifest to file " + testOutputFile)


# now verify the asset and check the manifest for a do not train assertion

allowed = True # opt out model, assume training is ok if the assertion doesn't exist
try:
    reader = Reader.from_file(testOutputFile)
    manifest_store = json.loads(reader.json())

    manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
    for assertion in manifest["assertions"]:
        if assertion["label"] == "c2pa.training-mining":
            if getitem(assertion, ("data","entries","c2pa.ai_training","use")) == "notAllowed":
                allowed = False

    # get the ingredient thumbnail
    uri = getitem(manifest,("ingredients", 0, "thumbnail", "identifier"))
    reader.resource_to_file(uri, output_dir + "thumbnail_v2.jpg")
except Exception as err:
    sys.exit(err)

if allowed:
    print("Training is allowed")
else:
    print("Training is not allowed")
