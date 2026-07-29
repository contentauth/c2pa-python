# PR #303 — re-review after the hardening pass

**Branch state:** `mathern/http-resolver-custom` at `377cd27` ("fix: hardening").
**Baseline:** the prior adversarial review at `c785450`.
**Method:** every accepted change was re-derived against the c2pa-rs FFI at the pinned tag `c2pa-v0.90.1` and, where ctypes/urllib semantics decide it, re-run (results quoted). Signer callback confirmed untouched, as you noted.

## Bottom line

The four accepted fixes are all **correctly implemented and adversarially confirmed sound** — including two subtleties the fixes could have gotten wrong but didn't. There is **one new, CI-breaking regression** introduced by the refactor (a lint error), and a few small notes. Nothing here is memory-unsafe. The one must-fix is trivial.

---

## Part 1 — Accepted fixes: re-verified

**B2 (status range check) — correct, and tight.** `if not 100 <= status <= 599` now sits after the int/bool check. Confirmed the double-truncation is fully closed: 599 is the max accepted, far below both i32 and u16 limits, so there is no value that passes the Python check and then changes meaning under Rust's `status as u16`. Boundary-tested: 100/599 accepted; 99/600/65736/-1 rejected. The one behavioral consequence worth a mention: nonstandard 6xx/7xx statuses that some CDNs emit now raise instead of passing through. That is a defensible trade (it's the price of killing the truncation alias) — just flag it in the `with_resolver` notes so it isn't a surprise.

**B3 (falsy-body mask) — correct.** `payload = result.body; if payload is None: payload = b""` replaced the `or b""`. Re-confirmed the hole is closed: a `0` / `False` / `[]` body now reaches the isinstance check and raises `TypeError` naming the type, while `None` still legitimately means empty. The `data = bytes(payload)` snapshot (the A1 fix from last round) remains correctly placed right after the type check.

**B5 (error-message hardening) — correct, and safe in its own edge cases.** NUL is escaped (`replace("\x00", "\\x00")`), length capped at 1024 codepoints + `"...(truncated)"`, then `encode(..., "replace")`. Confirmed: the truncation slices on codepoints (not bytes), so no mid-character mojibake; the resulting CString is bounded. Also checked the failure mode of the size-limiting block itself — if a pathological `__str__` raises, the surrounding `except BaseException: pass` swallows it and the slot goes unset (degrades to the "stale slot" case, not a crash). Acceptable. The `"Other: "` prefix is preserved, so error-type spoofing via a crafted message remains impossible.

**B6 (write-status-last) — correct, and its safety claim actually holds against Rust.** This is the one I attacked hardest, because the comment makes a specific promise. Verified end to end:
- The body fields are written first; `response.status = status` is the last statement before `return 0`.
- The promised property is "a partial write leaves `status = 0`, which Rust rejects." Confirmed on both sides: Rust constructs the response struct fresh per call as `{status: 0, body: null, body_len: 0}`, and `Response::builder().status(0 as u16)` fails (`StatusCode::from_u16(0)` is an error), so a half-written struct read as success by the ctypes guard's default `0` return becomes a **clean Rust-side failure**, not accepted data.
- The subtler question — does the malloc'd body leak in that partial-write case? — is **no**. Rust's `TryFrom<C2paHttpResponse>` copies and `libc::free`s the body *before* it builds the Response and hits the invalid-status error (verified in `c_api.rs`: the free happens in the body-extraction block that precedes `.status().body()`). So even the partial-success path frees correctly. The reorder is strictly a safety improvement with zero cost.

**B1 (SSRF/local-file — example resolvers) — correct, no bypass found.** `_reject_non_http` uses `urllib.parse.urlsplit(url).scheme.lower()` and both example resolvers call it as their first line. Attacked the scheme check directly:
- `file://`, `FILE://`, `ftp://`, `gopher://`, `data:`, `jar:file://`, and scheme-relative `//evil` are all **blocked**. Good.
- Probed for check-vs-client divergence (a URL the check reads as http but `urlopen` fetches as something else, or vice-versa). The only divergences found — embedded-newline schemes like `"http\n://evil"` — **fail closed**: the check may pass them, but `urllib.request.urlopen` then raises `URLError: unknown url type` and performs no fetch. Confirmed by running it. So there is no "allowed by check, fetched anyway" path. The fix is sound.
- The README bullet correctly frames the URL as attacker-influenced and names both `file://` read and internal-network SSRF.

**B8 docstrings + docs — done and accurate.** The ctypes struct docstrings no longer claim to be a resolver-author surface; the musl/C-runtime note and the concurrent-`close()` warning both landed in the README with correct framing.

---

## Part 3 — Rejected items: my read on the rejections

You said some changes were rejected; reconciling against what shipped:

- **B4 (signer-callback hardening) — rejected, and you confirmed no signer changes.** For the record so it's a deliberate decision and not a silent gap: the signer callback still catches `Exception` (not `BaseException`), still never calls `c2pa_error_set_last`, and still truncates an oversized signature via `min(len, signed_len)`. None of these is memory-unsafe — they're diagnostic/robustness gaps, and the signing path is out of this PR's stated scope (HTTP resolver). Leaving it is a reasonable scoping call. If you ever want it, it's a self-contained follow-up; no dependency on anything here.
- **B7 (reentrancy guard) — rejected.** Fine. It was explicitly marked optional last round. Reentrancy stays documented-UB rather than a caught error. No residue in the code from a partial attempt — clean rejection.

Neither rejection leaves a correctness or safety hole in the resolver path.

---

## Part 4 — Smaller notes (optional)

- **N1 (test coverage gap).** The three new guards (B1 scheme reject, B2 range, B3 falsy body) and the B5 message shaping have **no tests**. The guards are correct, but they're exactly the kind of thing a future refactor silently removes. Cheap, all no-network: `file://` URL → both example resolvers raise (assert nothing read from disk); status `65736`/`-1` → typed error naming the value; body `0` → typed error naming `int`, body `None` → empty ok; exception message `"boom\x00hidden"` → resulting `C2paError` contains `boom` and the escaped marker. These are the same six from the prior plan's Part C, minus the signer ones. Worth adding before merge since this directory is the reference.
- **N2 (status upper bound).** 599 excludes the rare nonstandard 6xx/7xx. If any target environment legitimately sees those, widen to `<= 999` (still within u16, still kills the truncation alias). Default to 599 unless you know otherwise — just don't let it surprise anyone.
- **N3.** Two pre-existing E501s in `http_resolver_example_impl.py` (lines 18, 55) are untouched by this PR and not linted by CI (only `src/c2pa/c2pa.py` is checked), so they're harmless — noting them only so they're not mistaken for new.

## Fix order

R1 (delete the blank line — unblocks CI) → N1 tests if you want them in this PR → N2 only if your environments need it. Everything in Part 1 is done and verified; don't touch it.
