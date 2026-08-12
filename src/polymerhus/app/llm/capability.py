"""The capability-profile reader (#106 - T3 of the #100 LLM API gateway programme).

Realises ADR D5 Rule 1 (provenance-gated trust), D6 (resolution order + the
typed profile), D7 (client-side, fail-open, resolve-and-hold, off the retry
axis), and the D11 reasoning-replay surface (ADR `llm-gateway-100-decisions.md`).

Surface for #95 (context-window auto-compact) and #99 (capability-adaptive
client). NOT consumed by `build_chat_model` (that seam is T4, #107); nothing
wires this reader into session construction in this ticket.

Properties, per D7:

- **client-side**: lives in `app/llm` (a helper module, never a bounded
  context - CONTEXT-MAP ruling), NOT in the gateway - the gateway stays
  harness-agnostic (D3).
- **fail-open** (D7): a missing or unreachable gateway degrades to the
  env -> default chain and NEVER raises into the session construction path;
  the gap is logged (surfaced for the sync's notification path, D9).
- **provenance-gated** (D5 Rule 1): the reader trusts a record's capability
  fields only when the record carries our `capability_source` provenance tag
  (authored by the sync, T2 `sync_mapping.py`). A record without the tag, or
  a field absent from a tagged record, is `unknown` - encoded as `None` (the
  absence of an authored field), treated as `false` for capability gating
  (spec §5), surfaced for logging. `unknown` is never encoded as a value.
- **resolve-and-hold**: resolved once per (provider, model) and held for the
  PROCESS lifetime (operator refinement 2026-08-11: the read occurs at
  bootstrap and capabilities remain static - a strict superset of the per-
  `SessionContext` cache the ticket letter named; every session shares the
  held profile, never re-queried mid-session).
- **off the retry axis**: a SINGLE synchronous read. Never wrapped in
  `invoke_with_escalating_timeout`, never nested in the #73 retry - not even
  a failed read is re-attempted (the held degraded result stands; a retry
  here re-creates the #32 multiplied-retry defect).

Resolution order (D6), for `context_limit`:
1. gateway `/model/info` -> `model_info.max_input_tokens` (provenance-tagged)
2. `LLM_ROLE_MODEL_CONTEXT_LIMIT` env override - an UNUSABLE value (not a
   positive int) raises `LLMConfigError` (operator ruling 2026-08-11: a config
   lie fails fast, per the `providers.py` precedent; the app-module config
   validation component #112 catches it at control-plane launch) - never the
   reverse order, so a stale env value can never shadow a fresh synced record
3. 150k default (spec §5; the SwissAI-is-not-on-models.dev gap takes this).

`output_limit` has NO env fallback (D6): it resolves gateway-only
(`max_output_tokens`) and is `None` when missing - the consumer (#95) decides.

D11 reasoning-replay surface: `reasoning_in_response` (bool) and
`reasoning_field` (`reasoning_content` | `reasoning_details`) are read from
the tagged record exactly like the window fields (Rule 1: absent tag or
absent field = `None`, never asserted). There is NO reasoning-CACHING field
on the profile (D11 grey point - unassertable from the registry; runtime
cache-hit tracking is T6's work).

Wire shape: the /model/info bodies read here are exactly what the sync (T2,
`sync_mapping.py`) authors - provenance keys `capability_source` /
`capability_synced_at` / `capability_staleness`, the D5 mapped fields
`max_input_tokens` / `max_output_tokens`, the D11 keys, and the slash-form
registered model name `<provider>/<id>` (zen-family id stripped) - which is
also the reader's lookup key. The gateway is the co-located litellm proxy
(D1); `/model/info` is litellm's standard `{"data": [{"model_name": ...,
"model_info": {...}}]}` surface, auth'd with `LITELLM_MASTER_KEY` when set.

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6): the gateway URL, the master key, and the HTTP client resolve on
call, never at import.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from polymerhus.app.llm.providers import LLMConfigError, _ZEN_FAMILY

logger = logging.getLogger(__name__)

# --- The D5 provenance keys the reader gates on (authored by T2
# `sync_mapping.py`; the exact names are load-bearing). The third key,
# `capability_staleness`, rides on the wire but is NOT surfaced on the
# profile (D6: `source` / `synced_at` carry the provenance). ---------------
PROVENANCE_SOURCE_KEY = "capability_source"
PROVENANCE_SYNCED_AT_KEY = "capability_synced_at"

# The registered-name prefix used for slash-form lookup keys.
SLASH_SEP = "/"

# D6 step 3: the conservative default covering the SwissAI-is-not-on-models.dev
# gap (spec §5).
DEFAULT_CONTEXT_LIMIT = 150_000

# The context-limit env override (D6 step 2; beats the default only when the
# gateway is silent). Unusable (non-positive-int) values fail fast - LLMConfigError.
CONTEXT_LIMIT_ENV = "LLM_ROLE_MODEL_CONTEXT_LIMIT"

GATEWAY_URL_ENV = "LLM_GATEWAY_URL"
MASTER_KEY_ENV = "LITELLM_MASTER_KEY"

# A single bounded read budget for the metadata GET. Short by design: this is
# a one-shot capability probe inside the same container (D1), NOT a generation
# call - a hung metadata read must not park session construction; fail-open
# turns any timeout into the env -> default chain.
MODEL_INFO_TIMEOUT_S = 10.0
MODEL_INFO_CONNECT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class CapabilityProfile:
    """The typed per-(provider, model) capability profile (D6/D11).

    Every field is `None` when UNKNOWN per D5 Rule 1 - `unknown` is never
    encoded as a value, it is the absence of an authored field. Consumers
    treat `None` as `false` for capability gating (spec §5) and surface it
    for logging.

    - `context_limit` / `output_limit`: the model's input/output window in
      tokens; `output_limit` has NO env fallback (resolves `None` when the
      gateway lacks it; #95 decides).
    - `source` / `synced_at`: full provenance (`capability_source` /
      `capability_synced_at`) for logging and staleness; `source` may be the
      literal `"unknown"` (D9 unknown-model path).
    - `reasoning_in_response` / `reasoning_field` (D11): whether reasoning
      tokens come back in the response and under which field - the reasoning-
      replay surface, provenance-gated exactly like the window fields.
      NO reasoning-CACHING field here (D11 grey point; T6's work).
    """

    context_limit: int | None = None
    output_limit: int | None = None
    source: str | None = None
    synced_at: dt.datetime | None = None
    reasoning_in_response: bool | None = None
    reasoning_field: str | None = None


# The process-lifetime hold (resolve-and-hold, D7): one resolution per
# (provider, model), never re-queried. Every session shares the held profile.
_PROFILE_CACHE: dict[tuple[str, str], CapabilityProfile] = {}


def _registered_name(provider: str, model: str) -> str:
    """The gateway lookup key - the T2 registered-name convention (D5 model_id
    row): `<provider>/<id>` with the zen-family id stripped (the strip moves
    from `build_chat_model` into the mapping layer in gateway mode)."""
    if provider in _ZEN_FAMILY:
        model = model.rsplit(SLASH_SEP, 1)[-1]
    return f"{provider}{SLASH_SEP}{model}"


def _gateway_url() -> str | None:
    url = os.environ.get(GATEWAY_URL_ENV)
    return url.strip().rstrip(SLASH_SEP) if url and url.strip() else None


def _master_key() -> str | None:
    key = os.environ.get(MASTER_KEY_ENV)
    return key.strip() if key and key.strip() else None


def _context_env_override() -> int | None:
    """D6 step 2: the env override, validated fail-fast (operator ruling
    2026-08-11). Absent/empty -> None (fall to the 150k default). An unusable
    value is a config lie - it fails fast rather than silently degrading."""
    raw = os.environ.get(CONTEXT_LIMIT_ENV)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        raise LLMConfigError(
            f"{CONTEXT_LIMIT_ENV} must be a positive integer number of tokens "
            f"(got {raw!r})"
        ) from None
    if value <= 0:
        raise LLMConfigError(
            f"{CONTEXT_LIMIT_ENV} must be a positive integer number of tokens "
            f"(got {raw!r})"
        )
    return value


def _parse_synced_at(raw: Any) -> dt.datetime | None:
    """Parse T2's ISO-8601 `capability_synced_at` string into a datetime.
    Unparsable -> None (unknown), logged - a bad timestamp degrades the
    provenance display, never the capability fields."""
    if raw is None:
        return None
    if isinstance(raw, dt.datetime):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return dt.datetime.fromisoformat(raw.strip())
    except ValueError:
        logger.warning("capability record carries an unparsable %s (%r); "
                       "treating synced_at as unknown",
                       PROVENANCE_SYNCED_AT_KEY, raw)
        return None


def _typed_positive_int(value: Any) -> int | None:
    """A wire value usable as an int token limit (bool is rejected - bool is
    an int subclass), or degradation to unknown (None) when the wire carries
    a wrong-typed value. The wire is untrusted; a wrong type must degrade,
    never leak into the typed profile contract (#95/#99 consume)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _typed_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _typed_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _profile_from_record(provider: str, model: str, body: Any) -> CapabilityProfile | None:
    """Build the profile from a /model/info body for the given (provider,
    model); None when the gateway answers but holds no matching record.

    Rule 1: the record's capability fields are trusted ONLY when the record
    carries `capability_source`; a tagged record's ABSENT fields are unknown.
    Fields whose wire value is wrong-typed also degrade to unknown (the typed
    contract is protected at this boundary). `capability_staleness` is not
    surfaced on the profile (D6: `source` / `synced_at` carry the provenance
    for logging/staleness)."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        logger.warning("capability gateway answered a /model/info body without "
                       "a 'data' list; resolving unknown")
        return None
    key = _registered_name(provider, model)
    for record in data:
        if not isinstance(record, dict) or record.get("model_name") != key:
            continue
        info = record.get("model_info")
        if not isinstance(info, dict) or PROVENANCE_SOURCE_KEY not in info:
            logger.warning(
                "capability record %s carries no %s tag (litellm bundled "
                "defaults?); rule 1: trusting nothing - resolving unknown",
                key, PROVENANCE_SOURCE_KEY)
            return CapabilityProfile()
        synced_at = _parse_synced_at(info.get(PROVENANCE_SYNCED_AT_KEY))
        profile = CapabilityProfile(
            context_limit=_typed_positive_int(info.get("max_input_tokens")),
            output_limit=_typed_positive_int(info.get("max_output_tokens")),
            source=_typed_str(info[PROVENANCE_SOURCE_KEY]),
            synced_at=synced_at,
            reasoning_in_response=_typed_bool(info.get("reasoning_in_response")),
            reasoning_field=_typed_str(info.get("reasoning_field")),
        )
        return profile
    logger.warning("no gateway capability record for %s; resolving unknown", key)
    return None


def _fetch_model_info(url: str, key: str | None, http: httpx.Client) -> Any:
    """The ONE synchronous read: GET /model/info, bearer-auth'd when a master
    key is set. Bounded by a short budget; the caller fail-opens on anything
    this raises."""
    headers = {}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    resp = http.get(f"{url}/model/info", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"/model/info answered HTTP {resp.status_code}")
    return resp.json()


def resolve_capability(
    provider: str,
    model: str,
    *,
    http: httpx.Client | None = None,
) -> CapabilityProfile:
    """Resolve the capability profile for (provider, model) - resolve-and-hold.

    One synchronous read per (provider, model), then held for the process
    lifetime: a second call returns the SAME held profile, even when the first
    resolution degraded (off the #73 retry axis - a failed read is never
    re-attempted here). The gateway is consulted only when `LLM_GATEWAY_URL`
    is set; any gateway failure (unreachable, non-200, malformed, unregistered
    model) degrades silently to the env -> default chain with the gap logged;
    the session can always start. The only raise is `LLMConfigError` for an
    unusable `LLM_ROLE_MODEL_CONTEXT_LIMIT` override (a config lie, caught at
    control-plane launch by #112).

    `http` accepts any client exposing `.get(url, headers=...)` (an
    `httpx.Client`); tests inject a fake - the unit tier touches no live
    gateway. Resolution order (D6): gateway -> env -> 150k default for
    `context_limit`; gateway -> None for `output_limit`. Auth: bearer
    `LITELLM_MASTER_KEY` when set, never hardcoded, never logged."""
    cached = _PROFILE_CACHE.get((provider, model))
    if cached is not None:
        return cached

    url = _gateway_url()
    profile = None
    if url is not None:
        try:
            body = _fetch_model_info(url, _master_key(), http or httpx.Client(
                timeout=httpx.Timeout(
                    MODEL_INFO_TIMEOUT_S,
                    connect=min(MODEL_INFO_CONNECT_TIMEOUT_S, MODEL_INFO_TIMEOUT_S)),
            ))
            profile = _profile_from_record(provider, model, body)
        except Exception as exc:  # noqa: BLE001 - fail-open: NEVER into session construction
            logger.warning(
                "capability gateway %s unreachable/unusable for %s: %s; "
                "degrading to env -> default (session must start)",
                url, _registered_name(provider, model), exc)

    if profile is not None and profile.context_limit is not None:
        context_limit = profile.context_limit
    else:
        context_limit = _context_env_override() or DEFAULT_CONTEXT_LIMIT
        if profile is not None and profile.context_limit is None:
            logger.warning(
                "capability record for %s lacks max_input_tokens (unknown per "
                "rule 1); context_limit resolved from env/default (%d)",
                _registered_name(provider, model), context_limit)

    held = CapabilityProfile(
        context_limit=context_limit,
        output_limit=profile.output_limit if profile is not None else None,
        source=profile.source if profile is not None else None,
        synced_at=profile.synced_at if profile is not None else None,
        reasoning_in_response=profile.reasoning_in_response if profile is not None else None,
        reasoning_field=profile.reasoning_field if profile is not None else None,
    )
    _PROFILE_CACHE[(provider, model)] = held
    return held