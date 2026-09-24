"""Deterministic local target for the #238 live end-to-end gate.

No internet target is involved. This service is the whole "target" the rate
mapping measures, and every number it produces is arithmetic:

* ``GET /canonical``     - the canonical route. Guarded by a CAPACITY-1 LEAKY
                           BUCKET with a known rate (`RATE_PER_S`, plus a
                           documented scheduling tolerance): at most one
                           request per interval, no burst credit. A sustained
                           probe above the rate therefore produces a stable
                           refusal fingerprint: ``429`` + ``Retry-After`` +
                           ``X-RateLimit-Remaining: 0`` and a constant body.
                           The bucket is per RAW PATH, and the counter is
                           process-wide, so concurrent probes from several
                           leased namespaces share it (the aggregate-load
                           assertion).

                           Capacity 1 is deliberate. A bucket WITH burst credit
                           passes the mapper's own one-second boundary probe at
                           the refusal rate (that is what a burst is for), which
                           the classifier then reports - correctly - as an
                           `inconsistent` surface. The gate needs a limiter whose
                           sustained rate and short-probe rate agree.
* any other path        - served with ``200`` and counted but never limited.
                           ``GET /canonical/`` is the ROUTE-NORMALIZATION
                           variant: the application treats it as the same
                           resource (same normalized body), while the limiter -
                           which keys on the raw path - has its own fresh
                           bucket. That is exactly the differential the bypass
                           evidence gate needs: a variant that materially
                           changes limiter state without changing semantics.
* ``GET /counters``     - JSON counters + per-request timestamps, for the
                           aggregate assertions.
* ``GET /reset``        - clear the counters and refill every bucket.

The response body never echoes a request header and never carries a cookie or
credential, so nothing this fixture answers can leak into an artifact, a run
stat or a model prompt.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LIMITED_PATH = "/canonical"
MAX_TIMES = 5000


class LeakyBucket:
    """Capacity-1 leaky bucket with an injected clock (monotonic, seconds).

    `take()` accepts at most one request per `1/rate_per_s` seconds and never
    accumulates credit, so it is deterministic under load and does not depend on
    how long the previous experiment left it drained. `jitter_s` is the
    documented scheduling tolerance that keeps a correctly paced client (a
    Vegeta `-rate`) from being refused by millisecond noise.
    """

    def __init__(self, *, rate_per_s: float, jitter_s: float = 0.0, clock=time.monotonic):
        self.rate_per_s = float(rate_per_s)
        self.min_interval_s = max(0.0, (1.0 / float(rate_per_s)) - float(jitter_s))
        self._clock = clock
        self._last_accepted: float | None = None

    def take(self) -> bool:
        now = self._clock()
        if self._last_accepted is not None:
            if now - self._last_accepted < self.min_interval_s:
                return False
        self._last_accepted = now
        return True


class Counters:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.requests = 0
            self.statuses: dict[str, int] = {}
            self.routes: dict[str, int] = {}
            self.limited_accepted = 0
            self.limited_refused = 0
            self.times: list[float] = []

    def record(self, path: str, status: int, *, limited: bool) -> None:
        with self._lock:
            self.requests += 1
            self.statuses[str(status)] = self.statuses.get(str(status), 0) + 1
            self.routes[path] = self.routes.get(path, 0) + 1
            if limited:
                if status == 429:
                    self.limited_refused += 1
                else:
                    self.limited_accepted += 1
            if len(self.times) < MAX_TIMES:
                self.times.append(time.time())

    def snapshot(self) -> dict:
        with self._lock:
            times = list(self.times)
            return {
                "requests": self.requests,
                "statuses": dict(self.statuses),
                "routes": dict(self.routes),
                "limited_accepted": self.limited_accepted,
                "limited_refused": self.limited_refused,
                "first_at": times[0] if times else None,
                "last_at": times[-1] if times else None,
                "times": times,
            }


class Target:
    def __init__(self, *, rate_per_s: float, jitter_s: float = 0.0):
        self.counters = Counters()
        self._buckets: dict[str, LeakyBucket] = {}
        self._lock = threading.Lock()
        self.rate_per_s = rate_per_s
        self.jitter_s = jitter_s

    def bucket(self, path: str) -> LeakyBucket:
        with self._lock:
            bucket = self._buckets.get(path)
            if bucket is None:
                bucket = LeakyBucket(rate_per_s=self.rate_per_s, jitter_s=self.jitter_s)
                self._buckets[path] = bucket
            return bucket

    def reset(self) -> None:
        self.counters.reset()
        with self._lock:
            self._buckets.clear()


def normalized_resource(path: str) -> str:
    """The resource the application serves - the route-normalization variant's
    ``/canonical/`` and the canonical ``/canonical`` are the SAME resource."""
    trimmed = path.rstrip("/")
    return trimmed or "/"


def _body(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _make_handler(target: Target):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol name
            raw_path = urlsplit(self.path).path or "/"
            if raw_path == "/counters":
                self._send(200, target.counters.snapshot())
                return
            if raw_path == "/reset":
                target.reset()
                self._send(200, {"reset": True})
                return

            limited = raw_path == LIMITED_PATH
            if limited and not target.bucket(raw_path).take():
                target.counters.record(raw_path, 429, limited=True)
                body = _body({"error": "rate limited"})
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "1")
                self.send_header("X-RateLimit-Limit", f"{target.rate_per_s:g}")
                self.send_header("X-RateLimit-Remaining", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            target.counters.record(raw_path, 200, limited=limited)
            self._send(
                200,
                {"route": raw_path, "resource": normalized_resource(raw_path)},
                limited=limited,
            )

        def _send(self, status: int, payload: dict, *, limited: bool = False) -> None:
            body = _body(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if limited:
                self.send_header("X-RateLimit-Remaining", "1")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args) -> None:
            pass

    return Handler


def main() -> None:
    port = int(os.environ.get("PORT", "80"))
    rate_per_s = float(os.environ.get("RATE_PER_S", "1.0"))
    jitter_s = float(os.environ.get("RATE_JITTER_S", "0.15"))
    target = Target(rate_per_s=rate_per_s, jitter_s=jitter_s)
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(target))
    server.serve_forever()


if __name__ == "__main__":
    main()
