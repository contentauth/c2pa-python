
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

import c2pa
import pytest
import json
import tempfile
import c2pa_api

# a little helper function to get a value from a nested dictionary
from functools import reduce
import operator

manifest_def = {
    "claim_generator_info": [{
        "name": "python test",
        "version": "0.1"
    }],
    "title": "My Title",
    "thumbnail": {
        "format": "image/jpeg",
        "identifier": "A.jpg"
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

def getitem(d, key):
    return reduce(operator.getitem, key, d)

def test_version():
    assert c2pa.version() == "0.4.0"

def test_sdk_version():
    assert "c2pa-rs/" in c2pa.sdk_version()

def test_v2_read():
     #example of reading a manifest store from a file
    try:
        reader = c2pa_api.Reader.from_file("tests/fixtures/C.jpg")
        jsonReport = reader.json()
        manifest_store = json.loads(jsonReport)
        manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
        assert "make_test_images" in manifest["claim_generator"]
        assert manifest["title"]== "C.jpg"
        assert manifest,["format"] == "image/jpeg"
        # There should be no validation status errors
        assert manifest.get("validation_status") == None
        # read creative work assertion (author name)
        assert getitem(manifest,("assertions",0,"label")) == "stds.schema-org.CreativeWork"
        assert getitem(manifest,("assertions",0,"data","author",0,"name")) == "Adobe make_test"
        # read Actions assertion
        assert getitem(manifest,("assertions",1,"label")) == "c2pa.actions"
        assert getitem(manifest,("assertions",1,"data","actions",0,"action")) == "c2pa.created"
        # read signature info
        assert getitem(manifest,("signature_info","issuer")) == "C2PA Test Signing Cert"
        # read thumbnail data from file
        assert getitem(manifest,("thumbnail","format")) == "image/jpeg"
        # check the thumbnail data
        uri = getitem(manifest,("thumbnail","identifier"))
        reader.resource_file(uri, "target/thumbnail_read_v2.jpg")

    except Exception as e:
        print("Failed to read manifest store: " + str(e))
        exit(1)

def test_v2_sign():
    # define a source folder for any assets we need to read
    data_dir = "tests/fixtures/"
    try:
        def sign_ps256(data: bytes) -> bytes:
            return c2pa_api.sign_ps256(data, data_dir+"ps256.pem")
        
        certs = open(data_dir + "ps256.pub", "rb").read()
        # Create a local signer from a certificate pem file
        signer = c2pa_api.LocalSigner.from_settings(sign_ps256, c2pa.SigningAlg.PS256, certs, "http://timestamp.digicert.com")

        builder = c2pa_api.Builder(signer, manifest_def)

        builder.add_resource_file("A.jpg", data_dir + "A.jpg")

        with tempfile.TemporaryDirectory() as output_dir:
            c2pa_data = builder.sign_file(data_dir + "A.jpg", output_dir + "out.jpg")
            assert len(c2pa_data) > 0

        reader = c2pa_api.Reader.from_file(output_dir + "out.jpg")
        print(reader.json())
        manifest_store = json.loads(reader.json())
        manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
        assert "python_test" in manifest["claim_generator"]
        # check custom title and format
        assert manifest["title"]== "My Title" 
        assert manifest,["format"] == "image/jpeg"
        # There should be no validation status errors
        assert manifest.get("validation_status") == None
    except Exception as e:
        print("Failed to sign manifest store: " + str(e))
        exit(1)