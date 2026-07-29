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


class HttpRequest:
    """An HTTP request the SDK asks a custom resolver to perform.

    Attributes:
        url: Absolute request URL.
        method: HTTP method ("GET", "POST", ...).
        headers: Request headers as a dict. Names are lowercased by the
            native layer; when a header repeats, the last value wins.
        body: Request body bytes (b"" when there is none). Timestamp
            requests POST a body; manifest fetches send none.

    Reference shape only:
    c2pa hands your resolve() a duck-typed object with these same four attributes,
    not necessarily an instance of this exact class.
    Define your own compatible type, or just use this one.
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
        status: HTTP status code. Remote manifest fetches only accept 200;
            any other code surfaces as a typed C2paError.
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

    Caching policy:
    - Only read GET requests answered with 200 are cached.
    - POSTs (timestamp requests) and error responses are not.

    Retry policy: 429 and 503 are retried up to max_retries times,
    honoring a capped Retry-After when the header is present,
    and otherwise backing off exponentially.
    Any other status is final and is passed through to the SDK.
    Transport errors raise, which marks a hard failure.
    """

    def __init__(self, cache=None, timeout=10.0, max_retries=3,
                 backoff_seconds=0.5, max_retry_after=10.0):
        self.cache = cache if cache is not None else TtlLruCache()
        self._timeout = timeout
        self._max_retries = int(max_retries)
        self._backoff = float(backoff_seconds)
        self._max_retry_after = float(max_retry_after)

    def resolve(self, request):
        _reject_non_http(request.url)
        cacheable = request.method.upper() == "GET"
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

        # Timestamp requests POST a body, manifest fetches send none.
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
            # Pass the status through and let the SDK turn it into its own typed error:
            # a remote manifest fetch only accepts 200 as marker the data was retrieved.
            return HttpResponse(e.code, e.read())
