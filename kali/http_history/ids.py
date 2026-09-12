"""ULID generation with no third-party dependency.

A ULID is 128 bits rendered in Crockford base32: a 48-bit millisecond
timestamp followed by 80 bits of randomness. Within one process the random
component is monotonic so ids created in the same millisecond still sort in
creation order. Deliberately dependency-free: the mitmproxy addon runs in its
own Python 3.13 environment and must not need a shared ULID library.
"""
from __future__ import annotations

import os
import threading
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_BITS = 80
_RANDOM_MASK = (1 << _RANDOM_BITS) - 1
_TIME_MASK = (1 << 48) - 1

_lock = threading.Lock()
_last_ms = 0
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid() -> str:
    """Return a fresh, time-sortable 26-character ULID."""
    global _last_ms, _last_random
    with _lock:
        now_ms = int(time.time() * 1000)
        if now_ms > _last_ms:
            _last_ms = now_ms
            _last_random = int.from_bytes(os.urandom(10), "big")
        else:
            now_ms = _last_ms
            _last_random = (_last_random + 1) & _RANDOM_MASK
        return _encode(now_ms & _TIME_MASK, 10) + _encode(_last_random, 16)


def decode_timestamp_ms(value: str) -> int:
    """Decode the millisecond timestamp of a ULID (first 10 characters)."""
    timestamp = 0
    for char in value[:10]:
        timestamp = (timestamp << 5) | _CROCKFORD.index(char)
    return timestamp


def new_artifact_id() -> str:
    """A new immutable HTTP-artifact identifier: ``http_<ulid>``."""
    return f"http_{new_ulid()}"
