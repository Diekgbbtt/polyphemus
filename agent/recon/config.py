import os

MAX_POD_ITERS = int(os.environ.get("MAX_POD_ITERS", "3"))
EXEC_TIMEOUT_S = int(os.environ.get("EXEC_TIMEOUT_S", "300"))
MAX_PODS = int(os.environ.get("MAX_PODS", "20"))

# steel.dev cloud-browser credential. The steel_* crawl tools drive a
# steel.dev session via Playwright-over-CDP (see agent/recon/crawl/steel_client.py);
# there is NO remote MCP host URL - the tool provider is instantiated in-process.
STEEL_API_KEY = os.environ.get("STEEL_API_KEY", "")
CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
CRAWL_MAX_DEPTH = int(os.environ.get("CRAWL_MAX_DEPTH", "3"))
CRAWL_MAX_ITERS = int(os.environ.get("CRAWL_MAX_ITERS", "30"))
CRAWL_JOB_TIMEOUT_S = int(os.environ.get("CRAWL_JOB_TIMEOUT_S", "480"))
