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
import sys
import tempfile
PROJECT_PATH = os.getcwd()
SOURCE_PATH = os.path.join(
    PROJECT_PATH,"target","python"
)
sys.path.append(SOURCE_PATH)

import c2pa;


#  ManifestStoreReader = c2pa.ManifestStoreReader
class Reader(c2pa.Reader):
    def __init__(self, format, stream):
        self.format = format
        self.stream = C2paStream(stream)
        super().__init__()

    def from_file(path: str, format=None):
        file = open(path, "rb")
        if format is None:
            # determine the format from the file extension
            format = os.path.splitext(path)[1][1:]
        reader = Reader(format, file)
        return reader

    def read(self):
        return super().read(self.format, self.stream)
    
    def resource(self, uri, stream) -> None:
        super().resource(uri, C2paStream(stream))

    def resource_file(self, uri, path) -> None:
        file = open(path, "wb")
        self.resource(uri, file)


class Builder(c2pa.Builder):
    def __init__(self, signer, manifest = None):
        self.signer = signer
        super().__init__()
        if manifest is not None:
            self.set_manifest(manifest)

    def set_manifest(self, manifest):
        if not isinstance(manifest, str):
            manifest = json.dumps(manifest)
        self.with_json(manifest)
        return self
    
    def add_resource(self, uri, stream):
        return super().add_resource(uri, stream)
    
    def add_resource_file(self, uri, path):
        stream = C2paStream.open_file(path, "rb")
        return self.add_resource(uri, stream)
    
    def sign_stream(self, format, input, output=None):
        return self.sign(format, input, output, self.signer)

    def sign_file(self, sourcePath, outputPath):
        format = "image/jpeg" #sourcePath.extension[1:]
        input = C2paStream.open_file(sourcePath, "rb")
        output = C2paStream.open_file(outputPath, "wb")
        return self.sign_stream(format, input, output)


# Implements a C2paStream given a stream handle
class C2paStream(c2pa.Stream):
    def __init__(self, stream):
        self.stream = stream
    
    def read_stream(self, length: int) -> bytes:   
        #print("Reading " + str(length) + " bytes")
        return self.stream.read(length)

    def seek_stream(self, pos: int, mode: c2pa.SeekMode) -> int:
        whence = 0
        if mode is c2pa.SeekMode.CURRENT:
            whence = 1
        elif mode is c2pa.SeekMode.END:
            whence = 2
        #print("Seeking to " + str(pos) + " with whence " + str(whence))
        return self.stream.seek(pos, whence)

    def write_stream(self, data: str) -> int:
        #print("Writing " + str(len(data)) + " bytes")
        return self.stream.write(data)

    def flush_stream(self) -> None:
        self.stream.flush()

    # A shortcut method to open a C2paStream from a path/mode
    def open_file(path: str, mode: str) -> c2pa.Stream:
        return C2paStream(open(path, mode))


class SignerCallback(c2pa.SignerCallback):
    def __init__(self,callback):
        self.sign = callback
        super().__init__()

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

def sign_ps256(data: bytes, key_path: str) -> bytes:
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
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


class LocalSigner:

    def __init__(self, config, sign_callback):
        callback = SignerCallback(sign_callback)
        self.signer = c2pa.CallbackSigner(callback, config)

    def signer(self):
        return self.signer
    
    def from_settings(sign_callback, alg, certs, timestamp_url=None):
        config = c2pa.SignerConfig(alg, certs, timestamp_url)
        return LocalSigner(config, sign_callback).signer