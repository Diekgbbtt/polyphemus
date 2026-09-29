"""Which HOST does the governor match a policy against? (#238 live fix, a2)

The verdict `docs/superpowers/notes/2026-09-25-live-concurrency-verdict.md`
names this ring: in mitmproxy's transparent mode `request.host` is the
CONNECTION's IP, while `request.pretty_host` is the name the client asked for -
the name every `traffic-policy/v2` `host_patterns` speaks.
"""
from __future__ import annotations

import asyncio

from kali.http_history.addon import HttpHistoryAddon
from kali.http_history.governor import (
    GovernorDecision,
    GovernorPermit,
    TargetGovernor,
    host_matches,
)
from kali.http_history.models import CaptureContext
from kali.http_history.registry import SourceRegistration, SourceRegistry
from tests.kali.fakes import FakeConnection, FakeFlow, FakeHeaders

_POLICY = {
    "target_key": "app.example.com",
    "host_patterns": ["app.example.com"],
    "rate_per_s": 2.0,
    "burst": 1,
    "max_concurrency": 1,
    "min_delay_ms": 500.0,
    "source": "measured-transition",
    "version": "traffic-policy/v2",
}


class TransparentRequest:
    """A mitmproxy-shaped request in TRANSPARENT mode.

    `host` is the inferred connection address (an IP); `host_header` - and so
    `pretty_host` - is the name the client actually asked for, exactly as
    mitmproxy documents.
    """

    def __init__(self, *, host: str, host_header: str, path: str = "/x"):
        self.host = host
        self.host_header = host_header
        self.url = f"http://{host}{path}"
        self.pretty_url = f"http://{host_header}{path}"
        self.method = "GET"
        self.http_version = "HTTP/1.1"
        self.headers = FakeHeaders([("Host", host_header)])
        self.content = b""

    @property
    def pretty_host(self) -> str:
        return self.host_header


class _Resolver:
    def __init__(self, registration):
        self.registration = registration

    def lookup(self, source_ip):
        return (self.registration.project_id, self.registration.capture_context)

    def lookup_registration(self, source_ip):
        return self.registration


class _RecordingGovernor:
    """Records every admission request AND mirrors the real host predicate, so
    a double can never make an uncovered host look governed."""

    def __init__(self):
        self.calls: list = []

    async def acquire(self, project_id, *, traffic_policy, context=None):
        self.calls.append((project_id, traffic_policy, context))
        request_host = context.request_host if context is not None else None
        if not host_matches(request_host, traffic_policy.get("host_patterns")):
            return GovernorDecision(False)
        return GovernorDecision(
            True, 0.0, traffic_policy["target_key"],
            GovernorPermit(key=(project_id, traffic_policy["target_key"]),
                           permit_id="perm-1"),
        )

    async def release(self, permit):
        return None


def _flow(*, host: str, host_header: str) -> FakeFlow:
    return FakeFlow(
        request=TransparentRequest(host=host, host_header=host_header),
        client_conn=FakeConnection(peername=("172.30.0.2", 4444)),
    )


def _addon(tmp_path, governor, *, policy=_POLICY):
    return HttpHistoryAddon(
        root=tmp_path,
        resolver=_Resolver(
            SourceRegistration("proj-1", CaptureContext(exec_id="e1"), policy)
        ),
        governor=governor,
    )


def test_a_transparent_flow_is_governed_by_the_host_the_client_asked_for(tmp_path):
    governor = _RecordingGovernor()
    addon = _addon(tmp_path, governor)

    asyncio.run(
        addon.request(_flow(host="172.29.0.9", host_header="app.example.com"))
    )

    assert len(governor.calls) == 1, (
        "the armed policy must match the requested host, not the transparent IP"
    )
    _, _, context = governor.calls[0]
    assert context.request_host == "app.example.com"
    assert addon.status()["governed"] == 1
    assert addon.status()["ungoverned_host"] == 0


def test_a_genuinely_uncovered_host_is_disclosed_never_silent(tmp_path):
    """An armed lease whose flow is for another host is not this policy's
    business - but it must be COUNTED and NAMED, never dropped in silence."""
    governor = _RecordingGovernor()
    addon = _addon(tmp_path, governor)

    asyncio.run(
        addon.request(_flow(host="172.29.0.9", host_header="other.example.com"))
    )

    assert len(governor.calls) == 1
    assert governor.calls[0][2].request_host == "other.example.com"
    status = addon.status()
    assert status["governed"] == 0
    assert status["ungoverned_host"] == 1
    assert status["last_ungoverned_host"] == "other.example.com"


def test_a_legacy_capture_only_lease_is_never_counted_as_ungoverned(tmp_path):
    governor = _RecordingGovernor()
    addon = _addon(tmp_path, governor, policy=None)

    asyncio.run(
        addon.request(_flow(host="172.29.0.9", host_header="app.example.com"))
    )

    status = addon.status()
    assert status["ungoverned_host"] == 0
    assert status["governed"] == 0


def test_the_production_entry_injects_the_policy_aware_registry():
    """(a2) sub-case 2: the shipped entry must pass the SQLite registry itself
    as the addon resolver - a resolver without `lookup_registration` silently
    disarms governance for every flow.

    Pinned statically (the deployment-test precedent in this tier): the unit
    image has no mitmproxy (`addon_entry` imports it at module scope; the proxy
    lives in `/opt/mitmproxy-env` inside the kali image), so the wiring is
    asserted on the source and the resolver's own contract.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "kali" / "http_history" / "addon_entry.py"
    ).read_text(encoding="utf-8")

    assert "resolver=registry" in source
    assert hasattr(SourceRegistry, "lookup_registration")


def test_a_real_registry_lease_governs_the_matching_host(tmp_path):
    """The registry contract end to end: a lease armed in the shared SQLite
    registry governs a transparent flow to the policy's host - through the REAL
    governor, so the admission is a real permit, not a double's verdict."""
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register(
        "172.30.0.2", "proj-1", CaptureContext(exec_id="e1"), traffic_policy=_POLICY
    )
    governor = TargetGovernor()
    addon = HttpHistoryAddon(
        root=tmp_path / "data", resolver=registry, governor=governor
    )

    asyncio.run(
        addon.request(_flow(host="172.29.0.9", host_header="app.example.com"))
    )

    registry.close()
    assert addon.status()["governed"] == 1
    assert governor.status()["admitted"] == 1
    assert governor.status()["peak_inflight"] == 1
