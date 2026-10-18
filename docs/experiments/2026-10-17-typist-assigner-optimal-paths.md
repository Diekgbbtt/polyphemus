# Typist and assigner optimal paths vs executed paths, and failure-mode clusters (Task Area 2, W2.4 + W2.5)

Status: complete (2026-10-17).
Branch: `feat/recon-coverage-and-eval-wellformedness`.
Plan: `docs/design/plans/2026-10-17-recon-coverage-and-eval-wellformedness.md`, W2.4 + W2.5.
Companion: `docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md` (W2.3, the scores this doc explains).

Every claim below cites a Langfuse observation id or a chunk hash from the two formal (arm J) runs:

- comfyui formal: project `d04b947f-d6c3-48be-9b18-1c4eef851241`, window 2026-10-16 19:37:30Z - 20:32:28Z.
- white-jotter formal: project `f16de150-b032-4566-871b-2df6fa4d48a9`, window 2026-10-16 20:32:29Z - 21:23:05Z.

## 1. The roles and their real capabilities

From `src/polymerhus/analysis/graph_tools.py` (the single tool-binding seam, `build_surface_tools`):

- The **assigner** turn binds ONLY the HTTP-history pair: `search_http_history` and `get_http_artifact` (line 17: "The Assigner turn binds ONLY the HTTP-history pair").
  Its structured output is one `L1DeltaBatch` of `aggregates` (Service slug + L0 identity + evidence refs).
  It deliberately does NOT bind `graph_view` (line 127: "A previous graph_view-capable Assigner degraded quality").
- The **mechanism-typist** turn binds `graph_view` always, the HTTP-history pair when `with_http`, and a bounded `exec` (line 21-23).
  Its structured output is a proposal of Systems (`kind` + `discriminator`) and edges.
  The bounded `exec` exists to confirm a mechanism in the target's real response (line 23).

The typist's algorithm (`mechanism_typist.py`, lines 14-33) is THREE sequential calls over one service chunk:
REFLECTION (free prose), SYSTEMS EXTRACTION (structured: each system delta carries a COMPOUNDED NL `props.description` that folds in the triager's adversarial insight, and the emission REPLACES the stored description), and SERVICES LINKING (structured: `system_edges`).

Attribution note (matters for the W2.3 metric reading): the rich System **descriptions** that carry the M3 System statements are the typist's own compounds, emitted as `systems[].props.description` in the SYSTEMS EXTRACTION call.
Example: the final wj AuthorizationSystem compound (call `927f59a7`, 20:58:12) is byte-identical to the graph node description quoted in W2.3, and it cites the typist's own exec artifacts.
The triager's per-asset insight is folded in as an INPUT (the triager's "adversarial insight" text is part of the L0 blocks), not as the author.
So the M3 System statement items measure the typist's compounded description.

## 2. Chunk inventory and GT-unit chunk map

The window pull renders the streamed surface blocks the roles saw.
Formal comfyui has 6 distinct blocks; formal white-jotter has 6.

| run | block hash | rows | content |
|---|---|---|---|
| comfyui | `05699d126352` | 138 endpoints | the main L0 chunk (all GT-reachable comfyui endpoints) |
| comfyui | `3b6e23fb278e` | 10 endpoints | second page-set chunk |
| comfyui | `406eb9631c54` | 2 endpoints | the http/https root pair, both `GET /` status 307 |
| comfyui | `2c75aa911f05` | 2 endpoints | root + `/experiment/models` |
| comfyui | `652c01ad14bf` | 1 endpoint | root BaseURL + headers + triager adversarial notes |
| comfyui | `928afb09f964` | 0 endpoints | 793 response Headers + root BaseURL (noise block) |
| wj | `4c7e54ba195f` | 74 endpoints | the main L0 chunk (all GT-reachable wj endpoints) |
| wj | `d1163e68af02` | 0 endpoints | root BaseURL + the webpack-chunk adversarial note |
| wj | `531a089c7b83` | 2 endpoints | small page-set chunk |
| wj | `52d39b9790d6`, `4753d5b98699`, `e9fe28c7b867` | 1 each | root/redirect page-set chunks |

Per-unit map (required endpoint: chunk membership; assigner proposal):

| unit | required endpoints | in a chunk | assigner proposal |
|---|---|---|---|
| comfyui-001/002 | `/userdata`, `/userdata/comfy.settings.json` | none | none |
| comfyui-003 | `/upload/image`, `/upload/mask` (GT: POST) | `05699d` as GET | `6b986606` -> image-upload as GET |
| comfyui-004 | `/view` (GET), `/view_metadata/checkpoints` (GET) | `/view` in `05699d`; `/view_metadata` nowhere | `6b986606` -> image-viewing as GET |
| comfyui-005 | `/manager/channel_url_list`, `/manager/version` | none | none |
| comfyui-006 | `/manager/queue/{start,status,install_model}` | none | none |
| wj-001 | `/api/authentication`, `/api/logout`, `/api/login` (POST) | `4c7e54` as GET | `b4ff9a0b` -> account-sign-in as GET |
| wj-002/004 | `/api/admin/user`, `/api/admin/content/article`, `/api/admin/content/article/1` (DELETE) | first two in `4c7e54` as GET; DELETE nowhere | `/api/admin/user` -> user-administration; article path none |
| wj-003 | `/api/admin/content/article` (POST) | `4c7e54` as GET | none |
| wj-005 | `/api/search` + `keywords` | `4c7e54` as GET | `b4ff9a0b` -> book-search as GET |
| wj-006 | `/api/file/cover.png` | none | none |
| wj-007 | `/api/register` (POST) | `4c7e54` as GET | `b4ff9a0b` -> account-registration as GET |

The manager-surface comfyui endpoints and the wj cover route are absent from every chunk: no role ever saw them (cluster C1).
Every other GT endpoint reached the right service in the assigner's proposal, with the block's method (cluster C2).

## 3. Optimal paths

Epistemic rule for "optimal": each branch uses only evidence that existed in L0 or the HTTP history at analysis time, through tools the role actually binds.
Ground-truth knowledge selects which available evidence matters; it never invents a step the role cannot run.

### 3.1 Assigner optimal end-to-end path (per chunk)

```
A0  Read the chunk rows and the candidate roster (contracts).
A1  Classify each row by evidence strength:
    R1 status_code present, source httpx/katana/steel  -> reachability evidence
    R2 status_code NULL, source jsluice               -> route template, method unverified
    R3 write-shaped noun (upload, register, login, delete, install, overwrite, save)
                                                      -> method MUST be verified before judgment
A2  R3 branch: search_http_history(request.url contains <path>)
      -> pick the strongest record, get_http_artifact on it
      -> read the recorded method/status; if the only non-GET record sits on a chained
         twin (e.g. /api/api/register 405), record the chaining defect in evidence_refs
      -> aggregate the L0 node as it exists; the recorded method truth goes into evidence
A3  Ambiguous-noun branch: search_http_history(url contains <noun>) for each noun with no
    contract match (executed in-run for /nodes, /v2/, user-select, covers, content/article)
      -> get_http_artifact for the strongest response
      -> assign to the contract owner or leave unassigned WITH a written reason
A4  Path-carrier branch (file name, numeric id): aggregate the endpoint; record the carrier
    as a capability gap (no Parameter node exists to reference)
A5  Commit gate: emit the L1DeltaBatch only after every outstanding A2/A3 search returned
    (the runs violated this gate; cluster C3)
```

Instantiation on the wj main chunk (`4c7e54ba195f`), the two consequential rows:

- `/api/register` (R3): search returns `GET /api/register` 200 (20:43:10 and 20:52:41) and `POST /api/api/register` 405 (20:48:11, 20:49:31).
  Optimal: aggregate `GET /api/register` to `account-registration` with the evidence "write-shaped; the only recorded POST went to a chained twin; real-path POST unwitnessed (#365, #363)".
  Executed: `b4ff9a0b` proposed exactly that aggregate, but without the search (its round was dropped, C3); evidence_refs cite only the path noun.
- `/api/admin/content/article` (R3 + A3): search returns only `GET /api/admin/content/article[/EXPR]` rows (20:43:14, status NULL).
  Optimal: aggregate to `article-publishing` (the same chunk's `/admin/content/editor` went there) with the unwitnessed-write note.
  Executed: `f2106593` asked for the search ('content/article', 'covers', '/api/'), the round was dropped (C3), and `b4ff9a0b` left the path unassigned: "leave unassigned (three-way ambiguity)? ... I'll leave /admin/content/article* unassigned to preserve precision" (cluster C5).

Executed assigner paths, per turn (id, aggregates, searching):

| run | turn (id, time) | what it did |
|---|---|---|
| comfyui | `d2834b1b` 19:41:09 | root triage: searches host/GET/text-html |
| comfyui | `839a0e71` 19:49:45 | 1 aggregate (`model-inventory` <- `/experiment/models`) after 3 search rounds |
| comfyui | `da795007` 19:52:41 | 7 aggregates after the `/models` search round |
| comfyui | `8f47499b`/`ac02c48b`/`2b8c3a9b` 19:56 | 307 root pair triage: 3 search rounds, `get_http_artifact` on the 307 record |
| comfyui | `5f437dad` 19:59:06 | big chunk verification round: 4 searches (`/nodes`, `/v2/`, `user-select`, `/settings`) - NONE executed |
| comfyui | `6b986606` 20:00:03 | 64 aggregates; reasoning: "Let me commit to the defensible assignments from my analysis, quickly." |
| wj | `5c5efa6f` 20:39:23 | root triage (host/text-html) |
| wj | `1807f784` 20:41:58 | host search round |
| wj | `a66da09b` 20:45:05 | `/index.html` + html-header round |
| wj | `acf2816f` 20:48:38 | 307 status round |
| wj | `f2106593` 20:53:53 | big chunk verification round: 3 searches (`covers`, `content/article`, `/api/`) - NONE executed |
| wj | `b4ff9a0b` 20:56:01 | 51 aggregates; reasoning: "I need to produce the aggregates now. Let me commit to my converged judgments." |

### 3.2 Typist optimal end-to-end path (per working turn)

```
T0  graph_view: read the L0 rows of the target services and the current L1 draft
T1  Presentation/API root sweep over the WHOLE service roster:
      SPA shell routes      -> EXPOSED_VIA WebPresentation <slug>::<shell>
      JSON API routes       -> EXPOSED_VIA RESTApi <overlay>
      (do not skip services; the executed runs typed overlays only for the services
       that happened to be in the turn's focus - cluster C6)
T2  Auth typed edges: one bounded exec probe per auth-relevant route
      (executed: `b4141c97` probed /api/authentication 302 + Set-Cookie JSESSIONID,
       /api/logout, /api/register 200)
      -> IDENTIFIED_BY / AUTHENTICATED_BY; AUTHORIZED_BY must include EVERY service whose
         routes the gate refuses, registration and sign-in included (cluster C6)
T3  Integration systems: DEPENDS_ON edges for services that call external systems
      (executed for comfyui: `1b2046dc` typed comfyui-cloud with `2bd28a39` DEPENDS_ON for
       sign-in/register/password-recovery; the model-download fetch edge is missing, C6)
T4  SYSTEMS EXTRACTION: emit each system with a COMPOUNDED `props.description`
      (fold the triager insight + your own exec-verified response shape into the text; the
       emission REPLACES the stored description - never empty, never kind+discriminator only)
T5  SERVICES LINKING: emit `system_edges` over the same roster (see T1/T2)
```

Executed typist structured calls (systems extraction then services linking; the `props.description` compounds are inside the extraction calls):

| run | systems extraction (id, time) | systems | linking (id, time) | edges |
|---|---|---|---|---|
| comfyui | `e864e594` 19:44:35 | ReverseProxy, AuthenticationMechanism, workflow-submission::editor-shell | `e864e594`/`b8873b2b` 19:44 | 3 |
| comfyui | `7a1dbe97` 19:47:56 (re-emitted `4b81ecf6` 19:48:52) | + core-rest, manager-rest, IdentificationSystem, AuthorizationSystem | `05f5f292` 19:49:05 | 30 |
| comfyui | `96e55f2f` 19:51:58 | + image-upload::editor-shell, image-viewing::editor-shell, workflow-history::editor-shell, user-profile::editor-shell | `3bf84226` 19:52:09 | 2 |
| comfyui | `4931faf3` 19:53:38 (re-emitted `9bf381b6` 19:55:48) | core-rest, ReverseProxy, AuthorizationSystem | `86180786` 19:56:01 | 21 |
| comfyui | `6d430431` 19:57:53 (re-emitted `cd48bc03` 19:58:40) | ReverseProxy | `7561b75a` 19:58:46 | 6 |
| comfyui | `1b2046dc` 20:03:08 | comfyui-cloud, core-rest, manager-rest | `2bd28a39` 20:03:20 | 9 |
| wj | `f0f6d140` 20:41:46 | ReverseProxy | `90511e43` 20:41:51 | 6 |
| wj | `1095164c` 20:44:35 | third-party-cdn-assets, IdentificationSystem, AuthenticationMechanism, ReverseProxy | `642112e0` 20:44:50 | 11 |
| wj | `f5c84ec5` 20:48:04 | + AuthorizationSystem, same-origin-json-api | `67c1a134` 20:48:19 | 35 |
| wj | `a43ad585` 20:50:45 | ReverseProxy | `e2a5e53c` 20:51:00 | 4 |
| wj | `823ac777` 20:53:29 | application-shell::spa-router, same-origin-json-api, AuthorizationSystem | `d7b52433` 20:53:44 | 10 |
| wj | `927f59a7` 20:58:12 | same-origin-json-api, AuthorizationSystem (final compounds) | `83d56227` 20:58:28 | 21 |

Credit where due: the typist's gate probe (`b4141c97`) and chunk-11 grep (`425edef1`, `bb1f917b`) are exactly the optimal-path behaviour, and they ground the AuthorizationSystem compound, which cites the typist's own artifacts and the role vocabulary `[sysadmin, contentmanager, visitor, test]` recovered from chunk 11.
The typist typed the GT-exact WebPresentation discriminators (`account-sign-in::login-shell`, `image-upload::editor-shell`, `article-publishing::editor-shell`, `book-cover-serving::library-shell`) without seeing the corpus.

## 4. Workflow deltas, mapped to clusters

Every delta maps to exactly one cluster. C-numbers are defined in section 5.

| # | delta | evidence | cluster |
|---|---|---|---|
| d1 | Required endpoints absent from every chunk: all comfyui manager paths, `/view_metadata/checkpoints`, wj `/api/file/cover.png`, wj DELETE article | chunk map (section 2); base-run history holds `/userdata` (51 flows) and `/view_metadata` (6) | C1 |
| d2 | comfyui-003 write routes present as GET rows | `05699d126352` rows; `6b986606` proposed GET | C2 |
| d3 | wj-001 `POST /api/login` present as GET row | `4c7e54ba195f`; `b4ff9a0b` proposed GET | C2 |
| d4 | wj-007 `POST /api/register` present as GET row; the only real-path POST is the chained twin 405 | `4c7e54ba195f`; history rows 20:43 GET 200, 20:48/20:49 twin POST 405, real-path POST only at 21:07 (post-analysis) | C2 |
| d5 | comfyui-004 Parameter nodes named `EXPR`/`EXPREXPREXPR` | graph Parameter nodes on `/view`, `/viewvideo`, `/api/view`, `/internal/view` | C4 |
| d6 | 0 of 17 required Parameter items aggregated, both runs | W2.3 section 2.3; `keywords` node exists unaggregated; assigner prompt is endpoint-only | C4 |
| d7 | wj-003 `/api/admin/content/article` witnessed (GET row) but left unassigned | `b4ff9a0b` reasoning: "leave unassigned (three-way ambiguity)? ... I'll leave ... to preserve precision" | C5 |
| d8 | comfyui small-chunk routes dropped by choice (`/nodes`, `/nodes/search`, `/v2/`, `/user-select`) | `6b986606` reasoning: "I'd rather drop /nodes and /nodes/search to preserve precision" | C5 |
| d9 | Both big-chunk verification rounds issued but never executed; the commit followed without results | `5f437dad` 19:59:06 (4 searches, last TOOL row 19:56:46) -> `6b986606` 20:00:03; `f2106593` 20:53:53 (3 searches, last TOOL row 20:48:44) -> `b4ff9a0b` 20:56:01 | C3 |
| d10 | Typed-edge coverage omissions: `account-registration` lacks AUTHORIZED_BY; `manager-preferences` lacks WebPresentation; `book-search` lacks RESTApi although its JSON endpoint is aggregated; `model-download` lacks DEPENDS_ON although the IntegrationSystem exists | `67c1a134` edge list (AUTHORIZED_BY to user-administration, user-password-reset, user-status-control, role-catalog only); W2.3 M4 lines | C6 |
| d11 | wj-004 missing statements S1 (log/principal), S2 (username), S4 (lookup) | typist compound `927f59a7`; spec `capability_gaps` declares "the logging sink and the outbound lookup are capability gaps"; no `username` Parameter node in L0 | C7 |
| d12 | Service spine 2/5 on every unit (`api_paradigm`, `auth_methods`, `business_function` absent) | W2.3 section 2.3; curation re-home rules | convention note (D-5), not a failure cluster |

## 5. Failure-mode clusters (W2.5)

### C1 - L0 absent: required endpoints never entered any chunk (recon discovery)
- Evidence: d1 (two runs, six endpoints, four GT units in comfyui and two in wj).
- Suspected root cause: client-side XHR routes (manager tabs, cover images) are invisible to the static crawler (#353), and the browser-observed transactions are never materialised into L0 (D-3).
- Candidate structural fix: #353 + #360 (steel CDP capture) + the history-to-L0 materialisation (referenced in the #353 comment).

### C2 - Method-blind rows: write routes appear (and are aggregated) as GET (recon probing + minting)
- Evidence: d2, d3, d4, plus the twin-POST corruption (a POST to `/api/api/register` 405 while the real path stayed GET-only).
- Suspected root cause: every discovery source is GET-shaped (httpx probes, katana navigation, jsluice templates without methods); no method hint reaches probing or minting.
- Candidate structural fix: #365 (method coverage) + #363 (chained-twin validation).

### C3 - Dropped tool round before commit (analysis proposer harness)
- Evidence: d9 - in BOTH runs the last verification round of the main chunk was issued and never executed; no ERROR observation accompanies it (the census ERROR rows sit in the hunting phase), and the following generation commits with "quickly"/"now" reasoning.
- Suspected root cause: the batch turn's final tool round is torn down before execution (turn/lane lifecycle), so the commit sees no results.
- Root cause CONFIRMED 2026-10-18 (#369): the blackloop cut, not a turn/lane teardown. Each cut turn's streamed reasoning crossed the 40k-char detection bound with no content yet (the content line AND the tool calls arrived after the crossing - 45,267 reasoning chars for `5f437dad0095952b`, 108,065 for `f2106593`), so `run_session_turn` cut the stream and ABORTED the live graph run: the model node's output (the four / three `search_http_history` calls) was discarded before the tools node, which is why no TOOL observation follows. `stateful_turn` then ran the blackloop recovery - a NEW generation composed from the captured reasoning plus the "END THIS STEP NOW ... most defensible conclusion" instruction - and that generation is the one that committed the batch with no results.
  Cross-checks: the ERROR-level `LangGraph` chain at each timestamp is the aborted run (the census's single analysis-window ERROR row); the following generation's request carries the verbatim recovery instruction; the aborted run left no assistant message in the trail (so the round was never re-issuable).
  Fix: the cut is scoped to a turn with no tools bound (`fix/369-proposer-final-tool-round`); a tool-bound turn streams to completion, so its round reaches the tool layer.
- Candidate structural fix: #369 (filed with this doc); the turn must either execute the round or fail loudly.

### C4 - Parameter carriers unusable (recon minting + analysis proposal surface)
- Evidence: d5 (placeholder names) and d6 (never aggregated; the prompt judges endpoints only).
- Suspected root cause: two independent gaps: JS template expressions minted as parameter names (#366); the assigner proposal surface has no Parameter judgment (#367).
- Candidate structural fix: #366 + #367.

### C5 - Precision-first non-aggregation under ambiguity (assigner judgment policy)
- Evidence: d7 (article path left unassigned) and d8 (comfyui routes dropped to preserve precision).
- Suspected root cause: the prompt's precision bias plus the missing verification round (C3): with no search results, "leave it out" is the locally rational move.
- Candidate structural fix: allow "aggregate with evidence-qualified uncertainty"; require the C3 round to complete before a precision drop.

### C6 - Typed-edge coverage is partial (typist sweep discipline)
- Evidence: d10 (four omissions across both runs, each with siblings that were typed) - `book-search` lacking RESTApi is the cleanest case because its JSON endpoint was already aggregated.
- Suspected root cause: edges are emitted opportunistically per focus area instead of as a roster-wide sweep (services x {WebPresentation shell, RESTApi overlay, IDENTIFIED_BY, AUTHENTICATED_BY, AUTHORIZED_BY, FRONTED_BY, DEPENDS_ON}).
- Candidate structural fix: a checklist step in the typist contract; the M4 metric makes the sweep measurable.

### C7 - Statements beyond observed evidence (GT spec scope)
- Evidence: d11 - two of three missing wj-004 statements are declared capability gaps by the spec itself, and the third (`username`) has no L0 carrier.
- Suspected root cause: the statement set mixes what recon can witness with what only source reading reveals.
- Candidate structural fix: a ruling - mark capability-gap statements as satisfied-by-declaration or excluded from M3, mirroring the `capability_gaps` mechanism used for `edges_to_l0`.

### Convention note (not a cluster)
- d12 (spine 2/5) is the deliberate re-homing of `api_paradigm` and `auth_methods` onto typed edges, plus a genuinely absent `business_function` prose field. See W2.3 D-5 for the pending ruling.

## 6. Verdict

The formal runs' shape is now explained end to end.
Recon delivered a GET-only, client-side-blind L0 surface (C1, C2, C4-minting); the assigner judged what it saw with sound ownership calls but committed without its final verification round (C3) and dropped ambiguous routes by policy (C5); the typist's edge typing was accurate but not swept (C6); and part of the System statement shortfall is a spec-scope question (C7).
The role-optimal paths in section 3 would NOT close the metric gaps on their own: the reachable role-side wins are C3 (evidence quality), C5 (one aggregation for the article path), and C6 (typed edges); the rest need the recon fixes already ticketed (#353, #360, #363, #365, #366) plus #367 and the new C3 ticket.
This is the joint-debugging agenda proposed to the operator in the W2.7 relay.
The single new ticket from this work is #369 (cluster C3).
