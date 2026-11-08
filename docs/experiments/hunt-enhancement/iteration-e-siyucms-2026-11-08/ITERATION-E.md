# Iteration E - the full local Steel pool on siyucms

*Status: planned, 2026-11-08. Run state and results are filled progressively.*

## What this iteration changes

The dev branch now carries the converged local Steel pool:

- one agent-facing `browser` tool with `start`, `exec`, and `end`;
- the pool manager and two `steel-worker` replicas on the instance compose
  network;
- the deterministic `steel_crawl` engine over the same pool MCP;
- the decoupled auth context (`accounts.<account>.browser_context.ref`) and
  the session-only state (cookies, localStorage, sessionStorage, indexedDB);
- no SSH tunnel, no Docker-socket tunnel, and no remote pool host.

This leg evaluates those changes qualitatively on a target that was never
part of the pool E2E: `siyucms` (SIYUCMS 6.1.8, ThinkPHP 6).

## Question

Does the full local Steel pool produce a usable browser tool and a usable
deterministic crawl on a real target, without the Steel cloud, and does the
decoupled auth context survive the gateway-to-crawl handoff?

The evaluation is qualitative.
The standard workbench metrics are reported beside it, but they are not the
gate.

## Hypothesis

The local pool should:

- boot both workers and discover them from Kali (`pool.discovered` with the
  configured replica count);
- serve the one `browser` tool through `start`, `exec`, and `end`, with no
  worker URL or session name reaching the model;
- restore the siyucms admin context in the crawl and pass the recorded
  `auth_probe` oracle;
- make `steel_crawl` reach the authenticated admin surface that katana and
  jsluice cannot see, and leave a manifest with a terminal stop reason;
- stop and release every session at `end`, with no leaked live session and
  no pool exhaustion.

## Design

| Item | Value |
|---|---|
| Arm | single arm, qualitative |
| Instance | `eval-server-2` |
| Target | `webexploitbench/siyucms` as `siyucms-web` |
| Start phase | `recon` (fresh project) |
| Data dependencies | `/root/eval-dd/data/siyucms` (auth, authn skill, KB) |
| Recon jobs | `httpx, httpx_reprofile, katana, jsluice, arjun, steel_crawl` |
| Code identity | the `eval-e` branch at the run commit, recorded in `trial.yaml` |
| Bring-up | one operator `up`; the trial runs with `--skip-up`, so it never recreates the target |
| Browser context | the preflight mints the admin session after the up and seeds the deterministic context ref |
| Thinking effort | design roles `max`, pod roles `high` (C.a patch) |
| Pod watchdog | `HUNT_POD_SESSION_TIMEOUT_S=5400` |
| Skill evolution | `SKILL_EVOLUTION_ENABLED=0` |
| Token budget | 7,000,000 capped |
| Trial clock | 24 hours; the token cap is the real bound |

## Frozen policy

```text
pipeline_sync            batched
pod_batch_size           2
promotion_risk_threshold 2.5
risk_threshold           156.25
token_budget             7000000
```

## First work item: the data-dependency alignment

The siyucms auth data dependency still carried the retired steel profile.

The live files and their pre-iteration backups:

| Live path | Backup |
|---|---|
| `/root/eval-dd/data/siyucms/auth/credentials.yaml` | `credentials.yaml.pre-iteration-e` |
| `/root/eval-dd/data/siyucms/skills/authn/SKILL.md` | `SKILL.md.pre-iteration-e` |

The alignment:

- `accounts.admin-first_authn_bootstrap.steel.state` became
  `accounts.admin-first_authn_bootstrap.browser_context.ref =
  steel-auth-siyucms-web-admin-first-authn-bootstrap`;
- the admin account is asserted `valid` after the preflight's oracle; the
  member account is `not_valid` for the browser candidate because it holds no
  decoupled context, while its request material remains;
- the admin snapshot was cleaned to the siyucms `PHPSESSID` only.
  The `cf_clearance`, `PrestaShop-*`, and `thinkphp_show_page_trace` cookies
  were leftovers from the C.a target substitution and did not belong to this
  target;
- the authn skill lost its nine stale live-session overlays and gained one
  browser-session section.
  The sign-in procedures remain request-replayable.
- `overview.auth_probe.url` was already
  `/index.php/admin/Index/index.html`.

The versioned, sanitised copy is under `data-dependencies/`.
The live files hold the secrets.

The setup records this as the first work item, `steel-browser-sessions`.

## Surfaces under test

- **Pool boot.** The Kali entrypoint starts the browser MCP; the pool manager
  discovers both `steel-worker` replicas and reports `pool.discovered`.
- **One browser tool.** The auth gateway and the hunting roles bind the single
  `browser` tool.
  The model never sees a session name, a worker URL, a port, or a CDP endpoint.
- **Session lifecycle.** `start` mounts the account context; `end` captures,
  saves, stops, releases, and settles.
  A worker that does not settle is quarantined.
- **Deterministic crawl.** `steel_crawl` mounts the same context reference,
  attaches the CDP sidecar, follows the symbolic frontier, and leaves a
  manifest with `run.partial`, `stop_reason`, and the HTTP-history artifacts.
- **Auth handoff.** The gateway writes `browser_context.ref` and `status`;
  the crawl mounts the same reference.
  The oracle is the only pass signal.

## Qualitative criteria

| Criterion | Evidence |
|---|---|
| Both workers discovered and healthy | Kali browser MCP log `pool.discovered` |
| The one browser tool is bound and used | agent tool list, Langfuse spans, pod observations |
| No worker URL or session name reaches the model | tool description, transcripts, Langfuse inputs |
| Context restore works | gateway `restored`, crawl manifest, oracle result |
| Crawl completes with a terminal stop reason | `steel_crawl` manifest and recon job status |
| Crawl adds endpoints the request crawlers miss | L0 graph delta, crawl manifest, HTTP history |
| Sessions stop and release | pool store record, worker session state, no live session |
| No leaked Chromium or zombie drift | worker process check, `init: true` |
| Failure modes are named, not silent | recon job status, manifest errors, trial remediations |

## Standard metrics

The workbench metrics are computed by `eval/measure_trial.sh` and the
`eval-measurer` role:

- GT verdict counts and identification rate;
- L0/L1 recall;
- impact rows, threat and precursor dispositions, chains, risk;
- capped tokens and the per-agent split;
- pod terminals, watchdog timeouts, and confirmed symptoms;
- workflow adherence.

They are reported for continuity, not as the gate.

## Monitoring

`monitor_iteration_e.py` polls every 120 s:

- `GET /projects/<id>/usage` for `capped_tokens` against the 7,000,000 cap;
- `GET /projects/<id>/hunting` for the run status and the risk total;
- the recon run's per-job statuses, including `steel_crawl`;
- the unit models under `hunting/threat_modeller/{produced,consumed,abandoned}`;
- the browser MCP log and the pool store.

Trail: `eval/runs-iteration-e-20261108/monitor.jsonl`.
Langfuse is the trajectory layer.
The session ids are `hunting:<run_id>:<role>`, `recon:<run_id>:<job>`, and
`pod:<dispatch_id>:<spec_id>`.

## Terminal state

Pending.

## Results

Pending.

## Learnings

Pending.

## Recommendation

Pending.
