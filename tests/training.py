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
import c2pa_python as c2pa;

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

# first create an asset with a do not train assertion

# define a manifest with the do not train assertion
manifest_json = json.dumps({
    "claim_generator": "python_test/0.1",
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
 })

# add the manifest to the asset
try: 
    # set up the signer info loading the pem and key files
    test_pem = open(pemFile,"rb").read()
    test_key = open(keyFile,"rb").read()
    sign_info = c2pa.SignerInfo(test_pem, test_key, "es256", "http://timestamp.digicert.com")

    result = c2pa.add_manifest_to_file_json(testFile, testOutputFile, manifest_json, sign_info, False, None)
    
except Exception as err:
    sys.exit(err)

print("successfully added do not train manifest to file " + testOutputFile)


# now verify the asset and check the manifest for a do not train assertion

allowed = True # opt out model, assume training is ok if the assertion doesn't exist
try:
    manifest_store = json.loads(c2pa.verify_from_file_json(testOutputFile))

    manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
    for assertion in manifest["assertions"]:
        if assertion["label"] == "c2pa.training-mining":
            if getitem(assertion, ("data","entries","c2pa.ai_training","use")) == "notAllowed":
                allowed = False

except Exception as err:
    sys.exit(err)

if allowed:
    print("Training is allowed")
else:
    print("Training is not allowed")

