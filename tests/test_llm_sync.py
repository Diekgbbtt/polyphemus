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
    """A recording stand-in for the gateway management API client.

    `_keys` maps each virtual key to its managed surface (`models`,
    `budget_limits`, `rpm_limit`) so the sync's idempotent convergence can be
    exercised: a no-change re-run records nothing, a budget/scope change
    records exactly one `key` call (#330, C9)."""

    def __init__(self, registered=None, keys=None):
        self.registered = [dict(r) for r in (registered or [])]
        self.calls: list[tuple] = []
        self._keys: dict[str, dict] = {
            k: {"models": list(v.get("models") or []),
                "budget_limits": list(v.get("budget_limits") or []) if v.get("budget_limits") is not None else None,
                "rpm_limit": v.get("rpm_limit")}
            for k, v in (keys or {}).items()}

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

    def ensure_virtual_key(self, key, models, *, budget_limits=None, rpm_limit=None):
        desired = sorted(models)
        manage_budget = budget_limits is not None
        canonical = S._canonical_budget_limits(budget_limits)
        current = self._keys.get(key)
        if current is not None:
            changed = current["models"] != desired
            if manage_budget:
                changed = changed or (
                    S._canonical_budget_limits(current.get("budget_limits")) != canonical)
                changed = changed or current.get("rpm_limit") != rpm_limit
            if not changed:
                return
            current["models"] = desired
            if manage_budget:
                current["budget_limits"] = list(budget_limits)
                current["rpm_limit"] = rpm_limit
            self.calls.append(("key", key, desired, list(budget_limits or []), rpm_limit))
            return
        self._keys[key] = {
            "models": desired,
            "budget_limits": list(budget_limits) if manage_budget else None,
            "rpm_limit": rpm_limit if manage_budget else None,
        }
        self.calls.append(("key", key, desired, list(budget_limits or []), rpm_limit))


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
    assert info["cache_read_input_token_cost"] == 0.0000000028
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


# ---------------------------------------------------------------------------
# #330 iteration 2: the provider-specific effective cost override ------------
# ---------------------------------------------------------------------------

_OVERRIDE_CATALOG = {
    "providers": {
        "opencode-go": {
            "id": "opencode-go",
            "models": {
                "deepseek-v4.1-flash": {
                    "id": "deepseek-v4.1-flash",
                    "limit": {"context": 1000000, "output": 384000},
                    "cost": {"input": 0.15, "output": 0.6, "cache_read": 0.003},
                },
            },
        },
    },
}


def _build_opencode_go_desired(catalog):
    return S.build_desired(
        {"opencode-go": {"deepseek-v4.1-flash"}}, catalog,
        base_urls={"opencode-go": "https://opencode.ai/zen/go/v1"},
        api_keys={"opencode-go": "oc_sk_key"}, synced_at=SYNCED_AT)


def test_build_desired_replaces_the_models_dev_cost_with_the_override():
    # The override authors the provider's real rate (the models.dev opencode-go
    # record) so the budget guard counts the real spend (ADR D13, #330 / EV-34).
    model = _build_opencode_go_desired(_OVERRIDE_CATALOG)[0]
    assert model.known is True
    assert model.model_info["input_cost_per_token"] == 1.5e-07
    assert model.model_info["output_cost_per_token"] == 6.0e-07
    assert model.model_info["cache_read_input_token_cost"] == 3e-09
    assert model.model_info["cost_source"] == M.COST_SOURCE_OVERRIDE
    # Capabilities stay models.dev-sourced.
    assert model.model_info["capability_source"] == \
        "models.dev/opencode-go/deepseek-v4.1-flash"


def test_build_desired_cost_override_survives_a_missing_models_dev_record():
    # Lifecycle: if models.dev drops or renames the record, the model degrades
    # to the D9 unknown path. The override is keyed by the registered name, not
    # by the models.dev record's presence, so it MUST still apply - otherwise
    # the guard silently fails OPEN for the eval's role model.
    catalog = {"providers": {"opencode-go": {"id": "opencode-go", "models": {}}}}
    model = _build_opencode_go_desired(catalog)[0]
    assert model.known is False
    assert model.model_info["capability_staleness"] == "unknown"
    assert model.model_info["input_cost_per_token"] == 1.5e-07
    assert model.model_info["output_cost_per_token"] == 6.0e-07
    assert model.model_info["cost_source"] == M.COST_SOURCE_OVERRIDE


def test_build_desired_warns_when_a_configured_override_has_no_live_model(caplog):
    # The provider is configured but /v1/models no longer lists the overridden
    # model: the override cannot apply, so it must not disappear silently.
    with caplog.at_level("WARNING"):
        S.build_desired(
            {"opencode-go": set()},
            {"providers": {"opencode-go": {"id": "opencode-go", "models": {}}}},
            base_urls={"opencode-go": "https://opencode.ai/zen/go/v1"},
            api_keys={"opencode-go": "oc_sk_key"}, synced_at=SYNCED_AT)
    assert any("cost-override" in r.message for r in caplog.records), \
        "an unreachable configured cost override must be logged loudly"


def _override_run_args(**kw):
    args = dict(
        fetch_catalog=lambda: _OVERRIDE_CATALOG,
        fetch_provider_models=lambda provider, api_key: {"deepseek-v4.1-flash"},
        gateway=FakeGateway(),
        providers={"opencode-go": "https://opencode.ai/zen/go/v1"},
        read_api_key=lambda provider: "oc_sk_key",
        synced_at=SYNCED_AT,
    )
    args.update(kw)
    return args


def test_sync_authors_the_cost_override_then_converges_to_idle():
    # The override is authored on every sync (a litellm-config-only override is
    # clobbered by the models.dev re-authoring), and a no-change re-run converges
    # to a no-op - it never fights the convergence diff.
    args = _override_run_args()
    gw = args["gateway"]
    assert S.run_sync(**args) == S.SYNC_OK
    _, name, _params, info = next(c for c in gw.calls if c[0] == "add")
    assert name == "opencode-go/deepseek-v4.1-flash"
    assert info["input_cost_per_token"] == 1.5e-07
    assert info["cost_source"] == M.COST_SOURCE_OVERRIDE

    gw2 = FakeGateway(registered=gw.registered, keys=dict(gw._keys))
    assert S.run_sync(**{**args, "gateway": gw2}) == S.SYNC_OK
    assert gw2.calls == [], \
        f"a converged override re-run must be idle (C9), got {gw2.calls}"


def test_sync_does_not_flag_the_overridden_model_as_unpriced(caplog):
    # The override makes the model pricesable, so the guard's pricing-gap
    # warning (which fires for records with no authored input/output cost) must
    # NOT fire for it - the budget guard can price the eval's role model.
    args = _override_run_args()
    with caplog.at_level("WARNING"):
        assert S.run_sync(**args) == S.SYNC_OK
    assert not any("pricing-gap" in r.message for r in caplog.records), \
        "the overridden model must not be reported as unpriced"


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


def test_key_rotation_forces_update_of_that_providers_models():
    # #193: a provider API-key rotation in env must re-push that provider's
    # key-bearing models (update path) so the gateway's persisted
    # litellm_params.api_key is refreshed. The masked-key diff treated a
    # rotation as a no-op, leaving the stale encrypted key after a restart.
    gw = _gateway_after_first_run()  # registered with sk-opencode-key
    rc = S.run_sync(**_default_run_args(
        gateway=gw,
        read_api_key=lambda provider: ("sk-opencode-key-NEW"
                                       if provider == "opencode" else "sk-openai-key")))
    assert rc == S.SYNC_OK
    updates = [c for c in gw.calls if c[0] == "update"]
    assert len(updates) == 2, f"both opencode models must be refreshed, got {gw.calls}"
    for _kind, _rid, name, params, _info in updates:
        assert name.startswith("opencode/")
        assert params["api_key"] == "sk-opencode-key-NEW"
    # The unchanged provider is untouched by the rotation.
    assert all(c[2].startswith("opencode/") for c in updates)


def test_key_rotation_is_idempotent_then_converges_to_noop():
    # After the rotation is applied, a further run with the same (new) key is
    # a fully idle no-op - the key fingerprint converges (D9/C9), never churns.
    gw = _gateway_after_first_run()
    rotated = lambda p: ("sk-opencode-key-NEW" if p == "opencode" else "sk-openai-key")  # noqa: E731
    S.run_sync(**_default_run_args(gateway=gw, read_api_key=rotated))
    gw2 = FakeGateway(registered=gw.registered, keys=dict(gw._keys))
    rc = S.run_sync(**_default_run_args(gateway=gw2, read_api_key=rotated))
    assert rc == S.SYNC_OK
    assert gw2.calls == [], f"a converged re-run after rotation must push nothing, got {gw2.calls}"


def test_legacy_snapshot_without_key_hashes_refreshes_once_then_converges():
    # A snapshot that predates #193's api_key_hashes records no applied key,
    # so the sync cannot know whether the stored keys are current. It
    # re-establishes the baseline ONCE (every model refreshed with the current
    # env keys - which also repairs an already-stale DB after an upgrade),
    # records the hashes, and the next re-run is a fully idle no-op.
    gw = _gateway_after_first_run()
    for r in gw.registered:
        if r["model_name"] == S.SNAPSHOT_MODEL_NAME:
            r["model_info"].pop("api_key_hashes", None)
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    updates = [c for c in gw.calls if c[0] == "update"]
    assert len(updates) == 4, f"the baseline must be re-established once, got {gw.calls}"
    snapshot = next(r for r in gw.registered
                    if r["model_name"] == S.SNAPSHOT_MODEL_NAME)
    assert "api_key_hashes" in snapshot["model_info"], \
        "the re-established baseline must record the applied key hashes"
    gw2 = FakeGateway(registered=gw.registered, keys=dict(gw._keys))
    rc2 = S.run_sync(**_default_run_args(gateway=gw2))
    assert rc2 == S.SYNC_OK
    assert gw2.calls == [], f"the converged re-run must push nothing, got {gw2.calls}"


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


def test_skip_warning_names_the_real_hyphenated_env_var(caplog):
    # #335 (secondary): the skip warning must print `_key_env`'s real name -
    # `API_KEY_OPENCODE_GO` (underscore) - not `provider.upper()`'s dash form
    # (`API_KEY_OPENCODE-GO`), which was the misleading string in the exact
    # oc_sk_ failure the ticket reports.
    gw = FakeGateway()
    with caplog.at_level("WARNING"):
        S.run_sync(**_default_run_args(
            gateway=gw,
            providers={"opencode-go": "https://opencode.ai/zen/go/v1",
                       "openai": "https://api.openai.com/v1"},
            read_api_key=lambda provider: ("sk-oai" if provider == "openai"
                                           else None)))
    messages = [r.message for r in caplog.records]
    assert any("API_KEY_OPENCODE_GO" in m for m in messages), \
        f"the skip warning must name the real env var, got {messages}"
    assert not any("API_KEY_OPENCODE-GO" in m for m in messages), \
        "the dash form must never be printed (there is no such env var)"


# ---------------------------------------------------------------------------
# Collapse: hard, abort push, exit 1 (D9 cold stop) --------------------------
# ---------------------------------------------------------------------------

def _snapshot_registered(count=4, names=None):
    # A converged, current-format snapshot: api_key_hashes records the key
    # fingerprints the sync last applied (the D9 last-known-good surface,
    # extended for #193 - the masked key cannot be diffed from the registered
    # side, so the snapshot carries it). Matches the default run keys below.
    names = names or ["openai/gpt-4o"]
    info = {"desired_count": count,
            "desired_hash": S.desired_hash(names),
            "api_key_hashes": {"opencode": S._key_hash("sk-opencode-key"),
                               "openai": S._key_hash("sk-openai-key")},
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
    # Absent -> POST /key/generate with the app-minted virtual key VALUE and
    # the provider-scoped registered model names (D3 client identity).
    http = StubHTTP(get_result=_response({}, status=404),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key("sk-provider-key", ["opencode/a", "opencode/b"])
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/key/generate"
    assert body == {"key": "sk-provider-key", "models": ["opencode/a", "opencode/b"]}


def test_gateway_client_refuses_a_non_sk_virtual_key():
    # #335: the mint write boundary refuses a non-`sk-` key outright, before
    # any request. A relayed provider credential would otherwise only fail at
    # litellm's 400 (and hard-stop the sync deep in the pipeline); fail loud
    # here with a named error, and never echo the secret.
    http = StubHTTP(get_result=_response({}, status=404),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    with pytest.raises(S.SyncPushError):
        gw.ensure_virtual_key("oc_sk_provider_credential", ["opencode/a"])
    assert http.requests == [], "no request may be sent for a non-sk key"


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
    # Every configured provider gets an APP-MINTED litellm-native virtual key,
    # scoped to ITS registered records (D3, amended #335): the client derives
    # the same key as its gateway-mode bearer, and the provider credential is
    # never the inbound key.
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(
        gateway=gw,
        read_api_key=lambda provider: ("sk-openai-proxy-key"
                                       if provider == "openai" else "dummy-key")))
    assert rc == S.SYNC_OK
    key_calls = [c for c in gw.calls if c[0] == "key"]
    assert len(key_calls) == 2  # openai + opencode keys from the fixtures
    assert {tuple(c[2]) for c in key_calls} == {
        ("opencode/deepseek-v4-flash-free", "opencode/deepseek-v4-pro"),
        ("openai/gpt-4o", "openai/gpt-4o-2024-08-06"),
    }
    for _kind, key, _scope, _budget, _rpm in key_calls:
        assert key.startswith("sk-"), "every minted key must be litellm-native"
        assert key not in ("dummy-key", "sk-openai-proxy-key"), \
            "the provider credential must never be the inbound virtual key"


def test_sync_mints_the_same_virtual_key_the_client_derives():
    # The load-bearing #335 agreement: the sync's minted inbound key equals the
    # client's gateway-mode bearer for the same provider credential, so the
    # client authenticates with no persisted mapping and no new env var.
    from polymerhus.app.llm.providers import gateway_virtual_key

    gw = FakeGateway()
    S.run_sync(**_default_run_args(
        gateway=gw,
        read_api_key=lambda provider: {"opencode": "oc_sk_go",
                                       "openai": "sk-oai"}[provider]))
    minted = {c[1] for c in gw.calls if c[0] == "key"}
    assert minted == {gateway_virtual_key("opencode", "oc_sk_go"),
                      gateway_virtual_key("openai", "sk-oai")}


class LiteLLMNativeKeyEnforcingGateway(FakeGateway):
    """A FakeGateway that enforces litellm's inbound virtual-key format rule.

    `POST /key/generate` (and `/key/update`) rejects any key not prefixed
    `sk-` with the live 400 (`litellm.proxy.proxy_server.generate_key_fn`,
    #335): a non-`sk-` provider key surfaces here exactly as it does against
    the live gateway - as a `SyncPushError` -> `SYNC_HARD`."""

    def ensure_virtual_key(self, key, models, *, budget_limits=None, rpm_limit=None):
        if not key.startswith("sk-"):
            raise S.SyncPushError(
                "POST /key/generate failed: 400 Invalid key format. LiteLLM "
                "Virtual Key must start with 'sk-'. Received: "
                f"{key[:4]}****")
        super().ensure_virtual_key(key, models, budget_limits=budget_limits,
                                   rpm_limit=rpm_limit)


def test_non_sk_provider_key_is_minted_as_a_litellm_native_virtual_key():
    # #335: the opencode-go provider key is now `oc_sk_...`, which litellm's
    # /key/generate rejects (400, "must start with 'sk-'"). The sync must MINT
    # a litellm-native virtual key per provider, never pass the provider
    # credential through as the inbound key.
    gw = LiteLLMNativeKeyEnforcingGateway()
    rc = S.run_sync(**_default_run_args(
        gateway=gw,
        read_api_key=lambda provider: ("oc_sk_opencode_go_provider"
                                       if provider == "opencode"
                                       else "sk-openai-provider")))
    assert rc == S.SYNC_OK, (
        "a non-sk provider key must not hard-stop the sync (#335)")
    minted = {c[1] for c in gw.calls if c[0] == "key"}
    assert minted, "the sync must provision a virtual key per provider"
    assert all(k.startswith("sk-") for k in minted), \
        f"every minted key must be litellm-native (sk-), got {minted}"
    assert "oc_sk_opencode_go_provider" not in minted, \
        "the provider credential must never be the inbound virtual key"


def test_non_sk_provider_key_still_reaches_the_models_as_the_upstream_credential():
    # The provider credential still lands in each model's
    # litellm_params.api_key (the gateway's upstream key custody, #193) - only
    # the inbound virtual key is decoupled from it.
    gw = LiteLLMNativeKeyEnforcingGateway()
    S.run_sync(**_default_run_args(
        gateway=gw,
        read_api_key=lambda provider: ("oc_sk_opencode_go_provider"
                                       if provider == "opencode"
                                       else "sk-openai-provider")))
    _, name, params, _info = next(
        c for c in gw.calls
        if c[0] == "add" and c[1] == "opencode/deepseek-v4-flash-free")
    assert params["api_key"] == "oc_sk_opencode_go_provider"


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


# ---------------------------------------------------------------------------
# #330: the gateway cost guard - the virtual-key USD budget plan ------------
#
# LiteLLM's native virtual-key `budget_limits` (USD, from the sync's existing
# models.dev per-token costs) mirror opencode-go's dollar-denominated cap
# ($30/7d weekly - the dominant, first-binding boundary - and $60/30d monthly;
# no 5h cap). The conservatism factor k (default 1.0) is a pure safety margin;
# with the override authoring the provider's real rate, LiteLLM's spend count
# matches the charge and the guard trips at the real cap. See ADR D13.
# ---------------------------------------------------------------------------

_BUDGET_ENV = (
    "LLM_GATEWAY_BUDGET_7D_USD",
    "LLM_GATEWAY_BUDGET_30D_USD",
    "LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR",
    "LLM_GATEWAY_KEY_RPM_LIMIT",
)


def _clear_budget_env(monkeypatch):
    for name in _BUDGET_ENV:
        monkeypatch.delenv(name, raising=False)


def test_budget_plan_default_is_the_real_provider_caps(monkeypatch):
    _clear_budget_env(monkeypatch)
    plan = S.gateway_budget_plan()
    assert plan.budget_limits == (
        {"budget_duration": "7d", "max_budget": 30.0},
        {"budget_duration": "30d", "max_budget": 60.0},
    )
    assert plan.rpm_limit is None


def test_budget_plan_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_7D_USD", "40")
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_30D_USD", "80")
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR", "0.25")
    monkeypatch.setenv("LLM_GATEWAY_KEY_RPM_LIMIT", "30")
    plan = S.gateway_budget_plan()
    assert plan.budget_limits == (
        {"budget_duration": "7d", "max_budget": 10.0},
        {"budget_duration": "30d", "max_budget": 20.0},
    )
    assert plan.rpm_limit == 30


def test_budget_plan_rejects_a_factor_above_one(monkeypatch):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR", "1.5")
    with pytest.raises(S.SyncConfigError):
        S.gateway_budget_plan()


def test_budget_plan_rejects_a_nonpositive_rpm(monkeypatch):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv("LLM_GATEWAY_KEY_RPM_LIMIT", "0")
    with pytest.raises(S.SyncConfigError):
        S.gateway_budget_plan()


def test_budget_plan_rejects_a_non_numeric_cap(monkeypatch):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_7D_USD", "lots")
    with pytest.raises(S.SyncConfigError):
        S.gateway_budget_plan()


def test_gateway_client_ensure_virtual_key_provisions_budget_windows():
    http = StubHTTP(get_result=_response({}, status=404),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key(
        "sk-ph-key", ["opencode/a"],
        budget_limits=[{"budget_duration": "5h", "max_budget": 6.0}],
        rpm_limit=30)
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/key/generate"
    assert body == {"key": "sk-ph-key", "models": ["opencode/a"],
                    "budget_limits": [{"budget_duration": "5h", "max_budget": 6.0}],
                    "rpm_limit": 30}


def test_gateway_client_ensure_virtual_key_converges_when_budget_matches():
    # /key/info echoes the server-initialised `reset_at` per window; the diff
    # ignores it (it is re-derived server-side on every write), so a re-run is
    # a no-op (C9) rather than perpetual churn.
    info = {"models": ["opencode/a"],
            "budget_limits": [{"budget_duration": "5h", "max_budget": 6.0,
                               "reset_at": "2026-10-06T20:00:00+00:00"}],
            "rpm_limit": 30}
    http = StubHTTP(get_result=_response({"info": info}),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key(
        "sk-ph-key", ["opencode/a"],
        budget_limits=[{"budget_duration": "5h", "max_budget": 6.0}],
        rpm_limit=30)
    assert len(http.requests) == 1  # info only - converged


def test_gateway_client_ensure_virtual_key_updates_only_on_budget_change():
    info = {"models": ["opencode/a"],
            "budget_limits": [{"budget_duration": "5h", "max_budget": 6.0}],
            "rpm_limit": 30}
    http = StubHTTP(get_result=_response({"info": info}),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key(
        "sk-ph-key", ["opencode/a"],
        budget_limits=[{"budget_duration": "5h", "max_budget": 3.0}],
        rpm_limit=30)
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/key/update"
    assert body == {"key": "sk-ph-key", "models": ["opencode/a"],
                    "budget_limits": [{"budget_duration": "5h", "max_budget": 3.0}],
                    "rpm_limit": 30}


def test_gateway_client_ensure_virtual_key_adds_budget_to_an_unbudgeted_key():
    # A key minted before #330 carries no budget; the first post-deploy run
    # adds the windows once, then converges.
    http = StubHTTP(get_result=_response({"info": {"models": ["opencode/a"]}}),
                    post_results=[_response({})])
    gw = S.GatewayClient("http://127.0.0.1:4000", "sk-master", client=http)
    gw.ensure_virtual_key(
        "sk-ph-key", ["opencode/a"],
        budget_limits=[{"budget_duration": "5h", "max_budget": 6.0}],
        rpm_limit=None)
    method, url, headers, body = http.requests[1]
    assert method == "POST" and url == "http://127.0.0.1:4000/key/update"
    assert body["budget_limits"] == [{"budget_duration": "5h", "max_budget": 6.0}]
    assert body["rpm_limit"] is None


def test_sync_provisions_virtual_keys_with_the_budget_plan(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR", "1.0")
    monkeypatch.delenv("LLM_GATEWAY_KEY_RPM_LIMIT", raising=False)
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_OK
    key_calls = [c for c in gw.calls if c[0] == "key"]
    assert key_calls, "the sync must provision a virtual key per provider"
    for _kind, _key, _scope, budget, rpm in key_calls:
        assert budget == [{"budget_duration": "7d", "max_budget": 30.0},
                          {"budget_duration": "30d", "max_budget": 60.0}]
        assert rpm is None


def test_budget_change_converges_then_is_a_noop(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR", "1.0")
    monkeypatch.delenv("LLM_GATEWAY_KEY_RPM_LIMIT", raising=False)
    gw = FakeGateway()
    assert S.run_sync(**_default_run_args(gateway=gw)) == S.SYNC_OK

    # Changing the conservatism factor re-budgets BOTH provider keys exactly
    # once (a key update), not on every subsequent run.
    gw2 = FakeGateway(registered=gw.registered, keys=dict(gw._keys))
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR", "0.5")
    assert S.run_sync(**_default_run_args(gateway=gw2)) == S.SYNC_OK
    key_calls = [c for c in gw2.calls if c[0] == "key"]
    assert len(key_calls) == 2, f"both provider keys must re-budget once, got {gw2.calls}"
    assert key_calls[0][3][0] == {"budget_duration": "7d", "max_budget": 15.0}

    gw3 = FakeGateway(registered=gw2.registered, keys=dict(gw2._keys))
    assert S.run_sync(**_default_run_args(gateway=gw3)) == S.SYNC_OK
    assert [c for c in gw3.calls if c[0] == "key"] == [], \
        "a converged budget re-run must be fully idle (C9)"


def test_malformed_budget_config_cold_stops_before_any_push(monkeypatch):
    # An unusable budget override is a config lie: the run cold-stops (exit 1)
    # on a CLEAN gateway, before any model/key write (#330, ADR D13).
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR", "2")
    gw = FakeGateway()
    rc = S.run_sync(**_default_run_args(gateway=gw))
    assert rc == S.SYNC_HARD
    assert gw.calls == [], "a config lie must abort before any gateway write"


def test_unpriced_registered_models_are_logged_as_a_budget_gap(caplog):
    # A registered model with no authored cost cannot reserve budget
    # (LiteLLM #35524: reserve_budget_for_request returns None), so the USD
    # guard fails OPEN for it. The sync makes the gap LOUD at bootstrap so an
    # unpriced eval model cannot silently escape the guard (#330, ADR D13).
    catalog = {
        "providers": {
            "opencode": {
                "id": "opencode",
                "api": "https://opencode.ai/zen/v1",
                "models": {
                    "no-price": {"id": "no-price", "tool_call": True,
                                 "limit": {"context": 1000, "output": 100}},
                },
            },
        },
        "models": {},
    }
    gw = FakeGateway()
    with caplog.at_level("WARNING"):
        rc = S.run_sync(**_default_run_args(
            gateway=gw, fetch_catalog=lambda: catalog,
            providers={"opencode": "https://opencode.ai/zen/v1"},
            fetch_provider_models=lambda p, k: {"no-price"}))
    assert rc == S.SYNC_OK
    messages = " ".join(r.message for r in caplog.records)
    assert "opencode/no-price" in messages, (
        "an unpriced registered model must be named in the budget-gap log")
    assert "pricing" in messages.lower()
