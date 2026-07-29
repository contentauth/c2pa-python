# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

"""Example implementations of a custom HTTP resolver for c2pa.

c2pa ships no HttpRequest/HttpResponse/HttpResolver types:
the resolver passed to ContextBuilder.with_resolver()/Context(resolver=...)
is never isinstance-checked, so any of these classes is a starting point to copy
and adapt, not a required dependency.

This module has no dependency on c2pa itself: it only needs to satisfy
the attribute shape the SDK expects.
"""

import base64
import collections
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod


def _reject_non_http(url):
    """Raise if url's scheme is not http/https.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"refusing to resolve non-http(s) URL scheme: {scheme!r}")


def _has_opaque_encoded_final_segment(url):
    """True if the URL's last path segment looks like an encoded blob
    (e.g. an OCSP request) rather than an ordinary resource name.
    Such GETs should not be cached like a plain resource fetch.
    """
    seg = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    seg = urllib.parse.unquote(seg)
    if len(seg) < 40:
        return False
    try:
        base64.b64decode(seg, validate=True)
    except Exception:
        return False
    return True


def _is_safe_to_cache(request):
    """Oonly True for a GET positively known to be safe
    (not opaque-encoded, not a DID document request).
    Anything else (POSTs, ambiguous or unrecognized GETs)
    is False by default.
    """
    if request.method.upper() != "GET":
        return False
    if _has_opaque_encoded_final_segment(request.url):
        return False
    headers = {k.lower(): v for k, v in request.headers.items()}
    if "application/did+json" in headers.get("accept", ""):
        return False
    return True


class HttpRequest:
    """An HTTP request the SDK asks a custom resolver to perform.

    Attributes:
        url: Absolute request URL.
        method: HTTP method ("GET", "POST", ...).
        headers: Request headers as a dict. Names are lowercased by the
            native layer; when a header repeats, the last value wins.
        body: Request body bytes (b"" when there is none). A request
            carrying a payload (typically a POST) sets this; a plain GET
            usually doesn't.

    Reference shape only:
    c2pa hands resolve() a duck-typed object with these same four attributes,
    not necessarily an instance of this exact class.
    A compatible type can be defined separately, or this one reused directly.
    """
    __slots__ = ("url", "method", "headers", "body")

    def __init__(self, url: str, method: str, headers: dict, body: bytes):
        self.url = url
        self.method = method
        self.headers = headers
        self.body = body

    def __repr__(self):
        return (f"HttpRequest(method={self.method!r}, url={self.url!r}, "
                f"body_len={len(self.body)})")


class HttpResponse:
    """The answer a custom resolver returns to the SDK.

    Attributes:
        status: HTTP status code. Only 200 is treated as success; any
            other code surfaces as a typed C2paError.
        body: Response body bytes.

    Reference shape only:
    c2pa accepts any object exposing these two attributes,
    not necessarily an instance of this exact class.
    """
    __slots__ = ("status", "body")

    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self.body = body

    def __repr__(self):
        return (f"HttpResponse(status={self.status}, "
                f"body_len={len(self.body or b'')})")


class HttpResolver(ABC):
    """Optional base class for custom HTTP resolvers.

    Attach an instance via ContextBuilder.with_resolver() or the
    Context(resolver=...) constructor kwarg.
    """

    @abstractmethod
    def resolve(self, request: HttpRequest) -> HttpResponse:
        """Perform the request.

        Raising instead marks the request as a hard failure, which
        surfaces as a typed C2paError.
        """
        raise NotImplementedError


# The resolvers implemented here are classes that hold their own config in
# __init__ and never capture a Context, Reader, or Builder in a closure.
# This avoids reference-cycles and lifetime issues.
# It also means resolve() never reaches for a mutable global.


class TtlLruCache:
    """A small LRU cache whose entries also expire after a TTL."""

    def __init__(self, max_items=100, ttl_seconds=120.0):
        self._max_items = int(max_items)
        self._ttl = float(ttl_seconds)
        self._entries = collections.OrderedDict()  # key -> (expiry, value)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > time.monotonic():
                self._entries.move_to_end(key)
                self.hits += 1
                return entry[1]
            if entry is not None:
                del self._entries[key]
            self.misses += 1
            return None

    def put(self, key, value):
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = (time.monotonic() + self._ttl, value)
            while len(self._entries) > self._max_items:
                self._entries.popitem(last=False)


class CachingHttpResolver(HttpResolver):
    """An HTTP resolver with a response cache and bounded retries.

    Caching policy: only GETs `_is_safe_to_cache` positively clears,
    answered with 200, are cached. POSTs, errors, and anything not
    positively cleared are never cached (see `_is_safe_to_cache`).

    Retry policy: 429/503 retried up to max_retries, honoring a capped
    Retry-After or backing off exponentially. Any other status is final.
    Transport errors raise, marking a hard failure.
    """

    def __init__(self, cache=None, timeout=10.0, max_retries=3,
                 backoff_seconds=0.5, max_retry_after=10.0):
        # Capture config here
        self.cache = cache if cache is not None else TtlLruCache()
        self._timeout = timeout
        self._max_retries = int(max_retries)
        self._backoff = float(backoff_seconds)
        self._max_retry_after = float(max_retry_after)

    def resolve(self, request):
        _reject_non_http(request.url)
        cacheable = _is_safe_to_cache(request)
        if cacheable:
            cached = self.cache.get(request.url)
            if cached is not None:
                return HttpResponse(cached[0], cached[1])

        status, body = self._fetch_with_retries(request)
        if cacheable and status == 200:
            self.cache.put(request.url, (status, body))
        return HttpResponse(status, body)

    def _fetch_with_retries(self, request):
        data = request.body or None
        for attempt in range(self._max_retries + 1):
            req = urllib.request.Request(
                request.url,
                data=data,
                method=request.method,
                headers=request.headers)
            try:
                with urllib.request.urlopen(
                        req, timeout=self._timeout) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                retryable = e.code in (429, 503)
                if not retryable or attempt == self._max_retries:
                    # Pass the status back so the SDK can report it.
                    return e.code, e.read()
                delay = self._retry_delay(e, attempt)
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _retry_delay(self, error, attempt):
        retry_after = error.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), self._max_retry_after)
            except ValueError:
                pass
        return self._backoff * (2 ** attempt)


class AlwaysFailResolver(HttpResolver):
    """Answers every request with a fixed status. Needs no network."""

    def __init__(self, status):
        self._status = status

    def resolve(self, request):
        return HttpResponse(self._status, b"")


class DebugHttpResolver(HttpResolver):
    """Logs every SDK HTTP request and response status.
    The actual transfer is delegated to urllib.
    """

    def __init__(self, timeout=10.0):
        self._timeout = timeout
        self.requests = []

    def resolve(self, request):
        _reject_non_http(request.url)
        self.requests.append((request.method, request.url))

        data = request.body or None
        req = urllib.request.Request(
            request.url,
            data=data,
            method=request.method,
            headers=request.headers)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return HttpResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            # A 4xx/5xx is still a response.
            # Pass the status through and let the SDK turn it
            # into its own typed error.
            # Only 200 is treated as success.
            return HttpResponse(e.code, e.read())
