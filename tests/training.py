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

import json
import os
import sys

from c2pa import *

# set up paths to the files we we are using
PROJECT_PATH = os.getcwd()
testFile = os.path.join(PROJECT_PATH,"tests","fixtures","A.jpg")
pemFile = os.path.join(PROJECT_PATH,"tests","fixtures","es256_certs.pem")
keyFile = os.path.join(PROJECT_PATH,"tests","fixtures","es256_private.key")
testOutputFile = os.path.join(PROJECT_PATH,"target","dnt.jpg")

# a little helper function to get a value from a nested dictionary
from functools import reduce
import operator
def getitem(d, key):
    return reduce(operator.getitem, key, d)

print("version = " + version())

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
    key = open("tests/fixtures/ps256.pem","rb").read()
    def sign(data: bytes) -> bytes:
        return sign_ps256(data, key)
    
    certs = open("tests/fixtures/ps256.pub","rb").read()

    # Create a signer from a certificate pem file
    signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

    builder = Builder(manifest_json)

    builder.add_resource_file("thumbnail", "tests/fixtures/A_thumbnail.jpg")

    builder.add_ingredient_file(ingredient_json, "tests/fixtures/A.jpg")

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
    reader.resource_to_file(uri, "target/thumbnail_v2.jpg")
except Exception as err:
    sys.exit(err)

if allowed:
    print("Training is allowed")
else:
    print("Training is not allowed")

