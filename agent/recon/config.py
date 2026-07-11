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

# steel.dev cloud-browser credential. The steel_* crawl tools drive a
# steel.dev session via Playwright-over-CDP (see agent/recon/crawl/steel_client.py);
# there is NO remote MCP host URL - the tool provider is instantiated in-process.
STEEL_API_KEY = os.environ.get("STEEL_API_KEY", "")
CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
CRAWL_MAX_DEPTH = int(os.environ.get("CRAWL_MAX_DEPTH", "3"))
CRAWL_MAX_ITERS = int(os.environ.get("CRAWL_MAX_ITERS", "30"))
CRAWL_JOB_TIMEOUT_S = int(os.environ.get("CRAWL_JOB_TIMEOUT_S", "480"))
