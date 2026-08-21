"""Unit tier: the hunting configuration contract (#151 / #84 T1).

The test-executor pod's two roles (`pod_runner`, `pod_triager`) join
`HUNTING_ROLES` as `session`/`high` (D84-1) - one model key per agent, the
HUNTING_ROLES precedent, never app-boot ROLES (operator ruling 2026-08-06).
These tests pin the registry entries and the env-var contract.
"""
from __future__ import annotations

from polymerhus.app.llm import providers as P


def test_pod_roles_registered_in_hunting_roles():
    """`pod_runner` / `pod_triager` are HUNTING_ROLES entries - each `session` +
    `high`, absent from the app-boot `ROLES` (off-app-boot, like every hunting
    role)."""
    ids = {r.role_id for r in P.HUNTING_ROLES}
    assert "pod_runner" in ids and "pod_triager" in ids
    assert not (ids & {r.role_id for r in P.ROLES})  # off app boot
    assert P.role_record("pod_runner").agent_mode == "session"
    assert P.role_record("pod_runner").thinking == "high"
    assert P.role_record("pod_triager").agent_mode == "session"
    assert P.role_record("pod_triager").thinking == "high"


def test_pod_role_model_keys_are_distinct():
    """One env var per pod agent (one model per agent, the HUNTING_ROLES
    precedent) - actor (probe/execute) and critic (classify/mine) are distinct
    cognitive jobs with independent tuning surfaces. A future many-to-one share
    stays a one-line `model_key` edit (D84-1)."""
    assert P.role_record("pod_runner").model_key == "LLM_MODEL_POD_RUNNER"
    assert P.role_record("pod_triager").model_key == "LLM_MODEL_POD_TRIAGER"
    assert P.role_record("pod_runner").model_key != P.role_record("pod_triager").model_key