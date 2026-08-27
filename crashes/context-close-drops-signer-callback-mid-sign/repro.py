"""SIGSEGV reproduction: Context.close() racing a context-sign that uses a
callback signer. Run from the repository root:

    python3 crashes/context-close-drops-signer-callback-mid-sign/repro.py

Expected: the process dies with SIGSEGV (exit 139) within a few trials.
The crash needs the `cryptography` package for the ES256 callback.
"""
import sys, io, os, threading, time, faulthandler

sys.path.insert(0, "src")
faulthandler.enable()

from c2pa import Builder, Signer, Context, C2paSigningAlg as Alg
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

FIXTURES = "tests/fixtures"
certs = open(os.path.join(FIXTURES, "es256_certs.pem"), "rb").read().decode()
key_bytes = open(os.path.join(FIXTURES, "es256_private.key"), "rb").read()
image = open(os.path.join(FIXTURES, "C.jpg"), "rb").read()
MANIFEST = {"claim_generator_info": [{"name": "repro", "version": "0.1"}],
            "assertions": []}

private_key = serialization.load_pem_private_key(key_bytes, password=None)


def sign_callback(data: bytes) -> bytes:
    return private_key.sign(data, ec.ECDSA(hashes.SHA256()))


def make_context() -> Context:
    signer = Signer.from_callback(sign_callback, Alg.ES256, certs,
                                  "http://timestamp.digicert.com")
    return Context(signer=signer)   # consumes the signer


for trial in range(80):
    ctx = make_context()
    entered = threading.Event()

    def worker():
        try:
            builder = Builder(dict(MANIFEST), context=ctx)
            entered.set()
            builder.sign("image/jpeg", io.BytesIO(image), io.BytesIO())
            builder.close()
        except Exception:
            entered.set()

    t = threading.Thread(target=worker)
    t.start()
    entered.wait(5)
    time.sleep(0.002)      # let the sign enter the native call
    ctx.close()            # drops _signer_callback_cb mid-invocation
    t.join(20)
    if trial % 20 == 0:
        print("trial", trial, "still alive")

print("survived 80 trials (crash did not reproduce this run)")
