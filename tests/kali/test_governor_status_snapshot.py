"""The live governance counters must cross the proxy -> MCP process boundary.

`proxy_status()` is served by the MCP process, but the governor and the addon
both live in the mitmdump process, so the addon publishes a snapshot the
service reads back. This is the instrument the #238 live-concurrency diagnosis
reads (`addon.governed` against `governor.peak_inflight`).
"""
import json

from kali.http_history.addon import HttpHistoryAddon
from kali.http_history.governor import TargetGovernor


def test_runtime_counters_expose_the_governor_and_the_addon(tmp_path):
    addon = HttpHistoryAddon(root=tmp_path, governor=TargetGovernor())

    counters = addon.runtime_counters()

    assert counters["governor"]["peak_inflight"] == 0
    assert counters["governor"]["admitted"] == 0
    assert counters["governor"]["duplicate_releases"] == 0
    assert "governed" in counters["addon"]
    assert "governor_refusals" in counters["addon"]


def test_publish_writes_one_snapshot_file(tmp_path):
    addon = HttpHistoryAddon(root=tmp_path, governor=TargetGovernor())

    addon._publish_runtime_counters(force=True)

    payload = json.loads((tmp_path / "governor-status.json").read_text(encoding="utf-8"))
    assert payload["governor"]["buckets"] == 0
    assert "addon" in payload


def test_a_governor_without_a_status_surface_still_publishes(tmp_path):
    """Publishing is a DIAGNOSTIC: it must never raise into the request hook,
    because a raising hook would let the flow egress ungoverned."""

    class _NoStatusGovernor:
        pass

    addon = HttpHistoryAddon(root=tmp_path, governor=_NoStatusGovernor())

    counters = addon.runtime_counters()
    assert counters["governor"] == {}

    addon._publish_runtime_counters(force=True)
    payload = json.loads((tmp_path / "governor-status.json").read_text(encoding="utf-8"))
    assert payload["governor"] == {}
    assert payload["addon"]["governed"] == 0


def test_an_unwritable_status_path_is_disclosed_not_raised(tmp_path):
    """A failing publish is counted and named, never propagated."""
    addon = HttpHistoryAddon(root=tmp_path / "missing" / "deeper", governor=None)
    (tmp_path / "missing").write_text("not a directory", encoding="utf-8")

    addon._publish_runtime_counters(force=True)

    assert addon.status()["governor_last_error"] == "status_publish_failed"
