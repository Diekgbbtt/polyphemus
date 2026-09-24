"""E2E-ONLY mitmdump entry point: the production addon with a governor that raises.

The adversarial regression "a governor exception must produce ZERO target
egress" needs a Kali whose governor actually throws. Production has no fault
switch for that - by design: a switch would be a second way to arm the failure
the feature exists to prevent. So the fault lives HERE, in the test tier:

* the PRODUCTION addon is imported and used unchanged
  (`kali.http_history.addon.HttpHistoryAddon` via the production
  `addon_entry.build_addons`);
* only the governor is replaced, by one whose `acquire` raises;
* the refusal adapter is the production one (a local 503 with the refusal
  header), so the failure path under test is the shipped one.

Compose runs it by pointing `KALI_HTTP_ADDON_ENTRY` at this file for the
`kali-failing-governor` service only. No production module imports this file.
"""
from __future__ import annotations

from kali.http_history.addon_entry import (
    build_addons as _production_build_addons,
)
from kali.http_history.addon_entry import mitmproxy_refuse_flow


class ExplodingGovernor:
    """A governor that fails on the first acquire - the "enforcement is broken
    while a policy is armed" state. It answers the same surface as the real
    `TargetGovernor`, so the addon CANNOT tell them apart."""

    def __init__(self, *args, **kwargs) -> None:
        self.acquires = 0
        self.releases: list = []

    async def acquire(self, project_id, *, traffic_policy, context=None):
        self.acquires += 1
        raise RuntimeError("e2e exploding governor: enforcement is unavailable")

    async def release(self, permit) -> None:
        self.releases.append(permit)

    def status(self) -> dict:
        return {"buckets": 0, "keys": [], "admitted": 0, "waited_s": 0.0,
                "inflight": 0, "duplicate_releases": 0, "e2e": "exploding"}


def build_addons() -> list:
    """The production addons, with the exploding governor injected."""
    return _production_build_addons(
        governor_factory=ExplodingGovernor,
        refusal_factory=mitmproxy_refuse_flow,
    )


addons = build_addons()
