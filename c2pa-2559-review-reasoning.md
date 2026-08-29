# c2pa-rs PR #2559 — adversarial review, downstream impact, and c2pa-python #312 re-review

Full reasoning record. Everything below is **static analysis only** — there is no Rust
toolchain in the working container (`static.rust-lang.org` is not on the egress allowlist),
so nothing here was compiled or executed. Where a claim rests on an assumption rather than
on traced code, that is stated inline.

Artifacts read:

| Repo | Ref | How |
|---|---|---|
| `contentauth/c2pa-rs` | head `145b754`, base `b3cd390` (PR #2559, branch `gpeacock/c_ffi_opaque_ids`) | full tarball + diff |
| `contentauth/c2pa-cpp` | `main` HEAD | full tarball |
| `contentauth/c2pa-python` | `main` HEAD | full tarball |
| `contentauth/c2pa-python` | `385b28c` (PR #312, branch `mathern/error-slot-sentinel`, base `mathern/sigsev-sigabort`) | full tarball + diff vs main |

---

## Part 1 — What #2559 actually does

### 1.1 The change

`PointerRegistry` previously keyed its `HashMap` on the **real address** of every tracked
allocation. The pointer handed to C *was* the object's address. #2559 splits the key space
in two:

- **Handles** (`C2paReader`, `C2paBuilder`, `C2paSigner`, `C2paSettings`, `C2paContext`,
  `C2paContextBuilder`, `C2paStream`, `C2paHttpResolver`) are now keyed by a synthetic
  **opaque id** produced by `scramble_to_odd_id`, and it is the id — not the address —
  that crosses the FFI boundary. `track_by_id` (utils.rs:~100-120).
- **Buffers** returned by `to_c_string` (utils.rs:512) and `to_c_bytes` (utils.rs:547) stay
  keyed by their **real address**, because C dereferences them. `track_by_address`
  (utils.rs:117-125).

`scramble_to_odd_id(counter) = (2·counter + 1) · M mod 2^N`, with
`M = 0x9e3779b97f4a7c15` on 64-bit and `M = 0x9e3779b9` on 32-bit. Producing only odd
values is what keeps the two key spaces from overlapping: real allocations are assumed
always even.

`validate_pointer` / `untrack_pointer` change return type from `Result<(), Error>` to
`Result<*mut T, Error>`, so every deref macro now goes id → registry → real address →
deref. `PointerRegistry::validate` is renamed to `resolve`. Two new macros,
`deref_mut_option!` and `deref_mut_option_or_return!` (macros.rs:331-357, 358-380), give a
non-erroring `Option` form for cleanup paths.

### 1.2 The vulnerability it fixes — confirmed

Under address keying: object X at address P is freed (removed from the map, `Box` dropped);
a new object Y of the same type is later allocated at P and tracked; a **stale handle P now
resolves to Y**. Same type, wrong live instance. That is a textbook ABA, and it is real.

The fix works for that case: ids are drawn from a monotonic counter and are never recycled,
so a stale id fails lookup with `UntrackedPointer:`.

An extra detail that makes the old bug much more likely than it first looks, and that
matters for the Python analysis in Part 3: consuming calls such as
`c2pa_builder_with_archive` do `untrack_or_return_null!` → `Box::from_raw` → drop →
`box_tracked!(new Box)`. The new `Box` is the same size as the one just freed, and glibc's
tcache is LIFO, so **the replacement handle very often had the identical numeric value as
the consumed one**. Downstream code holding the old pointer was frequently, not rarely,
holding a pointer to the live replacement.

---

## Part 2 — Findings on #2559

Severity, anchor, and where each comment can physically go. GitHub only allows inline
comments on lines inside a diff hunk, so a few of these are forced into the review body.

### F1 — MEDIUM. "Ids are never reused" is false on 32-bit; the period is 2^(N−1)

`(2c+1) mod 2^N` takes only **2^(N−1)** distinct values, because `c` and `c + 2^(N−1)` map
to the same value. Multiplying by an odd `M` is a bijection and does not restore the lost
bit. So the id sequence has period 2^(N−1), not 2^N.

- 64-bit: 2^63. Unreachable.
- wasm32-unknown-emscripten (a supported target — `c2pa_c_ffi/Cargo.toml` has a
  `cfg(target_arch = "wasm32")` dependency table, and `maybe_send_sync.rs` exists for it):
  **2^31 ≈ 2.1e9 handles**, reachable in a long-running process. At wrap, the exact ABA
  this PR fixes returns, silently.

The doc at utils.rs:55-59 states distinct counters are "mathematically guaranteed" to
scramble to distinct odd ids. Off by exactly this factor of two.

Secondary point for the same comment: the PR argues that a stray deref of a handle produces
an immediate obvious crash. On x86-64 that holds — ids land in non-canonical address space
(high bits derived from `0x9e3779b9…`), so the deref faults. On wasm32 it does **not**
generally hold: ids are uniformly distributed 32-bit odd values, and any id smaller than
the current linear-memory size falls inside valid memory and reads garbage instead of
trapping.

→ **Inline, utils.rs:60** (`fn scramble_to_odd_id`, inside the `@@ -33,33 +36,97` hunk).
Ask for the real bound in the doc plus a hard stop on 32-bit once the counter passes 2^31.

### F2 — MEDIUM. The odd/even non-collision invariant is asserted, never enforced, and rests on the allocator rather than on Rust

utils.rs:51-54 justifies non-collision with "real Rust allocations always land on at least a
2-byte boundary, so their addresses are always even."

Both `track_by_address` callers allocate **align-1** memory: `CString::into_raw`
(utils.rs:512) produces a `Vec<u8>`, and `to_c_bytes` (utils.rs:547) produces a
`Box<[u8]>`. Rust guarantees only `align_of::<u8>() == 1`. The claim is true in practice
only because `std`'s `System` allocator forwards to malloc/dlmalloc, which align to 8 or
16 — an allocator property, not a language one. A downstream `#[global_allocator]` (bump
and arena allocators are common in wasm builds) can hand back odd addresses.

If it ever broke, the failure would be **silent, not an error**: `track_by_id`'s
`tracked.insert(id, …)` (utils.rs:114) would overwrite the string's entry, drop its
`CleanupFn` (leak), and make `c2pa_free(that_string)` free the *object* instead.

→ **Inline, utils.rs:117** (`fn track_by_address`). Suggest
`debug_assert_eq!(real_addr & 1, 0)` there, and checking `insert`'s return value in
`track_by_id` so a collision is detected rather than assumed away.

### F3 — MEDIUM. The ABA class is only half fixed, and the new doc does not say so

`to_c_string` / `to_c_bytes` stay address-keyed. A stale `char*` still resolves to whatever
buffer lands at that address next, so `c2pa_free` on it can free a *different* live string.
Same ABA, and undetectable in the CString→CString case since the `TypeId` check passes.

The keying cannot change — C dereferences these — but the registry doc at utils.rs:66-84
explains why handles are safe without noting that the address-keyed half remains exposed,
and the PR description reads as if ABA is closed generally.

→ **Inline, utils.rs:77-84** (the `track_by_address` bullet in the registry doc comment).

### F4 — MEDIUM. Breaking Rust API change, source-compatible in the dangerous direction

`validate_pointer` and `untrack_pointer` change signature; `PointerRegistry::validate` is
renamed to `resolve`. Both functions are re-exported at the crate root
(`cimpl/mod.rs:72-75`) and `cimpl::utils` is a `pub mod` reachable through
`pub use cimpl::*` in `lib.rs`. So this is a breaking change to the `c2pa-c-ffi` crate's
Rust API.

The dangerous part: existing downstream `untrack_pointer(p)?;` **still compiles**. `*mut T`
is not `#[must_use]`, so the returned real pointer is silently discarded, and the caller's
subsequent `Box::from_raw(p)` operates on the handle id. UB with no compile error.

`.github/workflows/semver-checks.yml` lists `c2pa-c-ffi` as a public-API crate but only
runs on PRs targeting `stable` / `v0.*`, so it will **not** fire on this PR against `main`.
It will surface at the release PR instead.

→ **Review body** for the semver/CHANGELOG point (`c2pa_c_ffi/CHANGELOG.md` has an empty
`## [Unreleased]`), plus **inline `#[must_use]` asks at utils.rs:316 and utils.rs:343**.

### F5 — MEDIUM. Nothing tests the new invariants

Codecov reports 83.6% patch coverage, 7 uncovered lines in `utils.rs`. Every test change in
the PR is mechanical (`untrack_pointer(...).unwrap()` adjusted for the new return type).
Grepping the test module in `cimpl/utils.rs` finds no reference to `scramble`, `odd`,
`next_id`, `track_by_id`, or `track_by_address`.

Nothing asserts:

- an id differs from the real address;
- ids are odd;
- a stale handle fails `resolve` after its address is reused by a new same-type object —
  **the actual regression test for the bug in the title**, and it needs no threads: track,
  `cimpl_free`, `track_box` a new `T`, assert `validate_pointer(old_id).is_err()`;
- wrong-type resolve returns `WrongPointerType`;
- `free` on a stale id returns −1.

→ **Inline, utils.rs:~620** (the `@@ -543,14 +620,15` test-module hunk).

### F6 — LOW. One missed call site: `C2paStream::extract_context` (c2pa_stream.rs:110)

Still does `Box::from_raw(self.context)` on what is now a handle id, and never untracks, so
the registry entry persists.

Honest severity: `StreamContext` is a unit struct (c2pa_stream.rs:27), i.e. a ZST, so
`Box<ZST>` drop never calls the allocator — a non-null value is trivially aligned for
align-1, and this will not crash or double-free today. It also has no in-repo callers. But
it is `pub` via `pub use c2pa_stream::*`, and it is precisely the pattern the PR swept for.
Delete it or route it through `untrack_pointer`.

→ **Review body only** — line 110 falls outside every diff hunk.

### F7 — LOW. `resolve` / `untrack` / `free` are `pub` on a `pub` struct in a `pub` module

The premise of the change is that the real address never leaves the registry, yet
`pub fn resolve(&self, id: usize, …) -> Result<usize, Error>` lets any downstream crate turn
a handle back into an address. `pub(crate)` preserves the property.

→ **Inline, utils.rs:128.**

### F8 — LOW. The TOCTOU window is narrowed, not closed

`resolve` drops the `MutexGuard` before returning; the caller then dereferences the real
address outside the lock (macros.rs:248, 304, 354, 378). A concurrent `cimpl_free` of the
*same* handle between resolve and deref is still a use-after-free. The PR fixes
wrong-object; same-object-freed-underneath remains. Pre-existing and arguably out of scope,
but the PR body reads as though the threading hazard is handled.

→ **Inline, macros.rs:304.**

### F9–F11 — NITs

- Error messages lost the real address: `wrong_pointer_type(id as u64)` /
  `untracked_pointer(id as u64)` (utils.rs:~136-140) report the opaque id, which means
  nothing to a debugger. In the `wrong_pointer_type` arm the real address is in hand.
  → inline utils.rs:136-140.
- `deref_mut_option!` is `#[macro_export]` (macros.rs:346) while its own doc calls it
  internal-only. `#[doc(hidden)]` at minimum. → inline macros.rs:346.
- `deref_or_return!` / `deref_mut_or_return!` still evaluate `$ptr` twice
  (`ptr_or_return!($ptr, …)` then `validate_pointer($ptr)`), whereas the two new macros
  correctly bind it once. Harmless for current call sites (all simple locals or casts), but
  both lines are already open in this diff. → inline macros.rs:246-247, 302-303.

### 2.1 Cleared while reviewing — checked and dismissed

- **All 79 `extern "C"` fns scanned programmatically.** Every parameter typed
  `*mut C2paStream / C2paSigner / C2paBuilder / C2paReader / C2paSettings / C2paContext /
  C2paContextBuilder / C2paHttpResolver` passes through a `deref_*`, `untrack_or_return_*`,
  or `cimpl_free!` macro. No unvalidated handle params remain.
- The `&mut *stream` / `&mut *source` / `&mut *dest` occurrences at c_api.rs:1888, 1927,
  1969, 2011-2012, 2061, 2482 are **reborrows of the macro-produced `&mut C2paStream`**, not
  raw derefs. They look like missed call sites and are not.
- The only two remaining raw-pointer derefs in the crate are c_api.rs:5077
  (`&*(context as *const AtomicU32)`, a test counter) and json_api.rs:71 (`&*signer`, an
  `Arc` deref). Neither is a tracked handle.
- `TestC2paStream::reader` and `seeker` already used `deref_mut_or_return_int!` on main;
  only `writer` needed the fix. Verified against the diff hunks.
- `to_c_bytes` returns NULL for empty input (utils.rs:543), so no `NonNull::dangling()`
  value of `1` can ever be tracked by address and collide with the odd id space.
- `drop_c_stream`: the `if let Some(real_stream)` binding scope ends before
  `cimpl_free(c_stream)`, so there is no live `&mut` across the free.
- `test_c2pa_create_stream` frees `context` exactly once — `c2pa_release_stream` does not
  touch the context.
- `untrack`'s `tracked.get(&id)` followed by `tracked.remove(&id)` inside the matched arm:
  no scrutinee binding is used in the arm body, so NLL should end the immutable borrow
  before the `remove`. Should compile; CI would catch it otherwise. The destructuring
  `let (real_addr, _, _) = …` drops the `CleanupFn`, which for `track_box` captures only a
  `usize` — harmless.
- `next_id` starts at 0, so the first id is `1 · M = 0x9e3779b97f4a7c15`, non-zero and odd.
  `Ordering::Relaxed` on `fetch_add` is fine: the RMW is atomic, so values are unique
  regardless of ordering.
- `arc_tracked!` is unused, so the pre-existing `untrack_or_return!` → `Box::from_raw`
  mismatch for `Arc`-tracked entries is not reachable. Not this PR's concern.
- `mergeable_state` was `unstable`; the GitHub API rate-limited before the check-runs list
  could be read, so the failing check is unidentified. Codecov's patch gate at 83.6% is the
  likely candidate but that is a guess.

---

## Part 3 — Downstream impact

### 3.1 c2pa-cpp — one confirmed hard break

`tests/c-app-test/file_stream.h:114`:

```c
int close_file_stream(C2paStream *stream)
{
    if (stream == NULL) { return -1; }
    FILE *file = (FILE *)stream->context;   // <-- breaks
    int result = fclose(file);
    c2pa_release_stream(stream);
    return result;
}
```

`stream` is the pointer returned by `c2pa_create_stream`, which is now an opaque id. On
x86-64 that address is non-canonical, so this is an immediate SIGSEGV — exactly the
"obvious crash" the PR intends, but in a downstream consumer rather than internal code.

This is the empirical proof for a review point worth adding to #2559: `C2paStream` is
`#[repr(C)]`, cbindgen emits its fields into `c2pa.h`, and the header therefore advertises
a layout the returned pointer no longer has. **Ask for `C2paStream` (and the other handle
types) to go into cbindgen's `opaque_types`** — that converts this whole class of downstream
break from a runtime fault into a compile error. c2pa-cpp's own fix is to keep the `FILE*`
alongside the handle instead of reading it back out.

Everything else in c2pa-cpp is clean:

- The C++ wrappers (`include/c2pa.hpp`, `src/c2pa_*.cpp`) only store handles and hand them
  back to `c2pa_free` / `c2pa_release_stream`. No field access, no arithmetic, no use as map
  keys, no `unique_ptr<C2paX>`, no `delete`.
- Stream contexts it passes in — `reinterpret_cast<StreamContext *>(&istream)` at
  c2pa.hpp:571, 633, 693 — are **C++-owned and never enter the registry**. `c2pa_create_stream`
  stores the context verbatim and the C++ callbacks cast it straight back. Untouched by #2559.
  (The `deref_mut_or_return_int!` on `context` inside `c2pa_stream.rs` applies only to the
  Rust-side `TestC2paStream` helper.)

**wasm relevance:** `Makefile:151` downloads a `wasm32-unknown-emscripten` build from
c2pa-rs releases, pinned at `CMakeLists.txt:20` → `C2PA_VERSION "0.90.16"`. That is the
32-bit target where F1 applies: 2^31 id period, and stray derefs that read garbage instead
of trapping.

### 3.2 c2pa-python (main) — net leak fix, one latent footgun

The binding's ownership model rests on *"a guarded free is a real free if ours, a no-op if
not"* (`ManagedResource._free_native_ptr`, c2pa.py:268-289; `_release_handle`, 341-349).
Under address keying that was only **probabilistically** true, for the tcache reason in §1.2:
a stale free could hit the live replacement, or a recycled object on another thread. That is
a use-after-free, not a leak. After #2559 the old id is dead forever and `c2pa_free`
deterministically returns −1. The comment at c2pa.py:490-493 about *"races a recycled address
in other threads"* describes precisely the hazard this closes.
`tests/test_unit_tests_threaded.py` is where it would have surfaced.

**The error-tag routing survives unchanged.** `_PRE_CONSUME_ERROR_TAGS` matches on
`"UntrackedPointer:"` / `"WrongPointerType:"` (c2pa.py:421); #2559 only swaps the numeric
value inside those messages, not the tag text. The retain-vs-consume decision in
`_raise_consume_failure` behaves identically.

Leak behaviour changes in two small ways, both benign:

1. The retain branch fires more often — a stale handle reaching native is now *always*
   rejected with `UntrackedPointer:`, so the Python object stays `ACTIVE` with a dead
   handle. Nothing leaks in Rust; the previous behaviour (succeeding against a recycled
   object) was strictly worse.
2. Ids are never recycled, so a genuinely leaked handle now leaks faithfully and its
   registry entry persists. Address recycling used to clean some of these up by accident.
   **A latent leak — e.g. `__del__` not firing under a reference cycle — may become visible
   for the first time in soak/perf runs.** That is a diagnostic win, not a new regression,
   but it is worth expecting.

**Latent footgun:** `class C2paStream(ctypes.Structure)` at c2pa.py:658-692 declares the real
`_fields_` (`context`, `reader`, `seeker`, `writer`, `flusher`), unlike every other opaque
type in the file which uses `_fields_ = []`. Nothing dereferences it today —
`c2pa_create_stream` is called with `context=None` (c2pa.py:2003-2009) and the callbacks
close over a weakref — so there is no live bug. But it is the same shape as the c2pa-cpp
break. Change it to `_fields_ = []`.

**Checked and clear:** `_convert_to_py_string` (c2pa.py:1220-1254) and the mime-type array
paths operate on `to_c_string` / `to_c_bytes` pointers, which stay address-keyed.
`ctypes.addressof(data.contents)` at c2pa.py:1879 is the read callback's real `*mut u8`
buffer, not a handle. `if not handle` truthiness is safe since ids are never 0. No
pointer-identity maps, no arithmetic, no reconstruction of pointers from stored ints.

---

## Part 4 — c2pa-python PR #312 re-review

PR #312, *"fix: Put a sentinel in the native thread local error slot"*, head `385b28c`,
base `mathern/sigsev-sigabort` (not `main`), 8 commits, approved by ale-adobe, awaiting
ok-nick.

### 4.1 What it does

`_MARKER_ADDR = 1` is passed to `c2pa_free` to plant a known error into the thread-local
`LAST_ERROR` slot. The exact text is **learned at import** rather than hardcoded
(`_learn_sentinel_no_native_error_text`, c2pa.py:1271-1296), since the format is a native
implementation detail. `_invoke_consume` marks the slot before every consuming call
(c2pa.py:594), and `_read_native_error` re-marks after reading (c2pa.py:899), so an error is
consumed exactly once by the caller that observes it.

### 4.2 Is #312 still warranted given #2559? — split answer

**The sentinel core: yes, and #2559 makes it *more* necessary.**

`LAST_ERROR` stickiness is orthogonal to how the registry is keyed. #2559 does not clear the
slot, does not change thread-locality, and does not change the message text for a failed
free — so `_learn_sentinel_no_native_error_text()` keeps working unchanged.

Second-order effect worth adding to the PR description: after #2559, a guarded free of a
dead handle **always** returns −1 and **always** writes `UntrackedPointer:` into the slot.
Under address keying, a fraction of those frees silently succeeded and set nothing, because
the address had been recycled. So pre-consume-tag pollution of the sticky slot becomes
strictly more frequent once #2559 lands, and the misclassification #312 fixes gets more
likely, not less.

Mapping the PR body's two motivations:

| Motivation in #312 body | Status after #2559 |
|---|---|
| Stale tag from a finished task on a pooled worker thread | **Untouched.** This is the load-bearing one. |
| Address reuse: stale free finds a live entry and destroys another thread's object | **Eliminated.** |

**The leak flip: warranted today, obsolete once #2559 ships.**

This is the substantive difference from `main`. On `main`, `_raise_consume_failure`'s
"no error in the slot" branch did `self._release_handle()` — free defensively. On #312
(c2pa.py:648-658) it does `_teardown(free_handle=False)`, and the justification is verbatim
*"a free here can race a recycled address in other threads."* The same reasoning appears in
the non-tag branch at 641-646.

That is precisely and only the hazard #2559 removes. #312 trades a possible UAF for a
certain leak — which the PR body concedes: *"On any consume failure where the verdict is not
certain, this takes the consumed branch, meaning leaks could appear."* Once a
#2559-containing c2pa-rs is the floor, both branches can revert to `_release_handle()` and
recover the leak, **independently of the 0.91.0 always-consumed contract the PR body is
waiting on**. Recommendation: land #312 as-is, with a TODO / issue link on those two
branches so it is not forgotten — the existing note points at 0.91.0, which is a different
mechanism arriving later.

### 4.3 New interaction to flag on #312 — `_MARKER_ADDR = 1`

```python
# Unaligned address passed to c2pa_free to plant a marker
# in the native error slot.
# Never a real handle: allocations are aligned, and the Python
# layer only passes real handles or this constant to c2pa_free.
_MARKER_ADDR = 1
```

That justification is exactly the invariant #2559 inverts. After it, registry keys are no
longer all real addresses: handle ids are `(2c+1)·M mod 2^N`, i.e. **always odd** — the same
namespace as `1`.

Multiplication by an odd constant is a bijection mod 2^N, so there is exactly one counter
value per period producing id `1`. Solve `(2c+1)·M ≡ 1 (mod 2^N)`, i.e. `2c+1 ≡ M⁻¹`:

| Width | `M` | `M⁻¹ mod 2^N` | counter yielding id `1` |
|---|---|---|---|
| 64-bit | `0x9e3779b97f4a7c15` | `0xf1de83e19937733d` | `8714256306465913246` ≈ 2^63 |
| 32-bit | `0x9e3779b9` | `0x144cbc89` | **`170286660`** ≈ 2^28 |

Reachability, stated honestly: **c2pa-python ships 64-bit wheels only.**
`scripts/download_artifacts.py` maps to `x86_64` / `aarch64` across
`apple-darwin`, `pc-windows-msvc`, `unknown-linux-gnu` — no i686, no wasm. So this is **not
reachable for Python in practice**. It is reachable on c2pa-cpp's emscripten path, where
170M tracked handles is a soak-test-scale number rather than an astronomical one.

Consequence if it ever hit: `_mark_sentinel_no_native_error()` → `c2pa_free(1)` frees a
**live object** belonging to another thread, returns 0, and sets no error. And it is called
on every `_invoke_consume` and every `_read_native_error`, so it is a hot path.

Fix: pick a marker that is outside every key space under **both** the current v0.90
scheme and #2559, rather than one justified by whichever scheme happens to be loaded. That
is `_MARKER_ADDR = 8` — see §5.1 for the two independent properties that make it safe under
each, the constant-derived assert that replaces the hardcoded `"0x1"` at c2pa.py:1297, and
why `0` must not be used.

### 4.4 Carried over unchanged into #312

- `C2paStream._fields_` at c2pa.py:833-844 still declares the real layout while every other
  opaque type uses `_fields_ = []`. Still no live bug (`c2pa_create_stream` is called with
  `context=None` at c2pa.py:2282-2288), still the same shape as the confirmed c2pa-cpp
  break at `file_stream.h:114`. Still worth `_fields_ = []`.
- `_PRE_CONSUME_ERROR_TAGS` grew to four entries (c2pa.py:567-572), adding `NullParameter:`
  and `InvalidBufferSize:`. All four still match after #2559; `resolve()` returning
  `null_parameter("pointer")` for id 0 keeps the `NullParameter:` tag meaningful, and ids
  are never 0, so it only fires on genuine nulls.

---

## Part 5 — Making the plan work against v0.90 *and* #2559

**Revision note.** The first version of §4.3 recommended `_MARKER_ADDR = 2` justified by
"handle ids are always odd." That reasoning only holds *after* #2559 and says nothing about
v0.90. This part replaces it with a set of choices that are correct under both, and
separates the items that need no version-awareness at all from the one that genuinely does.

Three native behaviours are in play:

| | key space | ownership on a failed consuming call |
|---|---|---|
| **v0.90.x (today)** | real addresses only, recyclable | ambiguous |
| **v0.90.x + #2559** | odd synthetic ids for handles, real addresses for buffers | ambiguous |
| **v0.91.0 (announced)** | as above | always consumed by native |

Only the *middle* column differs from today in a way that changes a Python decision, and
only for one branch. Everything else can be made version-blind.

### 5.1 The marker address — version-blind, and worth changing now

`_MARKER_ADDR` must be a value that the registry can never legitimately hold as a key,
under any of the three columns. Two independent properties give that:

1. **Below the first page.** No allocator returns an address in the null page, under any
   scheme, so it can never be a real allocation and therefore never an address-keyed buffer
   entry. This is the property that covers v0.90, where *all* keys are addresses.
2. **Even.** Under #2559, ids are `(2c+1)·M` with `M` odd, so every id is odd *by
   construction* — not by allocator convention. An even value can therefore never be a
   synthetic id.

`1` has property 1 but not property 2. Use **`_MARKER_ADDR = 8`**: it satisfies both, and
each property alone is sufficient for one of the two schemes, so the marker is safe whether
or not #2559 is present in the loaded library. Do not use `0` — `PointerRegistry::free`
short-circuits `key == 0` to `Ok(())` (utils.rs), so a zero marker would return 0 and set no
error, silently disabling the whole mechanism.

Rewrite the justification comment accordingly:

```python
# Address passed to c2pa_free purely to plant a known marker in the
# native thread-local error slot.
#
# Safe under every native key scheme:
#   - below the first page, so never a real allocation and never an
#     address-keyed buffer entry;
#   - even, and synthetic handle ids are odd by construction, so never
#     a handle id either.
# Must not be 0: the registry treats a 0 key as a successful no-op.
_MARKER_ADDR = 8
```

**Derive the assert rather than hardcoding the literal.** c2pa.py:1297 currently reads
`assert "0x1" in _NO_NATIVE_ERROR_TEXT`, which both hardcodes the constant and is a loose
substring test (`"0x1"` matches `0x1a2b…`). Replace it with something tied to the constant
and anchored, and move it inside `_learn_sentinel_no_native_error_text()` — which also
answers ale-adobe's review comment:

```python
def _learn_sentinel_no_native_error_text():
    ...
    if f"0x{_MARKER_ADDR:x}" not in text:
        raise ImportError(
            "c2pa native library's untracked-pointer error text no longer "
            "includes the planted address; the error-slot marker assumption "
            "no longer holds")
    return text
```

The message text itself needs no version handling: v0.90 formats
`untracked_pointer(ptr as u64)` and #2559 formats `untracked_pointer(id as u64)`, and for
the marker the value passed *is* the key in both cases, so the learned string is identical.
Learning at import already makes this robust; the only thing that was version-specific was
the choice of constant.

### 5.2 The free-vs-leak branches — the one place version-awareness is needed

`_raise_consume_failure`'s two `_teardown(free_handle=False)` branches (c2pa.py:641-646 and
648-658) leak on an ambiguous failure, to avoid a defensive free racing a recycled address.
That trade is **correct on v0.90 and unnecessary after #2559**.

Before building any machinery for this, check the release sequencing, because it may be
moot: #2559 targets `main`, and the announced always-consumed contract is v0.91.0. If both
ship in 0.91.0, there is never a release where ids are opaque *and* ownership is ambiguous —
the middle column of the table above never exists — and the right answer is simply to leave
#312's leak branches alone permanently, since under always-consumed they are correct by
contract rather than as a workaround. **Resolve that question first.** Everything in the
rest of this subsection is contingent on the middle window being real.

If it is real, detect the scheme behaviourally rather than by version string. A version
parse has to encode which release contains #2559 and breaks on backports; a behavioural
probe describes the property it actually depends on:

```python
def _detect_opaque_handles(probes=4):
    """True when the native library returns synthetic handle ids rather
    than real addresses.

    Synthetic ids are odd by construction; real allocation addresses are
    aligned to at least 8 bytes by every allocator this library ships
    against. Requiring every probe to come back odd means a stray odd
    address cannot flip the verdict, and any failure falls to the
    conservative (address-keyed) answer.
    """
    handles = []
    try:
        for _ in range(probes):
            h = _lib.c2pa_settings_new()
            if not h:
                return False
            handles.append(h)
        return all(
            ctypes.cast(h, ctypes.c_void_p).value & 1 for h in handles)
    except Exception:
        return False
    finally:
        for h in handles:
            _lib.c2pa_free(h)
```

`c2pa_settings_new` is `box_tracked!(C2paSettings::new())` — a single `Box`, no I/O, present
in both the v0.90 FFI and the #2559 head. Allocating several before freeing any prevents the
allocator from handing back the same address each round, which would make the probe a test
of one address rather than of the scheme.

Failure directions are asymmetric and the probe is oriented safely:

- **False negative** (says address-keyed when it is id-keyed): keeps the leak branch. The
  status quo of #312. Harmless.
- **False positive** (says id-keyed when it is address-keyed): re-enables the defensive
  free, which is the UAF #312 exists to prevent. This requires *every* probe to return an
  odd address — impossible with malloc/dlmalloc alignment, and made vanishingly unlikely by
  the `all()` over several probes. Any exception path also returns `False`.

Then gate only the branches, leaving the tag routing untouched:

```python
_HANDLES_ARE_OPAQUE = _detect_opaque_handles()

# ... inside _raise_consume_failure, both ambiguous branches:
if _HANDLES_ARE_OPAQUE:
    # Freeing a dead handle is a guaranteed no-op: ids are never
    # recycled, so this cannot reach another thread's object.
    self._release_handle()
else:
    # Address keys are recyclable; a defensive free could destroy a
    # live object at a reused address. Accept the leak.
    self._teardown(free_handle=False)
```

**Import ordering.** Run `_detect_opaque_handles()` *before*
`_learn_sentinel_no_native_error_text()`. The probe's frees succeed and set no error, so
they cannot disturb the slot, but learning the sentinel last leaves the error slot in the
known state the rest of the module assumes.

**Test it under both.** A unit test can force each branch by monkeypatching
`_HANDLES_ARE_OPAQUE`, so the leak path and the free path are both covered on a single
native build. Add one assertion that the probe itself agrees with `sdk_version()` on the CI
matrix, so a future native change that breaks the odd-id invariant is caught loudly rather
than silently downgrading to the leak branch forever.

### 5.3 Items that are already version-blind

No change needed for compatibility; they behave identically under all three columns.

- `C2paStream._fields_ = []` (c2pa.py:833-844). Nothing derefs it under either scheme; the
  change only removes the ability to.
- `_PRE_CONSUME_ERROR_TAGS` (c2pa.py:567-572). All four tags are produced by both v0.90 and
  #2559, with the same text.
- The c2pa-cpp fix to `tests/c-app-test/file_stream.h:114` — keeping the `FILE*` alongside
  the handle instead of reading `stream->context` back — is correct under both, since it
  simply stops depending on the struct layout.
- Every c2pa-rs finding in Part 2 is a comment on #2559 itself and has no v0.90 dimension.

### 5.4 One sequencing constraint created by the cbindgen ask

The recommendation to move `C2paStream` and the other handle types into cbindgen's
`opaque_types` (Part 2, review-body item) turns the c2pa-cpp break from a runtime segfault
into a compile error. That is the desired outcome, but it means **`file_stream.h` stops
compiling the moment c2pa-cpp bumps to a release containing the change**. Land the c2pa-cpp
fix first, or land both in a coordinated bump, and call the header change out in the
c2pa-c-ffi changelog alongside the F4 semver note — it is a source-breaking change for any C
consumer that touches those structs, not only for this one test helper.

---

## Part 6 — Consolidated action list

**On c2pa-rs #2559**

1. Inline utils.rs:60 — F1, period is 2^(N−1); 32-bit wraps at 2^31; the crash-loudly
   argument does not carry to wasm32.
2. Inline utils.rs:117 — F2, `debug_assert_eq!(real_addr & 1, 0)`; check `insert`'s return.
3. Inline utils.rs:77-84 — F3, document that address-keyed buffers remain ABA-prone.
4. Inline utils.rs:316 and utils.rs:343 — F4, `#[must_use]`.
5. Inline utils.rs:~620 — F5, add the stale-handle regression test.
6. Inline utils.rs:128 — F7, `pub(crate)` on `resolve` / `untrack` / `free`.
7. Inline macros.rs:304 — F8, note the residual resolve→deref window.
8. Inline utils.rs:136-140, macros.rs:346, macros.rs:246-247 / 302-303 — F9–F11 nits.
9. **Review body:** F6 (`extract_context`, outside all hunks); F4's semver/CHANGELOG point;
   and the cbindgen `opaque_types` ask, citing the c2pa-cpp break as the motivating case and
   noting the §5.4 sequencing constraint.

**On c2pa-cpp**

10. Fix `tests/c-app-test/file_stream.h:114` — keep the `FILE*` alongside the handle. Land
    before, or with, the version bump that carries the cbindgen change.

**On c2pa-python #312 — safe under v0.90 today, and after #2559**

11. `_MARKER_ADDR = 8` with the two-property justification from §5.1. Not `1`, not `0`.
12. Derive the sentinel assert from `_MARKER_ADDR` and move it inside
    `_learn_sentinel_no_native_error_text()` (also answers the open review comment).
13. `C2paStream._fields_ = []` at c2pa.py:833-844.

**On c2pa-python — deferred, and only if the middle release window turns out to be real**

14. Confirm with the c2pa-rs team whether #2559 and the always-consumed contract ship in the
    same release. If yes, stop here and leave the leak branches permanently.
15. If no: add `_detect_opaque_handles()` (§5.2), gate the two ambiguous branches on it,
    order it before the sentinel learn, and add both-branch coverage plus a probe-versus-
    `sdk_version()` consistency check in CI.

---

## Appendix — verification notes and limits

- No Rust toolchain available; nothing compiled or run. Findings are static traces through
  the tarballs listed at the top.
- GitHub's REST API rate-limited partway through, so the #2559 check-runs list was never
  read. `mergeable_state: unstable` is all that is known about CI.
- The `untrack` borrow-check question (§2.1) is a reasoned NLL argument, not a compiler
  result.
- The modular-inverse figures in §4.3 were computed directly (`pow(M, -1, 2**N)`) and
  round-tripped: `((2c+1)·M) mod 2^N == 1` for both widths.
- Reachability claims about counter exhaustion assume one counter increment per tracked
  handle, which matches `track_by_id` being the single id source for `track_box`,
  `track_arc`, and `track_arc_mutex`.
- The `_detect_opaque_handles` probe in §5.2 is proposed, not tested. Its v0.90 side rests
  on malloc/dlmalloc returning 8- or 16-byte-aligned addresses — an allocator property, the
  same one F2 flags as unenforced upstream. That is acceptable here only because the probe
  fails toward the conservative branch; it should not be reused anywhere the failure
  direction is reversed.
- The release-sequencing question in §5.2 and item 14 is unresolved and cannot be settled
  from the repositories alone. It is stated as an open question, not an assumption.
