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


def read_c2pa_data(media_path: str):
    print(f"Reading {media_path}")
    try:
        with c2pa.Reader(media_path) as reader:
            print(reader.detailed_json())
    except Exception as e:
        print(f"Error reading C2PA data from {media_path}: {e}")
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        media_path = "tests/fixtures/cloud.jpg"
    else:
        media_path = sys.argv[1]

    load_trust_anchors()
    read_c2pa_data(media_path)
