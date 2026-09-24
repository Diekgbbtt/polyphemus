"""The deterministic multi-posture target fixture (#238 follow-up, Task 8).

ONE application, instantiated once per posture as a separate Compose service.
Every number it produces is arithmetic - no internet target, no randomness:

* `RATE_FIXTURE_POSTURE` selects the behaviour (`no_limiter`, `high_limit`,
  `low_limit`, `false_bypass`, `burst_inconclusive`);
* `GET /health`   - liveness + the posture this instance runs;
* `POST /reset`   - clears counters/buckets and mints a GENERATION id;
* `GET /counters` - totals, per-route counts, header names with sensitive
  values redacted, current/peak in-flight, and the ordered event sequence;
* `GET /events`   - just the ordered event list;
* every other path - an ordinary target route (what auth, the probes, arjun and
  ffuf actually touch).

`/counters` and `/events` REQUIRE the current generation (query parameter), so a
stale read can never be mistaken for the current scenario's state.

Secret safety: the fixture never echoes a request header value in a body, and
every sensitive header (`authorization`, `cookie`, `proxy-authorization`,
`x-api-key`, `set-cookie`) plus any operator-configured secret value is replaced
by `<redacted>` before it is recorded.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal
from urllib.parse import parse_qs, urlsplit

LIMITED_PATH = "/canonical"
MAX_EVENTS = 5000

SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)


@dataclass(frozen=True)
class Posture:
    """One deterministic target posture. The route logic is SHARED; only these
    data differ, so a posture can never drift into its own code path."""

    name: str
    limit: bool
    rate_per_s: float = 1000.0
    jitter_s: float = 0.15
    #: "normalized" folds `/canonical/` onto `/canonical` (a normalization
    #: variant therefore does NOT bypass); "raw" gives each raw path its own
    #: bucket (a variant LOOKS like it bypasses).
    limiter_key: Literal["normalized", "raw"] = "normalized"
    #: When True, the FIRST request to a non-canonical path is accepted and the
    #: rest are refused - a bypass SHAPE whose independent repetition fails, so
    #: the evidence gate reads `no_bypass`.
    first_variant_free: bool = False
    #: When True, the limited route alternates accept/refuse deterministically,
    #: so no stable transition can be bracketed (`inconclusive`).
    alternate: bool = False


POSTURES: dict[str, Posture] = {
    "no_limiter": Posture("no_limiter", limit=False),
    "high_limit": Posture("high_limit", limit=True, rate_per_s=20.0),
    "low_limit": Posture("low_limit", limit=True, rate_per_s=1.0),
    "false_bypass": Posture(
        "false_bypass", limit=True, rate_per_s=1.0,
        limiter_key="raw", first_variant_free=True,
    ),
    "burst_inconclusive": Posture(
        "burst_inconclusive", limit=True, rate_per_s=1.0, alternate=True,
    ),
}


def posture_from_env(env: dict | None = None) -> Posture:
    env = os.environ if env is None else env
    name = str(env.get("RATE_FIXTURE_POSTURE", "no_limiter")).strip()
    if name not in POSTURES:
        raise ValueError(
            f"RATE_FIXTURE_POSTURE must be one of {sorted(POSTURES)}, got {name!r}"
        )
    return POSTURES[name]


def normalized_resource(path: str) -> str:
    """The resource the application serves: `/canonical/` and `/canonical` are
    the SAME resource (the route-normalization differential)."""
    return path.rstrip("/") or "/"


class LeakyBucket:
    """Capacity-1 leaky bucket: at most one accept per `1/rate - jitter` seconds,
    never accumulating credit, so it is deterministic under load."""

    def __init__(self, *, rate_per_s: float, jitter_s: float = 0.0,
                 clock=time.monotonic):
        self.rate_per_s = float(rate_per_s)
        self.min_interval_s = max(0.0, (1.0 / float(rate_per_s)) - float(jitter_s))
        self._clock = clock
        self._last_accepted: float | None = None

    def take(self) -> bool:
        now = self._clock()
        if self._last_accepted is not None and now - self._last_accepted < self.min_interval_s:
            return False
        self._last_accepted = now
        return True


@dataclass
class Counters:
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.generation = uuid.uuid4().hex[:12]
            self.requests = 0
            self.statuses: dict[str, int] = {}
            self.routes: dict[str, int] = {}
            self.headers: dict[str, str] = {}
            self.events: list[dict] = []
            self.in_flight = 0
            self.peak_in_flight = 0
            self._limited_attempts = 0

    # --- in-flight accounting -------------------------------------------------
    def enter(self) -> int:
        with self.lock:
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
            return self.in_flight

    def leave(self) -> None:
        with self.lock:
            self.in_flight = max(0, self.in_flight - 1)

    def record(self, path: str, status: int, headers: dict[str, str]) -> None:
        with self.lock:
            self.requests += 1
            self.statuses[str(status)] = self.statuses.get(str(status), 0) + 1
            self.routes[path] = self.routes.get(path, 0) + 1
            # `headers` already carries the redaction decision: sensitive names
            # map to `<redacted>`, every other value has configured secrets
            # scrubbed out of it.
            for name, value in headers.items():
                self.headers.setdefault(name, value)
            if len(self.events) < MAX_EVENTS:
                self.events.append({
                    "seq": len(self.events) + 1,
                    "monotonic_s": time.monotonic(),
                    "route": path,
                    "status": status,
                    "in_flight": self.in_flight,
                    "peak_in_flight": self.peak_in_flight,
                })

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "generation": self.generation,
                "requests": self.requests,
                "statuses": dict(self.statuses),
                "routes": dict(self.routes),
                "headers": dict(self.headers),
                "current_in_flight": self.in_flight,
                "max_in_flight": self.peak_in_flight,
                "events": [dict(event) for event in self.events],
            }


def redact(value: str, secrets: tuple[str, ...]) -> str:
    """Replace any configured secret VALUE with `<redacted>` (defence in depth on
    top of dropping sensitive header values entirely)."""
    for secret in secrets:
        if secret:
            value = value.replace(secret, "<redacted>")
    return value


def redacted_headers(headers, secrets: tuple[str, ...] = ()) -> dict[str, str]:
    """Header NAME -> `<redacted>` for sensitive names, else the value with any
    configured secret scrubbed. Values are never echoed in a response body."""
    out: dict[str, str] = {}
    for name, value in headers.items():
        key = str(name).lower()
        out[key] = "<redacted>" if key in SENSITIVE_HEADERS else redact(str(value), secrets)
    return out


class Target:
    """One posture instance: shared route logic, posture-driven limiting."""

    def __init__(self, posture: Posture, *, secrets: tuple[str, ...] = ()):
        self.posture = posture
        self.secrets = secrets
        self.counters = Counters()
        self._buckets: dict[str, LeakyBucket] = {}
        self._variant_seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def reset(self) -> str:
        self.counters.reset()
        with self._lock:
            self._buckets.clear()
            self._variant_seen.clear()
        return self.counters.generation

    def _key(self, path: str) -> str:
        if self.posture.limiter_key == "normalized":
            return normalized_resource(path)
        return path

    def admit(self, path: str) -> bool:
        """Whether this request is served (True) or refused 429 (False)."""
        if not self.posture.limit:
            return True
        key = self._key(path)
        if self.posture.limiter_key == "raw" and normalized_resource(path) == LIMITED_PATH:
            with self._lock:
                seen = self._variant_seen.get(key, 0)
                self._variant_seen[key] = seen + 1
            if seen == 0:
                # The bypass SHAPE: a first, unreproducible acceptance.
                return True
            return False
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = LeakyBucket(
                    rate_per_s=self.posture.rate_per_s,
                    jitter_s=self.posture.jitter_s,
                )
                self._buckets[key] = bucket
        if self.posture.alternate:
            with self._lock:
                self.counters._limited_attempts += 1
                attempt = self.counters._limited_attempts
            return attempt % 2 == 1
        return bucket.take()


def _body(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _make_handler(target: Target):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def _handle(self, _method: str) -> None:
            parts = urlsplit(self.path)
            path = parts.path or "/"
            query = parse_qs(parts.query)
            # Control endpoints BYPASS limiter and in-flight accounting: reading
            # the counters must never appear as target traffic (design 14).
            if path == "/health":
                self._send(200, {"ok": True, "posture": target.posture.name})
                return
            if path == "/reset":
                generation = target.reset()
                self._send(200, {"reset": True, "generation": generation})
                return
            if path in ("/counters", "/events"):
                self._read_state(path, query)
                return

            target.counters.enter()
            try:
                served = target.admit(path)
                status = 200 if served else 429
                self._record(path, status)
                if not served:
                    self._send(
                        429, {"error": "rate limited"},
                        extra_headers={
                            "Retry-After": "1",
                            "X-RateLimit-Limit": f"{target.posture.rate_per_s:g}",
                            "X-RateLimit-Remaining": "0",
                        },
                    )
                    return
                self._send(
                    200, {"route": path, "resource": normalized_resource(path)},
                    extra_headers={"X-RateLimit-Remaining": "1"}
                    if target.posture.limit else None,
                )
            finally:
                target.counters.leave()

        def _read_state(self, path: str, query: dict) -> None:
            snapshot = target.counters.snapshot()
            supplied = (query.get("generation") or [None])[0]
            if supplied != snapshot["generation"]:
                self._send(
                    409,
                    {
                        "error": "stale_generation" if supplied else "generation_required",
                        "generation": snapshot["generation"],
                    },
                )
                return
            if path == "/events":
                self._send(200, {"generation": snapshot["generation"],
                                 "events": snapshot["events"]})
            else:
                self._send(200, snapshot)

        def _record(self, path: str, status: int) -> None:
            headers = redacted_headers(dict(self.headers.items()), target.secrets)
            target.counters.record(path, status, headers)

        def _send(self, status: int, payload: dict, *,
                  extra_headers: dict | None = None) -> None:
            body = _body(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args) -> None:
            pass

    return Handler


def build_server(posture: Posture, *, host: str = "0.0.0.0", port: int = 80,
                 secrets: tuple[str, ...] = ()) -> ThreadingHTTPServer:
    """A ready-to-serve instance. The unit tier passes port 0 and reads
    `server.server_address[1]`; Compose passes the posture env and port 80."""
    return ThreadingHTTPServer((host, port), _make_handler(Target(posture, secrets=secrets)))


def main() -> None:
    posture = posture_from_env()
    secrets = tuple(
        value for value in os.environ.get("RATE_FIXTURE_SECRETS", "").split(",") if value
    )
    server = build_server(
        posture, port=int(os.environ.get("PORT", "80")), secrets=secrets
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
