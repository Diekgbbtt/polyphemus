"""Unit tests for the sync pipeline (T2, #105).

The sync CLI (`polymerhus.app.llm.sync`, spawned as `python -m
polymerhus.app.llm.sync`) runs the D2/D9 pipeline fetch -> join -> map ->
validate -> diff -> push against the gateway management API, with BOTH sources
and the management API mocked - no live model, no live gateway, no DB
(acceptance criteria + CODING_STANDARD §10). The exit-code contract (0 ok /
1 hard collapse / 2 soft source failure) is the load-bearing handoff the T1
entrypoint (`gateway_entrypoint.py::_run_sync`) branches on.

All fixtures mirror the live `https://models.dev/catalog.json` schema and the
litellm 1.96 management API (`GET /model/info`, `POST /model/new|update|delete`),
verified against the live feed and the litellm docs 2026-08-11.
"""

import pytest

from polymerhus.app.llm import sync_mapping as M
from polymerhus.app.llm import sync as S


# ---------------------------------------------------------------------------
# Fixtures: a catalog + /v1/models reality mirroring the live sources --------
# ---------------------------------------------------------------------------

CANONICAL_GPT4O = {
    "id": "openai/gpt-4o",
    "tool_call": True,
    "reasoning": False,
    "structured_output": True,
    "limit": {"context": 128000, "output": 16384},
    "cost": {"input": 2.5, "output": 10.0, "cache_read": 2.5, "cache_write": 10.0},
    "modalities": {"input": ["text", "image"], "output": ["text"]},
}

CATALOG = {
    "providers": {
        "opencode": {
            "id": "opencode",
            "api": "https://opencode.ai/zen/v1",
            "models": {
                "deepseek-v4-flash-free": {
                    "id": "deepseek-v4-flash-free",
                    "tool_call": True,
                    "reasoning": True,
                    "interleaved": {"field": "reasoning_content"},
                    "limit": {"context": 128000, "output": 32768},
                    "cost": {"input": 0.14, "output": 0.28,
                             "cache_read": 0.0028, "cache_write": 0.0},
                    "modalities": {"input": ["text"], "output": ["text"]},
                    "structured_output": True,
                    "open_weights": True,
                },
            },
        },
        "openai": {
            "id": "openai",
            "api": "https://api.openai.com/v1",
            "models": {
                "gpt-4o": dict(CANONICAL_GPT4O),
                # Inheritance case (Rule 2): sparse override over the canonical.
                "gpt-4o-2024-08-06": {
                    "id": "gpt-4o-2024-08-06",
                    "base_model": "openai/gpt-4o",
                    "cost": {"input": 1.25},
                },
            },
        },
    },
    "models": {"openai/gpt-4o": CANONICAL_GPT4O},
}

PROVIDER_MODEL_IDS = {
    "opencode": {"deepseek-v4-flash-free", "deepseek-v4-pro"},  # second = unknown
    "openai": {"gpt-4o", "gpt-4o-2024-08-06"},
}

SYNCED_AT = "2026-08-11T12:00:00+00:00"


def _default_run_args(**kw):
    args = dict(
        fetch_catalog=lambda: CATALOG,
        fetch_provider_models=lambda provider, api_key: PROVIDER_MODEL_IDS[provider],
        gateway=FakeGateway(),
        providers={"opencode": "https://opencode.ai/zen/v1",
                   "openai": "https://api.openai.com/v1"},
        read_api_key=lambda provider: {"opencode": "sk-opencode-key",
                                       "openai": "sk-openai-key"}[provider],
        synced_at=SYNCED_AT,
    )
    args.update(kw)
    return args


class FakeGateway:
    """A recording stand-in for the gateway management API client."""

    def __init__(self, registered=None, keys=None):
        self.registered = [dict(r) for r in (registered or [])]
        self.calls: list[tuple] = []
        self._keys: dict[str, list[str]] = {k: list(v) for k, v in (keys or {}).items()}

    def list_models(self):
        return [dict(r) for r in self.registered]

    def add_model(self, model_name, litellm_params, model_info):
        self.calls.append(("add", model_name, litellm_params, model_info))
        self.registered.append({"model_name": model_name,
                                "litellm_params": dict(litellm_params),
                                "model_info": dict(model_info),
                                "id": 100 + len(self.registered)})

    def update_model(self, row_id, model_name, litellm_params, model_info):
        self.calls.append(("update", row_id, model_name, litellm_params, model_info))
        for r in self.registered:
            if r["id"] == row_id:
                r.update(litellm_params=dict(litellm_params),
                         model_info=dict(model_info))

    def delete_model(self, row_id):
        self.calls.append(("delete", row_id))
        self.registered = [r for r in self.registered if r["id"] != row_id]

    def upsert_snapshot(self, model_info):
        self.calls.append(("snapshot", model_info))
        for r in self.registered:
            if r["model_name"] == S.SNAPSHOT_MODEL_NAME:
                r["model_info"] = dict(model_info)
                return True
        self.registered.append({"model_name": S.SNAPSHOT_MODEL_NAME,
                                "model_info": dict(model_info),
                                "id": 999})
        return True

    def ensure_virtual_key(self, key, models):
        models = sorted(models)
        if self._keys.get(key) == models:
            return
        self._keys[key] = models
        self.calls.append(("key", key, models))


# ---------------------------------------------------------------------------
# Exit-code contract (D9, the T1 handoff) ------------------------------------
# ---------------------------------------------------------------------------

def test_exit_codes_are_the_d9_contract():
    assert S.SYNC_OK == 0
    assert S.SYNC_HARD == 1
    assert S.SYNC_SOFT == 2


# ---------------------------------------------------------------------------
# Happy path: fetch -> join -> map -> validate -> diff -> push -> snapshot ---
# ---------------------------------------------------------------------------

def test_happy_path_pushes_adds_and_snapshot():
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    kinds = [c[0] for c in gw.calls]
    assert kinds == ["add", "add", "add", "add", "key", "key", "snapshot"]
    added = {c[1] for c in gw.calls if c[0] == "add"}
    assert added == {"opencode/deepseek-v4-flash-free",
                     "opencode/deepseek-v4-pro",
                     "openai/gpt-4o",
                     "openai/gpt-4o-2024-08-06"}


def test_happy_path_known_record_has_full_provenance_and_mapping():
    gw = FakeGateway()
    S.run_sync(**_default_run_args(gateway=gw))
    _, name, params, info = next(c for c in gw.calls
                                 if c[0] == "add" and c[1] == "opencode/deepseek-v4-flash-free")
    # Zen strip in gateway mode: the openai/ ROUTING prefix + bare zen wire id
    # (litellm strips the prefix, the zen gateway sees the bare id), zen
    # api_base, and the upstream api_key (masked by litellm in /model/info).
    assert params == {"model": "openai/deepseek-v4-flash-free",
                      "api_base": "https://opencode.ai/zen/v1",
                      "api_key": "sk-opencode-key"}
    assert info["max_input_tokens"] == 128000
    assert info["max_output_tokens"] == 32768
    assert info["input_cost_per_token"] == 0.00000014
    assert info["output_cost_per_token"] == 0.00000028
    assert info["input_cost_per_token_cache_read"] == 0.0000000028
    assert info["reasoning_in_response"] is True
    assert info["reasoning_field"] == "reasoning_content"
    assert info["capability_source"] == "models.dev/opencode/deepseek-v4-flash-free"
    assert info["capability_synced_at"] == SYNCED_AT
    assert info["capability_staleness"] == "fresh"


def test_happy_path_inheritance_resolved_before_push():
    # Rule 2: gpt-4o-2024-08-06 overrides only cost.input; context/output and
    # capabilities come from the canonical base - one global truth lands.
    gw = FakeGateway()
    S.run_sync(**_default_run_args(gateway=gw))
    _, name, params, info = next(c for c in gw.calls
                                 if c[0] == "add" and c[1] == "openai/gpt-4o-2024-08-06")
    assert info["max_input_tokens"] == 128000  # inherited
    assert info["max_output_tokens"] == 16384  # inherited
    assert info["supports_function_calling"] is True  # inherited
    assert info["input_cost_per_token"] == 0.00000125  # provider override wins
    assert info["output_cost_per_token"] == 0.00001  # inherited cost.output


def test_happy_path_unknown_model_registered_with_provenance_only(caplog):
    # deepseek-v4-pro exists on /v1/models but has no registry entry: it is
    # still registered for routing, with NO capability fields and a provenance
    # tag marking it unknown (D9). The gap is logged.
    gw = FakeGateway()
    with caplog.at_level("INFO"):
        S.run_sync(**_default_run_args(gateway=gw))
    _, name, params, info = next(c for c in gw.calls
                                 if c[0] == "add" and c[1] == "opencode/deepseek-v4-pro")
    assert params == {"model": "openai/deepseek-v4-pro",
                      "api_base": "https://opencode.ai/zen/v1",
                      "api_key": "sk-opencode-key"}
    assert info == {"capability_source": "unknown",
                    "capability_synced_at": SYNCED_AT,
                    "capability_staleness": "unknown"}
    assert any("deepseek-v4-pro" in r.message for r in caplog.records), \
        "the unknown-model gap must be logged (D9)"


def test_happy_path_snapshot_persisted_with_count_and_hash():
    gw = FakeGateway()
    S.run_sync(**_default_run_args(gateway=gw))
    kind, info = gw.calls[-1]
    assert kind == "snapshot"
    assert info["desired_count"] == 4
    assert info["desired_hash"] == S.desired_hash(
        ["opencode/deepseek-v4-flash-free", "opencode/deepseek-v4-pro",
         "openai/gpt-4o", "openai/gpt-4o-2024-08-06"])


def test_desired_hash_is_stable_and_order_independent():
    a = S.desired_hash(["a/x", "b/y"])
    b = S.desired_hash(["b/y", "a/x"])
    assert a == b
    assert a != S.desired_hash(["a/x", "b/z"])


# ---------------------------------------------------------------------------
# Idempotent re-run: no source changes -> pushes nothing ---------------------
# ---------------------------------------------------------------------------

def _gateway_after_first_run():
    gw = FakeGateway()
    S.run_sync(**_default_run_args(gateway=gw))
    return FakeGateway(registered=gw.registered, keys=dict(gw._keys))


def test_second_run_with_no_changes_pushes_nothing():
    gw = _gateway_after_first_run()
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    assert gw.calls == [], f"a no-change re-run must push nothing, got {gw.calls}"


def test_second_run_with_changed_catalog_pushes_full_update_only():
    # One model's price changes: the re-run updates THAT record with the FULL
    # model_info (D9: never a partial merge), nothing else.
    gw = _gateway_after_first_run()
    catalog = dict(CATALOG)
    catalog["providers"]["opencode"]["models"]["deepseek-v4-flash-free"] = dict(
        CATALOG["providers"]["opencode"]["models"]["deepseek-v4-flash-free"],
        cost={"input": 0.28, "output": 0.56, "cache_read": 0.0056, "cache_write": 0.0})
    rc = S.run_sync(**_default_run_args(gateway=gw, fetch_catalog=lambda: catalog))
    assert rc == S.SYNC_OK
    kinds = [c[0] for c in gw.calls]
    assert kinds == ["update"]
    kind, row_id, name, params, info = gw.calls[0]
    assert name == "opencode/deepseek-v4-flash-free"
    assert info["input_cost_per_token"] == 0.00000028
    # Full authored model_info on update - not a patch of one field.
    assert info["max_input_tokens"] == 128000
    assert info["reasoning_field"] == "reasoning_content"
    assert info["capability_source"] == "models.dev/opencode/deepseek-v4-flash-free"


def test_second_run_model_disappeared_from_existence_is_deleted():
    gw = _gateway_after_first_run()
    # openai/gpt-4o-2024-08-06 drops off /v1/models.
    ids = {"opencode": {"deepseek-v4-flash-free", "deepseek-v4-pro"},
           "openai": {"gpt-4o"}}
    rc = S.run_sync(**_default_run_args(gateway=gw,
                                        fetch_provider_models=lambda p, k: ids[p]))
    assert rc == S.SYNC_OK
    deletes = [c for c in gw.calls if c[0] == "delete"]
    assert len(deletes) == 1
    assert deletes[0][1] == 101  # the row id of openai/gpt-4o-2024-08-06
    # The snapshot pseudo-model is NEVER deleted by the diff.
    names = {r["model_name"] for r in gw.registered}
    assert S.SNAPSHOT_MODEL_NAME in names


# ---------------------------------------------------------------------------
# Source failure: soft, skip push, keep DB, exit 2 (D9) ----------------------
# ---------------------------------------------------------------------------

def test_registry_fetch_failure_is_soft(caplog):
    gw = FakeGateway()
    def boom():
        raise S.SyncSourceError("registry refused")
    rc = S.run_sync(**_default_run_args(gateway=gw, fetch_catalog=boom))
    assert rc == S.SYNC_SOFT
    assert gw.calls == [], "a soft source failure must NOT push (D9 keep DB)"
    assert any("source" in r.message.lower() for r in caplog.records)


def test_registry_parse_error_is_soft():
    gw = FakeGateway()
    def garbage():
        raise S.SyncSourceError("catalog.json is not valid JSON")
    rc = S.run_sync(**_default_run_args(gateway=gw, fetch_catalog=garbage))
    assert rc == S.SYNC_SOFT
    assert gw.calls == []


def test_provider_models_refusal_is_soft():
    gw = FakeGateway()
    def boom(provider, api_key):
        raise S.SyncSourceError(f"{provider} /v1/models refused")
    rc = S.run_sync(**_default_run_args(gateway=gw, fetch_provider_models=boom))
    assert rc == S.SYNC_SOFT
    assert gw.calls == []


def test_provider_without_configured_key_is_skipped_not_soft(caplog):
    # A provider with no API key is not configured (the app cannot route to it
    # either); skipping it is NOT a source failure. Documented in the module.
    gw = FakeGateway()
    def no_key(provider):
        return None if provider == "opencode" else "dummy-key"
    rc = S.run_sync(**_default_run_args(gateway=gw, read_api_key=no_key))
    assert rc == S.SYNC_OK
    added = {c[1] for c in gw.calls if c[0] == "add"}
    assert "opencode/deepseek-v4-flash-free" not in added
    assert "openai/gpt-4o" in added
    assert any("skipping" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Collapse: hard, abort push, exit 1 (D9 cold stop) --------------------------
# ---------------------------------------------------------------------------

def _snapshot_registered(count=4, names=None):
    names = names or ["openai/gpt-4o"]
    info = {"desired_count": count,
            "desired_hash": S.desired_hash(names),
            "capability_source": "models.dev",
            "capability_synced_at": SYNCED_AT,
            "capability_staleness": "fresh"}
    return [{"model_name": S.SNAPSHOT_MODEL_NAME, "model_info": info, "id": 999}]


def test_collapse_below_half_of_snapshot_is_hard(caplog):
    # Last-known-good said 4 desired; the registry now yields 1 (< 50%).
    gw = FakeGateway(registered=_snapshot_registered(count=4))
    ids = {"openai": {"gpt-4o"}}
    rc = S.run_sync(**_default_run_args(gateway=gw,
                                        fetch_provider_models=lambda p, k: ids[p]))
    assert rc == S.SYNC_HARD
    assert gw.calls == [], "a collapse must abort the whole push (D9 cold stop)"
    assert any("collapse" in r.message.lower() or "hard" in r.message.lower()
               for r in caplog.records)


def test_collapse_zero_desired_records_is_hard():
    gw = FakeGateway(registered=_snapshot_registered(count=4))
    rc = S.run_sync(**_default_run_args(
        gateway=gw, fetch_provider_models=lambda p, k: set()))
    assert rc == S.SYNC_HARD
    assert gw.calls == []


def test_zero_records_first_run_without_snapshot_is_hard():
    # Even with NO snapshot (first bootstrap), zero desired records is a hard
    # stop - a registry that yields nothing cannot be pushed (D9 verbatim).
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(
        gateway=gw, fetch_provider_models=lambda p, k: set()))
    assert rc == S.SYNC_HARD
    assert gw.calls == []


def test_no_snapshot_first_run_pushes_without_collapse_check():
    # The very first bootstrap has no last-known-good: the collapse check has
    # nothing to compare against, so the sync pushes (a fresh gateway is empty
    # by design - not a collapse).
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    assert [c[0] for c in gw.calls].count("add") == 4


def test_half_of_snapshot_is_not_a_collapse():
    # 50% is the boundary; D9 says "desired-set count < 50% of the
    # last-known-good snapshot" - exactly half still pushes.
    gw = FakeGateway(registered=_snapshot_registered(count=4))
    ids = {"opencode": {"deepseek-v4-flash-free", "deepseek-v4-pro"},
           "openai": {"gpt-4o"}}
    rc = S.run_sync(**_default_run_args(gateway=gw,
                                        fetch_provider_models=lambda p, k: ids[p]))
    assert rc == S.SYNC_OK


# ---------------------------------------------------------------------------
# Push failure and gateway API errors: hard (exit 1) -------------------------
# ---------------------------------------------------------------------------

def test_management_api_push_failure_is_hard(caplog):
    gw = FakeGateway()
    def fail_add(model_name, litellm_params, model_info):
        raise S.SyncPushError("POST /model/new refused")
    gw.add_model = fail_add
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_HARD
    assert any("push" in r.message.lower() or "hard" in r.message.lower()
               for r in caplog.records)


def test_management_api_info_failure_is_hard():
    gw = FakeGateway()
    def fail_list():
        raise S.SyncPushError("GET /model/info refused")
    gw.list_models = fail_list
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_HARD


# ---------------------------------------------------------------------------
# Provenance: Rule 1 - capability fields authored, never litellm defaults -----
# ---------------------------------------------------------------------------

def test_every_pushed_record_carries_the_provenance_tag():
    gw = FakeGateway()
    S.run_sync(**_default_run_args(gateway=gw))
    for c in gw.calls:
        if c[0] not in ("add", "update"):
            continue
        _, name, params, info = c
        assert M.PROVENANCE_SOURCE_KEY in info, f"{name} lacks capability_source"
        assert M.PROVENANCE_SYNCED_AT_KEY in info, f"{name} lacks capability_synced_at"
        assert M.PROVENANCE_STALENESS_KEY in info, f"{name} lacks capability_staleness"


def test_diff_ignores_litellm_added_defaults_and_volatile_synced_at():
    # /model/info may return model_info with litellm's own merged defaults and
    # a different capability_synced_at; the diff compares ONLY the authored
    # keys (excluding the volatile timestamp), so a no-change re-run stays
    # idempotent (Rule 1: litellm's bundled defaults are never trusted, and
    # they never trigger a spurious update).
    gw = _gateway_after_first_run()
    for r in gw.registered:
        r["model_info"]["some_litellm_default"] = "bundled"
        r["model_info"]["capability_synced_at"] = "2026-08-11T11:59:00+00:00"
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    assert gw.calls == []


def test_diff_ignores_unauthored_params_and_normalizes_sequences():
    # Two churn sources found against the live proxy (2026-08-17): (1) the
    # PATCH endpoint re-embodies updateLiteLLMParams pydantic DEFAULTS
    # (merge_reasoning_content_in_choices, use_in_pass_through, ...) into the
    # stored litellm_params, so a full-dict comparison never converges; (2)
    # authored tuples (modalities) come back as JSON lists. The authored
    # surface comparison must ignore un-authored params and normalize
    # sequences on both sides - otherwise every run diffs 62 updates forever.
    gw = _gateway_after_first_run()
    for r in gw.registered:
        params = r.setdefault("litellm_params", {})
        params["merge_reasoning_content_in_choices"] = False
        params["use_in_pass_through"] = False
        params["use_litellm_proxy"] = False
        params["use_xai_oauth"] = False
        for key in ("modalities_in", "modalities_out"):
            value = r["model_info"].get(key)
            if isinstance(value, tuple):
                r["model_info"][key] = list(value)
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    assert gw.calls == []


def test_snapshot_record_survives_diff_and_is_never_recounted_as_desired():
    # A registered snapshot must be neither deleted by the diff nor treated as
    # a desired record; when count+hash are unchanged it is not rewritten.
    names = ["opencode/deepseek-v4-flash-free", "opencode/deepseek-v4-pro",
             "openai/gpt-4o", "openai/gpt-4o-2024-08-06"]
    gw = FakeGateway(registered=_snapshot_registered(count=4, names=names))
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    assert all(c[0] != "delete" for c in gw.calls)
    assert all(c[0] != "snapshot" for c in gw.calls)


# ---------------------------------------------------------------------------
# GatewayClient: the management-API wire shape (litellm 1.96) ----------------
# ---------------------------------------------------------------------------

class StubHTTP:
    """A minimal recording httpx client stand-in (unit tier - no live gateway)."""

    def __init__(self, get_result=None, post_results=None):
        self.requests: list[tuple] = []
        self.get_result = get_result
        self.post_results = list(post_results or [])

    def request(self, method, url, *, json=None, headers=None, timeout=None):
        self.requests.append((method, url, headers, json))
        if method == "GET":
            return self.get_result
        return self.post_results.pop(0)

    def get(self, url, *, headers=None, timeout=None):
        self.requests.append(("GET", url, headers, None))
        return self.get_result


def _response(payload, status=200):
    return SimpleNamespaceResponse(payload, status)


class SimpleNamespaceResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise S.httpx.HTTPStatusError("bad status", request=None, response=self)

    def json(self):
        return self._payload


def test_gateway_client_list_models_wire_shape():
    client = StubHTTP(get_result=_response({"data": [{"model_name": "openai/gpt-4o"}]}))
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    entries = gw.list_models()
    assert entries == [{"model_name": "openai/gpt-4o"}]
    method, url, headers, _body = client.requests[0]
    assert method == "GET"
    assert url == "http://127.0.0.1:4000/model/info"
    assert headers == {"Authorization": "Bearer sk-master"}


def test_gateway_client_add_model_wire_shape():
    client = StubHTTP(post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    gw.add_model("opencode/deepseek-v4-flash-free",
                 {"model": "deepseek-v4-flash-free", "api_base": "https://opencode.ai/zen/v1"},
                 {"max_input_tokens": 128000, "capability_source": "models.dev"})
    method, url, headers, body = client.requests[0]
    assert method == "POST"
    assert url == "http://127.0.0.1:4000/model/new"
    assert headers == {"Authorization": "Bearer sk-master"}
    assert body["model_name"] == "opencode/deepseek-v4-flash-free"
    assert body["litellm_params"] == {"model": "deepseek-v4-flash-free",
                                      "api_base": "https://opencode.ai/zen/v1"}
    assert body["model_info"]["max_input_tokens"] == 128000


def test_gateway_client_update_model_wire_shape():
    # The DB-backed PATCH endpoint (/model/{model_id}/update) persists BOTH
    # litellm_params and model_info (the old POST /model/update rewrites only
    # litellm_params), and model_info must echo the row's model_id: pydantic
    # fabricates a random uuid when it is absent and the handler merges it in,
    # corrupting the row identity (verified against litellm 1.96.0 2026-08-17).
    client = StubHTTP(post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    gw.update_model(42, "openai/gpt-4o", {"model": "gpt-4o"}, {"max_input_tokens": 128000})
    method, url, headers, body = client.requests[0]
    assert method == "PATCH"
    assert url == "http://127.0.0.1:4000/model/42/update"
    assert body == {"model_name": "openai/gpt-4o",
                    "litellm_params": {"model": "gpt-4o"},
                    "model_info": {"max_input_tokens": 128000, "id": 42}}


def test_gateway_client_delete_model_wire_shape():
    client = StubHTTP(post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    gw.delete_model(42)
    method, url, headers, body = client.requests[0]
    assert method == "POST"
    assert url == "http://127.0.0.1:4000/model/delete"
    assert body == {"id": 42}


def test_gateway_client_upsert_snapshot_updates_existing_else_adds():
    # Existing snapshot -> PATCH /model/{model_id}/update; absent -> /model/new.
    # The snapshot record is a pseudo-model; litellm_params carries the marker.
    http = StubHTTP(
        get_result=_response({"data": [{"model_name": S.SNAPSHOT_MODEL_NAME,
                                        "model_info": {"id": 7}}]}),
        post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.upsert_snapshot({"desired_count": 4})
    method, url, headers, body = http.requests[1]
    assert method == "PATCH" and url == "http://127.0.0.1:4000/model/7/update"
    assert body["model_info"]["id"] == 7
    assert body["model_info"]["desired_count"] == 4
    assert body["litellm_params"] == {"model": f"openai/{S.SNAPSHOT_MODEL_NAME}"}

    http = StubHTTP(
        get_result=_response({"data": []}),
        post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.upsert_snapshot({"desired_count": 4})
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/model/new"


def test_gateway_client_ensure_virtual_key_generates_when_absent():
    # Absent -> POST /key/generate with the per-provider key VALUE as the key
    # and the provider-scoped registered model names (D3 client identity).
    http = StubHTTP(get_result=_response({}, status=404),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key("sk-provider-key", ["opencode/a", "opencode/b"])
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/key/generate"
    assert body == {"key": "sk-provider-key", "models": ["opencode/a", "opencode/b"]}


def test_gateway_client_ensure_virtual_key_updates_only_on_scope_change():
    # Present with the SAME scope -> no-op (C9 convergence); different scope
    # -> POST /key/update with the full desired scope.
    http = StubHTTP(get_result=_response({"info": {"models": ["opencode/a"]}}),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key("sk-provider-key", ["opencode/a"])
    assert len(http.requests) == 1  # info only - converged

    http = StubHTTP(get_result=_response({"info": {"models": ["opencode/a"]}}),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key("sk-provider-key", ["opencode/a", "opencode/b"])
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/key/update"
    assert body == {"key": "sk-provider-key",
                    "models": ["opencode/a", "opencode/b"]}


def test_sync_provisions_virtual_keys_per_provider():
    # Every configured provider's key becomes a virtual key scoped to ITS
    # registered records (D3): the client's gateway-mode bearer is the
    # per-provider key, and the proxy's auth accepts only master + virtual.
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(
        gateway=gw,
        read_api_key=lambda provider: ("sk-openai-proxy-key"
                                       if provider == "openai" else "dummy-key")))
    assert rc == S.SYNC_OK
    key_calls = [c for c in gw.calls if c[0] == "key"]
    assert len(key_calls) == 2  # openai + opencode keys from the fixtures
    by_key = {c[1]: c[2] for c in key_calls}
    assert by_key["dummy-key"] == ["opencode/deepseek-v4-flash-free",
                                   "opencode/deepseek-v4-pro"]
    assert by_key["sk-openai-proxy-key"] == ["openai/gpt-4o",
                                             "openai/gpt-4o-2024-08-06"]
    assert rc == S.SYNC_OK


def test_gateway_client_http_failure_raises_sync_push_error():
    client = StubHTTP(get_result=_response({}, status=503))
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    with pytest.raises(S.SyncPushError):
        gw.list_models()


def test_gateway_client_push_http_error_is_hard_not_silent():
    # A 4xx/5xx from /model/new must surface as SyncPushError (hard), never
    # be swallowed - otherwise the sync would report success on a failed push.
    client = StubHTTP(get_result=_response({"data": []}),
                      post_results=[_response({}, status=422)])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    with pytest.raises(S.SyncPushError):
        gw.add_model("openai/gpt-4o", {"model": "gpt-4o"}, {})


def test_gateway_client_unparseable_info_raises_sync_push_error():
    client = StubHTTP(get_result=_response({"not": "data"}))
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=client)
    with pytest.raises(S.SyncPushError):
        gw.list_models()
