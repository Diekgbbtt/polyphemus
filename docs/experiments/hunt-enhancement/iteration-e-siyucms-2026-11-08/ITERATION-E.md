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

## Post-run diagnosis (2026-11-09)

### Observability recovery

The local Node build was linked against `libsimdjson.33.dylib` while Homebrew had simdjson 36 installed, so every `npx` invocation failed before the CLI loaded.
`brew reinstall node` moved Node to 26.13.0 and `npx langfuse-cli` works again.
The Langfuse Cloud project is on the v4 ingestion path: the v3 `/api/public/traces` endpoint returns zero rows, while `/api/public/v2/observations` returns the analysis records.
The app's flush was healthy; the empty trace list was a query-endpoint mismatch, not a tracing failure.
The session review used:

```bash
npx langfuse-cli api observations list \
  --from-start-time 2026-11-08T22:40:00Z \
  --to-start-time 2026-11-08T23:30:00Z \
  --fields core,basic,io,metadata,model,usage,metrics \
  --all --max-items 20000 --json
```

### The L1 graph did insert its edges

The earlier `69 nodes / 0 links` reading was stale.
It was taken before the new analysis wrote, when only the previous run's bootstrap shells existed.
The current project graph reads `269 nodes / 261 links`.
The L1 core is:

| Edge | Count |
|---|---:|
| `Service->System` (`ROUTED_BY`) | 5 |
| `Service->System` (`IDENTIFIED_BY`) | 5 |
| `Service->System` (`EXPOSED_VIA`) | 4 |
| `AGGREGATES` (`Service->L0`) | 8 |
| `EVIDENCED_BY` (`System->L0`) | 40 |

The 14 `Service->System` edges cover the five public front-office services: `home-page`, `site-search`, `column-listing`, `entry-detail`, `team-management`.
The other 28 Services have no L1 edge because the crawl never delivered an admin endpoint.
The graph is thin because the L0 input is thin, not because the writer dropped edges.

### Analysis session review

The analysis ran four Assigner sessions and four mechanism-typist sessions.
Three of each were read end-to-end from Langfuse, with every model turn, tool call, tool result, and curator receipt.

| Session | Chunk | Result | Decision quality | Finding |
|---|---|---|---|---|
| Assigner 1 | `httpx:0` | 1 aggregate (`home-page`) | Sound | Correct root-route ownership; the artifact read returned metadata only, as documented |
| Assigner 2 | `katana:0` | 8 aggregates over 7 endpoints | Sound | Shared ownership on the two team-detail routes is justified; the mangled path was left unassigned rather than guessed |
| Assigner 3 | `arjun:0` | 2 aggregates | Sound | No tool calls needed; both contracts match the path nouns |
| Typist 1 | `httpx:0` | 3 Systems, 3 edges | Sound | Correct proxy, session, and home-shell typing; the first two `graph_view` calls used the domain slug and returned empty |
| Typist 2 | `katana:0` | 6 Systems, 10 edges | Sound | Strongest session: it probed the encoded path, the search reflection and SQL trace, and the listing class; all decision nodes hold |
| Typist 3 | `arjun:0` | 2 Systems, 0 edges | Sound | It verified the existing five Services already carry the proxy and session edges, and withheld the missing `team-management` presentation edge because no `team-management::site-shell` node exists |

No wrong ownership or mechanism decision was found in the sampled sessions.
The null results are deliberate and evidence-backed, not failures.
The typist's multiple candidate hypotheses, read-only probes, and duplicate-edge checks are the behaviour the design asks for.

### Confirmed defects

1. **`graph_view` accepted the caller's `project_id`.**
   The analysis tool merged the bound scope first and the caller's parameters second.
   The typist sees the domain slug `siyucms` in the overview, so `params={"project_id": "siyucms"}` naturally followed.
   The read returned zero rows instead of an error.
   Two of the four typist sessions lost their first two `graph_view` calls this way.
   The bound scope is now authoritative, and the contract says the tool injects it.
2. **The inert reflection-turn `L1DeltaBatch` tool invited retries.**
   The tool is bound on the reflection turn for cache-shape stability, but its result said only "structured output is only produced on the extraction turn".
   The model retried the full payload one to three times per chunk.
   The refused calls cost about 240 seconds of model time across the four sessions, including one 74.6-second call.
   The result now names the reflection turn and tells the model to finish with prose.
3. **`response_size` is the wire size.**
   The HTTP-history summary reports the compressed body size, while the L0 graph's `content_length` is decoded.
   Assigner 1 noticed the `19,997` versus `135,861` discrepancy; Assigner 2 used the compressed sizes to compare detail and listing classes.
   The relative comparison held, but the absolute values are not comparable across the two tools.
4. **`get_http_artifact` never returns the body.**
   Its contract says so, but the typist prompt invites a transaction read when a hypothesis depends on what the page renders.
   The typist correctly fell back to one bounded `exec` fetch.
   The Assigner has no `exec`, so it cannot read a body at all.
   This is a prompt-versus-tool contract gap, not a data loss.

### Crawl diagnosis and fixes (2026-11-09)

The crawl stopped at `session_deadline` after 648 seconds: 111 endpoints, 11 parameters, 4 pages, 10,757 flows, 919 MB.
The loaded session did carry the admin auth context.
The oracle passed, the restored context held 6 cookies, 1 origin, and 1 storage key, and a manual admin navigation returned `SIYUCMS | 控制台` in 4.87 seconds.
The member-centre link `/index/user/index.html` was in the root DOM and the crawl clicked it, but it redirected to `/index/user/login` because the admin `PHPSESSID` is not a member session.
`/index/User/set.html` sits behind that member login, so the admin session cannot reach it.
That redirect is expected auth scoping, not a page-parser failure.

`/index/honours.html` was a visible link in the root navigation, but the crawl did not reach it before the deadline.
The root page reloaded about sixty times in the 648 seconds: each local-state action is followed by a restore navigation, so 71 actions cost roughly nine seconds each.
The honours link was offered, but the budget expired first.
The 600-second budget was genuinely too short; the default is now 1800 seconds.

The admin console is not linked from the public root.
The root DOM contains no `/admin`, `/index.php/admin`, or `/index/User/set.html` link.
The coverage algorithm therefore cannot discover the admin surface by navigation, so its absence was genuine for the public surface.
The surface is technically reachable because the scaffolded `overview.yaml` names `auth_probe.url = /index.php/admin/Index/index.html`, and the authn skill and auth gateway use it.
The crawl used that URL only in the oracle fetch, never as a frontier seed.
The new `crawl_seed_urls` helper loads the auth probe as the first seed and the public root second, so the authenticated backend is rendered and explored before the public site.

The CDP capture sidecar already attaches before the root load and the auth probe; the oracle fetch is in the manifest as an observed endpoint.
The cheap sidecar ordering fix was therefore already present.
The missing piece was page exploration, which the auth-probe seed supplies.

The partial-manifest defect was confirmed.
`_manifest_partial` returned `manifest: None`, so the pod failed and discarded the 111 endpoints.
A partial v2 manifest now keeps its manifest, parses its endpoints and parameters, and adds one `reduced_crawl_coverage` observation.
The captured manifest parses to 268 assets: 133 `BaseURL`, 133 `Endpoint`, and 2 `Parameter`; the other parameter records lack a valid endpoint anchor.

The worker stop reported `released: true` and `stopped: false` at the five-second settle bound.
The session was not leaked; the worker had only not installed its fresh idle placeholder yet.
The default settle window is now 30 seconds.
The regression test drives a worker that settles at six seconds with a fake clock.

### Hunting bootstrap

The hunting run `e82960ac-1b0c-4f13-9501-ca321982c32a` never reached its first LLM call.
Both the hunting start and the stop handlers raised `No module named 'cvss'`.
The deployed `polymerhus-agent:latest` was built at `2026-11-08T15:42:54Z`, before `cvss==3.6` entered `requirements-app.txt`.
The API-key hypothesis is not supported: the analysis made 122 successful calls and the failure occurs before any hunting call.
The image was rebuilt at `2026-11-09T09:17:32Z` from the eval worktree (then at `7a7d41c9`), and `docker run --rm polymerhus-agent:latest python -c "import cvss"` reports `3.6`.
The hunting run is therefore a deployment-artifact failure, not a model, quota, or graph failure.

### Remaining work

The crawl fixes are in place: partial-manifest ingestion with `reduced_crawl_coverage`, an 1800-second default crawl budget, the admin `auth_probe` as the first frontier seed, and a 30-second worker settle window.
The `login_url` is not a seed because it renders the signed-out form; the probe is the authenticated entry.
The analysis's L1 coverage will stay thin until the crawl delivers the admin surface: the current run saw 15 endpoints, while the crawl captured 111.
The next run should use the rebuilt image, the updated analysis code, and the populated L0 graph.

## Terminal state

Recon and analysis completed.
The `steel_crawl` job ended `degraded` with a partial manifest at `session_deadline` and zero recon assets.
The analysis drained at `23:21:04` with 6 passes and 274 L0 assets.
The hunting run started at `23:21:19`, hung at the `cvss` import, and was stopped by the operator.
The stack is down; volumes and artifacts are preserved.

## Results

The auth gateway and the single browser tool passed.
The admin context mounted from the deterministic reference, restored 6 cookies, 1 origin, and 1 storage key, and the oracle returned the SIYUCMS console.
The crawl produced a real partial manifest: 111 endpoints, 11 parameters, 4 pages, 10,757 captured flows, 919 MB, 648 seconds.
The analysis wrote the public L1 skeleton: 269 nodes, 261 links, 14 `Service->System` edges, 8 `AGGREGATES`, 40 `EVIDENCED_BY`.
Hunting produced no units, no specs, no pods, and no hunting-agent calls.
Capped spend was 708,946 over 122 calls: `mechanism_typist` 438,413, `job_orchestrator` 116,856, `triager` 79,654, `assigner` 74,023.

## Learnings

- A stale graph read can look exactly like a write failure. Read the graph after the analysis drains, not before.
- The analysis tool bound the project scope but let the caller overwrite it. A silent empty read is worse than a rejected one.
- The reflection-turn tool gate needs a directive message; the model will retry an inert tool when the prompt says the tool is the only channel.
- The L1 graph is input-bound. A discarded crawl manifest removes seven eighths of the endpoint surface and no analysis prompt can recover it.
- An authenticated entry known to the gateway is not a public link. Seed the crawl with the auth probe instead of expecting the public navigation to discover it.
- A local-state action costs one page restore, so the crawl budget must cover the reload cost, not only the page count.
- A container image built before a dependency lands is a deployment defect that presents as a model hang.

## Recommendation

Rebuild the image before every eval run from the same commit that supplies `requirements-app.txt`, and assert `import cvss` in the image health check.
Run the next iteration E with the rebuilt image, the bound `graph_view` scope, the directive reflection gate, and the fixed crawl.
Measure the L1 edge count and the L0 endpoint recall against the crawl manifest, not against the stale bootstrap graph.
