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

import os
import io
import json
import shutil
from c2pa import Reader, Builder, Signer, C2paSigningAlg, C2paSignerInfo

PROJECT_PATH = os.getcwd()

# Test paths
test_path = os.path.join(PROJECT_PATH, "tests", "fixtures", "C.jpg")
temp_dir = os.path.join(PROJECT_PATH, "tests", "temp")
output_path = os.path.join(temp_dir, "python_out.jpg")

# Ensure temp directory exists
os.makedirs(temp_dir, exist_ok=True)

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

# Load private key and certificates
private_key = open("tests/fixtures/ps256.pem", "rb").read()
certs = open("tests/fixtures/ps256.pub", "rb").read()

# Create a local Ps256 signer with certs and a timestamp server
signer_info = C2paSignerInfo(
    alg=b"ps256",
    sign_cert=certs,
    private_key=private_key,
    ta_url=b"http://timestamp.digicert.com"
)
signer = Signer.from_info(signer_info)
builder = Builder(manifestDefinition)

# Load source image
source = open(test_path, "rb").read()

# Run the benchmark: python -m pytest tests/benchmark.py -v


def test_files_read():
    """Benchmark reading a C2PA asset from a file."""
    with open(test_path, "rb") as f:
        reader = Reader("image/jpeg", f)
        result = reader.json()
        reader.close()
        assert result is not None
        # Parse the JSON string into a dictionary
        result_dict = json.loads(result)
        # Additional assertions to verify the structure of the result
        assert "active_manifest" in result_dict
        assert "manifests" in result_dict
        assert "validation_state" in result_dict
        assert result_dict["validation_state"] == "Valid"


def test_streams_read():
    """Benchmark reading a C2PA asset from a stream."""
    with open(test_path, "rb") as file:
        source = file.read()
    reader = Reader("image/jpeg", io.BytesIO(source))
    result = reader.json()
    reader.close()
    assert result is not None
    # Parse the JSON string into a dictionary
    result_dict = json.loads(result)
    # Additional assertions to verify the structure of the result
    assert "active_manifest" in result_dict
    assert "manifests" in result_dict
    assert "validation_state" in result_dict
    assert result_dict["validation_state"] == "Valid"


def test_files_build():
    """Benchmark building a C2PA asset from a file."""
    # Delete the output file if it exists
    if os.path.exists(output_path):
        os.remove(output_path)
    with open(test_path, "rb") as source_file:
        with open(output_path, "w+b") as dest_file:
            builder.sign(signer, "image/jpeg", source_file, dest_file)


def test_streams_build():
    """Benchmark building a C2PA asset from a stream."""
    output = io.BytesIO(bytearray())
    with open(test_path, "rb") as source_file:
        builder.sign(signer, "image/jpeg", source_file, output)


def test_files_reading(benchmark):
    """Benchmark file-based reading."""
    benchmark(test_files_read)


def test_streams_reading(benchmark):
    """Benchmark stream-based reading."""
    benchmark(test_streams_read)


def test_files_builder_signer_benchmark(benchmark):
    """Benchmark file-based building."""
    benchmark(test_files_build)


def test_streams_builder_benchmark(benchmark):
    """Benchmark stream-based building."""
    benchmark(test_streams_build)


def teardown_module(module):
    """Clean up temporary files after all tests."""
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
