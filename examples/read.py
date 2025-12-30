import sys
import c2pa
import urllib.request


# This example shows how to read a C2PA manifest embedded in a media file, and validate
# that it is trusted according to the official trust anchor certificate list.
# The output is printed as prettified JSON.

TRUST_ANCHORS_URL = "https://contentcredentials.org/trust/anchors.pem"


def load_trust_anchors():
    try:
        with urllib.request.urlopen(TRUST_ANCHORS_URL) as response:
            anchors = response.read().decode('utf-8')
        settings = {
            "verify": {
                "verify_cert_anchors": True
            },
            "trust": {
                "trust_anchors": anchors
            }
        }
        c2pa.load_settings(settings)
    except Exception as e:
        print(f"Warning: Could not load trust anchors from {TRUST_ANCHORS_URL}: {e}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <image_path>")
        sys.exit(1)

    load_trust_anchors()

    image_path = sys.argv[1]
    try:
        with c2pa.Reader(image_path) as reader:
            print(reader.detailed_json())
    except Exception as e:
        print(f"Error reading C2PA data from {image_path}: {e}")
        sys.exit(1)
