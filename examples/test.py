import os
import c2pa
import io

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# ensure the output directory exists
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

print("c2pa version:")
version = c2pa.sdk_version()
print(version)

# Read existing C2PA metadata from the file
print("\nReading existing C2PA metadata:")
with open(fixtures_dir + "C.jpg", "rb") as file:
    reader = c2pa.Reader("image/jpeg", file)
    print(reader.json())

# Create a signer from certificate and key files
certs = open(fixtures_dir + "es256_certs.pem", "rb").read()
key = open(fixtures_dir + "es256_private.key", "rb").read()

signer_info = c2pa.C2paSignerInfo(
    alg=b"es256",  # Use bytes instead of encoded string
    sign_cert=certs,
    private_key=key,
    ta_url=b"http://timestamp.digicert.com"  # Use bytes and add timestamp URL
)

signer = c2pa.Signer.from_info(signer_info)

# Create a manifest definition as a dictionary
manifest_definition = {
    "claim_generator": "python_example",
    "claim_generator_info": [{
        "name": "python_example",
        "version": "0.0.1",
    }],
    "format": "image/jpeg",
    "title": "Python Example Image",
    "ingredients": [],
    "assertions": [
        {
            'label': 'stds.schema-org.CreativeWork',
            'data': {
                '@context': 'http://schema.org/',
                '@type': 'CreativeWork',
                'author': [
                    {'@type': 'Person', 'name': 'Example User'}
                ]
            },
            'kind': 'Json'
        }
    ]
}

builder = c2pa.Builder(manifest_definition)

# Sign the image
print("\nSigning the image...")
with open(fixtures_dir + "C.jpg", "rb") as source:
    with open(output_dir + "C_signed.jpg", "wb") as dest:
        result = builder.sign(signer, "image/jpeg", source, dest)

# Read the signed image to verify
print("\nReading signed image metadata:")
with open(output_dir + "C_signed.jpg", "rb") as file:
    reader = c2pa.Reader("image/jpeg", file)
    print(reader.json())

print("\nExample completed successfully!")

