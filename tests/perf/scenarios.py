# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

"""
Plain functions (no pytest dependencies) that exercise the profiling scenarios.
Each function is called N times by run_profile.py.
"""

import gc
import io
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from c2pa import Builder, C2paSignerInfo, Context, Reader, Signer, Stream

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
READING_FIXTURES_DIR = FIXTURES_DIR / "files-for-reading-tests"
SIGNING_FIXTURES_DIR = FIXTURES_DIR / "files-for-signing-tests"

SIGNED_JPEG = FIXTURES_DIR / "C.jpg"
CLOUD_JPEG = FIXTURES_DIR / "cloud.jpg"
SOURCE_JPEG = FIXTURES_DIR / "A.jpg"
SIGNING_PNG = SIGNING_FIXTURES_DIR / "sample1.png"

_DST_COMPOSITE = "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"

_PARENT_ID    = "xmp:iid:aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"
_PLACED_ID    = "xmp:iid:bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"
_PARENT_ID2   = "xmp:iid:cccccccc-0003-0003-0003-cccccccccccc"
_PLACED_ID2   = "xmp:iid:dddddddd-0004-0004-0004-dddddddddddd"
_PARENT_ID3   = "xmp:iid:eeeeeeee-0005-0005-0005-eeeeeeeeeeee"
_PLACED_ID3   = "xmp:iid:ffffffff-0006-0006-0006-ffffffffffff"
_PLACED_ID4   = "xmp:iid:11111111-0007-0007-0007-111111111111"
_PLACED_ID5   = "xmp:iid:22222222-0008-0008-0008-222222222222"

MANIFEST_BASE = {
    "claim_generator": "perf_test",
    "claim_generator_info": [{"name": "perf_test", "version": "0.0.1"}],
    "format": "image/jpeg",
    "title": "Perf Test Image",
    "ingredients": [],
    "assertions": [
        {
            "label": "c2pa.actions",
            "data": {
                "actions": [
                    {
                        "action": "c2pa.created",
                        "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                    }
                ]
            },
        }
    ],
}


# Scenario name for progress output, set per-run by run_profile.py via the env.
_SCENARIO = os.environ.get("PERF_SCENARIO", "")


def _iterate(n: int):
    """Yield range(n), printing a progress line to stderr ~every 10%.

    The memray run phase is otherwise silent for the whole scenario, which at
    high iteration counts looks hung. The print is gated to ~10 lines total so
    it stays readable at N=100 and N=100000 alike, and writes to stderr so it
    never lands in the captured/parsed metrics output.
    """
    step = max(1, n // 10)
    label = f"{_SCENARIO}: " if _SCENARIO else ""
    for i in range(n):
        if i % step == 0:
            print(f"  {label}iter {i}/{n} ({i * 100 // n if n else 100}%)",
                  file=sys.stderr, flush=True)
        yield i
    print(f"  {label}iter {n}/{n} (100%)", file=sys.stderr, flush=True)


def _make_signer() -> Signer:
    certs = (FIXTURES_DIR / "es256_certs.pem").read_bytes()
    key = (FIXTURES_DIR / "es256_private.key").read_bytes()
    info = C2paSignerInfo(
        alg=b"es256",
        sign_cert=certs,
        private_key=key,
        ta_url=b"http://timestamp.digicert.com",
    )
    return Signer.from_info(info)


def _sign_file(path: Path, mime: str, iterations: int) -> None:
    signer = _make_signer()
    source_bytes = path.read_bytes()
    manifest = {**MANIFEST_BASE, "format": mime}
    for _ in _iterate(iterations):
        source = io.BytesIO(source_bytes)
        output = io.BytesIO()
        builder = Builder(manifest)
        builder.sign(signer, mime, source, output)


def _read_file(path: Path, mime: str, iterations: int) -> None:
    for _ in _iterate(iterations):
        with open(path, "rb") as f:
            reader = Reader(mime, f)
            reader.json()
            reader.close()


# Context-API helpers: the Context is built once before the loop and reused on
# every iteration, so its settings are parsed a single time. Most scenarios use
# these. The `_legacy` jpeg/png scenarios build the Reader/Builder without a
# Context, which re-reads thread-local settings on each construction; running a
# legacy scenario against its `_with_context` pair isolates the settings cost.

def _sign_file_context(path: Path, mime: str, iterations: int) -> None:
    signer = _make_signer()
    context = Context(signer=signer)  # signer is consumed into the context
    source_bytes = path.read_bytes()
    manifest = {**MANIFEST_BASE, "format": mime}
    for _ in _iterate(iterations):
        source = io.BytesIO(source_bytes)
        output = io.BytesIO()
        builder = Builder(manifest, context=context)
        # str first arg selects the context signer (c2pa_builder_sign_context).
        builder.sign(mime, source, output)


def _read_file_context(path: Path, mime: str, iterations: int) -> None:
    context = Context()
    for _ in _iterate(iterations):
        with open(path, "rb") as f:
            reader = Reader(mime, f, manifest_data=None, context=context)
            reader.json()
            reader.close()


# Parallel signing: one Context built once and shared across threads. Each
# thread uses its own BytesIO source/dest and its own Builder per sign; the
# Context (and its signer) is only read. This exercises Context thread-safety
# under concurrent signing.

_PARALLEL_THREADS = 10


def _sign_parallel(path: Path, mime: str, iterations: int, *,
                   per_thread_full: bool, launch: str) -> None:
    """Sign from `_PARALLEL_THREADS` threads sharing one Context.

    per_thread_full=False: the iteration budget is split across threads (each
        does iterations // _PARALLEL_THREADS), so total work matches the
        single-threaded scenarios.
    per_thread_full=True: each thread runs the full `iterations` loop, so total
        work is _PARALLEL_THREADS x iterations (aggregate concurrent load).
    launch="pool": ThreadPoolExecutor(max_workers=_PARALLEL_THREADS).
    launch="barrier": threads released together by a Barrier so all signs run
        simultaneously (peak Context contention).
    """
    signer = _make_signer()
    context = Context(signer=signer)  # built once, shared, kept open
    source_bytes = path.read_bytes()
    manifest = {**MANIFEST_BASE, "format": mime}

    per_thread = (
        iterations if per_thread_full
        else max(1, iterations // _PARALLEL_THREADS)
    )

    def work(barrier=None):
        if barrier is not None:
            barrier.wait()  # release all threads at once
        for _ in range(per_thread):
            source = io.BytesIO(source_bytes)  # per-thread, never shared
            output = io.BytesIO()
            builder = Builder(manifest, context=context)
            # str first arg selects the context signer.
            builder.sign(mime, source, output)

    if launch == "pool":
        with ThreadPoolExecutor(max_workers=_PARALLEL_THREADS) as ex:
            futures = [ex.submit(work) for _ in range(_PARALLEL_THREADS)]
            for f in futures:
                f.result()  # surface exceptions from worker threads
    else:  # barrier
        barrier = threading.Barrier(_PARALLEL_THREADS)
        threads = [
            threading.Thread(target=work, args=(barrier,))
            for _ in range(_PARALLEL_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


# Reader scenarios: read manifests from files with manifests

def scenario_reader_jpeg_legacy(iterations: int = 100) -> None:
    _read_file(SIGNED_JPEG, "image/jpeg", iterations)


def scenario_reader_mp4(iterations: int = 100) -> None:
    _read_file_context(READING_FIXTURES_DIR / "video1.mp4", "video/mp4", iterations)


def scenario_reader_wav(iterations: int = 100) -> None:
    _read_file_context(READING_FIXTURES_DIR / "sample1_signed.wav", "audio/wav", iterations)


# Builder.sign (without ingredients))

def scenario_builder_sign_jpeg_legacy(iterations: int = 100) -> None:
    _sign_file(SOURCE_JPEG, "image/jpeg", iterations)


def scenario_builder_sign_gif(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "sample1.gif", "image/gif", iterations)


def scenario_builder_sign_heic(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "sample1.heic", "image/heic", iterations)


def scenario_builder_sign_m4a(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "sample1.m4a", "audio/mp4", iterations)


def scenario_builder_sign_png_legacy(iterations: int = 100) -> None:
    _sign_file(SIGNING_FIXTURES_DIR / "sample1.png", "image/png", iterations)


def scenario_builder_sign_webp(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "sample1.webp", "image/webp", iterations)


def scenario_builder_sign_avi(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "test.avi", "video/x-msvideo", iterations)


def scenario_builder_sign_mp4(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "video1.mp4", "video/mp4", iterations)


def scenario_builder_sign_tiff(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_FIXTURES_DIR / "TUSCANY.TIF", "image/tiff", iterations)


# Builder.sign scenarios with ingredient linking

def scenario_builder_sign_jpeg_parent_of(iterations: int = 100) -> None:
    """One parentOf ingredient linked to c2pa.opened action."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    ingredient_bytes = SIGNED_JPEG.read_bytes()
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [{
                "action": "c2pa.opened",
                "softwareAgent": {"name": "perf_test"},
                "parameters": {"ingredientIds": [_PARENT_ID]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _PARENT_ID},
                "image/jpeg", ing,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_component_of(iterations: int = 100) -> None:
    """One componentOf ingredient linked to c2pa.placed action."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    ingredient_bytes = SIGNED_JPEG.read_bytes()
    manifest = {
        **MANIFEST_BASE,
        "ingredients": [{"format": "image/jpeg", "relationship": "componentOf", "instance_id": _PLACED_ID}],
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [{
                "action": "c2pa.placed",
                "softwareAgent": {"name": "perf_test"},
                "parameters": {"ingredientIds": [_PLACED_ID]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID},
                "image/jpeg", ing,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_parent_and_component(iterations: int = 100) -> None:
    """parentOf + componentOf ingredients (both JPEG) linked to opened + placed actions."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    parent_bytes = SIGNED_JPEG.read_bytes()
    placed_bytes = CLOUD_JPEG.read_bytes()
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [
                {
                    "action": "c2pa.opened",
                    "softwareAgent": {"name": "perf_test"},
                    "parameters": {"ingredientIds": [_PARENT_ID2]},
                    "digitalSourceType": _DST_COMPOSITE,
                },
                {
                    "action": "c2pa.placed",
                    "softwareAgent": {"name": "perf_test"},
                    "parameters": {"ingredientIds": [_PLACED_ID2]},
                    "digitalSourceType": _DST_COMPOSITE,
                },
            ]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        with io.BytesIO(parent_bytes) as ing1, io.BytesIO(placed_bytes) as ing2:
            builder.add_ingredient(
                {"relationship": "parentOf",   "instance_id": _PARENT_ID2}, "image/jpeg", ing1,
            )
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID2}, "image/jpeg", ing2,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_parent_and_component_mixed_mime(iterations: int = 100) -> None:
    """parentOf JPEG + componentOf PNG linked to opened + placed actions."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    parent_bytes = SIGNED_JPEG.read_bytes()
    placed_bytes = SIGNING_PNG.read_bytes()
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [
                {
                    "action": "c2pa.opened",
                    "softwareAgent": {"name": "perf_test"},
                    "parameters": {"ingredientIds": [_PARENT_ID3]},
                    "digitalSourceType": _DST_COMPOSITE,
                },
                {
                    "action": "c2pa.placed",
                    "softwareAgent": {"name": "perf_test"},
                    "parameters": {"ingredientIds": [_PLACED_ID3]},
                    "digitalSourceType": _DST_COMPOSITE,
                },
            ]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        with io.BytesIO(parent_bytes) as ing1, io.BytesIO(placed_bytes) as ing2:
            builder.add_ingredient(
                {"relationship": "parentOf",   "instance_id": _PARENT_ID3}, "image/jpeg", ing1,
            )
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID3}, "image/png",  ing2,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_two_components_same_mime(iterations: int = 100) -> None:
    """Two componentOf JPEG ingredients in a single c2pa.placed action."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    comp1_bytes = SIGNED_JPEG.read_bytes()
    comp2_bytes = CLOUD_JPEG.read_bytes()
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [{
                "action": "c2pa.placed",
                "softwareAgent": {"name": "perf_test"},
                "parameters": {"ingredientIds": [_PLACED_ID4, _PLACED_ID5]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        with io.BytesIO(comp1_bytes) as ing1, io.BytesIO(comp2_bytes) as ing2:
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID4}, "image/jpeg", ing1,
            )
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID5}, "image/jpeg", ing2,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_two_components_mixed_mime(iterations: int = 100) -> None:
    """componentOf JPEG + componentOf PNG in a single c2pa.placed action."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    comp1_bytes = SIGNED_JPEG.read_bytes()
    comp2_bytes = SIGNING_PNG.read_bytes()
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [{
                "action": "c2pa.placed",
                "softwareAgent": {"name": "perf_test"},
                "parameters": {"ingredientIds": [_PLACED_ID4, _PLACED_ID5]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        with io.BytesIO(comp1_bytes) as ing1, io.BytesIO(comp2_bytes) as ing2:
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID4}, "image/jpeg", ing1,
            )
            builder.add_ingredient(
                {"relationship": "componentOf", "instance_id": _PLACED_ID5}, "image/png",  ing2,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_archive_roundtrip(iterations: int = 100) -> None:
    """Serialize builder to archive, reload, add ingredient, sign."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    ingredient_bytes = SIGNED_JPEG.read_bytes()
    for _ in _iterate(iterations):
        archive = io.BytesIO()
        Builder(MANIFEST_BASE).to_archive(archive)
        archive.seek(0)
        # from_archive() yields a context-less Builder; to keep the Context
        # (and its signer), build with the context first, then load the archive.
        builder = Builder(MANIFEST_BASE, context=context).with_archive(archive)
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _PARENT_ID},
                "image/jpeg", ing,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


# jpeg + png context variants, paired with the `_legacy` scenarios above for
# side-by-side comparison.

def scenario_builder_sign_jpeg_with_context(iterations: int = 100) -> None:
    _sign_file_context(SOURCE_JPEG, "image/jpeg", iterations)


def scenario_builder_sign_png_with_context(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_PNG, "image/png", iterations)


def scenario_reader_jpeg_with_context(iterations: int = 100) -> None:
    _read_file_context(SIGNED_JPEG, "image/jpeg", iterations)


# Parallel signing variants: one shared Context across 10 threads.
# {split, full} x {pool, barrier} x {jpeg, png}.

def scenario_builder_sign_jpeg_parallel_split_pool(iterations: int = 100) -> None:
    _sign_parallel(SOURCE_JPEG, "image/jpeg", iterations, per_thread_full=False, launch="pool")


def scenario_builder_sign_jpeg_parallel_split_barrier(iterations: int = 100) -> None:
    _sign_parallel(SOURCE_JPEG, "image/jpeg", iterations, per_thread_full=False, launch="barrier")


def scenario_builder_sign_png_parallel_split_pool(iterations: int = 100) -> None:
    _sign_parallel(SIGNING_PNG, "image/png", iterations, per_thread_full=False, launch="pool")


def scenario_builder_sign_png_parallel_split_barrier(iterations: int = 100) -> None:
    _sign_parallel(SIGNING_PNG, "image/png", iterations, per_thread_full=False, launch="barrier")


# ──────────────────────────────────────────────────────────────────────────────
# Fork-safety scenarios — prove no deadlock and no parent-side memory leaks.
# All are no-ops on Windows (no os.fork). Under memray a deadlock manifests as
# a hung subprocess, which CI catches via overall timeout.
# ──────────────────────────────────────────────────────────────────────────────

def _fork_wait(child_fn) -> None:
    """Fork; run child_fn() in child then _exit(0); parent waits up to 5 s."""
    import signal

    def _on_alarm(signum, frame):
        raise TimeoutError("fork child deadlocked — 5 s alarm fired")

    pid = os.fork()
    if pid == 0:
        child_fn()
        os._exit(0)

    old = signal.signal(signal.SIGALRM, _on_alarm)
    try:
        signal.alarm(5)
        _, status = os.waitpid(pid, 0)
        signal.alarm(0)
    finally:
        signal.signal(signal.SIGALRM, old)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, (
        f"child exited abnormally: status={status}"
    )


def scenario_fork_no_deadlock_reader(iterations: int = 100) -> None:
    """Baseline: create Reader, fork, child gc.collect() + _exit, parent closes.
    Guard fires in child (no deadlock); parent frees normally (no leak).
    """
    if not hasattr(os, "fork"):
        return
    for _ in _iterate(iterations):
        with open(SIGNED_JPEG, "rb") as f:
            reader = Reader("image/jpeg", f)
        _fork_wait(lambda: gc.collect())
        reader.close()


def scenario_fork_contended_mutex(iterations: int = 100) -> None:
    """8 threads create/close Readers in a tight loop while the main thread
    forks 5× per iteration (500 total forks). Maximises the probability that
    the registry Mutex is held at the instant of fork(). If pthread_atfork
    didn't reinit the Rust mutex the first cimpl_free in the child would
    deadlock; the Python guard is also exercised by child GC.
    """
    if not hasattr(os, "fork"):
        return
    stop = threading.Event()

    def _worker():
        while not stop.is_set():
            with open(SIGNED_JPEG, "rb") as f:
                r = Reader("image/jpeg", f)
            r.close()

    threads = [threading.Thread(target=_worker, daemon=True)
               for _ in range(8)]
    for t in threads:
        t.start()
    try:
        for _ in _iterate(iterations):
            for _ in range(5):
                _fork_wait(lambda: gc.collect())
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)


def scenario_fork_thread_local_orphan(iterations: int = 100) -> None:
    """Reproduces the s5cmd pattern: thread stores Reader in threading.local,
    joins, then main forks. CPython drops absent thread-states in the child,
    refcount-finalizing the thread-local Reader. Guard must fire before c2pa_free.
    """
    if not hasattr(os, "fork"):
        return
    for _ in _iterate(iterations):
        tl = threading.local()

        def _create():
            with open(SIGNED_JPEG, "rb") as f:
                tl.reader = Reader("image/jpeg", f)

        t = threading.Thread(target=_create)
        t.start()
        t.join()
        _fork_wait(lambda: gc.collect())


def scenario_fork_gc_cycle(iterations: int = 100) -> None:
    """Reader in a reference cycle — freed only by cyclic GC, not refcounting.
    Child calls gc.collect(), which triggers __del__ on the Reader. Without the
    guard this deadlocks; with it the guard returns immediately.
    """
    if not hasattr(os, "fork"):
        return
    for _ in _iterate(iterations):
        with open(SIGNED_JPEG, "rb") as f:
            reader = Reader("image/jpeg", f)
        container = SimpleNamespace(reader=reader)
        reader.container = container   # cycle: reader ↔ container
        del reader, container          # refcount > 0; cycle survives until GC

        _fork_wait(lambda: gc.collect())
        gc.collect()                   # parent cleans up


def scenario_fork_parent_frees_after_fork(iterations: int = 100) -> None:
    """20 Readers created, fork, child exits immediately, parent closes all 20.
    Primary false-positive test: if is_foreign_process() wrongly fires in the
    parent, all 20 native frees are skipped and leaked_bytes spikes ~20x.
    """
    if not hasattr(os, "fork"):
        return
    for _ in _iterate(iterations):
        readers = []
        for _ in range(20):
            with open(SIGNED_JPEG, "rb") as f:
                readers.append(Reader("image/jpeg", f))
        _fork_wait(lambda: None)       # child does nothing, exits 0
        for r in readers:
            r.close()


def scenario_fork_child_sys_exit(iterations: int = 100) -> None:
    """Child calls sys.exit(0) — full Python shutdown: atexit, finalizers, GC.
    Every native-handle wrapper's __del__ fires in the child. Guard must
    survive Py_Finalize() without deadlocking.
    """
    if not hasattr(os, "fork"):
        return
    for _ in _iterate(iterations):
        with open(SIGNED_JPEG, "rb") as f:
            reader = Reader("image/jpeg", f)
        context = Context()

        def _child():
            import sys as _sys
            _sys.exit(0)   # full Python shutdown, not _exit

        _fork_wait(_child)
        reader.close()
        context.close()


def scenario_fork_stream_cleanup(iterations: int = 100) -> None:
    """Stream wraps a BytesIO with ctypes callbacks stored as instance attributes.
    Both Stream.__del__ and Stream.close carry fork guards. This tests the
    stream-specific path (separate from ManagedResource).
    """
    if not hasattr(os, "fork"):
        return
    source_bytes = SIGNED_JPEG.read_bytes()
    for _ in _iterate(iterations):
        stream = Stream(io.BytesIO(source_bytes))
        _fork_wait(lambda: gc.collect())
        stream.close()


SCENARIOS = {
    "reader_jpeg_legacy": scenario_reader_jpeg_legacy,
    "reader_jpeg_with_context": scenario_reader_jpeg_with_context,
    "reader_mp4": scenario_reader_mp4,
    "reader_wav": scenario_reader_wav,
    "builder_sign_jpeg_legacy": scenario_builder_sign_jpeg_legacy,
    "builder_sign_jpeg_with_context": scenario_builder_sign_jpeg_with_context,
    "builder_sign_png_legacy": scenario_builder_sign_png_legacy,
    "builder_sign_png_with_context": scenario_builder_sign_png_with_context,
    "builder_sign_jpeg_parallel_split_pool": scenario_builder_sign_jpeg_parallel_split_pool,
    "builder_sign_jpeg_parallel_split_barrier": scenario_builder_sign_jpeg_parallel_split_barrier,
    "builder_sign_png_parallel_split_pool": scenario_builder_sign_png_parallel_split_pool,
    "builder_sign_png_parallel_split_barrier": scenario_builder_sign_png_parallel_split_barrier,
    "builder_sign_gif": scenario_builder_sign_gif,
    "builder_sign_heic": scenario_builder_sign_heic,
    "builder_sign_m4a": scenario_builder_sign_m4a,
    "builder_sign_webp": scenario_builder_sign_webp,
    "builder_sign_avi": scenario_builder_sign_avi,
    "builder_sign_mp4": scenario_builder_sign_mp4,
    "builder_sign_tiff": scenario_builder_sign_tiff,
    "builder_sign_jpeg_parent_of": scenario_builder_sign_jpeg_parent_of,
    "builder_sign_jpeg_component_of": scenario_builder_sign_jpeg_component_of,
    "builder_sign_jpeg_parent_and_component": scenario_builder_sign_jpeg_parent_and_component,
    "builder_sign_jpeg_parent_and_component_mixed_mime": scenario_builder_sign_jpeg_parent_and_component_mixed_mime,
    "builder_sign_jpeg_two_components_same_mime": scenario_builder_sign_jpeg_two_components_same_mime,
    "builder_sign_jpeg_two_components_mixed_mime": scenario_builder_sign_jpeg_two_components_mixed_mime,
    "builder_sign_jpeg_archive_roundtrip": scenario_builder_sign_jpeg_archive_roundtrip,
    "fork_no_deadlock_reader":             scenario_fork_no_deadlock_reader,
    "fork_contended_mutex":                scenario_fork_contended_mutex,
    "fork_thread_local_orphan":            scenario_fork_thread_local_orphan,
    "fork_gc_cycle":                       scenario_fork_gc_cycle,
    "fork_parent_frees_after_fork":        scenario_fork_parent_frees_after_fork,
    "fork_child_sys_exit":                 scenario_fork_child_sys_exit,
    "fork_stream_cleanup":                 scenario_fork_stream_cleanup,
}


# Canonical scenario name list, derived from SCENARIOS so the two cannot drift.
# (dict preserves insertion order, so this matches the dict's declaration order.)
SCENARIO_NAMES = tuple(SCENARIOS)
