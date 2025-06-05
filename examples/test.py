import os
import c2pa

fixtures_dir = os.path.join(os.path.dirname(__file__), "../tests/fixtures/")
output_dir = os.path.join(os.path.dirname(__file__), "../output/")

# ensure the output directory exists
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

print("c2pa version:")
version = c2pa.version()
print(version)

reader = c2pa.Reader(fixtures_dir + "C.jpg")
print(reader.json())

certs = open(fixtures_dir + "es256_certs.pem", "rb").read()
key = open(fixtures_dir + "es256_private.key", "rb").read()

signer_info = c2pa.C2paSignerInfo(
    alg="es256".encode('utf-8'),
    sign_cert=certs,
    private_key=key,
    ta_url=None
)

signer = c2pa.Signer.from_info(signer_info)

builder = c2pa.Builder.from_json('{ }')

source = open(fixtures_dir + "C.jpg", "rb");
dest = open(output_dir + "C_signed.jpg", "wb");
result =builder.sign(signer, "image/jpeg", source, dest)

reader = c2pa.Reader(output_dir + "C_signed.jpg")
print(reader.json())

