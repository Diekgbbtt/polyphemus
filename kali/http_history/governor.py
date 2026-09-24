"""Shared per-target egress governor: ONE token bucket per target.

The transparent proxy leases a namespace per concurrent execution, and every
lease carries the run's `TrafficPolicy` in the shared source registry. This
module is what makes that policy an *aggregate* budget: the bucket is keyed by
`(project_id, target_key)`, so twenty concurrent pods for one target consume
one allowance instead of twenty, while unrelated targets and projects never
block each other.

Determinism and non-blocking-ness are design properties, not test conveniences:
the monotonic clock and the async waiter are injected, the per-target lock is
ALWAYS released before a wait (a cancelled waiter can never wedge its target,
and a wait on one target can never delay another), and nothing here reads the
environment or performs I/O at import time.

The policy crossing this seam is the transport form of
`polymerhus.recon.domain.rate_limit.TrafficPolicy` (`traffic-policy/v1`). It is
validated here because Kali never imports the recon domain package: an invalid
or unknown-version policy is NOT enforced (the caller treats it as unarmed),
which is why the exec seam refuses before running when a policy it cannot
enforce is demanded.
"""
from __future__ import annotations

import asyncio
import fnmatch
import math
import time
from dataclasses import dataclass

#: The only policy version this governor understands. Single-sourced with the
#: recon contract by value: a mismatch is refused, never coerced.
TRAFFIC_POLICY_VERSION = "traffic-policy/v1"


@dataclass(frozen=True)
class GovernorDecision:
    """The outcome of one admission request.

    `governed=False` means this flow is NOT this policy's business (a foreign
    host, an invalid policy) and no token was involved. `governed=True` means a
    token was consumed, after waiting `waited_s` for it if the bucket was empty.
    """

    governed: bool
    waited_s: float = 0.0
    target_key: str = ""


@dataclass
class _Bucket:
    rate_per_s: float
    burst: int
    tokens: float
    last_refill: float

    def refill(self, now: float) -> None:
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate_per_s)
            self.last_refill = now

    def materially_differs(self, rate_per_s: float, burst: int) -> bool:
        return self.rate_per_s != rate_per_s or self.burst != burst


@dataclass(frozen=True)
class _Limits:
    target_key: str
    host_patterns: tuple[str, ...]
    rate_per_s: float
    burst: int
    max_concurrency: int
    min_delay_ms: float
    source: str


def _positive_float(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _non_negative_float(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _limits_from(policy) -> _Limits | None:
    """Parse a transport policy, or None when it cannot be enforced.

    Strict on purpose: an unknown version, a missing/blank `target_key`, a
    non-positive rate or burst, or a malformed host pattern means the governor
    has no defensible budget to enforce, so it must not pretend to have one.
    """
    if not isinstance(policy, dict):
        return None
    if policy.get("version") != TRAFFIC_POLICY_VERSION:
        return None
    target_key = policy.get("target_key")
    if not isinstance(target_key, str) or not target_key.strip():
        return None
    rate = _positive_float(policy.get("rate_per_s"))
    if rate is None:
        return None
    burst = policy.get("burst", 1)
    if isinstance(burst, bool) or not isinstance(burst, int) or burst < 1:
        return None
    concurrency = policy.get("max_concurrency", 1)
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        return None
    min_delay = _non_negative_float(policy.get("min_delay_ms", 0.0))
    if min_delay is None:
        return None
    raw_patterns = policy.get("host_patterns", [])
    if not isinstance(raw_patterns, (list, tuple)):
        return None
    patterns: list[str] = []
    for pattern in raw_patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            return None
        patterns.append(pattern.strip().lower())
    source = policy.get("source")
    return _Limits(
        target_key=target_key.strip(),
        host_patterns=tuple(patterns),
        rate_per_s=rate,
        burst=burst,
        max_concurrency=concurrency,
        min_delay_ms=min_delay,
        source=source if isinstance(source, str) else "",
    )


def validate_traffic_policy(policy) -> dict | None:
    """The canonical enforced form of a `traffic-policy/v1` payload, or None.

    The service stores this canonical dict in the registry (so a slightly
    differently-ordered or extra-keyed producer payload lands as one shape), and
    the addon only ever enforces what this function accepted.
    """
    limits = _limits_from(policy)
    if limits is None:
        return None
    return {
        "target_key": limits.target_key,
        "host_patterns": list(limits.host_patterns),
        "rate_per_s": limits.rate_per_s,
        "burst": limits.burst,
        "max_concurrency": limits.max_concurrency,
        "min_delay_ms": limits.min_delay_ms,
        "source": limits.source,
        "version": TRAFFIC_POLICY_VERSION,
    }


def host_matches(request_host: str | None, host_patterns) -> bool:
    """Whether a request host is this policy's business.

    An empty pattern list means "whatever this project sends through the
    governed namespace" (the policy is already per-target). A non-empty list is
    exact-match plus shell-style wildcards (`*.example.com`), and it never
    matches a host the caller could not name.
    """
    patterns = tuple(pattern.lower() for pattern in (host_patterns or ()))
    if not patterns:
        return True
    if not request_host:
        return False
    host = request_host.strip().lower()
    return any(fnmatch.fnmatchcase(host, pattern) for pattern in patterns)


class TargetGovernor:
    """The process-wide governor: one bucket and one lock per target.

    `acquire` never denies: an empty bucket means "wait for the refill", which
    is the only outcome that keeps the offered rate at the measured safe bound.
    Refusal (returncode 78, no runner call) is the exec seam's job - it happens
    BEFORE a command is allowed to run, when no namespace/healthy proxy exists
    to govern it at all.
    """

    def __init__(self, *, clock=None, sleeper=None):
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        # `_guard` protects the two dicts only, and is never held across an
        # await: a wait on one target must not delay another.
        self._guard = asyncio.Lock()
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._admitted = 0
        self._waited_s = 0.0

    async def acquire(
        self, project_id: str, policy, request_host: str | None = None
    ) -> GovernorDecision:
        limits = _limits_from(policy)
        if limits is None:
            return GovernorDecision(False)
        if not host_matches(request_host, limits.host_patterns):
            return GovernorDecision(False)
        key = (project_id or "", limits.target_key)
        lock = await self._lock_for(key)
        waited = 0.0
        while True:
            async with lock:
                bucket = await self._bucket_for(key, limits)
                now = self._clock()
                bucket.refill(now)
                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    self._admitted += 1
                    return GovernorDecision(True, waited, limits.target_key)
                wait = (1.0 - bucket.tokens) / bucket.rate_per_s
            # OUTSIDE the bucket lock: unrelated targets (and a cancelled
            # waiter's successor on this target) stay independent.
            await self._sleeper(wait)
            waited += wait
            self._waited_s += wait

    async def _lock_for(self, key: tuple[str, str]) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def _bucket_for(self, key: tuple[str, str], limits: _Limits) -> _Bucket:
        async with self._guard:
            bucket = self._buckets.get(key)
            now = self._clock()
            if bucket is None:
                bucket = _Bucket(
                    rate_per_s=limits.rate_per_s,
                    burst=limits.burst,
                    tokens=float(limits.burst),
                    last_refill=now,
                )
                self._buckets[key] = bucket
            elif bucket.materially_differs(limits.rate_per_s, limits.burst):
                # A material replacement never gifts the old allowance: leftover
                # tokens are clamped to the NEW burst, and the new rate applies
                # from this instant on.
                bucket = _Bucket(
                    rate_per_s=limits.rate_per_s,
                    burst=limits.burst,
                    tokens=min(bucket.tokens, float(limits.burst)),
                    last_refill=now,
                )
                self._buckets[key] = bucket
            return bucket

    def status(self) -> dict:
        return {
            "buckets": len(self._buckets),
            "keys": sorted(f"{project}/{target}" for project, target in self._buckets),
            "admitted": self._admitted,
            "waited_s": round(self._waited_s, 6),
        }
