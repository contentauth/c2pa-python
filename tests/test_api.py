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

import json
import os
import pytest
import tempfile
import shutil

from c2pa import Builder, Error, Reader, SigningAlg, create_signer, sdk_version, sign_ps256, version

# a little helper function to get a value from a nested dictionary
from functools import reduce
import operator

def getitem(d, key):
    return reduce(operator.getitem, key, d)

# define the manifest we will use for testing
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

def test_v2_read_cloud_manifest():
    reader = Reader.from_file("tests/fixtures/cloud.jpg")
    manifest = reader.get_active_manifest()
    assert manifest is not None

def test_version():
    assert version() == "0.5.2"

def test_sdk_version():
    assert "c2pa-rs/" in sdk_version()

def test_v2_read():
     #example of reading a manifest store from a file
    try:
        reader = Reader.from_file("tests/fixtures/C.jpg")
        manifest = reader.get_active_manifest()
        assert manifest is not None
        assert "make_test_images" in manifest["claim_generator"]
        assert manifest["title"]== "C.jpg"
        assert manifest["format"] == "image/jpeg"
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
        reader.resource_to_file(uri, "target/thumbnail_read_v2.jpg")

    except Exception as e:
        print("Failed to read manifest store: " + str(e))
        exit(1)

def test_reader_from_file_no_store():
    with pytest.raises(Error.ManifestNotFound) as err:  
        reader = Reader.from_file("tests/fixtures/A.jpg")

def test_v2_sign():
    # define a source folder for any assets we need to read
    data_dir = "tests/fixtures/"
    try:
        key = open(data_dir + "ps256.pem", "rb").read()
        def sign(data: bytes) -> bytes:
            return sign_ps256(data, key)
        
        certs = open(data_dir + "ps256.pub", "rb").read()
        # Create a local signer from a certificate pem file
        signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

        builder = Builder(manifest_def)

        builder.add_resource_file("A.jpg", data_dir + "A.jpg")

        builder.to_archive(open("target/archive.zip", "wb"))

        builder = Builder.from_archive(open("target/archive.zip", "rb"))

        with tempfile.TemporaryDirectory() as output_dir:
            output_path = output_dir + "out.jpg"
            if os.path.exists(output_path):
                os.remove(output_path)
            c2pa_data = builder.sign_file(signer, data_dir + "A.jpg", output_dir + "out.jpg")
            assert len(c2pa_data) > 0

        reader = Reader.from_file(output_dir + "out.jpg")
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

# Test signing the same source and destination file
def test_v2_sign_file_same():
    data_dir = "tests/fixtures/"
    try:
        key = open(data_dir + "ps256.pem", "rb").read()
        def sign(data: bytes) -> bytes:
            return sign_ps256(data, key)
        
        certs = open(data_dir + "ps256.pub", "rb").read()
        # Create a local signer from a certificate pem file
        signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

        builder = Builder(manifest_def)

        builder.add_resource_file("A.jpg", data_dir + "A.jpg")

        with tempfile.TemporaryDirectory() as output_dir:
            path = output_dir + "/A.jpg"
            # Copy the file from data_dir to output_dir
            shutil.copy(data_dir + "A.jpg", path)
            c2pa_data = builder.sign_file(signer, path, path)
            assert len(c2pa_data) > 0

            reader = Reader.from_file(path)
            manifest = reader.get_active_manifest()

            # check custom title and format
            assert manifest["title"]== "My Title" 
            assert manifest["format"] == "image/jpeg"
            # There should be no validation status errors
            assert manifest.get("validation_status") == None
    except Exception as e:
        print("Failed to sign manifest store: " + str(e))
        #exit(1)