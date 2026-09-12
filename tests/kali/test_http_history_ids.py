"""ULID artifact ids: opaque, time-sortable, unique, immutably prefixed."""
from __future__ import annotations

import re
import threading
import time

from kali.http_history.ids import decode_timestamp_ms, new_artifact_id, new_ulid

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def test_ulid_is_26_crockford_chars():
    value = new_ulid()
    assert len(value) == 26
    assert set(value) <= set(_CROCKFORD)


def test_artifact_id_has_http_prefix():
    assert re.fullmatch(r"http_[0-9A-HJKMNP-TV-Z]{26}", new_artifact_id())


def test_ulid_encodes_creation_time():
    before = int(time.time() * 1000)
    value = new_ulid()
    after = int(time.time() * 1000)
    assert before <= decode_timestamp_ms(value) <= after


def test_ulids_sort_by_creation_time():
    first = new_ulid()
    time.sleep(0.002)
    second = new_ulid()
    assert first < second


def test_ulids_are_unique_under_concurrency():
    seen: list[str] = []
    lock = threading.Lock()

    def worker():
        local = [new_ulid() for _ in range(200)]
        with lock:
            seen.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(seen) == 1600
    assert len(set(seen)) == 1600
