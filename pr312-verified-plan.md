# PR #312 — verified plan (compatible with v0.90.15 today and v0.91.0 next)

Everything below was checked against running code, not read off the two source
documents. Evidence tier is marked per claim: **ran** (executed, read the output),
**read** (opened the source at a named revision), **inferred** (reasoned, not confirmed).

Revisions used:

| Repo | Ref | Meaning |
|---|---|---|
| c2pa-python | `9f62daf` (`mathern/error-slot-sentinel`) | branch under review |
| c2pa-rs | `stable` = `0.90.15` | what the binding loads today |
| c2pa-rs | `origin/main` = `0.91.0-dev` (`be7f5ea2`) | what ships next |
| c2pa-rs | `pr2559` = `145b754a`, base `b3cd390a` | opaque-ids PR, not merged |

Local native library after `make rebuild`: `c2pa-c-ffi/0.90.15 c2pa-rs/0.90.15`.

---

## What the adversarial pass changed

Three corrections to the input documents, each of which moves the plan.

### The release-sequencing question is answered, and the answer is the opposite of the guess

The review document (§5.2, item 14) leaves open whether #2559 and the always-consumed
contract ship together, and recommends building a behavioural probe
(`_detect_opaque_handles`) if they do not. That machinery is not needed.

**Read** — the always-consumed ordering came from PR #2344, merged 2026-07-23, and is
already on `main`, independent of #2559:

```
78b5b709 2026-07-23 fix: builder style c_ffi_api functions will now consistently
                    consume the self parameter (#2344)
```

**Ran** — `git merge-base --is-ancestor 78b5b709 stable` reports #2344 is *not* in the
0.90 line, and `main` is `0.91.0-dev`. **Read** — the reordered body is identical on
`origin/main` and on `pr2559`, and its base `b3cd390a` already contains it, so #2559 did
not introduce it.

Both changes therefore arrive in the same 0.91.0 release. The middle column of the review
document's table — opaque ids *with* ambiguous ownership — never exists as a shipped
release. **Drop `_detect_opaque_handles` entirely.** It is roughly 30 lines of probe plus
a CI consistency check built for a window that does not occur, and its own author's note
concedes its v0.90 side rests on the same unenforced allocator assumption that finding F2
criticises upstream.

### The ordering flip is real, and it is the reason Fix 1 is not optional

**Read** — `c2pa_reader_with_manifest_data_and_stream`, the two revisions side by side:

```rust
// stable (0.90.15) — validate first, reader still tracked on early return
let format = cstr_or_return_null!(format);
let stream = deref_mut_or_return_null!(stream, C2paStream);
let manifest_bytes = bytes_or_return_null!(manifest_data, manifest_size, "manifest_data");
untrack_or_return_null!(reader, C2paReader);

// main (0.91.0-dev) — take ownership first, every early return drops it
let reader = untrack_or_return_null!(reader, C2paReader);
let format = cstr_or_return_null!(format);
```

**Ran** — against the pinned 0.90.15 library, a rejected call leaves the handle alive:

```
c2pa_reader_with_manifest_data_and_stream(reader, "image/jpeg", NULL, NULL, 0)
  -> NULL,  error = 'NullParameter: stream'
c2pa_free(reader) -> 0        # 0 = still tracked, native did NOT consume it
```

After the bump the same message means the opposite. A classifier that decides ownership
from message text is therefore correct today and wrong on 0.91.0.

### The address-reuse hazard is certain, not probabilistic

The review document argues from glibc tcache LIFO that a stale free "very often" hits the
live replacement. **Ran** — on this macOS build it is not "often", it is total:

```
allocate -> free -> allocate (same type), 200 trials
address reuse: 200/200 = 100%
```

So on v0.90 a defensive free of a handle whose ownership is uncertain reliably destroys
the object that took its address. This is the strongest available justification for the
leak-over-free trade, and it is what makes Fix 1 the correct direction rather than merely
a forward-compatibility hedge.

---

## Confirmed by execution before writing any code

- **Marker candidates.** `c2pa_free(0) -> 0` with an empty error string, so `0` silently
  disables the sentinel; `c2pa_free(8) -> -1` with `Other: UntrackedPointer: 0x8`.
  **Read** — `PointerRegistry::free` short-circuits `key == 0` to `Ok(())`, which is the
  mechanism behind that result.
- **Handle shape on v0.90.** Eight consecutive `c2pa_settings_new()` handles were all real
  addresses, all 256-byte aligned, none below the first page. Both properties the marker
  argument depends on hold on the library we actually load.
- **Scramble arithmetic**, recomputed independently rather than taken from the document:
  `scr(0) == scr(2^(N-1))` on both widths, so the id period is 2^(N-1), confirming F1; the
  32-bit counter producing id `1` is `170286660`; no id is ever even, on any input.
- **Fix 2 and Fix 3 defects**, both **read** in the current source: `_maybe_flush_pending`
  (line ~511) returns on `_in_native_section()` without calling
  `_register_for_section_flush(self)`, while `_teardown` (line 474) does register on the
  same condition — the deferral has no remaining flush path. `_finish_teardown` writes
  `self._released = True` as its first statement (line 492) and is called outside the lock,
  so a second entrant arriving before that write repeats the whole teardown.

## Already done on this branch — no action

- The sentinel assert is **already** derived from the constant (`marker_hex =
  hex(_MARKER_ADDR)`) and **already** inside `_learn_sentinel_no_native_error_text()`.
  Review items 11-part-two and 12 are complete; the document describes an older revision.
- `_PRE_CONSUME_ERROR_TAGS` is back to two entries. Commit `9f62daf` removed
  `NullParameter:` and `InvalidBufferSize:`, so §4.4's four-entry description is stale.

## Pre-existing breakage this plan must absorb

**Ran** — on a clean tree after `make rebuild`: **4 failed, 482 passed**. All four trace to
`9f62daf` removing the two tags without updating the tests that assert the old behaviour.
They fail independently of anything proposed here.

```
test_invalid_buffer_size_rejection_retains_the_handle   AssertionError: the retained handle was dropped
test_null_parameter_rejection_retains_the_handle        AssertionError: the retained handle was dropped
test_repeated_rejections_do_not_accumulate_handles      10 of 10 handles leaked
test_native_rejections_observed_from_the_library_still_classify
```

The version test that failed before the rebuild (`'0.90.16' not found in '0.90.15'`) was a
stale-artifact problem and is now green.

---

## The plan

### 1. Fix 1 — once a consuming call has been issued, never free the handle

Collapse the three branches of `_raise_consume_failure` and the `except` path of
`_invoke_consume` to `self._teardown(free_handle=False)`. Ownership stops being derived
from error text; the tags survive only to select a log line.

Correct on 0.91.0 by contract. On 0.90.15 it accepts a bounded leak on an error path in
exchange for making a free of a reused address structurally impossible — which the 200/200
measurement shows is the real hazard, not a theoretical one.

Mechanical follow-ons: drop `_raise_consume_failure`'s `previous_state` parameter and
`_invoke_consume`'s `reserved` keyword with their call sites; leave `_abort_consume` for
the two `except` paths where the handle provably never reached native.

### 2. Fix 2 — register for section flush when a native section blocks the drain

Add the missing `_register_for_section_flush(self)`, add the `is_foreign_process` guard
`_teardown` already has, and move `_finish_teardown` inside the lock.

### 3. Fix 3 — make `_finish_teardown` idempotent

Guard on `self._released` before setting it. With Fix 2's locking this closes both the
duplicate `_release()` and the double-free window.

### 4. Marker address `1` -> `8`

Not reachable on shipped Python wheels (64-bit only; the colliding counter is ~2^62), so
this is hardening, not a live bug — I would rather say that plainly than overstate it. It
costs one line and removes a justification comment that is already wrong in its reasoning:
"allocations are aligned" stops being the relevant property once ids are synthetic. `8` is
below the first page (safe under v0.90 address keys) and even (safe under #2559 odd ids).
Not `0`, for the measured reason above.

### 5. `C2paStream._fields_ = []`

**Read** — every other opaque type in the file uses `_fields_ = []`; this one declares the
real layout. Nothing dereferences it today (`c2pa_create_stream` is called with
`context=None`), so there is no live bug — but it is the same shape as the confirmed
c2pa-cpp break at `file_stream.h:114`, where reading `stream->context` back out segfaults
once the pointer is an opaque id.

### 6. Tests — remove what is obsolete, keep what still holds

Per your instruction, and split deliberately rather than deleting all four failures:

Remove — these assert retain-and-retry, a promise deleted by `9f62daf` and contradicted by
the 0.91.0 ordering:
- `test_null_parameter_rejection_retains_the_handle`
- `test_invalid_buffer_size_rejection_retains_the_handle`
- `test_pre_consume_rejection_restores_the_resource`
- `test_repeated_rejections_do_not_accumulate_handles` (asserts no leak; Fix 1 trades that
  away knowingly)
- `test_with_fragment_pre_consume_rejection_keeps_handle`

Amend rather than delete — `test_native_rejections_observed_from_the_library_still_classify`
pins the wording the library actually emits, which is worth keeping. Drop its
`c2pa_reader_from_stream(None, None)` half, whose `NullParameter` message is deliberately
no longer classified, and keep the `c2pa_free(0x9999)` half.

Keep untouched: `test_pre_consume_tags_still_match_the_native_wording`,
`test_pre_consume_tag_match_is_substring_not_prefix`,
`test_caller_text_quoting_a_tag_is_not_a_rejection`,
`test_concurrent_close_runs_release_once`.

Add: a regression test for Fix 2 that wraps the existing
`test_context_close_during_sign_defers_teardown` in a second `_native_call()`, since one
nesting level does not exercise the stranded path.

### 7. Perf — the part that will fail silently if skipped

**Read** — `run_profile.py` gates the run on `leaked_bytes` at a 1.1x threshold, and
`scenario_reader_with_fragment_pre_consume_rejection` asserts:

```python
if reader._handle is None:
    raise AssertionError("handle was dropped on a pre-consume rejection; ...")
```

Fix 1 makes that assertion fire on every iteration, and raises the scenario's
`leaked_bytes` (baseline `3417826`) by design. Both must move together:

- Invert the scenario's assertion to expect the consumed-and-not-freed outcome, and drop
  the `_is_pre_consume_rejection` requirement now that the tags no longer decide ownership.
- Re-measure and re-baseline that one entry, rather than raising the global threshold —
  a threshold bump would mask unrelated regressions across the other 59 scenarios.
- Add a scenario covering the Fix 1 leak on a **non**-rejection consuming failure, so the
  bounded leak has a tracked ceiling instead of being asserted in prose.
- Add a repeated close-under-nested-section scenario for Fix 2: the stranded-deferral bug
  leaks a whole native object per occurrence, which is a memory signal the unit tests do
  not quantify.

### Out of scope, stated rather than silently dropped

`_abort_consume` reviving a resource with a queued teardown; `_native_section`'s `finally`
masking the body's exception; Python-side argument preflighting. All three are noted in the
fix plan and none is required for the paths that exist after Fix 1.

### Landing order

Fixes 2, 3, 4 and 5 are independent of native version and of each other. Fix 1 carries the
behaviour change, the test removals and the perf re-baseline, and is the one that must land
before the 0.91.0 bump.

---

## Limits

- No 0.91.0 build exists to test against; the ordering claim is **read** from `origin/main`
  source, and the runtime behaviour under 0.91.0 is **inferred** from it.
- #2559 is unmerged. If it lands in a later release than 0.91.0, the ownership conclusion
  is unaffected — that rests on #2344, which is already on main — but the marker-address
  reasoning in step 4 would be hardening ahead of a scheme not yet shipped.
- The 100% address-reuse measurement is this macOS allocator on this machine. The direction
  generalises; the exact rate does not.
- Findings F1–F11 in the review document are comments on c2pa-rs #2559, not work in this
  repository. I verified F1's arithmetic, F2's mechanism and F4's empty changelog; I did not
  re-derive the rest, and none of them gates this plan.
