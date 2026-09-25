# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

"""
Plain functions (no pytest dependencies) asserting thread-safety invariants.
Each function is called once by run_thread_profile.py and loops internally.

These scenarios do not wait for a crash. A native use-after-free only faults when
the allocator happens to have reused the freed page, which makes crash detection
probabilistic (measured at p=0.00124 per round of sustained load). Instead each
scenario forces the dangerous interleaving and then asserts the guard state that
the hardening maintains, which is deterministic.

The forcing primitive is a stream or signer callback that blocks on an Event. A
callback runs on the thread that entered the native call, so blocking inside one
holds that native call open with the GIL released. A teardown issued from another
thread then lands mid-call by construction rather than by luck.

Every scenario reports the outcome of each round as a counter dict, and reports
NOT_PARKED when its callback never ran. A scenario whose injection stops working
would otherwise keep passing while testing nothing.
"""

import io
import json
import threading

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from c2pa import (
    Builder,
    C2paSigningAlg,
    Context,
    Reader,
    Signer,
)
import c2pa.c2pa as c2pa_module

from tests.perf.scenarios import (
    FIXTURES_DIR,
    MANIFEST_BASE,
    SIGNED_JPEG,
    SOURCE_JPEG,
)

# How long a scenario waits for its callback to be entered before giving up and
# reporting NOT_PARKED, and how long it then holds the native call open.
_PARK_TIMEOUT = 30.0
_RELEASE_TIMEOUT = 40.0
_JOIN_TIMEOUT = 40.0

_TSA_URL = "http://timestamp.digicert.com"

_CERTS = (FIXTURES_DIR / "es256_certs.pem").read_bytes().decode("utf-8")
_PRIVATE_KEY = (FIXTURES_DIR / "es256_private.key").read_bytes()

NOT_PARKED = "NOT_PARKED"


class ParkingStream(io.RawIOBase):
    """Stream that blocks once inside a callback, holding a native call open.

    On the first read (or write) past the start of the data it sets `inside` and
    waits on `release`. The callback runs on whichever thread entered the native
    call, so while it waits that call is open with the GIL dropped and another
    thread's teardown is guaranteed to arrive mid-call.
    """

    def __init__(self, data: bytes, inside, release, *, for_write: bool = False):
        self._buffer = io.BytesIO(b"" if for_write else data)
        self._inside = inside
        self._release = release
        self._for_write = for_write
        self._parked = False
        self._written = 0

    def readable(self) -> bool:
        return not self._for_write

    def writable(self) -> bool:
        return self._for_write

    def seekable(self) -> bool:
        return True

    def seek(self, offset, whence=0):
        if self._for_write:
            return self._written
        return self._buffer.seek(offset, whence)

    def tell(self):
        if self._for_write:
            return self._written
        return self._buffer.tell()

    def _park_once(self) -> None:
        if self._parked:
            return
        self._parked = True
        self._inside.set()
        self._release.wait(_RELEASE_TIMEOUT)

    def read(self, size=-1):
        # Park only after the first chunk, so the native side is already holding
        # the handle rather than still validating arguments.
        if self._buffer.tell() > 0:
            self._park_once()
        return self._buffer.read(size)

    def readinto(self, target):
        chunk = self.read(len(target))
        count = len(chunk)
        target[:count] = chunk
        return count

    def write(self, data):
        self._written += len(data)
        self._park_once()
        return len(data)


def parking_sign_callback(inside, release):
    """Signer callback that parks while native is calling through its trampoline.

    The trampoline is an ordinary refcounted Python object whose only reference is
    an attribute on the Context. Parking here means a Context teardown runs while
    native holds nothing but the trampoline's address.
    """

    def callback(data: bytes) -> bytes:
        inside.set()
        release.wait(_RELEASE_TIMEOUT)
        key = serialization.load_pem_private_key(_PRIVATE_KEY, password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key.sign(data, ec.ECDSA(hashes.SHA256()))

    return callback


def _callback_signer(inside, release) -> Signer:
    """A Signer whose callback parks. Signer.from_info has no Python trampoline,
    so only from_callback exercises the trampoline lifetime."""
    return Signer.from_callback(
        callback=parking_sign_callback(inside, release),
        alg=C2paSigningAlg.ES256,
        certs=_CERTS,
        tsa_url=_TSA_URL,
    )


def _first_resource_uri(reader: Reader):
    """A resource identifier from the reader's manifest, or None.

    resource_to_stream needs one, and it is the shared borrow that
    no_free_during_parked_call parks inside.
    """
    manifest = json.loads(reader.json())
    for entry in manifest.get("manifests", {}).values():
        thumbnail = entry.get("thumbnail") or {}
        identifier = thumbnail.get("identifier")
        if identifier:
            return identifier
    return None


def _close_quietly(resource) -> None:
    try:
        resource.close()
    except Exception:
        pass


class _ParkedResourceCall:
    """Runs resource_to_stream on a worker thread and parks inside its callback.

    Used as a context manager: the body runs while the native call is open. On
    entry `parked` says whether the callback was reached; when it is False the
    body must not assert anything.
    """

    def __init__(self, reader: Reader, uri: str):
        self._reader = reader
        self._uri = uri
        self._inside = threading.Event()
        self._release = threading.Event()
        self._thread = None
        self.parked = False

    def __enter__(self):
        stream = ParkingStream(b"", self._inside, self._release, for_write=True)

        def worker():
            try:
                self._reader.resource_to_stream(self._uri, stream)
            except Exception:
                # This call can fail once the resource is torn down. Scenarios
                # assert on the guard state the with-block observes, not on
                # this exception.
                pass

        self._thread = threading.Thread(target=worker, name="parked-resource-call")
        self._thread.start()
        self.parked = self._inside.wait(_PARK_TIMEOUT)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._release.set()
        if self._thread is not None:
            self._thread.join(_JOIN_TIMEOUT)
        return False

    @property
    def hung(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def _tally(rounds: int, one_round):
    """Run one_round() `rounds` times and count the outcomes."""
    counts: dict = {}
    for _ in range(rounds):
        try:
            outcome = one_round()
        except Exception as err:
            # A scenario raising here is a bug in the scenario, not the
            # invariant it is checking.
            outcome = f"ERROR:{type(err).__name__}"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def scenario_trampoline_held_during_sign(rounds: int = 20) -> dict:
    """The signer trampoline must outlive a Context closed mid-sign.

    Context._release() drops its reference to the trampoline. If that happens
    while native is calling through it, native is left calling freed memory, and
    a sign that never invoked the signer can still report success.

    HELD: the in-flight guard kept the trampoline alive.
    DROPPED: the only reference was dropped mid-call.
    """
    source = SOURCE_JPEG.read_bytes()
    manifest = {**MANIFEST_BASE, "format": "image/jpeg"}

    def one_round():
        inside = threading.Event()
        release = threading.Event()
        signer = _callback_signer(inside, release)
        context = Context(signer=signer)
        result: dict = {}

        def worker():
            try:
                result["manifest"] = Builder(manifest, context=context).sign(
                    "image/jpeg", io.BytesIO(source))
            except Exception as err:
                result["error"] = type(err).__name__

        thread = threading.Thread(target=worker, name="parked-sign")
        thread.start()
        if not inside.wait(_PARK_TIMEOUT):
            release.set()
            thread.join(_JOIN_TIMEOUT)
            _close_quietly(context)
            return NOT_PARKED

        # Native is inside the trampoline right now.
        _close_quietly(context)
        held = getattr(context, "_signer_callback_cb", None) is not None

        release.set()
        thread.join(_JOIN_TIMEOUT)
        if thread.is_alive():
            return "HUNG"
        return "HELD" if held else "DROPPED"

    return _tally(rounds, one_round)


def scenario_no_free_during_parked_call(rounds: int = 20) -> dict:
    """A handle must not be freed while a native call still holds it.

    c2pa_free is reached through the single funnel ManagedResource._free_native_ptr.
    A round only counts once its callback has parked, which confirms the call is
    still open, so counting frees from that point measures the use-after-free
    directly rather than waiting for it to fault.

    freed=0: the teardown was deferred until the call returned.
    freed=1: the in-use handle was freed mid-call.
    """
    signed = SIGNED_JPEG.read_bytes()

    def one_round():
        reader = Reader("image/jpeg", io.BytesIO(signed))
        reader.json()
        uri = _first_resource_uri(reader)
        if uri is None:
            _close_quietly(reader)
            return "NO_RESOURCE_URI"

        freed_while_open = []
        watching = {"active": False}
        original = c2pa_module.ManagedResource.__dict__["_free_native_ptr"]
        underlying = getattr(original, "__func__", original)

        def traced(ptr):
            if watching["active"]:
                freed_while_open.append(ptr)
            return underlying(ptr)

        c2pa_module.ManagedResource._free_native_ptr = staticmethod(traced)
        try:
            with _ParkedResourceCall(reader, uri) as parked:
                if not parked.parked:
                    return NOT_PARKED
                watching["active"] = True
                _close_quietly(reader)
                watching["active"] = False
                count = len(freed_while_open)
            return f"freed={count}"
        finally:
            # Restore even on failure: leaving the trace installed would corrupt
            # every later scenario in this process.
            c2pa_module.ManagedResource._free_native_ptr = staticmethod(underlying)

    return _tally(rounds, one_round)


def scenario_builder_no_free_during_parked_sign(rounds: int = 20) -> dict:
    """The Builder handle must not be freed while c2pa_builder_sign_context
    still holds it, parked inside the Context signer's callback.

    freed=0: the teardown was deferred until sign returned.
    freed=1: the in-use handle was freed mid-call.
    """
    source = SOURCE_JPEG.read_bytes()
    manifest = {**MANIFEST_BASE, "format": "image/jpeg"}

    def one_round():
        inside = threading.Event()
        release = threading.Event()
        signer = _callback_signer(inside, release)
        context = Context(signer=signer)
        builder = Builder(manifest, context=context)

        freed_while_open = []
        watching = {"active": False}
        original = c2pa_module.ManagedResource.__dict__["_free_native_ptr"]
        underlying = getattr(original, "__func__", original)

        def traced(ptr):
            if watching["active"]:
                freed_while_open.append(ptr)
            return underlying(ptr)

        c2pa_module.ManagedResource._free_native_ptr = staticmethod(traced)
        result: dict = {}

        def worker():
            try:
                result["manifest"] = builder.sign(
                    "image/jpeg", io.BytesIO(source))
            except Exception as err:
                result["error"] = type(err).__name__

        thread = threading.Thread(target=worker, name="parked-builder-sign")
        thread.start()
        try:
            if not inside.wait(_PARK_TIMEOUT):
                release.set()
                thread.join(_JOIN_TIMEOUT)
                return NOT_PARKED

            watching["active"] = True
            _close_quietly(builder)
            watching["active"] = False
            count = len(freed_while_open)

            release.set()
            thread.join(_JOIN_TIMEOUT)
            if thread.is_alive():
                return "HUNG"
            return f"freed={count}"
        finally:
            c2pa_module.ManagedResource._free_native_ptr = staticmethod(
                underlying)
            _close_quietly(context)

    return _tally(rounds, one_round)


# Scenario name -> (function, expected outcome on hardened code).
# The expected value is what the driver asserts; anything else fails the run.
THREAD_SCENARIOS = {
    "trampoline_held_during_sign": (
        scenario_trampoline_held_during_sign, "HELD"),
    "no_free_during_parked_call": (
        scenario_no_free_during_parked_call, "freed=0"),
    "builder_no_free_during_parked_sign": (
        scenario_builder_no_free_during_parked_sign, "freed=0"),
}

# Derived so the name list cannot drift from the registry.
THREAD_SCENARIO_NAMES = tuple(THREAD_SCENARIOS)
