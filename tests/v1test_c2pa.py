
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
    "claim_generator": "python_test/0.1",
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
    #assert c2pa.sdk_version() == "0.29.0-dev"


def test_verify_from_file():
    json_store = c2pa.read_file("tests/fixtures/C.jpg", None) 
    assert not "validation_status" in json_store

def test_verify_from_file_no_store():
    with pytest.raises(c2pa.Error.ManifestNotFound) as err:  
        json_store = c2pa.read_file("tests/fixtures/A.jpg", None) 
    #assert str(err.value).startswith("ManifestNotFound")

def test_verify_from_file_get_thumbnail():
    with tempfile.TemporaryDirectory() as data_dir:
        store_json = c2pa.read_file("tests/fixtures/C.jpg", data_dir)
        manifest_store = json.loads(store_json)
        manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
        print (store_json)
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
        thumb_name = getitem(manifest,("thumbnail","identifier"))
        with open(data_dir + "/" + thumb_name, "rb") as thumb_file:
            thumb_data = thumb_file.read()
    assert len(thumb_data) == 31608

def test_ingredient_from_file_get_thumbnail():
    with tempfile.TemporaryDirectory() as data_dir:
        ingredient_json = c2pa.read_ingredient_file("tests/fixtures/C.jpg", data_dir)
        ingredient = json.loads(ingredient_json)
        assert ingredient["title"]== "C.jpg"
        assert ingredient,["format"] == "image/jpeg"
        # read thumbnail data from file
        assert getitem(ingredient,("thumbnail","format")) == "image/jpeg"
        thumb_name = getitem(ingredient,("thumbnail","identifier"))
        assert thumb_name.startswith("self#jumbf=")
        # we won't get a thumbnail file generated if a valid one already exists in the store
        # with open(data_dir + "/" + thumb_name, "rb") as thumb_file:
        #     thumb_data = thumb_file.read()
        # assert len(thumb_data) == 31608
        #read c2pa data from file
        assert getitem(ingredient,("manifest_data","format")) == "application/c2pa"
        data_name = getitem(ingredient,("manifest_data","identifier"))
        with open(data_dir + "/" + data_name, "rb") as c2pa_file:
            c2pa_data = c2pa_file.read()
        assert len(c2pa_data) == 51240        

def test_sign_info():
          # set up the signer info loading the pem and key files
        test_pem = open("tests/fixtures/es256_certs.pem","rb").read()
        test_key = open("tests/fixtures/es256_private.key","rb").read()
        sign_info = c2pa.SignerInfo("es256", test_pem, test_key, "http://timestamp.digicert.com")
        assert sign_info.alg == "es256"
        assert sign_info.ta_url == "http://timestamp.digicert.com"

def test_add_manifest_to_file():
    # define a source folder for any assets we need to read
    data_dir = "tests/fixtures"

    # create temp folder for writing things
    with tempfile.TemporaryDirectory() as output_dir:
        # define a manifest with the do not train assertion
        manifest_json = json.dumps(manifest_def)

        # set up the signer info loading the pem and key files
        test_pem = open("tests/fixtures/es256_certs.pem","rb").read()
        test_key = open("tests/fixtures/es256_private.key","rb").read()
        sign_info = c2pa.SignerInfo("es256", test_pem, test_key, "http://timestamp.digicert.com")

        # add the manifest to the asset
        c2pa_data = c2pa.sign_file(data_dir + "/A.jpg", output_dir+"/out.jpg", manifest_json, sign_info, data_dir)
        assert len(c2pa_data) == 75864 #check the size of returned c2pa_manifest data

        # verify the asset and check the manifest has what we expect
        store_json = c2pa.read_file(output_dir + "/out.jpg", output_dir)
        manifest_store = json.loads(store_json)
        manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
        print (store_json)
        assert "python_test" in manifest["claim_generator"]
        # check custom title and format
        assert manifest["title"]== "My Title" 
        assert manifest,["format"] == "image/jpeg"
        # There should be no validation status errors
        assert manifest.get("validation_status") == None
        # check the thumbnail data
        thumb_name = getitem(manifest,("thumbnail","identifier"))
        with open(output_dir + "/" + thumb_name, "rb") as thumb_file:
            thumb_data = thumb_file.read()
        assert len(thumb_data) == 61720


def test_v2_read():
     #example of reading a manifest store from a file
    try:
        reader = c2pa_api.Reader.from_file("tests/fixtures/C.jpg")
        jsonReport = reader.read()
        assert "C.jpg" in jsonReport
        assert "validation_status" not in jsonReport
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
            assert len(c2pa_data) == 83075
    except Exception as e:
        print("Failed to sign manifest store: " + str(e))
        exit(1)