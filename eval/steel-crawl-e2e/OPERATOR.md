# Steel-crawl live e2e - operator runbook

This directory is the host-side scaffold for the three live `steel_crawl` walkthroughs.
The crawl runs inside the deployed agent container; only the target stack, the Steel session, and the assertions are outside it.
The assertions are in `ASSERTIONS.md`; the executable walkthroughs are in `tests/e2e/test_steel_crawl_e2e.py`.

## 1. What must exist on the eval server

- The instance stack `ph-dd131acc` with `agent`, `kali`, `postgres`, `neo4j`, and the shared front `ph-eval-front`.
- The three target images under `ph/webexploitbench/{comfyui,prestashop,siyucms}:*` and the `/root/WebExploitBench` checkout (the `targetctl` runner).
- `/root/eval-dd/data/<target>/{operator_kb.md,auth/overview.yaml,auth/credentials.yaml,skills/authn/}`.
- The Steel runtime at `192.33.91.87:3000`; the instance `.env` carries `STEEL_API_KEY`, `STEEL_BROWSER_API_URL`, and `API_KEY_TYPESAFE`.
- The front alias `t-1618c524.target` resolvable from the Steel runtime. The scaffold swaps the front upstream per target and restores the White Jotter conf.

The scaffold refuses a missing target, a missing data dependency, a missing Steel session, or a missing Agent container; it never substitutes a mock.

## 2. Prepare the host Python

The host test needs `pytest`, `httpx`, and `PyYAML`.
The eval venv already has `PyYAML`; install the other two:

```
/opt/eval-venv/bin/pip install pytest httpx
```

The test imports only stdlib plus those packages; the crawl code runs inside the agent.

## 3. Sync this worktree to the eval server

From the development host (the worktree root):

```
rsync -a --delete \
  --exclude .git --exclude .venv --exclude __pycache__ \
  ./ eval-server-polyphemus:/opt/steel-crawl-e2e/
```

The scaffold copies `/opt/steel-crawl-e2e` into the agent container on every run.
It also copies the pinned Steel CLI from the kali container into the agent at `/opt/localbin/steel` and `/opt/localbin/steel-real`.

## 4. Run one target

```
ssh eval-server-polyphemus
cd /opt/steel-crawl-e2e
STEEL_CRAWL_E2E=1 STEEL_CRAWL_E2E_REPO=/opt/steel-crawl-e2e \
  /opt/eval-venv/bin/python -m pytest \
  tests/e2e/test_steel_crawl_e2e.py -k comfyui -s \
  --confcutdir=/opt/steel-crawl-e2e/tests/e2e
```

Repeat with `-k prestashop` and `-k siyucms`.
The scaffold starts the target, mints the session, places the AuthContext and skill, runs the phase, asserts, then restores the front and stops the session.
`STEEL_CRAWL_E2E_KEEP=1` keeps the target stack and the session for inspection; the next run must stop them manually.

The action cap is `STEEL_CRAWL_MAX_ACTIONS` (default 300); the crawl deadline is `STEEL_CRAWL_MAX_DURATION_S` (default 900).

## 5. What the run does

1. `targetctl up <target>` and wait for the published port; the shared front is repointed to it (for PrestaShop the proxy keeps `Host prestashop` and rewrites the absolute `http://prestashop` URLs to the alias).
2. `POST /projects`, `PUT /settings` with `target_seed=t-1618c524.target`.
3. The Steel session is started **in the agent container**, not in Kali: the CLI's session catalogue is daemon-scoped, so a session minted in Kali is invisible to the crawl's CLI.
4. The target-specific bootstrap:
   - ComfyUI: root navigation only (no auth surface).
   - SiyuCMS: admin form login with the session-bound `__token__`; the browser keeps the rotated `PHPSESSID`.
   - PrestaShop: the runtime repair below, then the application's own `Cookie`/`EmployeeSession` classes mint the address-bound back-office cookie; the browser sets it.
5. The oracle fetch is verified; the session context is captured; the server AuthContext and the project `authn` skill are updated.
6. The four data-dependency endpoints place the overview, credentials, skill, and L1.
7. The phase runner starts the loopback HTTP-history edge, seeds the BaseURL, and runs `run_pipeline(..., job_subset=["steel_crawl"], with_analysis=False)` in the agent.
8. The runner returns the pipeline run/jobs and the edge store status; the host copies the manifest, summary, and ledger.
9. The assertions read the graph and the auth store through the app API, and the Steel catalogue after the stop.

### 5.1 PrestaShop target runtime repair (setup, not crawl behaviour)

A fresh PrestaShop target answers 500 on every modern admin controller until three target-side conditions hold:

1. **The Symfony cache is writable by `www-data`.** The cache is `/var/www/html/var/cache/prod`. Run `create-employee.php` and `mint-bo-session.php` as `www-data` (`docker exec -u www-data -e HOME=/tmp`). Running them as root leaves the cache root-owned and the controllers fail with `Unable to write in the "cache" directory`.
2. **PHP's execution limit covers the first compile.** `/usr/local/etc/php/php.ini` sets `max_execution_time = 30`; the first authenticated admin request compiles the Symfony container for about 100 s on the emulated amd64 host. The scaffold raises the limit to 300 s and restarts the web container.
3. **The first request is warmed in-container.** The Steel CLI's CDP navigate has a fixed, shorter command timeout, so the scaffold warms the entry page as `www-data` with the minted cookie and the front-reported egress as `X-Forwarded-For` before the browser navigates. The warm request builds the container; the crawl then traverses a warm target.

The shop domain stays `prestashop`; changing `PS_SHOP_DOMAIN` or `ps_shop_url` breaks server-side resolution. The front alias handles the host rewrite. The cookie is minted for the Steel egress (`192.33.91.87`), which `Tools::getRemoteAddr` trusts through `X-Forwarded-For`; the address-bound cookie then matches the browser's requests.

## 6. Failure branches

- The target stack does not answer: `targetctl ps <target>` and the container logs; the scaffold restores the front in `finally`.
- The Steel session is not live: `steel browser sessions --json` in the **agent** container; the scaffold never starts a replacement after a failed bootstrap.
- The PrestaShop admin page answers 500: check the three conditions above. A 30 s timeout in the Apache log is the PHP limit; `Unable to write in the "cache" directory` is the ownership; a cold compile during the browser navigate is the missing warm-up.
- The PrestaShop cookie lands on `AdminLogin`: the cookie's `remote_addr` does not match the request's `X-Forwarded-For`. Read the front's `/_ip` (the Steel egress) and mint with that value. The scaffold does this automatically.
- The oracle probe redirects: PrestaShop's legacy controllers can 302 to a tokenised Symfony route. The probe is the stable `AdminDashboard` page; a legacy controller that redirects is not a valid oracle.
- The auth gateway fails: read the recon job stats and the run status; the gateway is fail-closed, so the crawl does not run anonymously.
- The edge flush fails: the manifest is marked partial; the run result carries `http_history_flush_failed`.
- The crawl hits the action cap: `stop_reason=operator_cancel` and `partial=true`; the scaffold asserts exactly `STEEL_CRAWL_MAX_ACTIONS` actions. The wall-clock stop is `session_deadline` and is also accepted.
