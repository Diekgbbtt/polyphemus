"""The bootstrap sync CLI (T2, #105) - `python -m polymerhus.app.llm.sync`.

Runs the D2/D9 pipeline once at container bootstrap (ADR D2: stateless, no
scheduler): fetch the two sources (the provider `/v1/models` for existence;
`https://models.dev/catalog.json` for capability/cost/context - a plain JSON
fetch, no separate client package), join by model ID per provider namespace,
resolve `base_model` inheritance (Rule 2), map to the LiteLLM `model_info`
schema (D5 - see `sync_mapping.py`), validate (soft/hard exit codes + the
collapse check against the last-known-good snapshot), diff against
`GET /model/info`, and push the deltas via the gateway management API
(`POST /model/new|update|delete`).

## The exit-code contract (D9; the T1 entrypoint `gateway_entrypoint.py`
## branches on exactly these)

- `0` (SYNC_OK): the desired set was validated, diffed and pushed (or was a
  no-op). The agent starts.
- `1` (SYNC_HARD): an implausible collapse (desired-set count < 50% of the
  last-known-good snapshot, or zero records), a gateway management-API
  failure, or an unexpected error - the push is aborted and the agent must
  NOT start (cold stop).
- `2` (SYNC_SOFT): a source failure (registry fetch/parse, provider
  `/v1/models` refusal) - the push is skipped, the gateway DB is kept as-is
  (last-known-good records stay), and the agent starts on stale records
  (fail toward staleness, not toward guessing).

A provider with NO configured API key is skipped with a log (the app cannot
route to it either); a provider with a key whose `/v1/models` refuses is a
soft source failure.

## The last-known-good snapshot (D9)

After every successful push a small snapshot - `{desired_count,
desired_hash}` plus provenance - is persisted in the gateway DB under the
pseudo-model record named `__sync_snapshot__` via the same management API
(no new state surface, operator-ratified 2026-08-11). The next run's collapse
check compares its desired-set count against the snapshot's count. The
pseudo-model is excluded from the diff (never deleted, never counted as
desired) and is rewritten only when count or hash actually changed, so a
no-change re-run is fully idle.

## Provider API-key rotation (#193)

`/model/info` MASKs the stored `api_key` (litellm pops it from every
deployment), so the registered side can never be diffed for the key - the
routing trio's key is tracked independently in the snapshot's
`api_key_hashes`: a per-provider fingerprint of the key the sync last
successfully applied. When a provider's CURRENT env-key fingerprint differs
from the snapshot's, that provider's key-bearing models are force-refreshed
(update path - `PATCH /model/{id}/update` re-encrypts and persists a fresh
`litellm_params.api_key`, then clears the router cache) on the next push.
A snapshot that predates `api_key_hashes` (or is absent) is treated as
"unknown applied key": the configured providers are refreshed once to
establish the baseline, then the fingerprint is recorded and the re-run is
idle. Deterministic and idempotent under equal inputs: a rotation fires
exactly one update round, never churn.

## Diffable push (D9)

`GET /model/info` gives the registered set; add/update/delete is computed per
model. An update pushes the FULL authored `model_info` (never a partial
merge). The diff compares ONLY the authored keys (ignoring anything litellm
merged in from its own bundled cost map - Rule 1 - and the volatile
`capability_synced_at` timestamp), so a second run with no source changes
pushes nothing.

## No I/O at import (CODING_STANDARD §6)

Importing this module performs no HTTP call and reads no env var. Every
side-effecting collaborator (catalog fetch, provider fetch, the gateway
management client, the api-key reader) is an injectable callable with a real,
lazily-resolved default; the unit tier injects fakes (no live model, no live
gateway, no DB).
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from polymerhus.app.llm.providers import PROVIDERS
from polymerhus.app.llm.sync_mapping import (
    PROVENANCE_SOURCE_KEY,
    PROVENANCE_STALENESS_KEY,
    PROVENANCE_SYNCED_AT_KEY,
    STALENESS_FRESH,
    UNKNOWN_SOURCE,
    capability_record_from_resolved,
    capability_to_model_info,
    ROUTING_PROVIDER_PREFIX,
    registered_model_name,
    routing_model,
    resolve_model_record,
    unknown_model_info,
)

logger = logging.getLogger(__name__)

# --- The D9 exit-code contract (the T1 entrypoint branches on these) --------
SYNC_OK = 0
SYNC_HARD = 1
SYNC_SOFT = 2

DEFAULT_REGISTRY_URL = "https://models.dev/catalog.json"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:4000"
DEFAULT_FETCH_TIMEOUT_S = 30.0

# The last-known-good snapshot pseudo-model (D9; operator-ratified 2026-08-11).
# A dedicated model record in the gateway DB - no new state surface.
SNAPSHOT_MODEL_NAME = "__sync_snapshot__"


# --- Failure taxonomy (each maps to exactly one exit code) ------------------

class SyncSourceError(RuntimeError):
    """A source failure (registry fetch/parse, provider /v1/models refusal):
    soft - skip the push, keep the DB, exit 2 (D9)."""


class SyncCollapseError(RuntimeError):
    """An implausible collapse (desired count < 50% of the snapshot, or zero
    records): hard - abort the whole push, exit 1 (D9 cold stop)."""


class SyncPushError(RuntimeError):
    """A gateway management-API failure (auth, /model/info, or a push verb):
    hard - the gateway DB state is unknown after a partial push; the agent
    must not start on it (the T1 entrypoint treats any non-0/2 code as hard,
    the safe failure mode)."""


# --- Env readers (lazy, at call time - never at import) ----------------------

def provider_api_key(provider: str) -> str | None:
    """The provider's API key for the existence fetch, from the app's
    `API_KEY_{PROVIDER}` convention (providers.py `_key_env` - hyphens in the
    provider id normalize to underscores, so `opencode-go` -> `API_KEY_OPENCODE_GO`)."""
    from polymerhus.app.llm.providers import _key_env
    return os.environ.get(_key_env(provider))


def gateway_url() -> str:
    """The gateway management-API base URL. Defaults to the internal proxy
    port (4000, the T1 entrypoint's `PROXY_PORT`); overridable via
    `LLM_SYNC_GATEWAY_URL` so a host-side run can point at a published port.
    Per-env independence (D9) falls out of this: each env's sync writes only
    its own gateway."""
    return os.environ.get("LLM_SYNC_GATEWAY_URL") or DEFAULT_GATEWAY_URL


def master_key() -> str | None:
    """`LITELLM_MASTER_KEY` - the management-API credential, env-only (never
    in the repo, never hardcoded)."""
    return os.environ.get("LITELLM_MASTER_KEY")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Fetch (the two sources; both raise SyncSourceError) ---------------------

def _fetch_catalog() -> dict:
    """Fetch `catalog.json` (provider endpoints + model metadata in ONE
    response - the join needs no second registry fetch)."""
    try:
        with httpx.Client(timeout=DEFAULT_FETCH_TIMEOUT_S) as client:
            response = client.get(DEFAULT_REGISTRY_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # network, HTTP status, JSON parse
        raise SyncSourceError(f"fetching {DEFAULT_REGISTRY_URL} failed: {exc}") from exc
    if not isinstance(data, dict):
        raise SyncSourceError(f"{DEFAULT_REGISTRY_URL} did not return a JSON object")
    return data


def _fetch_provider_model_ids(provider: str, api_key: str) -> set[str]:
    """Fetch one provider's `/v1/models` (existence is the ONLY fact trusted
    from this source - nothing else, spec §3.1)."""
    url = f"{PROVIDERS[provider]}/models"
    try:
        with httpx.Client(timeout=DEFAULT_FETCH_TIMEOUT_S) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # network, HTTP status, JSON parse
        raise SyncSourceError(f"fetching {url} failed (provider {provider} refused): {exc}") from exc
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise SyncSourceError(f"{url} returned an unparseable body (no 'data' list)")
    ids: set[str] = set()
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(item["id"])
    return ids


# --- Join + map: the desired set (pure) --------------------------------------

@dataclass(frozen=True)
class DesiredModel:
    """One record the sync wants in the gateway: the registered `model_name`,
    the `litellm_params` for routing, and the authored `model_info` (empty of
    capability fields for unknown models)."""

    model_name: str
    litellm_params: dict
    model_info: dict
    known: bool


def build_desired(provider_ids: dict[str, set[str]], catalog: dict, *,
                  base_urls: dict[str, str], api_keys: dict[str, str],
                  synced_at: str) -> list[DesiredModel]:
    """Join existence (`/v1/models` ids) with the registry per provider
    namespace, resolve inheritance (Rule 2) and map to the desired set.

    A model on `/v1/models` with no registry entry becomes an UNKNOWN record:
    still registered for routing (existence is real) with NO capability fields
    and a provenance tag marking it unknown (D9); the gap is logged.

    `litellm_params` carries the ROUTING trio (`routing_model` + `api_base` +
    `api_key`): litellm's router needs all three to serve a custom
    OpenAI-compatible endpoint (the api_key is masked by litellm in
    `/model/info` and excluded from diff matching - see `_registered_matches`)."""
    global_models = catalog.get("models") if isinstance(catalog, dict) else None
    providers = catalog.get("providers") if isinstance(catalog, dict) else None
    if not isinstance(global_models, dict):
        global_models = {}
    if not isinstance(providers, dict):
        providers = {}
    desired: list[DesiredModel] = []
    for provider in sorted(provider_ids):
        provider_entry = providers.get(provider)
        provider_models = provider_entry.get("models") if isinstance(provider_entry, dict) else {}
        if not isinstance(provider_models, dict):
            provider_models = {}
        for model_id in sorted(provider_ids[provider]):
            record = provider_models.get(model_id)
            resolved = resolve_model_record(record, global_models) if isinstance(record, dict) else None
            if resolved is None:
                info = unknown_model_info(synced_at)
                logger.info(
                    "unknown model gap (D9): %s/%s exists on /v1/models but has no "
                    "models.dev registry entry - registered for routing without "
                    "capability fields", provider, model_id)
            else:
                capability = capability_record_from_resolved(
                    provider, model_id, resolved, synced_at=synced_at)
                info = capability_to_model_info(capability)
            desired.append(DesiredModel(
                model_name=registered_model_name(provider, model_id),
                litellm_params={"model": routing_model(provider, model_id),
                                "api_base": base_urls[provider],
                                "api_key": api_keys[provider]},
                model_info=info,
                known=resolved is not None,
            ))
    return desired


# --- The last-known-good snapshot (D9) ----------------------------------------

@dataclass(frozen=True)
class Snapshot:
    desired_count: int
    desired_hash: str
    api_key_hashes: dict[str, str] | None = None


def desired_hash(model_names: list[str]) -> str:
    """A stable hash of the desired set (sorted registered names), so an
    unchanged desired set hashes identically across runs regardless of
    provider iteration order."""
    digest = hashlib.sha256()
    for name in sorted(model_names):
        digest.update(name.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _key_hash(api_key: str) -> str:
    """A deterministic, collision-resistant fingerprint of a provider API key.

    The plaintext key is NEVER persisted or logged - only this digest, which
    the sync compares to detect a rotation (#193). The gateway cannot help
    here: `/model/info` masks the stored key, so the applied key is known
    only to the sync that wrote it."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _providers_needing_refresh(snapshot: Snapshot | None,
                               current_hashes: dict[str, str]) -> set[str]:
    """The providers whose CURRENT env key differs from the key the sync last
    applied (the snapshot's `api_key_hashes`) and therefore need a forced
    refresh of their key-bearing models.

    A snapshot that predates `api_key_hashes` (or is absent) records no
    applied key, so the safe default is to refresh every configured provider
    once - the baseline is (re)established and recorded; the next re-run
    converges to a no-op. This is what repairs an already-stale DB after an
    upgrade, and what a fresh gateway (nothing registered yet) makes inert."""
    if snapshot is None or snapshot.api_key_hashes is None:
        return set(current_hashes)
    return {provider for provider, current in current_hashes.items()
            if snapshot.api_key_hashes.get(provider) != current}


def read_snapshot(registered: list[dict]) -> Snapshot | None:
    """Read the last-known-good snapshot from the registered set (the
    `__sync_snapshot__` pseudo-model). Absent or malformed -> None (the first
    bootstrap has no collapse check)."""
    for entry in registered:
        if not isinstance(entry, dict) or entry.get("model_name") != SNAPSHOT_MODEL_NAME:
            continue
        info = entry.get("model_info")
        if not isinstance(info, dict):
            return None
        count = info.get("desired_count")
        digest = info.get("desired_hash")
        if isinstance(count, int) and isinstance(digest, str):
            hashes = info.get("api_key_hashes")
            if not isinstance(hashes, dict):
                hashes = None
            return Snapshot(desired_count=count, desired_hash=digest,
                            api_key_hashes=hashes)
        return None
    return None


# --- Validate (D9: soft vs hard) ----------------------------------------------

def validate_desired(desired: list[DesiredModel], snapshot: Snapshot | None) -> None:
    """The D9 collapse check. Raises `SyncCollapseError` (hard) when the
    desired set is empty or implausibly collapsed vs the last-known-good."""
    count = len(desired)
    if count == 0:
        raise SyncCollapseError(
            "desired set is EMPTY (zero records): aborting the push (D9 cold stop)")
    if snapshot is not None and count < snapshot.desired_count * 0.5:
        raise SyncCollapseError(
            f"desired-set count {count} < 50% of the last-known-good snapshot "
            f"({snapshot.desired_count}): aborting the push (D9 cold stop)")


# --- Diff (pure; D9 diffable push) ---------------------------------------------

@dataclass
class Diff:
    adds: list[DesiredModel] = field(default_factory=list)
    updates: list[tuple[Any, DesiredModel]] = field(default_factory=list)
    deletes: list[Any] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.adds or self.updates or self.deletes)


def diff_desired(desired: list[DesiredModel], registered: list[dict], *,
                 force_update: set[str] | None = None) -> Diff:
    """Compute add/update/delete against the registered set.

    The comparison ignores (a) registered keys the desired record does not
    author (litellm's own bundled cost-map defaults are NEVER trusted or
    compared - Rule 1) and (b) the volatile `capability_synced_at` timestamp.
    An update pushes the FULL desired `model_info` (D9: never a partial
    merge). The snapshot pseudo-model is excluded from the registered set.

    `force_update` (a set of registered `model_name`s) bypasses the authored
    comparison: a forced model is updated even when its authored surface
    matches, because its provider's API key rotated - the key is masked in
    `/model/info`, so the rotation is invisible to `_registered_matches` and
    must be pushed (#193)."""
    registered_by_name: dict[str, dict] = {}
    for entry in registered:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model_name")
        if name == SNAPSHOT_MODEL_NAME or name is None:
            continue
        registered_by_name[name] = entry
    force_update = force_update or set()
    diff = Diff()
    for model in desired:
        entry = registered_by_name.pop(model.model_name, None)
        if entry is None:
            diff.adds.append(model)
        elif model.model_name in force_update or not _registered_matches(entry, model):
            diff.updates.append((_registered_model_id(entry), model))
    diff.deletes = [_registered_model_id(entry) for entry in registered_by_name.values()]
    return diff


def _norm_value(value: Any) -> Any:
    """Recursively normalize a JSON value for comparison: tuples -> lists
    (JSON stores tuples as arrays, and litellm's prisma layer returns them as
    lists - the same authored value must compare equal on both sides)."""
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        return [_norm_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm_value(v) for k, v in value.items()}
    return value


def _registered_matches(entry: dict, desired: DesiredModel) -> bool:
    """True when the registered record equals the desired record over the
    authored surface: desired model_info keys (minus the volatile synced-at
    timestamp) and the routing params the desired record authors (minus the
    masked api_key).

    The api_key is MASKED by litellm in `/model/info`, so it is never
    comparable on this surface; the sync tracks it independently - a rotation
    is detected via the snapshot's `api_key_hashes` fingerprint and forced
    through `diff_desired(..., force_update=...)`, never by comparing keys
    here (#193). A key change therefore never shows up as a diff here, by
    design.

    Rule 1 holds on BOTH surfaces: keys litellm adds on its own - cost-map
    defaults, pydantic-defaulted params like `use_in_pass_through` that
    `updateLiteLLMParams` re-embodies on every PATCH - are never compared,
    so they can never churn the diff."""
    reg_info = entry.get("model_info")
    if not isinstance(reg_info, dict):
        reg_info = {}
    authored = {k: v for k, v in desired.model_info.items()
                if k != PROVENANCE_SYNCED_AT_KEY}
    subset = {k: _norm_value(reg_info[k]) for k in authored if k in reg_info}
    if subset != _norm_value(authored):
        return False
    reg_params = entry.get("litellm_params")
    if not isinstance(reg_params, dict):
        reg_params = {}
    desired_params = {k: v for k, v in desired.litellm_params.items()
                      if k != "api_key"}
    params = {k: _norm_value(reg_params[k]) for k in desired_params
              if k in reg_params}
    return params == _norm_value(desired_params)


def _registered_model_id(entry: dict) -> Any:
    """The litellm row identity (`model_id`) of a registered record.

    `/model/new` stores the generated uuid inside `model_info.id` (verified
    against the proxy DB 2026-08-17), and `/model/info` returns it there. The
    top-level `id` key of an info entry is a config-level presentation id and
    is IGNORED by the management API (the update/delete handlers look the row
    up by `model_info.id` only), so the info entry's nested id is the only
    reliable handle for update/delete. Falls back to the top-level key so
    non-DB deployments still resolve."""
    info = entry.get("model_info")
    if isinstance(info, dict) and info.get("id") is not None:
        return info["id"]
    return entry.get("id")


# --- The gateway management client ---------------------------------------------

class GatewayClient:
    """The litellm management API (1.96.0, `store_model_in_db: true`):
    `GET /model/info`, `POST /model/new`, `POST /model/update`,
    `POST /model/delete`. Any failure raises `SyncPushError` (hard)."""

    def __init__(self, base_url: str, api_key: str, *, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client  # injectable for the unit tier; built lazily

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _request(self, method: str, path: str, *, json: dict | None = None) -> httpx.Response:
        client = self._client
        try:
            if client is None:
                with httpx.Client(timeout=DEFAULT_FETCH_TIMEOUT_S) as owned:
                    response = owned.request(method, f"{self._base_url}{path}",
                                             json=json, headers=self._headers())
            else:
                response = client.request(method, f"{self._base_url}{path}",
                                          json=json, headers=self._headers())
            response.raise_for_status()
            return response
        except SyncPushError:
            raise
        except Exception as exc:
            raise SyncPushError(f"{method} {self._base_url}{path} failed: {exc}") from exc

    def list_models(self) -> list[dict]:
        response = self._request("GET", "/model/info")
        try:
            data = response.json()
        except Exception as exc:
            raise SyncPushError(f"GET /model/info failed: {exc}") from exc
        entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise SyncPushError("GET /model/info returned an unparseable body "
                                "(expected a 'data' list)")
        return entries

    def add_model(self, model_name: str, litellm_params: dict, model_info: dict) -> None:
        self._request("POST", "/model/new",
                      json={"model_name": model_name,
                            "litellm_params": litellm_params,
                            "model_info": model_info})

    def update_model(self, row_id: Any, model_name: str,
                     litellm_params: dict, model_info: dict) -> None:
        """Refresh a registered record via the DB-backed PATCH endpoint.

        The old `POST /model/update` only rewrites `litellm_params` and
        ignores `model_info`, so capability/provenance changes could never
        converge (and it looks the row up by `model_info.id`, which its
        pydantic schema fabricates as a random uuid when absent - always
        "model not found"). The PATCH endpoint (`/model/{model_id}/update`)
        persists both surfaces. `model_info.id` MUST echo the row's
        `model_id`: pydantic generates a NEW random uuid when the field is
        absent and the handler merges it in, corrupting the row identity
        (verified against litellm 1.96.0 2026-08-17)."""
        self._request("PATCH", f"/model/{row_id}/update",
                      json={"model_name": model_name,
                            "litellm_params": litellm_params,
                            "model_info": {**model_info, "id": row_id}})

    def delete_model(self, row_id: Any) -> None:
        self._request("POST", "/model/delete", json={"id": row_id})

    def upsert_snapshot(self, model_info: dict) -> None:
        """Persist the last-known-good snapshot under the pseudo-model record.
        `litellm_params` carries the `openai/`-prefixed marker model so
        `/model/new` accepts the deployment into the router (a bare marker
        string is unroutable and the proxy 500s - same failure mode as a real
        model, verified 2026-08-17); the record is never routed to."""
        params = {"model": f"{ROUTING_PROVIDER_PREFIX}{SNAPSHOT_MODEL_NAME}"}
        for entry in self.list_models():
            if entry.get("model_name") == SNAPSHOT_MODEL_NAME:
                self.update_model(_registered_model_id(entry), SNAPSHOT_MODEL_NAME,
                                  params, model_info)
                return
        self.add_model(SNAPSHOT_MODEL_NAME, params, model_info)

    def key_info(self, key: str) -> dict | None:
        """The stored virtual-key record for `key`, or None when absent.

        The proxy's inbound auth (user_api_key_auth) accepts only master_key
        and virtual keys from `LiteLLM_VerificationTokenTable`; the per-provider
        client keys (operator decision, ADR D3 note in test_llm_providers.py)
        must therefore be provisioned there or the client's bearer is a 401."""
        url = f"{self._base_url}/key/info?key={key}"
        try:
            if self._client is None:
                with httpx.Client(timeout=DEFAULT_FETCH_TIMEOUT_S) as owned:
                    response = owned.get(url, headers=self._headers())
            else:
                response = self._client.get(url, headers=self._headers())
        except Exception as exc:
            raise SyncPushError(f"GET /key/info failed: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SyncPushError(
                f"GET /key/info failed: HTTP {response.status_code}: "
                f"{response.text}")
        try:
            data = response.json()
        except Exception as exc:
            raise SyncPushError(f"GET /key/info failed: {exc}") from exc
        info = data.get("info") if isinstance(data, dict) else None
        if not isinstance(info, dict):
            raise SyncPushError("GET /key/info returned an unparseable body")
        return info

    def ensure_virtual_key(self, key: str, models: list[str]) -> None:
        """Make `key` a virtual key scoped to `models`, idempotently.

        Absent -> `POST /key/generate {key, models}`; present -> `POST
        /key/update {key, models}` ONLY when the stored scope differs (a
        converged run is a no-op, C9). The key VALUE is the provider's own
        API key, so the client's existing bearer just works (D3: the gateway
        holds upstream keys itself; the client key is an identity, not a
        credential here)."""
        desired = sorted(set(models))
        info = self.key_info(key)
        stored = set(info.get("models") or []) if info else None
        if stored is not None:
            if set(stored) == set(desired):
                return
            self._request("POST", "/key/update",
                          json={"key": key, "models": desired})
            return
        self._request("POST", "/key/generate",
                      json={"key": key, "models": desired})


# --- The pipeline (impure orchestrator) -----------------------------------------

def run_sync(*,
             fetch_catalog: Callable[[], dict] | None = None,
             fetch_provider_models: Callable[[str, str], set[str]] | None = None,
             gateway: GatewayClient | None = None,
             providers: dict[str, str] | None = None,
             read_api_key: Callable[[str], str | None] | None = None,
             synced_at: str | None = None) -> int:
    """Run the full D2/D9 pipeline once; return the exit code (0/1/2).

    Every collaborator is injectable (CODING_STANDARD §6) with a real,
    lazily-resolved default. All source failures are soft (exit 2, DB kept);
    a collapse, a management-API failure, or any unexpected error is hard
    (exit 1, push aborted); success is 0."""
    if providers is None:
        providers = PROVIDERS
    if read_api_key is None:
        read_api_key = provider_api_key
    if synced_at is None:
        synced_at = _now_iso()
    if gateway is None:
        key = master_key()
        if not key:
            logger.error(
                "sync HARD (exit %d): LITELLM_MASTER_KEY is not set - the sync "
                "cannot authenticate to the gateway management API; refusing to "
                "guess a gateway state (D9 cold stop)", SYNC_HARD)
            return SYNC_HARD
        gateway = GatewayClient(gateway_url(), key)
    if fetch_catalog is None:
        fetch_catalog = _fetch_catalog
    if fetch_provider_models is None:
        fetch_provider_models = _fetch_provider_model_ids

    try:
        catalog = fetch_catalog()
        provider_ids: dict[str, set[str]] = {}
        api_keys: dict[str, str] = {}
        for provider, base_url in providers.items():
            api_key = read_api_key(provider)
            if not api_key:
                logger.warning(
                    "skipping provider %s: no API key configured "
                    "(API_KEY_%s); its models are not synced", provider,
                    provider.upper())
                continue
            provider_ids[provider] = fetch_provider_models(provider, api_key)
            api_keys[provider] = api_key
        desired = build_desired(provider_ids, catalog, base_urls=providers,
                                api_keys=api_keys, synced_at=synced_at)
        registered = gateway.list_models()
        snapshot = read_snapshot(registered)
        validate_desired(desired, snapshot)  # raises SyncCollapseError (hard)

        # #193: the routing trio's api_key is masked in /model/info, so a
        # provider key rotation is invisible to the authored-surface diff. It
        # is tracked via the snapshot's per-provider key fingerprint: when a
        # provider's CURRENT env key differs from the key last applied, its
        # key-bearing models are force-refreshed (update path) so the gateway
        # re-encrypts and persists the new key.
        current_key_hashes = {provider: _key_hash(key)
                              for provider, key in api_keys.items()}
        providers_to_refresh = _providers_needing_refresh(snapshot,
                                                          current_key_hashes)
        force_update = {m.model_name for m in desired
                        if m.model_name.split("/", 1)[0] in providers_to_refresh}
        diff = diff_desired(desired, registered, force_update=force_update)
        unknown = [m.model_name for m in desired if not m.known]
        logger.info(
            "sync diff: %d add(s), %d update(s), %d delete(s); "
            "%d unknown-model gap(s): %s",
            len(diff.adds), len(diff.updates), len(diff.deletes),
            len(unknown), unknown)
        for model in diff.adds:
            gateway.add_model(model.model_name, model.litellm_params, model.model_info)
        for row_id, model in diff.updates:
            gateway.update_model(row_id, model.model_name,
                                 model.litellm_params, model.model_info)
        for row_id in diff.deletes:
            gateway.delete_model(row_id)

        # Provision the inbound client identity (D3): the proxy's auth accepts
        # only master_key + virtual keys, and the operator decision is that in
        # gateway mode the client presents the per-provider API key (pinned in
        # test_llm_providers.py). Make each provider key a virtual key scoped
        # to that provider's registered records - idempotent, converges to a
        # no-op (C9), and the client's existing bearer just works.
        for provider, api_key in api_keys.items():
            scoped = [m.model_name for m in desired
                      if m.model_name.startswith(f"{provider}/")]
            gateway.ensure_virtual_key(api_key, scoped)

        new_snapshot = Snapshot(
            desired_count=len(desired),
            desired_hash=desired_hash([m.model_name for m in desired]),
            api_key_hashes=current_key_hashes)
        if snapshot is None or (
                (snapshot.desired_count, snapshot.desired_hash,
                 snapshot.api_key_hashes) != (
                new_snapshot.desired_count, new_snapshot.desired_hash,
                new_snapshot.api_key_hashes)):
            gateway.upsert_snapshot({
                "desired_count": new_snapshot.desired_count,
                "desired_hash": new_snapshot.desired_hash,
                "api_key_hashes": new_snapshot.api_key_hashes,
                PROVENANCE_SOURCE_KEY: DEFAULT_REGISTRY_URL,
                PROVENANCE_SYNCED_AT_KEY: synced_at,
                PROVENANCE_STALENESS_KEY: STALENESS_FRESH,
            })
        logger.info("sync complete: %d desired record(s) reconciled "
                    "(last-known-good snapshot %d, %s)",
                    len(desired), new_snapshot.desired_count,
                    new_snapshot.desired_hash)
        return SYNC_OK
    except SyncCollapseError as exc:
        logger.error("sync HARD (collapse, exit %d): %s", SYNC_HARD, exc)
        return SYNC_HARD
    except SyncSourceError as exc:
        logger.error(
            "sync SOFT (source failure, exit %d): %s - skipping the push and "
            "keeping the gateway DB as-is (D9 fail toward staleness, the agent "
            "starts on last-known-good records)", SYNC_SOFT, exc)
        return SYNC_SOFT
    except SyncPushError as exc:
        logger.error("sync HARD (gateway management-API failure, exit %d): %s",
                     SYNC_HARD, exc)
        return SYNC_HARD
    except Exception as exc:  # noqa: BLE001 - an unexpected error is hard too
        logger.exception("sync HARD (unexpected error, exit %d): %s",
                         SYNC_HARD, exc)
        return SYNC_HARD


def main() -> int:
    """CLI entrypoint: configure logging, run the pipeline, return the code."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_sync()


if __name__ == "__main__":
    raise SystemExit(main())
