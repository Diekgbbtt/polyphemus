"""C7-C11: the T2 sync CLI against the LIVE stack (#100, #105).

Runs `python -m polymerhus.app.llm.sync` inside the agent container (its
gateway's own management surface, inherited LITELLM_MASTER_KEY) and asserts
against the raw-source oracle (`gateway_stack.oracle_desired` - the D5/D9
join computed from the live catalog + /v1/models, never from the sync's
output).

The sync runs are the SEAM's own inputs: the live registered set is
recomputed and re-pushed by these tests, so the assertions hold regardless of
what state the bootstrap sync left behind. C9's idempotency and C11's
persistence make the runs self-verifying (a broken diff/push shows up red).

Skip gate: the whole module needs the agent container up (its 127.0.0.1:4000
is the only reachable gateway surface - ADR D1).
"""

import json

import httpx
import pytest

from polymerhus.app.llm.sync import _norm_value, _registered_model_id
from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j

skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")

# The snapshot pseudo-model (D9) - excluded from the desired set but present
# in the registered set.
SNAPSHOT_NAME = "__sync_snapshot__"


def _run_sync_in_container(env: dict | None = None):
    """Run the sync CLI inside the agent; returns (exit_code, stdout, stderr)."""
    result = gs.agent_python(
        "import subprocess, sys\n"
        "p = subprocess.run([sys.executable, '-m', 'polymerhus.app.llm.sync'],\n"
        "                   capture_output=True, text=True, timeout=300)\n"
        "print(p.returncode)\n"
        "print(p.stdout)\n"
        "print(p.stderr)\n",
        env=env,
    )
    assert result.returncode == 0, f"sync probe crashed: {result.stderr}"
    lines = result.stdout.splitlines()
    exit_code = int(lines[0])
    return exit_code, "\n".join(lines[1:])


def _live_registered_names() -> set[str]:
    return {entry.get("model_name") for entry in gs.model_info()
            if isinstance(entry, dict) and isinstance(entry.get("model_name"), str)}


def _snapshot_record():
    for entry in gs.model_info():
        if isinstance(entry, dict) and entry.get("model_name") == SNAPSHOT_NAME:
            return entry
    return None


# --- Management-API verbs driven in-container (C5''/C5'''/D3 surfaces) ------
# The convergence proof mutates the live registered set through the SAME
# management surface the sync uses: PATCH /model/{row_id}/update (sync.py
# update_model), POST /model/new, POST /model/delete, and GET /key/info. All
# run inside the agent (ADR D1: the proxy binds the container's loopback) with
# auth LITELLM_MASTER_KEY from the service env.

def _management_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """In-container httpx call against the gateway management surface (auth
    LITELLM_MASTER_KEY); returns (status, body). The generic sibling of
    gs.agent_http_get for the POST/PATCH verbs."""
    code = (
        "import httpx, json, os\n"
        f"url = {gs.GATEWAY_URL!r} + {path!r}\n"
        "key = os.environ.get('LITELLM_MASTER_KEY')\n"
        "headers = {'Authorization': f'Bearer {key}'} if key else {}\n"
        f"body = {body!r}\n"
        f"r = httpx.request({method!r}, url, json=body, headers=headers, timeout=15)\n"
        "print(r.status_code)\n"
        "print(r.text)\n"
    )
    result = gs.agent_python(code)
    if result.returncode != 0:
        raise RuntimeError(f"in-container {method} {path} failed: {result.stderr}")
    lines = result.stdout.strip().splitlines()
    status = int(lines[0])
    body_text = "\n".join(lines[1:])
    try:
        parsed = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        parsed = {"_raw": body_text}
    return status, parsed


def _patch_record(entry: dict, model_info: dict) -> None:
    """PATCH /model/{row_id}/update - refresh a registered row via the
    DB-backed endpoint with sync.py's update_model semantics: `model_info.id`
    MUST echo the row's `model_id` or the handler merges a fresh random uuid
    into the stored record (corrupting its identity). Used on the snapshot
    pseudo-model (whose litellm_params carry the unroutable marker, exactly as
    upsert_snapshot sends)."""
    row_id = _registered_model_id(entry)
    status, body = _management_request(
        "PATCH", f"/model/{row_id}/update",
        {"model_name": entry.get("model_name"),
         "litellm_params": entry.get("litellm_params") or {},
         "model_info": {**model_info, "id": row_id}})
    assert status == 200, f"PATCH /model/{row_id}/update answered HTTP {status}: {body}"


def _patch_live_record(model_name: str, field: str, value) -> None:
    """Corrupt one registered model record's model_info field via the
    DB-backed PATCH endpoint, keeping the record's routing params and
    re-asserting the provider's REAL api_key from the container env.

    /model/info strips `api_key` from litellm_params entirely, and the sync's
    diff ignores api_key, so a PATCH that omitted the key could clear the
    stored one without any later sync noticing (broken routing, invisible).
    The corruption therefore re-authors it from the container env."""
    provider = model_name.split("/", 1)[0]
    env_var = f"API_KEY_{provider.upper().replace('-', '_')}"
    code = (
        "import httpx, json, os\n"
        f"gateway = {gs.GATEWAY_URL!r}\n"
        "headers = {'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY']}\n"
        "entries = httpx.get(gateway + '/model/info', headers=headers, timeout=15).json()['data']\n"
        f"entry = next(e for e in entries if e.get('model_name') == {model_name!r})\n"
        "info = dict(entry.get('model_info') or {})\n"
        "row_id = info.get('id') or entry.get('id')\n"
        f"info[{field!r}] = {value!r}\n"
        "params = dict(entry.get('litellm_params') or {})\n"
        f"params['api_key'] = os.environ[{env_var!r}]\n"
        "body = {'model_name': entry['model_name'],\n"
        "        'litellm_params': params,\n"
        "        'model_info': info}\n"
        "body['model_info']['id'] = row_id\n"
        "r = httpx.request('PATCH', gateway + '/model/' + row_id + '/update',\n"
        "                  json=body, headers=headers, timeout=15)\n"
        "print(r.status_code)\n"
        "print(r.text)\n"
    )
    result = gs.agent_python(code)
    assert result.returncode == 0, f"in-container PATCH probe failed: {result.stderr}"
    lines = result.stdout.strip().splitlines()
    status = int(lines[0])
    assert status == 200, f"PATCH {model_name} answered HTTP {status}: {lines[1:]}"


def _add_record(model_name: str, litellm_params: dict, model_info: dict) -> None:
    """POST /model/new - inject a synthetic registered row."""
    status, body = _management_request(
        "POST", "/model/new",
        {"model_name": model_name,
         "litellm_params": litellm_params,
         "model_info": model_info})
    assert status == 200, f"POST /model/new answered HTTP {status}: {body}"


def _delete_record(row_id) -> None:
    """POST /model/delete - remove a registered row by id."""
    status, body = _management_request("POST", "/model/delete", {"id": row_id})
    assert status == 200, f"POST /model/delete answered HTTP {status}: {body}"


def _key_record(key: str) -> dict | None:
    """GET /key/info?key=... - the stored virtual-key record (D3), or None
    when the proxy holds no such key (404)."""
    status, body = _management_request("GET", f"/key/info?key={key}")
    if status == 404:
        return None
    assert status == 200, f"GET /key/info answered HTTP {status}: {body}"
    info = body.get("info") if isinstance(body, dict) else None
    assert isinstance(info, dict), f"GET /key/info returned no 'info' object: {body}"
    return info


# ---------------------------------------------------------------------------
# C7 - the exit-code contract (D9) ------------------------------------------
# ---------------------------------------------------------------------------

def test_c7a_sync_hard_without_master_key():
    """LITELLM_MASTER_KEY unset -> exit 1 (hard): the sync cannot authenticate
    and must NOT guess a gateway state. The registered set is untouched."""
    before = _live_registered_names()
    exit_code, output = _run_sync_in_container(
        env={"LITELLM_MASTER_KEY": ""})
    assert exit_code == 1, f"expected hard exit 1, got {exit_code}:\n{output}"
    assert "cannot authenticate" in output.lower()
    after = _live_registered_names()
    assert after == before, "a failed sync must not touch the registered set"


def test_c7b_sync_hard_on_management_api_failure():
    """A dead management surface (LLM_SYNC_GATEWAY_URL -> 127.0.0.1:1) is a
    hard failure (exit 1) - the gateway state is unknown after a partial push.
    The registered set is untouched."""
    before = _live_registered_names()
    exit_code, output = _run_sync_in_container(
        env={"LLM_SYNC_GATEWAY_URL": "http://127.0.0.1:1"})
    assert exit_code == 1, f"expected hard exit 1, got {exit_code}:\n{output}"
    after = _live_registered_names()
    assert after == before, "a failed sync must not touch the registered set"


# ---------------------------------------------------------------------------
# C8 - the registered set vs the raw-source oracle (D5/D9) -------------------
# ---------------------------------------------------------------------------

def test_c8_registered_set_equals_the_oracle():
    """The live registered `model_name` set EQUALS the D5/D9 join of the raw
    sources (both directions, exact string equality); every known record
    carries the three provenance keys; every record's authored capability
    fields equal the oracle's."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"sync failed (exit {exit_code}):\n{output}"

    desired = gs.oracle_desired()
    desired_names = {m.model_name for m in desired}
    registered = gs.model_info()
    live_names = {e.get("model_name") for e in registered
                  if isinstance(e, dict) and isinstance(e.get("model_name"), str)}
    live_names.discard(SNAPSHOT_NAME)

    assert live_names == desired_names, (
        f"registered set mismatch:\n  only live: {sorted(live_names - desired_names)}\n"
        f"  only desired: {sorted(desired_names - live_names)}")

    by_name = {m.model_name: m for m in desired}
    for entry in registered:
        name = entry.get("model_name")
        if name == SNAPSHOT_NAME or name is None:
            continue
        info = entry.get("model_info") or {}
        expected = by_name[name]
        if not expected.known:
            # Unknown model (on /v1/models, no registry entry): the sync pushes
            # ONLY the three provenance keys, staleness "unknown" (D9), and the
            # record MUST carry our provenance tag. litellm may MERGE its own
            # cost-map defaults into such a record at /model/info (observed on
            # opencode-go/hy3-preview 2026-08-18) - that enrichment is EXTERNAL
            # and bears no `capability_source` tag, so it is never trusted by
            # the reader (D5 Rule 1, as amended: an unknown model is low-tier
            # and never used, so filling capabilities is not required - no
            # litellm capability enrichment is treated as authored truth). We
            # therefore assert our authored provenance subset, not a byte-exact
            # provenance-only record, and confirm the record is tagged unknown.
            assert "capability_source" in info, (
                f"{name}: unknown-model record must carry a capability_source "
                f"tag (litellm may add untrusted default keys, but never a "
                f"provenance tag; got {sorted(info)})")
            assert "capability_synced_at" in info
            assert info.get("capability_staleness") == "unknown"
            continue
        # Known model: every authored key present with the oracle value
        # (capability_synced_at is volatile - excluded; litellm may MERGE its
        # own keys - Rule 1: we assert the authored subset, never the whole).
        assert "capability_source" in info
        assert "capability_synced_at" in info
        assert info.get("capability_staleness") == "fresh"
        for key, value in expected.model_info.items():
                if key == "capability_synced_at":
                    continue
                # JSON-normalized comparison (authored tuples come back as
                # lists from litellm's storage layer - _norm_value).
                assert _norm_value(info.get(key)) == _norm_value(value), (
                    f"{name}: authored {key} = {info.get(key)!r}, oracle says "
                    f"{value!r}")


def test_c8_snapshot_is_present_and_matches():
    """The last-known-good snapshot pseudo-model exists with the desired set's
    count and hash (D9) - the collapse check's baseline for the NEXT boot."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"sync failed (exit {exit_code}):\n{output}"
    snapshot = _snapshot_record()
    assert snapshot is not None, "the __sync_snapshot__ record must exist (D9)"
    info = snapshot.get("model_info") or {}
    desired = gs.oracle_desired()
    assert info.get("desired_count") == len(desired), (
        f"snapshot desired_count {info.get('desired_count')} != oracle "
        f"{len(desired)}")
    assert info.get("capability_source") == "https://models.dev/catalog.json"


# ---------------------------------------------------------------------------
# C9 - diffable-push idempotency (D9) ----------------------------------------
# ---------------------------------------------------------------------------

def test_c9_second_sync_is_a_noop():
    """Back-to-back syncs: the second run pushes ZERO adds/updates/deletes and
    leaves the registered set (and the snapshot) byte-identical."""
    exit_code, first = _run_sync_in_container()
    assert exit_code == 0, f"first sync failed (exit {exit_code}):\n{first}"
    registered_before = gs.model_info()
    snapshot_before = _snapshot_record()

    exit_code, second = _run_sync_in_container()
    assert exit_code == 0, f"second sync failed (exit {exit_code}):\n{second}"
    assert "0 add(s), 0 update(s), 0 delete(s)" in second, (
        f"second sync was not idle:\n{second}")

    registered_after = gs.model_info()
    assert registered_after == registered_before, (
        "a no-change re-run must leave the registered set byte-identical")
    assert _snapshot_record() == snapshot_before, (
        "a no-change re-run must leave the snapshot unchanged")


# ---------------------------------------------------------------------------
# C10 - the D11 reasoning surface on the live records ------------------------
# ---------------------------------------------------------------------------

def test_c10_reasoning_surface_matches_the_oracle_matrix():
    """Every registered known record's `reasoning_in_response` /
    `reasoning_field` equal the D11 matrix's verdict for that record (the
    oracle recomputes it from the raw catalog - interleaved shape). A record
    whose catalog shape carries neither interleaved nor reasoning carries
    NEITHER key."""
    desired = gs.oracle_desired()
    live = {e.get("model_name"): (e.get("model_info") or {})
            for e in gs.model_info() if isinstance(e, dict)}
    for model in desired:
        if not model.known:
            continue
        info = live.get(model.model_name, {})
        expected_reasoning = model.model_info.get("reasoning_in_response")
        expected_field = model.model_info.get("reasoning_field")
        if expected_reasoning is None:
            assert "reasoning_in_response" not in info and \
                "reasoning_field" not in info, (
                f"{model.model_name}: D11 matrix says NOT asserted - neither "
                f"key may be authored (got {sorted(info)}")
        else:
            assert info.get("reasoning_in_response") is expected_reasoning, (
                f"{model.model_name}: reasoning_in_response mismatch")
            if expected_field is None:
                assert "reasoning_field" not in info, (
                    f"{model.model_name}: interleaved-style profile must NOT "
                    f"author a reasoning_field (got {info.get('reasoning_field')!r})")
            else:
                assert info.get("reasoning_field") == expected_field, (
                    f"{model.model_name}: reasoning_field mismatch")


# ---------------------------------------------------------------------------
# C11 - STORE_MODEL_IN_DB persistence (D1) -----------------------------------
# ---------------------------------------------------------------------------

def test_c11_litellm_tables_hold_the_registered_set():
    """The gateway's dedicated postgres database carries the registered set
    under litellm's own tables (STORE_MODEL_IN_DB):
    `LiteLLM_ProxyModelTable` row count equals `/model/info` count, with the
    same model names. (DATABASE_URL - the gateway's own pointer, same postgres
    instance as the agent's POSTGRES_DSN but a dedicated database.)"""
    registered = gs.model_info()
    code = (
        "import os, json\n"
        "import psycopg\n"
        "with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5) as conn:\n"
        "    cur = conn.execute('SELECT model_name FROM \"LiteLLM_ProxyModelTable\"')\n"
        "    rows = [r[0] for r in cur.fetchall()]\n"
        "print(len(rows))\n"
        "print(json.dumps(sorted(rows)))\n"
    )
    result = gs.agent_python(code)
    assert result.returncode == 0, f"pg probe failed: {result.stderr}"
    lines = result.stdout.strip().splitlines()
    count = int(lines[0])
    names = set(json.loads("\n".join(lines[1:])))
    assert count == len(registered), (
        f"LiteLLM_ProxyModelTable rows {count} != /model/info records "
        f"{len(registered)}")
    live_names = {e.get("model_name") for e in registered
                  if isinstance(e, dict) and isinstance(e.get("model_name"), str)}
    assert names == live_names, (
        f"pg model_name set differs from /model/info:\n"
        f"  only pg: {sorted(names - live_names)}\n"
        f"  only /model/info: {sorted(live_names - names)}")


# ---------------------------------------------------------------------------
# C8 - the management-API verbs against a self-mutated live registered set ---
# ---------------------------------------------------------------------------
# Each test starts from a clean sync, mutates the registered set THROUGH the
# gateway management API (the exact shape an operator, or a corrupted row,
# would produce), re-runs the sync, asserts the verb fired, and restores the
# set to the converged state so the suite's other tests stay valid. Every test
# declares that mutation/restoration assumption in its docstring.

def test_c8_live_diff_update_converges_after_record_corruption():
    """C5'' (PATCH/update verb): corrupt one registered record's
    max_input_tokens via PATCH /model/{row_id}/update, then one re-run diffs
    "1 update(s)" and restores the field to the oracle value. ASSUMPTION: this
    test mutates the live gateway DB (one PATCH) and restores the converged
    set by re-running the sync."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"clean sync failed (exit {exit_code}):\n{output}"

    desired = gs.oracle_desired()
    by_name = {m.model_name: m for m in desired if m.known}
    target_name = "opencode-go/deepseek-v4-flash"
    if target_name not in by_name:
        target_name = sorted(by_name)[0]
    target = by_name[target_name]

    _patch_live_record(target_name, "max_input_tokens", 1)
    live = {e.get("model_name"): (e.get("model_info") or {})
            for e in gs.model_info()}
    assert live[target_name].get("max_input_tokens") == 1, "corruption did not land"

    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"convergence sync failed (exit {exit_code}):\n{output}"
    assert "1 update(s)" in output, f"expected exactly one update:\n{output}"
    assert "0 add(s)" in output and "0 delete(s)" in output, (
        f"the corruption must diff as a pure update:\n{output}")

    live = {e.get("model_name"): (e.get("model_info") or {})
            for e in gs.model_info()}
    for key, value in target.model_info.items():
        if key == "capability_synced_at":
            continue
        assert _norm_value(live[target_name].get(key)) == _norm_value(value), (
            f"{target_name}: authored {key} = {live[target_name].get(key)!r}, "
            f"oracle expects {value!r}")


def test_c8_live_diff_delete_removes_synthetic_model():
    """C5''' (delete verb): a synthetic model injected via POST /model/new
    (a name NOT in the desired set) is diffed as "1 delete(s)" and removed
    from /model/info by one re-run. ASSUMPTION: this test injects a synthetic
    registered row and removes it (via the sync's delete, force-removed in
    teardown if the delete did not fully happen) - the registered set is
    converged again at the end."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"clean sync failed (exit {exit_code}):\n{output}"
    fake_name = "polymerhus-e2e-delete-me"
    try:
        _add_record(fake_name,
                    {"model": "openai/polymerhus-e2e-delete-me",
                     "api_base": "https://opencode.ai/zen/v1",
                     "api_key": "sk-polymerhus-e2e"},
                    {"max_input_tokens": 1})
        assert fake_name in _live_registered_names(), "synthetic record did not land"

        exit_code, output = _run_sync_in_container()
        assert exit_code == 0, f"sync failed (exit {exit_code}):\n{output}"
        assert "1 delete(s)" in output, f"expected exactly one delete:\n{output}"
        assert "0 add(s)" in output and "0 update(s)" in output, (
            f"the synthetic must diff as a pure delete:\n{output}")
        assert fake_name not in _live_registered_names(), (
            "the synthetic record survived the diff")
    finally:
        for entry in gs.model_info():
            if entry.get("model_name") == fake_name:
                _delete_record(_registered_model_id(entry))


def test_c8_live_collapse_halts_when_snapshot_inflated():
    """C4' (genuine collapse, D9): inflate the __sync_snapshot__ record's
    desired_count far above the live count (5x) via PATCH, then the sync exits
    1 (hard collapse) and pushes nothing. The snapshot is restored to its true
    value (PATCHed back - a bare re-run would re-collapse against the inflated
    baseline) and a final clean sync confirms the suite is converged.
    ASSUMPTION: this test mutates the snapshot record and restores it before
    returning."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"clean sync failed (exit {exit_code}):\n{output}"
    snapshot = _snapshot_record()
    assert snapshot is not None, "the __sync_snapshot__ record must exist (D9)"
    info = snapshot.get("model_info") or {}
    real_count = info.get("desired_count")
    assert isinstance(real_count, int), \
        f"snapshot desired_count is not an int: {info!r}"

    _patch_record(snapshot, {**info, "desired_count": real_count * 5})
    inflated = _snapshot_record()
    assert inflated is not None and (inflated.get("model_info") or {}) \
        .get("desired_count") == real_count * 5, "inflated snapshot did not land"

    before = _live_registered_names()
    exit_code, output = _run_sync_in_container()
    assert exit_code == 1, f"expected hard collapse exit 1, got {exit_code}:\n{output}"
    assert "collapse" in output.lower(), f"exit 1 was not the collapse path:\n{output}"
    assert _live_registered_names() == before, \
        "a collapse must not push (D9 cold stop)"

    still_inflated = _snapshot_record()
    assert still_inflated is not None, "the snapshot record vanished"
    _patch_record(still_inflated, info)
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"restore sync failed (exit {exit_code}):\n{output}"
    assert "0 add(s), 0 update(s), 0 delete(s)" in output, (
        f"the restored set must be fully converged:\n{output}")


def test_c8_live_soft_source_failure_keeps_db_and_exits_2():
    """C0'/C1' (soft path, D9): a source failure must exit 2 and leave the
    registered set untouched. SKIPPED - the soft path cannot be forced purely
    via env inside the agent container. Verified 2026-08-18: the opencode zen
    `/v1/models` endpoints return HTTP 200 with the full list to a bogus
    bearer, so a wrong API_KEY_OPENCODE_GO never raises a SyncSourceError; and
    DEFAULT_REGISTRY_URL is a module constant, not env-overridable, so the
    catalog fetch cannot be broken by env either. The source seams
    (`fetch_catalog` / `fetch_provider_models`) are function-injection only;
    the CLI exposes no env knob to fail either source. Closing this live gap
    needs an injectable fetch seam (e.g. an LLM_SYNC_REGISTRY_URL override), a
    code change outside this test file. Do NOT fabricate a fake that edits
    source code."""
    pytest.skip(
        "cannot force a sync source failure via env alone: the zen /v1/models "
        "endpoints return 200 to a bogus key and DEFAULT_REGISTRY_URL is not "
        "env-overridable; the soft path needs an injectable fetch seam "
        "(LLM_SYNC_REGISTRY_URL or similar), a code change not made here")


def test_c8_live_virtual_key_provisioned_and_converges():
    """D3 C8 (the silent key path): each configured provider key exists as a
    virtual key scoped to its registered model_names (GET /key/info, keys read
    from the container env), and a SECOND clean sync leaves the scope
    unchanged - convergence to a no-op proves ensure_virtual_key is idempotent.
    ASSUMPTION: this test only runs clean syncs (no net mutation); the scope
    it asserts is the converged one."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"clean sync failed (exit {exit_code}):\n{output}"

    result = gs.agent_python(
        "import json, os\n"
        "keys = {v: os.environ.get(v) for v in ('API_KEY_OPENCODE', "
        "'API_KEY_OPENCODE_GO') if os.environ.get(v)}\n"
        "print(json.dumps(keys))\n")
    assert result.returncode == 0, f"env probe failed: {result.stderr}"
    keys = json.loads(result.stdout.strip().splitlines()[0])
    assert keys, "no provider keys in the agent container env"

    registered = {e.get("model_name") for e in gs.model_info()
                  if isinstance(e, dict) and isinstance(e.get("model_name"), str)}
    for env_var, key in keys.items():
        provider = env_var[len("API_KEY_"):].lower().replace("_", "-")
        scope = sorted(n for n in registered
                       if isinstance(n, str) and n.startswith(f"{provider}/"))
        info = _key_record(key)
        assert info is not None, (
            f"provider {provider} key is not a virtual key (D3): the client's "
            f"gateway-mode bearer would 401")
        assert sorted(info.get("models") or []) == scope, (
            f"{provider}: stored key scope {sorted(info.get('models') or [])} "
            f"!= registered names {scope}")

    exit_code, second = _run_sync_in_container()
    assert exit_code == 0, f"second sync failed (exit {exit_code}):\n{second}"
    assert "0 add(s), 0 update(s), 0 delete(s)" in second, (
        f"the converged re-run must be idle:\n{second}")
    for env_var, key in keys.items():
        provider = env_var[len("API_KEY_"):].lower().replace("_", "-")
        scope = sorted(n for n in registered
                       if isinstance(n, str) and n.startswith(f"{provider}/"))
        info = _key_record(key)
        assert info is not None and sorted(info.get("models") or []) == scope, (
            f"{provider}: key scope changed after a no-op sync - "
            f"ensure_virtual_key is not idempotent")


def test_c8_live_independent_oracle_value_checks():
    """A catalog-derived literal check against ONE live registered record
    (opencode-go/deepseek-v4-flash), computed inline from a fresh models.dev
    fetch - NOT via build_desired, so a self-referential mapping bug (a wrong
    join, a wrong unit conversion, a wrong registered name all reproducing
    themselves) cannot mask itself. The catalog's absolute values are
    hard-asserted; the per-token conversion and the provenance tag are derived
    inline and asserted against the live record. ASSUMPTION: read-only (one
    clean sync keeps the set converged; nothing is mutated)."""
    exit_code, output = _run_sync_in_container()
    assert exit_code == 0, f"clean sync failed (exit {exit_code}):\n{output}"

    with httpx.Client(timeout=60.0) as client:
        response = client.get(gs.DEFAULT_REGISTRY_URL)
        response.raise_for_status()
        catalog = response.json()

    record = catalog["providers"]["opencode-go"]["models"]["deepseek-v4-flash"]
    base = record.get("base_model")
    if isinstance(base, str) and base in catalog.get("models", {}):
        resolved = dict(catalog["models"][base])
        for key, value in record.items():
            if key in ("base_model", "base_model_omit"):
                continue
            if key in ("cost", "limit", "modalities") and isinstance(value, dict) \
                    and isinstance(resolved.get(key), dict):
                nested = dict(resolved[key])
                nested.update(value)
                resolved[key] = nested
            else:
                resolved[key] = value
    else:
        resolved = dict(record)

    limits = resolved.get("limit") or {}
    costs = resolved.get("cost") or {}
    interleaved = resolved.get("interleaved")

    # The catalog literals, hard-asserted so a silent upstream change surfaces
    # instead of silently re-baselining this guard.
    assert limits.get("context") == 1000000
    assert limits.get("output") == 384000
    assert costs.get("input") == 0.22
    assert costs.get("output") == 0.66
    assert costs.get("cache_read") == 0.007
    assert isinstance(interleaved, dict) \
        and interleaved.get("field") == "reasoning_content"

    expected_input = round(costs["input"] / 1_000_000, 12)
    expected_output = round(costs["output"] / 1_000_000, 12)
    expected_cache_read = round(costs["cache_read"] / 1_000_000, 12)

    matches = [e for e in gs.model_info()
               if e.get("model_name") == "opencode-go/deepseek-v4-flash"]
    assert matches, "opencode-go/deepseek-v4-flash is not registered live"
    info = matches[0].get("model_info") or {}
    assert info.get("max_input_tokens") == limits["context"]
    assert info.get("max_output_tokens") == limits["output"]
    assert info.get("input_cost_per_token") == expected_input
    assert info.get("output_cost_per_token") == expected_output
    assert info.get("input_cost_per_token_cache_read") == expected_cache_read
    assert info.get("reasoning_in_response") is True
    assert info.get("reasoning_field") == "reasoning_content"
    assert info.get("capability_source") == "models.dev/opencode-go/deepseek-v4-flash"
