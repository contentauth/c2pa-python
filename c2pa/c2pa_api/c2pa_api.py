# Copyright 2024 Adobe. All rights reserved.
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
import sys
import tempfile
import shutil
PROJECT_PATH = os.getcwd()
SOURCE_PATH = os.path.join(
    PROJECT_PATH,"target","python"
)
sys.path.append(SOURCE_PATH)

import c2pa.c2pa as api

#from c2pa import Error, SigningAlg, version, sdk_version

# This module provides a simple Python API for the C2PA library.

# Reader is used to read a manifest store from a stream or file.
# It performs full validation on the manifest store.
# It also supports writing resources to a stream or file.
#
# Example:
# reader = Reader("image/jpeg", open("test.jpg", "rb"))
# json = reader.json()
class Reader(api.Reader):
    def __init__(self, format, stream):
        super().__init__()
        self.from_stream(format, C2paStream(stream))

    @classmethod
    def from_file(cls, path: str, format=None):
        file = open(path, "rb")
        if format is None:
            # determine the format from the file extension
            format = os.path.splitext(path)[1][1:]
        return cls(format, file)
    
    def get_manifest(self, label):
        manifest_store = json.loads(self.json())
        return manifest_store["manifests"].get(label)
    
    def get_active_manifest(self):
        manifest_store = json.loads(self.json())
        active_label = manifest_store.get("active_manifest")
        if active_label:
            return manifest_store["manifests"].get(active_label)
        return None
    
    def resource_to_stream(self, uri, stream) -> None:
        return super().resource_to_stream(uri, C2paStream(stream))

    def resource_to_file(self, uri, path) -> None:
        file = open(path, "wb")
        return self.resource_to_stream(uri, file)

# The Builder is used to construct a new Manifest and add it to a stream or file.
# The initial manifest is defined by a Manifest Definition dictionary.
# It supports adding resources from a stream or file.
# It supports adding ingredients from a stream or file.
# It supports signing the asset with a signer to a stream or file.
#
# Example:
# manifest = {
#     "claim_generator_info": [{
#         "name": "python_test",
#         "version": "0.1"
#     }],
#     "title": "My Title",
#     "thumbnail": {
#         "format": "image/jpeg",
#         "identifier": "thumbnail"
#     }
# }
# builder = Builder(manifest)
# builder.add_resource_file("thumbnail", "thumbnail.jpg")
# builder.add_ingredient_file({"parentOf": true}, "B.jpg")
# builder.sign_file(signer, "test.jpg", "signed.jpg")
class Builder(api.Builder):
    def __init__(self, manifest):
        super().__init__()
        self.set_manifest(manifest)

    def set_manifest(self, manifest):
        if not isinstance(manifest, str):
            manifest = json.dumps(manifest)
        super().with_json(manifest)
        return self
    
    def add_resource(self, uri, stream):
        return super().add_resource(uri, C2paStream(stream))
    
    def add_resource_file(self, uri, path):
        file = open(path, "rb")
        return self.add_resource(uri, file)
    
    def add_ingredient(self, ingredient, format, stream):
        if not isinstance(ingredient, str):
            ingredient = json.dumps(ingredient)
        return super().add_ingredient(ingredient, format, C2paStream(stream))
    
    def add_ingredient_file(self, ingredient, path):
        format = os.path.splitext(path)[1][1:]
        file = open(path, "rb")
        return self.add_ingredient(ingredient, format, file)
    
    def to_archive(self, stream):
        return super().to_archive(C2paStream(stream))
    
    @classmethod
    def from_archive(cls, stream):
        self = cls({})
        super().from_archive(self, C2paStream(stream))
        return self
    
    def sign(self, signer, format, input, output = None):
        return super().sign(signer, format, C2paStream(input), C2paStream(output))

    def sign_file(self, signer, sourcePath, outputPath):
        return super().sign_file(signer, sourcePath, outputPath)
    


# Implements a C2paStream given a stream handle
# This is used to pass a file handle to the c2pa library
# It is used by the Reader and Builder classes internally  
class C2paStream(api.Stream):
    def __init__(self, stream):
        self.stream = stream
    
    def read_stream(self, length: int) -> bytes:   
        #print("Reading " + str(length) + " bytes")
        return self.stream.read(length)

    def seek_stream(self, pos: int, mode: api.SeekMode) -> int:
        whence = 0
        if mode is api.SeekMode.CURRENT:
            whence = 1
        elif mode is api.SeekMode.END:
            whence = 2
        #print("Seeking to " + str(pos) + " with whence " + str(whence))
        return self.stream.seek(pos, whence)

    def write_stream(self, data: str) -> int:
        #print("Writing " + str(len(data)) + " bytes")
        return self.stream.write(data)

    def flush_stream(self) -> None:
        self.stream.flush()

    # A shortcut method to open a C2paStream from a path/mode
    def open_file(path: str, mode: str) -> api.Stream:
        return C2paStream(open(path, mode))

# Internal class to implement signer callbacks
# We need this because the callback expects a class with a sign method
class SignerCallback(api.SignerCallback):
    def __init__(self, callback):
        self.sign = callback
        super().__init__() 


# Convenience class so we can just pass in a callback function
#class CallbackSigner(c2pa.CallbackSigner):
#    def __init__(self, callback, alg, certs, timestamp_url=None):
#        cb = SignerCallback(callback)
#        super().__init__(cb, alg, certs, timestamp_url)  

# Creates a Signer given a callback and configuration values
# It is used by the Builder class to sign the asset
#
# Example:
# def sign_ps256(data: bytes) -> bytes:
#     return c2pa_api.sign_ps256_shell(data, "tests/fixtures/ps256.pem")
#
# certs = open("tests/fixtures/ps256.pub", "rb").read()
# signer = c2pa_api.create_signer(sign_ps256, "ps256", certs, "http://timestamp.digicert.com")
#
def create_signer(callback, alg, certs, timestamp_url=None):
    return api.CallbackSigner(SignerCallback(callback), alg, certs, timestamp_url)  



# Example of using openssl in an os shell to sign data using Ps256
# Note: the openssl command line tool must be installed for this to work
def sign_ps256_shell(data: bytes, key_path: str) -> bytes:
    with tempfile.NamedTemporaryFile() as bytes:
        bytes.write(data)
        signature = tempfile.NamedTemporaryFile()
        os.system("openssl dgst -sha256 -sign {} -out {} {}".format(key_path, signature.name, bytes.name))
        return signature.read()

# Example of using python crypto to sign data using openssl with Ps256
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

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
