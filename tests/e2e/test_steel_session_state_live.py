"""Live guard: state survives a Steel session teardown (#395).

E2E tier against the deployed local runtime. It fails loud when the endpoint
is unset, like the #359 reachability guard: a missing deployment is a coverage
failure, never a skip.

Run on the host that reaches the runtime and is on its allowlist:

    STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1 \
    .venv/bin/python -m pytest tests/e2e/test_steel_session_state_live.py -q -s
"""
from __future__ import annotations

import os
import uuid

import pytest

from polymerhus.app import steel_session_state as st
from polymerhus.app.steel_endpoint import ENV_VAR

COOKIE_NAME = "ph_e2e_state"


def test_cookie_state_survives_capture_store_release_and_restore(tmp_path):
    endpoint = os.environ.get(ENV_VAR, "").strip()
    if not endpoint:
        pytest.fail(
            f"{ENV_VAR} is required for the session-state guard. "
            "Set it to the deployed runtime (the CLI form, "
            "http://<host>:<port>/v1). This live test never skips: a missing "
            "endpoint is a coverage failure."
        )

    domain = f"{uuid.uuid4().hex[:8]}.target"
    context = {
        "cookies": [{"name": COOKIE_NAME, "value": "v1", "domain": domain, "path": "/"}]
    }
    created = st.create_session(context, base_url=endpoint)
    store = tmp_path / "steel-state.json"
    # teardown_with_state releases the first session even if the capture fails.
    torn = st.teardown_with_state(created["id"], store, base_url=endpoint)
    captured = torn["context"].get("cookies") or []
    assert any(c.get("name") == COOKIE_NAME for c in captured), torn

    restored = st.restore_session(store, base_url=endpoint)
    try:
        again = st.capture_session_context(restored["id"], base_url=endpoint)
        names = {c.get("name") for c in again.get("cookies") or []}
        assert COOKIE_NAME in names, again
    finally:
        st.release_session(restored["id"], base_url=endpoint)
