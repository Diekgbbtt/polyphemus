# Arm K failure diagnosis - #384, #385, and the Overview workflow evaluation (2026-10-18)

Scope: diagnose the root causes of tickets #384 (white-jotter recon-orchestrator cost explosion) and #385 (white-jotter service-to-System linking collapse), and evaluate how the mechanism-typist and the assigner interpret and use the structured Overview entity across their sessions, against the workflow model derived by walking backward from the well-formed L1 units (`docs/experiments/2026-10-17-typist-assigner-optimal-paths.md`).

Evidence windows and projects (all timestamps UTC):

| Run | Project | Window | Artifacts |
|---|---|---|---|
| arm K white-jotter | `35189233-ca25-4fc9-8c09-33f7c913c6ca` | 17:54:39 - 18:36:51 | `/root/armk-wj-roleio.json`, `/root/wj-jo-full.json`, `/root/wj-ta-full.json`, `/root/wj-proposals.json`, `/root/wj-batches/manifest.json` |
| arm K comfyui (control) | `471401f8-d0ed-435e-bc8b-43de2095b0e7` | 16:32:06 - 17:34:50 | `/root/armk-comfyui-roleio.json`, `/root/comfy-ta-full.json` |
| arm J formal white-jotter (control) | `f16de150-b032-4566-871b-2df6fa4d48a9` | 2026-10-16 20:30 - 21:30 | `/root/armj-wj-jo.json`, `/root/armj-wj-typist.json` |

Method (the plan as executed, with the loops it named):

- **L1 loop (#384)** - reconstruct the orchestrator's per-call context growth from three independent sources (the app's compaction ledger in the container log, the Langfuse observations, the durable usage pull), red on the arm K white-jotter run, green on the arm K comfyui run and the arm J formal run.
- **L2 loop (#385)** - extract every `L1DeltaBatch` the typist and the assigner proposed from the Langfuse full-IO pull, replay them through the app's own models and post-processing locally, and diff proposals against the written graph (per service, per relation), red on arm K white-jotter, green on arm K comfyui.
- **L3 loop (Overview)** - extract the delivered Overview message and every Overview reference from the roles' outputs, and walk the key decision points against the optimal-path model, comparing arm K's structured delivery with arm J's prose delivery.

All commands are re-runnable; the captured artifacts and helper scripts (`/root/lf_pull.py`, `/root/diag_extract.py`, `/root/diag_dump_batches.py`, `/root/diag_overview.py`, `/root/diag_overview2.py`) live on the eval host.

---

## Part 1 - #384: the white-jotter recon-orchestrator cost explosion

### 1.1 The observable

The white-jotter arm K trial spent 4,006,400 capped tokens (the whole 4M budget), of which the `job_orchestrator` role alone booked **2,553,915 capped** (uncached input 2,548,105 + generated 5,810; cached 4,305,536 read but not billed) over **12 calls** - 64% of the budget - against **27,120 capped / 10 calls** in arm J formal. On comfyui the same role never called the model at all. The hunting phase was left ~0.6M tokens and identified none of the seven GT vulnerabilities.

### 1.2 The mechanism chain (all times 2026-10-18)

| Time | Event | Evidence |
|---|---|---|
| 17:58:28 | The auth-gateway turn starts: first generation, input 20,235 chars | `/root/wj-jo-full.json` generation 1 |
| 17:58:30 | `auth_store(read overview)` returns the store (6,158 chars) and `load_skill("authn")` returns the skill (14,674 chars) | TOOL rows |
| 17:58:32 | First replay command: `BASE=http://46.224.225.245:35493`, `curl .../api/authentication` with the stored JSESSIONID -> **`curl: (7) Failed to connect ... Could not connect to server`** (all three probes) | TOOL `execute_command` output |
| 17:58:35 | Reachability probes: root 000, `/dev/tcp` refused, ping OK (0.08 ms), route via 172.28.0.1 | TOOL output |
| 17:58:40 | A broad diagnostic grep (`grep -rIh --include=*.json ... "35493" /work /root`) matches a multi-MB minified line and returns **4,194,193 bytes** (an `hsluv` colour table) | TOOL row, `olen` 262,172 recorded after the 256 KiB Langfuse cap, tail marker `[truncated 3814821 bytes]` |
| 17:58:54 | Next generation input jumps to 261,904 chars (the recorded copy is truncated at the 256 KiB cap; the real thread is ~852k tokens) | generation input lengths |
| 17:59:13 | `compaction ledger ... occupancy=852,003 budget=200,000 over_budget=True`; compaction **reclaims 4,212 tokens** | container log |
| 17:59:13 - 18:00:31 | Nine more calls at 848,507-856,331 tokens occupancy, each re-reading the thread | container log ledger series |
| 18:00:32 | The model call raises `litellm.BadRequestError ... [invalid_request_error] tool message content must be a string on the gRPC path` | container log |
| 18:00:33 | The actor degrades and posts a no-decision reply; `auth gateway: no verdict for project 35189233-...; fail-open: pipeline runs every phase unauthenticated` | container log |
| 18:00:37 | The recon pipeline starts - unauthenticated | container log (whois/subdomain/naabu triager threads) |

### 1.3 Root cause

**The regenerated white-jotter auth bundle records the bootstrap deployment's public address instead of the run-stable target alias, and the gateway has no other source for the live target address.**

- The arm K bundle (`/root/eval-dd/data/white-jotter/auth/credentials.yaml`, captured 2026-10-17T19:50:54Z) stores `login_url: http://46.224.225.245:35493/api/login` and `domain: 46.224.225.245` on every account; the same stale address appears in `surface-map.md`, `research-notes.md` and `l1-surface.yaml`.
- The trial's target is published on a **new host port every run** (this run: 8443/tcp -> `0.0.0.0:48373`) behind the run-stable alias `t-1618c524.target` (172.17.0.1).
- The gateway brief deliberately carries no store contents and **no target address** (`orchestrator_agent.py::_gateway_human`: "The brief carries NO store contents - the model grounds itself through its own reads"), and no target env var reaches the orchestrator (its env census shows no TARGET/BASE variable).
- The gateway therefore derived its base URL from the account's stored `login_url`, which is stale by construction, and the prompt's section 4 explicitly forbids stopping early: "There is NO attempt cap and no duplicate-command rejection ... keep debugging while progress is real." The result is the thrash above.

**The differential that proves it** - the arm J formal run (2026-10-16) used the same gateway loop and completed in 10 calls / 27,120 capped tokens because its store carried the **run-stable alias**:

```
arm J store (2026-10-16):  "login_url": "http://t-1618c524.target/api/login",
                           "domain": "t-1618c524.target"
arm K bundle (2026-10-18): login_url: http://46.224.225.245:35493/api/login
                           domain: 46.224.225.245
```

Arm J's gateway replayed against `t-1618c524.target`, minted a fresh `wjprobe_*` account through `POST /api/register`, stored the JSESSIONID with `target: t-1618c524.target`, asserted `status: valid`, updated the overview's technical conditions and the authn skill - no thrash. The only variable that changed is the recorded address in the data dependency.

### 1.4 Amplifiers (each independently fixable)

1. **Unbounded tool output at the orchestrator seam.** The pod path caps its command stdout at 4,000 chars (`recon/domain/pod.py:794`); the orchestrator's `execute_command` (the Kali MCP tool) has no bound, and the Langfuse 256 KiB cap only limits what is *recorded*, never what enters the thread. One 4 MB result took occupancy from ~12k to 852k tokens.
2. **Compaction cannot shed a single oversized recent message.** The 200k-token budget is enforced, but the giant tool message sits in the protected recent tail, so compaction reclaimed 4,212 tokens (0.5% of the thread) and every later call stayed over budget.
3. **The terminal 400 and the silent degrade.** The final call was rejected by the gateway (`tool message content must be a string on the gRPC path`); the actor posted a no-decision reply, so the gateway emitted **no verdict** rather than a loud `failed` verdict - and the pipeline's fail-open ran the whole recon unauthenticated. The intended loud-failure path ("collection still runs, unauthenticated, loudly") degenerated into an unobserved one: the trial record shows no auth failure, only the cost.

### 1.5 Recommendations

1. **Inject the live target root into the gateway brief** (and/or rewrite the store's absolute `login_url` per run at seeding time), so the gateway never depends on a bootstrap-time address. Acceptance: the arm K white-jotter gateway completes with the live alias and no refused connection.
2. **Bound the orchestrator's tool output** at the exec seam (cap + truncation marker, mirroring the pod's 4,000-char discipline or a summarise step), so no single tool result can consume a trial.
3. **Make compaction able to drop/summarise an oversized single message** (or refuse to keep a message above N tokens without a summary stub), so the budget is enforceable in practice.
4. **Surface the auth outcome loudly**: a degraded gateway must still emit `failed` (or the pipeline must record `auth_gateway_degraded` on the trial), otherwise the unauth recon is invisible.
5. Normalise ToolMessage content to a string at the wire boundary (the 400's immediate trigger), so one odd message cannot kill the gateway.

**Regression seam:** a unit test at the gateway seam with an injected store whose `login_url` points at an unroutable host but whose brief carries the live alias must complete without the refused-connection path; plus a session-seam test capping an exec result and asserting the thread occupancy stays under budget.

### 1.6 The operator's #384 hypothesis, tested

The hypothesis was "some variable specific to iteration K - the codebase or the data dependencies". **Confirmed, and narrowed to the data dependency**: the code delta since arm J (the four fixes + the C5 node) is not implicated - the gateway loop, its prompt, its bindings and its tools are unchanged, and the comfyui arm K run (same code, empty auth store) never entered the loop. The changed variable is exactly the regenerated `auth/` bundle's recorded address.

---

## Part 2 - #385: the white-jotter typed-edge collapse

### 2.1 The observable

Arm K white-jotter wrote **4 L1-to-L1 edges** (`EXPOSED_VIA` 1, `FRONTED_BY` 1, `IDENTIFIED_BY` 1, `SHAPES_DATA_OF` 1) - all from `library-catalog` - against **87** in arm J formal; 4 of 15 Systems anchored (arm J: 24 of 29); GT M4 averaged 0.07 (arm J: 0.69), and the target score fell 0.66 -> 0.38.

### 2.2 The proposals exist - the writes do not

From the Langfuse role pull (`/root/wj-ta-full.json`, 92 generations):

- The white-jotter typist's structured proposals contain **`EXPOSED_VIA RESTApi::api` x18, per-service `WebPresentation` shells x2 each, `SHAPES_DATA_OF` x18, `FRONTED_BY` x16, `IDENTIFIED_BY` x12, `AUTHORIZED_BY` x10, `AUTHENTICATED_BY` x4** - roughly 110 edges across nine services.
- The written graph holds 4, all from `library-catalog`, whose four per-chunk proposals (18:03:58, 18:07:37, 18:14:16, 18:17:21) did land.
- The final pass (18:28-18:30) proposed **6 Systems and 44 edges** covering `article-management`, `book-management`, `jotter-reading`, `library-catalog`, `navigation-menu`, `register`, `role-permission-administration`, `sign-in`, `user-administration`. **None of it reached the graph** (the scaffolded Systems still carry `prov_job = data-dependency-scaffold` and no description).

### 2.3 The loss is at the structured-output seam, not the curator

Evidence chain:

1. **Channel census.** Classifying every typist generation by its answer channel: comfyui **53 tool calls / 0 text JSON**; white-jotter **63 tool calls / 4 text JSON** - and the four text-JSON answers are exactly the final pass's structured calls (systems extraction x2 attempts, services linking x2 attempts, at 18:28:41, 18:29:15, 18:29:38, 18:30:02).
2. **The duplicates are the escalating retry.** `invoke_with_escalating_timeout` returns the first NON-None result and retries a None under the next budget; each structured step ran exactly twice with an identical prompt.
3. **The batches are valid.** Replaying all four captured payloads through the app's own `L1DeltaBatch` model validates cleanly, and through the typist's post-processing chain (`_merge_systems`, `_reconcile_webpresentation`, `narrow_to_typing`, `drop_unknown_vocabulary`) they survive as **6 systems + 44 edges**.
4. **The seam reads only the tool-call channel.** `session._to_turn` takes `content = result.get("structured_response")` when a schema is set; a text answer leaves `structured_response` absent, so the call resolves to None.
5. **The body swallows the None.** `type_mechanisms` ends its structured steps with `... or L1DeltaBatch()` (mechanism_typist.py:646-651), so two exhausted attempts degrade to an empty batch with no error.
6. **The write census agrees.** Pass census `18:30:13 analyser chunked ... l0_assets=591 aggregates_written=70 systems_written=0`; in the same pass the assigner's structured call (a tool call) wrote 70 aggregates.
7. **The relax is the enabler, not the trigger.** The runtime logs `relaxed forced tool_choice 'any' -> 'auto' (A6 voluntary rung)` throughout; under `voluntary_function_calling` the model may answer in prose without calling the schema tool. It did so four times - only in the final, largest-context pass.

### 2.4 Root cause

**In the final 591-asset pass the model returned the `L1DeltaBatch` payload as assistant text instead of a tool call. The structured-output seam only accepts the tool-call channel (`structured_response`), the escalating retry repeated the text answer, and the typist body's `or L1DeltaBatch()` fallback silently produced empty batches - so 6 Systems and 44 Service-to-System edges covering nine services were discarded without a single warning.** The loss cascaded into the GT well-formedness M4 collapse (0.07 vs 0.69) and, with it, most of the white-jotter regression.

### 2.5 The operator's hypotheses, tested

- **"The l1 curator was not updated following the L1 domain model change with the new Overview entity."** **Refuted.** The Overview is deliberately not a graph unit (`docs/design/overview-entity-impact-map.md` section 3.3: `l1_curator.py` / `l1_types.py` "VERIFIED, NO CHANGE"); the arm J -> dev curator diff contains only the #354 `EVIDENCED_BY` writer plus its `enrich` parameter, and the system-edge writer is byte-identical; no curator skip/reject warning appears in the white-jotter window; and the dropped edges never reached the curator at all (they died at the parse).
- **"There should be more write failures also in the aggregation writes written by the assigner earlier."** **Refuted for aggregates.** The assigner's final batch arrived as a tool call and the pass wrote 70 aggregates (the graph holds 72 aggregated endpoints, matching the pass totals); no aggregate-write failures appear in the log. The write failures are real but they are **parse** failures concentrated in the typist's final pass, not curator or writer failures.

### 2.6 Recommendations

1. **Accept a text JSON answer for structured turns**: when the response carries no tool call but its text parses to the schema, use it (the parsing-recovery middleware is the natural home - it already owns malformed-call recovery, and this is the missing-call sibling).
2. **Make the fallback loud**: every `or L1DeltaBatch()` (and the comparable `or None` seams) must log a warning with the role, the step and the schema when a structured call resolves empty, and the pass census should carry `structured_parse_failures`.
3. **Re-ask bounded**: on an empty structured result for a typing step, re-ask once with an explicit "call the `L1DeltaBatch` tool" instruction (a channel nudge), rather than silently degrading.
4. Consider the pass shape: the final pass carried 591 assets / ~261k-char prompts; splitting it (or re-running the linking step per service group) would reduce both the drift and the blast radius.

**Regression seam:** a session-seam test where the stubbed model answers with the schema JSON in the message text and no tool call must yield the parsed object (red today); plus a typist-body test asserting a loud warning and a non-empty retry path when the linking call resolves empty.

---

## Part 3 - The Overview entity in the typist and assigner workflows

### 3.1 The delivery delta (arm J -> arm K)

**Arm J (prose, embedded)**: the Overview rode the role message as a paragraph:

> "APPLICATION OVERVIEW: The deployed application is a personal blog and library platform named White Jotter ("Your Mind Palace"). It is a Spring Boot REST backend (`wj`) that serves a Vue.js single-page application from the same origin, listening on port 8443. ... ROLE: the TechnicalSystem mechanism-typist GOAL: reconstruct, at breadth, the cross-cutt..."

**Arm K (structured, dedicated)**: a dedicated HumanMessage containing only the Overview - `Domain`, `Offered features`, `Canonical journeys`, each journey step annotated with the owning service and, where relevant, the exact WebPresentation shell:

> "APPLICATION OVERVIEW (the deployed application the following items belong to):
> Domain: white-jotter
> Offered features: White Jotter is a small self-hosted content site: a public journal and a public book library, rendered by a Vue single-page console over a Spring Boot JSON API, plus a back office where staff manage books, journal articles, the account roster and the role, permission and menu grants behind a cookie session. ...
> Canonical journeys:
> 1. Read the journal and browse the library
>    - Open the console root and let the home route render (WebPresentation library-catalog::catalogue-pages)
>    - Pager the journal article list page newest-first and open one article's full text (jotter-reading)
>    ..."

chained to the item message by the verbatim "Grounded in the application overview above, reflect on the streamed surface that follows." The scaffolding uses the same journey vocabulary, so the Overview is the roles' map from a surface to its owning service and shell.

### 3.2 Ground truth used

The workflow modelled by walking backward from the well-formed L1 units (`docs/experiments/2026-10-17-typist-assigner-optimal-paths.md`): the assigner's A0-A5 path (read the chunk and roster, classify the evidence strength, verify write-shaped routes through the HTTP history, assign to the contract owner **or leave unassigned with a written reason**, commit only after the verification round) and the typist's breadth-then-link path (orient over the whole roster, sweep the presentation/API roots, link each service to its shell/overlay, ground each System in evidence). The known failure clusters this model targets: C1/C2 (missing and method-blind rows), C5 (precision-first non-aggregation under ambiguity), C6 (partial typed-edge coverage).

### 3.3 The walkthrough

**Assigner, white-jotter, first chunk (18:01:07-18:01:14).** The root path's ownership was ambiguous between the two public services. The assigner resolved it with the Overview and said so:

> "The canonical journey says "Open the console root and let the home route render (WebPresentation library-catalog::catalogue-pages)"."
> "The overview maps the root to the *catalogue* pages, not to the reading pages, so this candidate is rejected as the second public surface, not co-owner."
> "The runner-up is `jotter-reading`, and the overview's home-route annotation discriminates between the two public surfaces in favour of `library-catalog`."

This is the C5 class of decision - in arm J the equivalent ambiguity ends in "leave unassigned to preserve precision" (`b4ff9a0b` on `/api/admin/content/article`). Here the Overview supplied the discriminator and the route was assigned with a citable reason.

**Assigner, comfyui, first chunk (16:35:37-16:35:45).** The same class, with an explicit meta-reflection on the Overview's evidentiary status:

> "Canonical journey 1 says "Open the editor page from the root (WebPresentation graph-authoring::editor-shell)"."
> "That's the app overview given to me, which is grounded evidence about what the root is."
> "The overview says the root page is "WebPresentation graph-authoring::editor-shell" - the app's own naming convention binds the editor shell to graph-authoring."
> "The only evidence is the overview's journey #1 parenthetical, which explicitly assigns it to graph-authoring as the WebPresentation discriminator."

**Typist, white-jotter (18:01:54-18:02:07 and the ORIENT at 18:27:52).** The Overview drove the linking and corrected the typist's reading of the surface:

> "The canonical journey explicitly maps 'Open the console root' to `WebPresentation library-catalog::catalogue-pages`."
> "But the app overview says Vue SPA over a Spring Boot JSON API."
> ORIENT: "... this is the existing `WebPresentation::library-catalog::catalogue-pages` shell, already described." and "almost every path on the surface exists twice - once bare, once under an `/api/` prefix, and the two twins answer differently."

**Typist, comfyui (16:38:05, 16:50:49).** The Overview named candidate components and bounded the systems:

> "The overview journey says "WebPresentation graph-authoring::editor-shell"."
> "But the application overview explicitly names an extension manager, environment-snapshot-management, model-installation."

**Quantified usage** (output-side mentions only): white-jotter typist - "overview" 31 hits in 11 of 77 generations, "journey" 19 in 8; comfyui typist - "overview" 34, "journey" 11; white-jotter assigner - 129 sentences carrying "overview"/"journey"; comfyui assigner - 60. The mentions cluster at the two ambiguity classes above (route-to-service ownership; service-to-shell linking), not in the mechanical steps.

### 3.4 Verdict

**Yes - the structured Overview measurably improves both roles' workflow, at exactly the decision points the arm J analysis flagged.** The dedicated message plus the journey annotations give the roles a citable, operator-authored mapping from a route to its owning service and shell, and the captured sessions show both roles using it as the discriminator: the assigner's root-ownership decision (both targets, replacing the C5 "leave unassigned" default) and the typist's shell linking and system hypothesis. The journey annotations also carry the exact discriminator keys the linking call must emit - a direct answer to C6 (partial typed-edge coverage).

Caveats, all measured:

- **The improvement is fragile in this run**: the white-jotter linking that the Overview steered was in the final pass and was discarded by #385's parse failure, so the improved decisions did not reach the graph. The evaluation above reads the roles' *behaviour*, not the run's outcome.
- **The roles treat the Overview as ground truth** ("grounded evidence about what the root is") - correct by design (it is authored from the operator KB), but it means an incorrect journey annotation would propagate straight into L1. The typist's witness discipline (#354) still binds each System to an L0 observation; the journey annotations themselves are not witness-checked.
- **#384's unauthenticated recon shrank the surface the Overview describes**: the journeys cover the authenticated back office, but the run's L0 held only the anonymous surface, so several journey steps had nothing to bind to. The Overview cannot compensate for a lost authenticated crawl.

### 3.5 Recommendations

1. Keep the Q4 delivery unchanged; it is the right shape and it is being used.
2. When #385's parse fallback lands, re-read the final-pass linking test: the Overview-driven shell edges should appear (the proposals already carry them).
3. Consider distinguishing **declared** Overview evidence from **observed** L0 evidence in the typed-edge provenance (e.g., the edge's `evidence_refs` citing the journey step), so a threat modeller can tell an operator-authored ownership claim from a witnessed one.
4. The journey annotations are doing the heavy lifting; keep them accurate and keep the scaffold's service/shell keys in lockstep with them (they already are).

---

## Appendix - reproduction

```
# full IO pulls
python3 /root/lf_pull.py <from> <to> <out.json> <role1,role2>        # /root/lf_pull.py, run from the instance dir
# proposal extraction and replay
python3 /root/diag_extract.py /root/wj-ta-full.json /root/wj-proposals.json
python3 /root/diag_dump_batches.py /root/wj-ta-full.json /root/wj-batches
#   then, in the repo venv: PYTHONPATH=src .venv/bin/python -c "<validate the batches with L1DeltaBatch + the typist post-processing>"
# context growth
docker logs ph-dd131acc-agent-1 2>&1 | grep "c9d3b8f3" | grep -iE "compaction|auth gateway|degraded"
# graph checks
docker exec ph-dd131acc-neo4j-1 cypher-shell -u $NEO4J_USER -p $NEO4J_PASSWORD "<the queries in Parts 1-2>"
```

Captured on the eval host under `/root/`: `wj-jo-full.json` (auth-gateway observations), `wj-ta-full.json`, `wj-proposals.json`, `wj-batches/` (the four discarded payloads + the controls), `armj-wj-jo.json` and `armj-wj-typist.json` (the controls), `armk-*` (the compact role pulls).
