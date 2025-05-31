from c2pa import  Builder, Error,  Reader, SigningAlg, create_signer,  sdk_version, sign_ps256
import os
import io
PROJECT_PATH = os.getcwd()

testPath = os.path.join(PROJECT_PATH, "tests", "fixtures", "C.jpg")

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
private_key = open("tests/fixtures/ps256.pem","rb").read()

# Define a function that signs data with PS256 using a private key
def sign(data: bytes) -> bytes:
    print("date len = ", len(data))
    return sign_ps256(data, private_key)

# load the public keys from a pem file
certs = open("tests/fixtures/ps256.pub","rb").read()

# Create a local Ps256 signer with certs and a timestamp server
signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

builder = Builder(manifestDefinition)

source = open(testPath, "rb").read()

testPath = "/Users/gpeacock/Pictures/Lightroom Saved Photos/IMG_0483.jpg"
testPath = "tests/fixtures/c.jpg"
outputPath = "target/python_out.jpg"

def test_files_build():
        # Delete the output file if it exists
    if os.path.exists(outputPath):
        os.remove(outputPath)
    builder.sign_file(signer, testPath, outputPath)

def test_streams_build():
    #with open(testPath, "rb") as file:
    output = io.BytesIO(bytearray())
    builder.sign(signer, "image/jpeg", io.BytesIO(source), output)

def test_func(benchmark):
    benchmark(test_files_build)

def test_streams(benchmark):
    benchmark(test_streams_build)

#def test_signer(benchmark):
#    benchmark(sign_ps256, data, private_key)