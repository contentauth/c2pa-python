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
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from c2pa import (
    Builder,
    C2paError,
    C2paSignerInfo,
    Context,
    Reader,
    Signer,
    Stream,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
READING_FIXTURES_DIR = FIXTURES_DIR / "files-for-reading-tests"
SIGNING_FIXTURES_DIR = FIXTURES_DIR / "files-for-signing-tests"

SIGNED_JPEG = FIXTURES_DIR / "C.jpg"
CLOUD_JPEG = FIXTURES_DIR / "cloud.jpg"
SOURCE_JPEG = FIXTURES_DIR / "A.jpg"
SIGNING_PNG = SIGNING_FIXTURES_DIR / "sample1.png"
DASH_INIT_MP4 = FIXTURES_DIR / "dashinit.mp4"
DASH_FRAGMENT = FIXTURES_DIR / "dash1.m4s"

_DST_COMPOSITE = "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"

_PARENT_ID    = "xmp:iid:aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"
_PLACED_ID    = "xmp:iid:bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"
_PARENT_ID2   = "xmp:iid:cccccccc-0003-0003-0003-cccccccccccc"
_PLACED_ID2   = "xmp:iid:dddddddd-0004-0004-0004-dddddddddddd"
_PARENT_ID3   = "xmp:iid:eeeeeeee-0005-0005-0005-eeeeeeeeeeee"
_PLACED_ID3   = "xmp:iid:ffffffff-0006-0006-0006-ffffffffffff"
_PLACED_ID4   = "xmp:iid:11111111-0007-0007-0007-111111111111"
_PLACED_ID5   = "xmp:iid:22222222-0008-0008-0008-222222222222"
_ARCH_PARENT_ID = "xmp:iid:33333333-0009-0009-0009-333333333333"
_ARCH_COMP_ID   = "xmp:iid:44444444-0010-0010-0010-444444444444"
_ARCH_COMP_ID2  = "xmp:iid:55555555-0011-0011-0011-555555555555"

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
        # from_archive() yields a context-less Builder. To keep the Context
        # (and its signer), build with the context first, then load the archive.
        builder = Builder(MANIFEST_BASE, context=context).with_archive(archive)
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _PARENT_ID},
                "image/jpeg", ing,
            )
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_with_archive_swap(iterations: int = 100) -> None:
    """Loop Builder.with_archive(), the consume-and-return FFI path.

    c2pa_builder_with_archive consumes the old native handle and returns a
    replacement, so the Python side swaps the pointer without freeing the
    consumed one. Freeing it would be a double-free, and failing to adopt the
    replacement would leak. The other builder scenarios never swap a live
    handle, so neither mistake would show up there.
    """
    context = Context(signer=_make_signer())
    archive = io.BytesIO()
    Builder(MANIFEST_BASE).to_archive(archive)
    archive_bytes = archive.getvalue()
    for _ in _iterate(iterations):
        builder = Builder(MANIFEST_BASE, context=context)
        builder.with_archive(io.BytesIO(archive_bytes))
        builder.close()


def scenario_reader_with_fragment_swap(iterations: int = 100) -> None:
    """Loop Reader.with_fragment(), the other consume-and-return FFI path.

    Same ownership hand-off as with_archive: c2pa_reader_with_fragment eats
    the old reader handle and returns a new one.
    """
    init_bytes = DASH_INIT_MP4.read_bytes()
    fragment_bytes = DASH_FRAGMENT.read_bytes()
    for _ in _iterate(iterations):
        reader = Reader("video/mp4", io.BytesIO(init_bytes))
        try:
            reader.with_fragment(
                "video/mp4",
                io.BytesIO(init_bytes),
                io.BytesIO(fragment_bytes),
            )
        except C2paError:
            # A failed call consumed the old handle just as a successful one
            # would, so the scenario measures both outcomes.
            pass
        finally:
            reader.close()


def scenario_builder_from_archive_roundtrip(iterations: int = 100) -> None:
    """Loop Builder.from_archive() itself (context-less alternate constructor),
    then sign. Regression guard for the classmethod's native-handle wrapping.
    """
    signer = _make_signer()
    source_bytes = SOURCE_JPEG.read_bytes()
    ingredient_bytes = SIGNED_JPEG.read_bytes()
    archive_bytes = io.BytesIO()
    Builder(MANIFEST_BASE).to_archive(archive_bytes)
    archive_bytes = archive_bytes.getvalue()
    for _ in _iterate(iterations):
        # from_archive() yields a context-less Builder, so sign() needs an
        # explicit signer (no Context to pull one from).
        builder = Builder.from_archive(io.BytesIO(archive_bytes))
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _PARENT_ID},
                "image/jpeg", ing,
            )
        builder.sign(signer, "image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


# Archive scenarios: builder as working store (to_archive/with_archive) and
# per-ingredient archives (write_ingredient_archive/add_ingredient_from_archive).

def _ingredient_archive_bytes(ingredient_json: dict, mime: str, asset_bytes: bytes) -> bytes:
    """Build a per-ingredient archive once, for reuse inside scenario loops."""
    builder = Builder(MANIFEST_BASE)
    with io.BytesIO(asset_bytes) as ing:
        builder.add_ingredient(ingredient_json, mime, ing)
    archive = io.BytesIO()
    builder.write_ingredient_archive(ingredient_json["instance_id"], archive)
    return archive.getvalue()


def scenario_builder_to_archive_with_ingredient(iterations: int = 100) -> None:
    """Serialize a builder holding one ingredient to an archive (no signing)."""
    ingredient_bytes = SIGNED_JPEG.read_bytes()
    for _ in _iterate(iterations):
        builder = Builder(MANIFEST_BASE)
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _ARCH_PARENT_ID},
                "image/jpeg", ing,
            )
        builder.to_archive(io.BytesIO())


def scenario_builder_sign_jpeg_archive_roundtrip_ingredient_in_archive(iterations: int = 100) -> None:
    """Add ingredient, serialize to archive, reload, sign.

    Unlike scenario_builder_sign_jpeg_archive_roundtrip, the ingredient is
    added before to_archive, so its resources travel through the archive.
    """
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
                "parameters": {"ingredientIds": [_ARCH_PARENT_ID]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        archive = io.BytesIO()
        src_builder = Builder(manifest)
        with io.BytesIO(ingredient_bytes) as ing:
            src_builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _ARCH_PARENT_ID},
                "image/jpeg", ing,
            )
        src_builder.to_archive(archive)
        archive.seek(0)
        builder = Builder(manifest, context=context).with_archive(archive)
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_write_ingredient_archive(iterations: int = 100) -> None:
    """Add one ingredient and write it out as a per-ingredient archive."""
    ingredient_bytes = SIGNED_JPEG.read_bytes()
    for _ in _iterate(iterations):
        builder = Builder(MANIFEST_BASE)
        with io.BytesIO(ingredient_bytes) as ing:
            builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _ARCH_PARENT_ID},
                "image/jpeg", ing,
            )
        builder.write_ingredient_archive(_ARCH_PARENT_ID, io.BytesIO())


def scenario_builder_sign_jpeg_add_ingredient_from_archive(iterations: int = 100) -> None:
    """Restore one ingredient from a prebuilt archive and sign."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    archive_bytes = _ingredient_archive_bytes(
        {"relationship": "parentOf", "instance_id": _ARCH_PARENT_ID},
        "image/jpeg", SIGNED_JPEG.read_bytes(),
    )
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [{
                "action": "c2pa.opened",
                "softwareAgent": {"name": "perf_test"},
                "parameters": {"ingredientIds": [_ARCH_PARENT_ID]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        builder.add_ingredient_from_archive(io.BytesIO(archive_bytes))
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_ingredient_archive_roundtrip(iterations: int = 100) -> None:
    """Write a per-ingredient archive from one builder, load into another, sign."""
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
                "parameters": {"ingredientIds": [_ARCH_PARENT_ID]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        archive = io.BytesIO()
        src_builder = Builder(MANIFEST_BASE)
        with io.BytesIO(ingredient_bytes) as ing:
            src_builder.add_ingredient(
                {"relationship": "parentOf", "instance_id": _ARCH_PARENT_ID},
                "image/jpeg", ing,
            )
        src_builder.write_ingredient_archive(_ARCH_PARENT_ID, archive)
        archive.seek(0)
        builder = Builder(manifest, context=context)
        builder.add_ingredient_from_archive(archive)
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())


def scenario_builder_sign_jpeg_two_ingredient_archives(iterations: int = 100) -> None:
    """Restore two ingredients (JPEG + PNG) from prebuilt archives and sign."""
    context = Context(signer=_make_signer())
    source_bytes = SOURCE_JPEG.read_bytes()
    archive1_bytes = _ingredient_archive_bytes(
        {"relationship": "componentOf", "instance_id": _ARCH_COMP_ID},
        "image/jpeg", SIGNED_JPEG.read_bytes(),
    )
    archive2_bytes = _ingredient_archive_bytes(
        {"relationship": "componentOf", "instance_id": _ARCH_COMP_ID2},
        "image/png", SIGNING_PNG.read_bytes(),
    )
    manifest = {
        **MANIFEST_BASE,
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {"actions": [{
                "action": "c2pa.placed",
                "softwareAgent": {"name": "perf_test"},
                "parameters": {"ingredientIds": [_ARCH_COMP_ID, _ARCH_COMP_ID2]},
                "digitalSourceType": _DST_COMPOSITE,
            }]},
        }],
    }
    for _ in _iterate(iterations):
        builder = Builder(manifest, context=context)
        builder.add_ingredient_from_archive(io.BytesIO(archive1_bytes))
        builder.add_ingredient_from_archive(io.BytesIO(archive2_bytes))
        builder.sign("image/jpeg", io.BytesIO(source_bytes), io.BytesIO())
def scenario_reader_error_no_manifest(iterations: int = 100) -> None:
    """Reader on an unsigned asset: partial-init cleanup."""
    source_bytes = SOURCE_JPEG.read_bytes()  # A.jpg carries no manifest
    for _ in _iterate(iterations):
        try:
            Reader("image/jpeg", io.BytesIO(source_bytes)).json()
        except C2paError:
            pass


def scenario_builder_error_invalid_manifest(iterations: int = 100) -> None:
    """Error case: Builder with malformed manifest JSON."""
    for _ in _iterate(iterations):
        try:
            Builder('{"not valid json')
        except C2paError:
            pass


def scenario_reader_string_apis(iterations: int = 100) -> None:
    """Uncached string returns: detailed_json/crjson/remote_url/resource_to_stream."""
    source_bytes = SIGNED_JPEG.read_bytes()
    context = Context()
    # Resolve a real resource URI once, outside the measured loop.
    probe = Reader("image/jpeg", io.BytesIO(source_bytes),
                   manifest_data=None, context=context)
    manifests = json.loads(probe.json())
    active = manifests["manifests"][manifests["active_manifest"]]
    thumb_uri = active["thumbnail"]["identifier"]
    probe.close()
    for _ in _iterate(iterations):
        reader = Reader("image/jpeg", io.BytesIO(source_bytes),
                        manifest_data=None, context=context)
        reader.detailed_json()
        reader.crjson()
        reader.get_remote_url()
        reader.resource_to_stream(thumb_uri, io.BytesIO())
        reader.close()


def scenario_signer_construction(iterations: int = 100) -> None:
    """Loop Signer.from_info()/__init__ construction and teardown.

    Every other scenario calls _make_signer() once outside its loop, so
    repeated Signer construction/destruction has no coverage elsewhere.
    Regression guard for Signer.__init__'s native-handle activation.
    """
    for _ in _iterate(iterations):
        signer = _make_signer()
        signer.close()


# jpeg + png context variants, paired with the `_legacy` scenarios above for
# side-by-side comparison.

def scenario_builder_sign_jpeg_with_context(iterations: int = 100) -> None:
    _sign_file_context(SOURCE_JPEG, "image/jpeg", iterations)


def scenario_builder_sign_png_with_context(iterations: int = 100) -> None:
    _sign_file_context(SIGNING_PNG, "image/png", iterations)


def scenario_reader_jpeg_with_context(iterations: int = 100) -> None:
    _read_file_context(SIGNED_JPEG, "image/jpeg", iterations)


def scenario_reader_manifest_data_context(iterations: int = 100) -> None:
    """Reader over a detached (sidecar) manifest with a Context.

    Exercises c2pa_reader_with_manifest_data_and_stream, the consume-and-swap
    FFI path (reader_from_context handle is consumed and replaced each call).
    The manifest is signed once outside the loop; each iteration re-reads the
    same asset + detached manifest, so flat RSS confirms no per-iteration leak
    in the consume-and-swap path.
    """
    source_bytes = SOURCE_JPEG.read_bytes()
    signer = _make_signer()
    builder = Builder({**MANIFEST_BASE, "format": "image/jpeg"})
    builder.set_no_embed()
    manifest_bytes = builder.sign(
        signer, "image/jpeg", io.BytesIO(source_bytes), io.BytesIO())
    builder.close()
    signer.close()

    context = Context()
    for _ in _iterate(iterations):
        reader = Reader("image/jpeg", io.BytesIO(source_bytes),
                        manifest_data=manifest_bytes, context=context)
        reader.json()
        reader.close()


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


def scenario_fork_reader_collect(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    Baseline: create Reader, fork, child gc.collect() + _exit, parent closes.
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
    """Fork safety benchmark scenario:
    8 threads create/close Readers in a tight loop while the main thread
    forks 5× per iteration (500 total forks). Maximises the probability that
    the registry Mutex is held at the instant of fork(). Each fork inherits
    a Reader created by the main thread; the child explicitly closes it
    (then runs GC), so the PID guard is exercised on every fork — without
    the guard the close would call into the native library and could
    deadlock on a mutex left locked by a vanished worker thread. The parent
    closes the same Reader after the child exits (its own PID: real free).

    Note: the workers' Readers are pinned by frozen thread frames in the
    child, so child gc.collect() alone would free nothing — hence the
    explicit close of an inherited object.
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
                with open(SIGNED_JPEG, "rb") as f:
                    reader = Reader("image/jpeg", f)

                def _child(r=reader):
                    r.close()
                    gc.collect()

                _fork_wait(_child)
                reader.close()
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)


def scenario_fork_thread_local_orphan(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    A thread stores Reader in threading.local, joins, then main forks.
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
    """Fork safety benchmark scenario:
    Reader in a reference cycle, freed only by cyclic GC, not refcounting.
    Child calls gc.collect(), which triggers __del__ on the Reader.
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
    """Fork safety benchmark scenario:
    20 Readers created, fork, child exits immediately, parent closes all 20.
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
    """Fork safety benchmark scenario:
    Child calls sys.exit(0), full Python shutdown: atexit, finalizers, GC.
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


def _fork_contended_over(make_object, iterations):
    """Fork over an object built by make_object() while 8 threads churn
    Readers, so the registry Mutex is likely held at the instant of fork().

    The child closes the inherited object. Without the PID guard that close
    calls into the native library and can block forever on a mutex left
    locked by a thread that fork() did not clone, which _fork_wait's alarm
    reports as a timeout. The parent closes afterwards for the real free.
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
                obj = make_object()

                def _child(o=obj):
                    o.close()
                    gc.collect()

                _fork_wait(_child)
                obj.close()
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)


def scenario_fork_contended_mutex_swap(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    fork over a Builder whose handle came from with_archive(), under the same
    thread contention as fork_contended_mutex. That scenario only ever forks
    over handles that came straight from a constructor, so a swapped-in
    handle losing its stamp would go unnoticed there.
    """
    if not hasattr(os, "fork"):
        return
    context = Context(signer=_make_signer())
    archive = io.BytesIO()
    Builder(MANIFEST_BASE).to_archive(archive)
    archive_bytes = archive.getvalue()

    def _make():
        builder = Builder(MANIFEST_BASE, context=context)
        builder.with_archive(io.BytesIO(archive_bytes))
        return builder

    _fork_contended_over(_make, iterations)


def scenario_fork_contended_mutex_wrap(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    fork over a Builder built by from_archive(), under thread contention.
    from_archive is the only path that bypasses __init__, so it is the one
    most likely to be missing the PID stamp the child's close() depends on.
    """
    if not hasattr(os, "fork"):
        return
    archive = io.BytesIO()
    Builder(MANIFEST_BASE).to_archive(archive)
    archive_bytes = archive.getvalue()

    _fork_contended_over(
        lambda: Builder.from_archive(io.BytesIO(archive_bytes)), iterations)


def scenario_fork_consumed_signer(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    the parent builds a Context that consumed a Signer, then forks. The child
    closes both. The consumed Signer holds no handle, so it must be inert in
    either process, and the Context must be skipped by the PID guard.
    """
    if not hasattr(os, "fork"):
        return
    for _ in _iterate(iterations):
        signer = _make_signer()
        context = Context(signer=signer)

        def _child(c=context, s=signer):
            s.close()
            c.close()
            gc.collect()

        _fork_wait(_child)
        signer.close()
        context.close()


def scenario_swap_chain_churn(iterations: int = 100) -> None:
    """Loop with_archive() repeatedly on one Builder, so a chain of handles
    is consumed and replaced on a single live object. Every other scenario
    swaps a given object at most once.

    This one is a crash and allocation-churn guard rather than a leak gate.
    Only one Builder is closed however many times the loop runs, so a
    close-path leak here is O(1) and invisible against the interpreter's
    allocation floor. What a broken swap does instead is fail loudly: keeping
    the consumed pointer makes the next call raise UntrackedPointer from the
    native registry, and freeing it makes the free itself fail. total_allocations
    still tracks the churn.
    """
    context = Context(signer=_make_signer())
    archive = io.BytesIO()
    Builder(MANIFEST_BASE).to_archive(archive)
    archive_bytes = archive.getvalue()
    builder = Builder(MANIFEST_BASE, context=context)
    for _ in _iterate(iterations):
        builder.with_archive(io.BytesIO(archive_bytes))
    builder.close()
    context.close()


def scenario_fork_swap_cleanup(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    the handle a Builder owns at fork time came from with_archive(), which
    consumed the original and returned a replacement. The child must skip the
    free on the swapped-in handle just as it would on an original one, and the
    parent must still free it exactly once afterwards. The other fork
    scenarios only ever fork over handles that came straight from a
    constructor.
    """
    if not hasattr(os, "fork"):
        return
    context = Context(signer=_make_signer())
    archive = io.BytesIO()
    Builder(MANIFEST_BASE).to_archive(archive)
    archive_bytes = archive.getvalue()
    for _ in _iterate(iterations):
        builder = Builder(MANIFEST_BASE, context=context)
        builder.with_archive(io.BytesIO(archive_bytes))

        def _child(b=builder):
            b.close()
            gc.collect()

        _fork_wait(_child)
        builder.close()


def scenario_fork_stream_cleanup(iterations: int = 100) -> None:
    """Fork safety benchmark scenario:
    Stream wraps a BytesIO with ctypes callbacks stored as instance attributes.
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
    "reader_manifest_data_context": scenario_reader_manifest_data_context,
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
    "builder_from_archive_roundtrip": scenario_builder_from_archive_roundtrip,
    "builder_with_archive_swap": scenario_builder_with_archive_swap,
    "reader_with_fragment_swap": scenario_reader_with_fragment_swap,
    "builder_to_archive_with_ingredient": scenario_builder_to_archive_with_ingredient,
    "builder_sign_jpeg_archive_roundtrip_ingredient_in_archive": scenario_builder_sign_jpeg_archive_roundtrip_ingredient_in_archive,
    "builder_write_ingredient_archive": scenario_builder_write_ingredient_archive,
    "builder_sign_jpeg_add_ingredient_from_archive": scenario_builder_sign_jpeg_add_ingredient_from_archive,
    "builder_ingredient_archive_roundtrip": scenario_builder_ingredient_archive_roundtrip,
    "builder_sign_jpeg_two_ingredient_archives": scenario_builder_sign_jpeg_two_ingredient_archives,
    "reader_error_no_manifest": scenario_reader_error_no_manifest,
    "builder_error_invalid_manifest": scenario_builder_error_invalid_manifest,
    "reader_string_apis": scenario_reader_string_apis,
    "signer_construction": scenario_signer_construction,
    "fork_reader_collect": scenario_fork_reader_collect,
    "fork_contended_mutex": scenario_fork_contended_mutex,
    "fork_thread_local_orphan": scenario_fork_thread_local_orphan,
    "fork_gc_cycle": scenario_fork_gc_cycle,
    "fork_parent_frees_after_fork": scenario_fork_parent_frees_after_fork,
    "fork_child_sys_exit": scenario_fork_child_sys_exit,
    "fork_stream_cleanup": scenario_fork_stream_cleanup,
    "fork_swap_cleanup": scenario_fork_swap_cleanup,
    "fork_contended_mutex_swap": scenario_fork_contended_mutex_swap,
    "fork_contended_mutex_wrap": scenario_fork_contended_mutex_wrap,
    "fork_consumed_signer": scenario_fork_consumed_signer,
    "swap_chain_churn": scenario_swap_chain_churn,
}


# Canonical scenario name list, derived from SCENARIOS so the two cannot drift.
# (dict preserves insertion order, so this matches the dict's declaration order.)
SCENARIO_NAMES = tuple(SCENARIOS)
