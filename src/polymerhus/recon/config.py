import os

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
