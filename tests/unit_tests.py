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
# each license.import unittest

import os
import io
import json
import unittest
from unittest.mock import mock_open, patch

from c2pa import  Builder, Error,  Reader, SigningAlg, create_signer,  sdk_version, sign_ps256

PROJECT_PATH = os.getcwd()

testPath = os.path.join(PROJECT_PATH, "tests", "fixtures", "C.jpg")

class TestC2paSdk(unittest.TestCase):

    def test_version(self):
        self.assertIn("0.5.2", sdk_version())


class TestReader(unittest.TestCase):

    def test_stream_read(self):
        with open(testPath, "rb") as file:
            reader = Reader("image/jpeg",file)
            json = reader.json()
            self.assertIn("C.jpg", json)

    def test_stream_read_and_parse(self):
        with open(testPath, "rb") as file:
            reader = Reader("image/jpeg",file)
            manifest_store = json.loads(reader.json())
            title = manifest = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
            self.assertEqual(title, "C.jpg")

    def test_json_decode_err(self):
        with self.assertRaises(Error.Io):
            manifest_store = Reader("image/jpeg","foo")

    def test_reader_bad_format(self):
        with self.assertRaises(Error.NotSupported):
            with open(testPath, "rb") as file:
                reader = Reader("badFormat",file)


class TestBuilder(unittest.TestCase):
    # Define a manifest as a dictionary
    manifestDefinition = {
        "claim_generator": "python_test",
        "claim_generator_info": [{
            "name": "python_test",
            "version": "0.0.1",
        }],
        "format": "image/jpeg",
        "title": "Python Test Image",
        "ingredients": [],
        "assertions": [
            {   'label': 'stds.schema-org.CreativeWork',
                'data': {
                    '@context': 'http://schema.org/',
                    '@type': 'CreativeWork',
                    'author': [
                        {   '@type': 'Person',
                            'name': 'Gavin Peacock'
                        }
                    ]
                },
                'kind': 'Json'
            }
        ]
    }

    # Define a function that signs data with PS256 using a private key
    def sign(data: bytes) -> bytes:
        key = open("tests/fixtures/ps256.pem","rb").read()
        return sign_ps256(data, key)

    # load the public keys from a pem file
    certs = open("tests/fixtures/ps256.pub","rb").read()

    # Create a local Ps256 signer with certs and a timestamp server
    signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

    def test_streams_build(self):
        with open(testPath, "rb") as file:
            builder = Builder(TestBuilder.manifestDefinition)
            output = io.BytesIO(bytearray())
            builder.sign(TestBuilder.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            self.assertIn("Python Test", reader.json())

    def test_streams_build(self):
        with open(testPath, "rb") as file:
            builder = Builder(TestBuilder.manifestDefinition)
            archive = byte_array = io.BytesIO(bytearray())
            builder.to_archive(archive)
            builder = Builder.from_archive(archive)
            output = byte_array = io.BytesIO(bytearray())
            builder.sign(TestBuilder.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            self.assertIn("Python Test", reader.json())

if __name__ == '__main__':
    unittest.main()