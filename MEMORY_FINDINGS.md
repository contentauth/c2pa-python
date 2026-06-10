# Memory investigation findings

Date: 2026-06-10. Environment: macOS arm64, Python 3.12, memray 1.19.3,
native library c2pa-v0.86.1 (local build). Methodology and harness live in
`tests/perf/` (see its README).

## Summary

Nine memray scenarios were written to cover previously unmeasured paths:
callback signers, sign-failure error paths, abandoned (never-closed)
readers, `ManifestNotFound` / invalid-manifest error loops, the uncached
Reader string APIs, thumbnail/resource transfer in both directions, and
per-iteration Context/Signer churn. After the investigation, only the three
that guard the fixed code paths were kept in `tests/perf/scenarios.py`
(`reader_error_no_manifest`, `builder_error_invalid_manifest`,
`reader_string_apis`); the others measured clean and added suite runtime
without guarding anything.

**No memory leak was found in c2pa-rs.** Native memory was measured flat
across all scenarios: `leaked_bytes` deltas between 100 and 300 iterations
were within noise (±4 KiB, i.e. zero per-iteration slope) on every scenario,
including both thumbnail/resource paths.

**One real issue was found and fixed in the Python bindings** (not a native
leak): several hot ctypes patterns created reference-cycle garbage on every
operation, which only the cycle collector could reclaim. This showed up as
live-memory growth of ~366 B per Reader iteration between garbage-collector
runs, plus avoidable gc pressure (3-4 cycle objects per operation). Details
below.

## Thumbnail / resource handling verdict

Both directions were profiled explicitly because they were suspected:

- `reader_string_apis` — per iteration: `detailed_json()`, `crjson()`,
  `get_remote_url()`, and `resource_to_stream()` extracting the active
  manifest's JPEG thumbnail (31,608 bytes per extraction) from
  `tests/fixtures/C.jpg`. Measured: leaked 2.10 MiB at N=100 vs 2.10 MiB at
  N=300 (delta −975 B). No growing allocation site above 4 KiB.
- `builder_add_resource_thumbnail` — per iteration: `Builder.add_resource`
  of a ~90 KB JPEG thumbnail followed by a context sign. Measured: leaked
  2.30 MiB at both N=100 and N=300 (delta −2.2 KiB). No growing site.

The constant ~2-4 MiB `leaked_bytes` floor in every scenario is the
documented one-time static overhead of loading the native library (see
"Why is leaked_bytes not zero?" in `tests/perf/README.md`), not a leak: it
does not scale with iterations.

Conclusion: the native `c2pa_reader_resource_to_stream`,
`c2pa_builder_add_resource`, manifest parse and sign paths free everything
they allocate. Nothing to report to c2pa-rs.

## The issue that was real: ctypes reference cycles in the bindings

Symptom (measured before the fix):

- `gc.collect()` after 100 Reader iterations found 344 unreachable objects;
  after 50 Builder signs, 208 — even when `close()` was called correctly.
- memray's high-watermark snapshot for `reader_jpeg_with_context` grew
  366 B/iteration (2,694 KiB at N=100 → 2,765 KiB at N=300): cycle garbage
  accumulating between collector runs counts as live memory.
- Garbage was ctypes-internal: `PyCArrayType` classes, `LP_C2paReader`
  pointer objects, and their type dicts/descriptors.

Root causes, isolated by measuring each pattern in a bare loop:

| Pattern | Cycle objects per call |
| --- | --- |
| `ctypes.cast(value, c_char_p)` (string returns, error strings) | 2 |
| `ctypes.cast(ffi_ptr, c_void_p)` (every native free) | 2 |
| `(ctypes.c_char * length)` built per stream-read call | ~0.6 |
| `ctypes.string_at(...)` / direct pointer pass | 0 |

Fixes applied in `src/c2pa/c2pa.py`:

1. `_convert_to_py_string` and the error path in
   `_parse_operation_result_for_error` now read native strings with
   `ctypes.string_at` instead of `ctypes.cast(..., c_char_p)`.
2. `ManagedResource._free_native_ptr` passes the pointer directly to
   `c2pa_free` (whose argtype is already `c_void_p`) instead of casting.
3. The per-chunk stream read path wraps the native buffer in a writable
   memoryview (`PyMemoryView_FromMemory`) instead of building a
   `(c_char * length)` array type — no class creation at all, for any chunk
   size. The view is `release()`d in a `finally` right after `readinto`, so
   a stream object that stashes the buffer gets a `ValueError` on later
   access instead of writing into freed native memory (the old ctypes-array
   approach had no such guard), and the reported read count is clamped to
   the buffer length. The remaining array-type sites (manifest byte arrays,
   signing payloads) were left as plain inline `(c_ubyte * n)` creations:
   they run once per operation, lengths there are data-dependent and rarely
   repeat, so caching would not hit and the one cyclic class per operation
   is negligible next to the operation itself.

Verified after the fix:

- `gc.collect()` finds **0** unreachable objects after 100 Reader
  iterations (with or without `close()`) and after 50 Builder signs.
- High-watermark growth: −13 B/iteration (flat) for the Reader control.
- Peak RSS without memray: flat at 33.7 MB for N=100/300/600.
- Full unit suite: 234 passed.

## Other paths checked and clean

| Scenario | leaked @100 → @300 | Verdict |
| --- | --- | --- |
| signer_from_callback_churn | 4.25 MiB → 4.25 MiB | clean |
| signer_callback_sign_error | 3.48 MiB → 3.48 MiB | clean (error strings freed) |
| stream_abandon_no_close | 2.10 MiB → 2.10 MiB | clean (gc + `__del__` releases native stream) |
| reader_error_no_manifest | 2.08 MiB → 2.08 MiB | clean (partial-init cleanup works) |
| builder_error_invalid_manifest | 2.05 MiB → 2.04 MiB | clean |
| context_churn | 2.30 MiB → 2.30 MiB | clean (`c2pa_context_free` + consumed signer) |
| signer_from_info_churn | 2.04 MiB → 2.04 MiB | clean (`c2pa_signer_free`) |

One measurement note: `memray`'s `metadata.peak_memory` shows a ~3-5 KiB
per-iteration upward slope even after the fix, while the sum of its
high-watermark allocation records, process RSS, and `leaked_bytes` are all
flat. That residual slope is profiler accounting overhead (it scales with
the number of allocation records), not application memory; use the
high-watermark records or RSS when judging peak behavior across different
iteration counts.

## Also found during review (not measured as leaking, fixed by design)

`Signer.from_callback` could leak the native signer pointer if signer
creation failed after `c2pa_signer_create` returned non-null. In practice
this path is unreachable with bad input — the native library defers
certificate validation to signing time (confirmed: garbage PEM creates a
signer successfully; the failure surfaces during `Builder.sign` as
`C2paError.Signature`, covered by the `signer_callback_sign_error`
scenario, which measures clean).
