import os

from polymerhus.recon.domain.rate_limit import (
    PROFILE_TTL_DEFAULT_S,
    RateLimitSafetyBudget,
)
from polymerhus.recon.domain.traffic_admission import TrafficAdmissionSettings

MAX_POD_ITERS = int(os.environ.get("MAX_POD_ITERS", "3"))
EXEC_TIMEOUT_S = int(os.environ.get("EXEC_TIMEOUT_S", "300"))
# Per-job CONCURRENCY ceiling: the max number of pods a job runs at once. A job
# processes ALL its input assets (up to MAX_JOB_ASSETS), MAX_PODS at a time, in
# waves - it is NOT a cap on how many assets are covered. Bounding concurrency
# (not coverage) is what keeps peak CPU/mem/sockets in check.
MAX_PODS = int(os.environ.get("MAX_PODS", "20"))
# Per-job total-work budget: the max input assets a single job will process,
# distinct from MAX_PODS. A deliberate safety cap so a pathological input (e.g.
# a 41k-subdomain org) cannot spawn unbounded pods; normal runs sit well under
# it and are fully covered. Raise for exhaustive scans.
MAX_JOB_ASSETS = int(os.environ.get("MAX_JOB_ASSETS", "500"))

# Crawl depth for `katana -d N`. The operator default stays 1 - see the long
# rationale above the `JOBS["katana"]` command template (depth 3 on a large
# catalog blows past EXEC_TIMEOUT_S, so the pod returns nothing at all), and
# depth is meant to become a per-pod configurator decision. Until then this is
# the ONE knob a deliberate deep-crawl experiment raises, instead of editing the
# template: set `KATANA_DEPTH=3` in the environment BEFORE the process imports
# `polymerhus.recon.control.jobs` - `JOBS` is built at import time, so setting
# it on an already-running agent (or an already-imported test process) is
# inert. It is a string, not an int: the template is assembled by
# concatenation (see jobs.py), and an int would need a cast at the one place
# that must never raise at import. Validated like every other knob here: a
# bad value is a loud ValueError at boot, never a mangled crawl command.
_KATANA_DEPTH = os.environ.get("KATANA_DEPTH", "1")
if not _KATANA_DEPTH.isdigit() or int(_KATANA_DEPTH) < 1:
    raise ValueError(f"KATANA_DEPTH must be a positive integer, got {_KATANA_DEPTH!r}")
KATANA_DEPTH = _KATANA_DEPTH

# #196 capture for recon pods: does a recon pod hand its project/run/spec
# identity to the kali terminal, so every HTTP request the scanning phase makes
# is recorded in the project's history store and can be reproduced later?
#
# ON by default, deliberately: the failure this closes is silent - a run whose
# traffic was never recorded cannot be replayed, debugged or reproduced, and the
# loss is discovered too late to fix. Two operational consequences are the
# operator's to own, and both are visible rather than hidden:
#   - each pod now egresses through a leased namespace and the recording proxy,
#     so the target sees the proxy's TLS fingerprint (design doc, Parte B) and
#     the crawl pays the proxy's latency;
#   - `KALI_HTTP_NAMESPACE_POOL` bounds how many pods can be captured at once.
#     Beyond it the exec degrades fail-open to an uncaptured run and says so in
#     `recon_jobs.stats[].capture`, never silently.
# Set `POD_HTTP_CAPTURE=0` in the agent environment (before the process starts -
# the pod graph reads this at import) to turn it off for a deployment.
POD_HTTP_CAPTURE = os.environ.get("POD_HTTP_CAPTURE", "1").strip().lower() not in (
    "0", "false", "no", "off",
)

# steel.dev cloud-browser credential. The steel_* crawl tools drive a
# steel.dev session via Playwright-over-CDP (see src/polymerhus/recon/crawl/steel_client.py);
# there is NO remote MCP host URL - the tool provider is instantiated in-process.
STEEL_API_KEY = os.environ.get("STEEL_API_KEY", "")
CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
CRAWL_MAX_DEPTH = int(os.environ.get("CRAWL_MAX_DEPTH", "3"))
CRAWL_MAX_ITERS = int(os.environ.get("CRAWL_MAX_ITERS", "30"))
CRAWL_JOB_TIMEOUT_S = int(os.environ.get("CRAWL_JOB_TIMEOUT_S", "480"))


# --- #238 rate-limit safety budget -------------------------------------------------
#
# The operator's HARD ceiling on the post-authentication rate-mapping turn: how
# many requests it may send, for how long, at what rate and concurrency, and
# whether it may probe client-identity mutations at all. The deterministic
# controller admits every experiment against this budget and can only consume
# it - no model-facing type carries a number that could enlarge it.
#
# Parsed ONCE, here, at import (the KATANA_DEPTH contract): an invalid or
# non-positive value raises at boot rather than being silently repaired at run
# time, because a silently-loosened safety budget is exactly the failure this
# knob exists to prevent. The defaults live on `RateLimitSafetyBudget` so the
# documented budget and this boundary cannot drift; `RATE_LIMIT_PROFILE_TTL_S`
# does the same from `PROFILE_TTL_DEFAULT_S`.
#
# `RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS` is OFF by default: client-IP and
# forwarded-header identity mutations are probed only on an explicit operator
# opt-in (spec, resolved decision 9).
#
# `RATE_LIMIT_AWAIT_TIMEOUT_S` bounds the WAIT for the rate turn's reply, not
# the turn itself: a hung or wrong-schema turn is drained and the run continues
# under the conservative fallback profile, never unthrottled. It is sized above
# any legitimate mapping span (the experiment budget, not the model, owns how
# long mapping takes).
_DEFAULT_RATE_LIMIT_BUDGET = RateLimitSafetyBudget()


def _rate_limit_int(name: str, default: int, *, minimum: int) -> int:
    """One integer knob, validated at the configuration boundary: a non-numeric
    or out-of-range value raises `ValueError` naming the variable."""
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {raw!r}")
    return value


def _rate_limit_float(name: str, default: float, *, minimum: float) -> float:
    """One float knob, validated the same way (`minimum` is exclusive-when-
    positive semantics: these knobs are all "must be greater than zero")."""
    raw = os.environ.get(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if not value > minimum:
        raise ValueError(f"{name} must be > {minimum}, got {raw!r}")
    return value


def _rate_limit_bool(name: str, default: bool) -> bool:
    """One boolean knob: only the documented true/false spellings are accepted,
    so an ambiguous value (`sometimes`) fails loudly instead of defaulting."""
    raw = os.environ.get(name, "true" if default else "false").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


RATE_LIMIT_MAX_REQUESTS = _rate_limit_int(
    "RATE_LIMIT_MAX_REQUESTS", _DEFAULT_RATE_LIMIT_BUDGET.max_requests, minimum=1
)
RATE_LIMIT_MAX_DURATION_S = _rate_limit_float(
    "RATE_LIMIT_MAX_DURATION_S", _DEFAULT_RATE_LIMIT_BUDGET.max_duration_s,
    minimum=0.0,
)
RATE_LIMIT_MAX_RATE = _rate_limit_float(
    "RATE_LIMIT_MAX_RATE", _DEFAULT_RATE_LIMIT_BUDGET.max_rate_per_s, minimum=0.0
)
RATE_LIMIT_MAX_CONCURRENCY = _rate_limit_int(
    "RATE_LIMIT_MAX_CONCURRENCY", _DEFAULT_RATE_LIMIT_BUDGET.max_concurrency,
    minimum=1,
)
RATE_LIMIT_MAX_BYPASS_VARIANTS = _rate_limit_int(
    "RATE_LIMIT_MAX_BYPASS_VARIANTS",
    _DEFAULT_RATE_LIMIT_BUDGET.max_bypass_variants,
    minimum=0,
)
RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS = _rate_limit_bool(
    "RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS",
    _DEFAULT_RATE_LIMIT_BUDGET.allow_identity_mutations,
)
RATE_LIMIT_AWAIT_TIMEOUT_S = _rate_limit_float(
    "RATE_LIMIT_AWAIT_TIMEOUT_S", 1800.0, minimum=0.0
)
RATE_LIMIT_PROFILE_TTL_S = _rate_limit_int(
    "RATE_LIMIT_PROFILE_TTL_S", int(PROFILE_TTL_DEFAULT_S), minimum=1
)

# --- #238 follow-up: job-admission thresholds --------------------------------
#
# The controller's deterministic admission thresholds, parsed ONCE here at the
# configuration boundary (the KATANA_DEPTH / rate-limit-budget contract): an
# invalid or non-positive value fails the boot loudly rather than being
# silently repaired, because a silently-loosened safety threshold is exactly
# the failure this knob exists to prevent. The deterministic admission
# controller reads THIS value object and records the effective values it used
# with every run (spec section 6).
TRAFFIC_ADMISSION_SETTINGS = TrafficAdmissionSettings.from_env()


def rate_limit_safety_budget() -> RateLimitSafetyBudget:
    """The operator's typed safety budget, built from the knobs above.

    The single constructor every rate-mapping collaborator reads: the
    controller admits experiments against THIS value, and `RateProfile`
    records it verbatim. Pure after import - it only assembles already-parsed
    values, so calling it twice is cheap and side-effect free."""
    return RateLimitSafetyBudget(
        max_requests=RATE_LIMIT_MAX_REQUESTS,
        max_duration_s=RATE_LIMIT_MAX_DURATION_S,
        max_rate_per_s=RATE_LIMIT_MAX_RATE,
        max_concurrency=RATE_LIMIT_MAX_CONCURRENCY,
        max_bypass_variants=RATE_LIMIT_MAX_BYPASS_VARIANTS,
        allow_identity_mutations=RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS,
    )
