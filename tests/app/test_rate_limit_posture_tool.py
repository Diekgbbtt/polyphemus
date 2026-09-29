"""The ONE read-only agent tool over the rate-limit posture bucket.

The four distinct outcomes are never collapsed, and the tool never raises into
the turn (fail-open); the store underneath stays fail-loud.
"""
import json

from polymerhus.app.rate_limit.store import RateLimitPostureStore
from polymerhus.app.rate_limit.tool import build_rate_limit_posture_tool
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.domain.rate_limit import RateProfile


def _store(tmp_path) -> RateLimitPostureStore:
    store = RateLimitPostureStore(root=tmp_path)
    store.write(
        "proj-1",
        RateProfile.conservative(
            "acme.com", ["acme.com"], rate_limit_safety_budget(), "fixture",
        ),
        "run-1",
    )
    return store


def test_resolve_reports_a_known_target(tmp_path):
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    result = tool.invoke({"command": "resolve", "host": "acme.com"})

    assert result["ok"] is True
    assert result["status"] == "known_target"
    assert result["posture"]["target_key"] == "acme.com"
    assert result["posture"]["advisory"] is True
    assert result["posture"]["fresh"] is True


def test_resolve_reports_an_unmeasured_host_with_the_conservative_default(tmp_path):
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    result = tool.invoke({"command": "resolve", "host": "api.acme.com"})

    assert result["ok"] is True
    assert result["status"] == "no_posture_for_host"
    assert result["assumed"]["rate_per_s"] == 1.0
    assert result["assumed"]["burst"] == 1
    assert result["assumed"]["max_concurrency"] == 1


def test_list_reports_no_postures_for_an_empty_project(tmp_path):
    tool = build_rate_limit_posture_tool(
        "proj-1", store=RateLimitPostureStore(root=tmp_path)
    )

    assert tool.invoke({"command": "list"})["status"] == "no_postures"


def test_an_unreadable_file_is_reported_never_absent(tmp_path):
    store = _store(tmp_path)
    (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").write_text(
        "::: not yaml :::", encoding="utf-8"
    )
    tool = build_rate_limit_posture_tool("proj-1", store=store)

    result = tool.invoke({"command": "resolve", "host": "acme.com"})

    assert result["ok"] is False
    assert result["status"] == "unreadable"


def test_the_tool_exposes_no_write_operation(tmp_path):
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    result = tool.invoke({"command": "get", "target": "acme.com"})
    assert result["ok"] is True  # read path works

    # There is no write command in the closed args schema: the schema itself is
    # the guarantee. Assert it here so a future widening fails loudly.
    assert set(tool.args_schema.model_fields) == {"command", "target", "host"}
    assert "write" not in str(tool.args_schema.model_fields["command"].annotation)


def test_a_raising_store_fails_open_never_into_the_turn(tmp_path):
    """The store is fail-LOUD; this adapter is the boundary that turns its
    failure into a legible answer, never a raise into the conversation."""

    class _Boom(RateLimitPostureStore):
        def list_targets(self, project_id):
            raise RuntimeError("the store exploded")

    tool = build_rate_limit_posture_tool("proj-1", store=_Boom(root=tmp_path))

    result = tool.invoke({"command": "list"})

    assert result["ok"] is False
    assert result["status"] == "store_unavailable"


def test_the_tool_returns_only_the_advisory_fields_never_secrets(tmp_path):
    """The posture carries no secrets by construction; this pins the rendered
    surface so a future widening (headers, credentials, raw evidence) reddens."""
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    posture = tool.invoke({"command": "get", "target": "acme.com"})["posture"]

    assert set(posture) == {
        "target_key", "outcome", "safe_rate_per_s", "burst", "max_concurrency",
        "host_patterns", "measured_at", "expires_at", "fresh", "source_run_id",
        "advisory",
    }
    blob = json.dumps(tool.invoke({"command": "resolve", "host": "acme.com"})).lower()
    for secret_shaped in ("authorization", "cookie", "password", "token", "header"):
        assert secret_shaped not in blob
