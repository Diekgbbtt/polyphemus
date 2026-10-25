# Tool-response occupancy assessment and minimisation plan

**Date:** 2026-10-23.
**Trial:** `white-jotter-1-20261022T030303-1618c524`.
**Scope:** the hunter and threat-modeller tool responses, with the HTTP-history pair and `skill_list` as the named targets.
**Out of scope:** tool-description duplication (another workstream), system prompts, loop payloads, pod responses, and a new trial.

## Verdict

The occupancy analysis names the right component class, but its worst-payload attribution is wrong.
The 74,649-character payload in the modeller session is `auth_store`, not `search_http_history`.
The modeller's 50-row HTTP page is 22,302 characters.
The prior follow-up plan repeats the same swap in the opposite direction.
The correction changes the ranking of the remaining work.

The largest remaining hunter payload is `skill_list`.
It is 46,514 characters on every call, 10 calls, 9.49M carry characters, and 3.06M token-equivalent, or 11.4% of all hunter input.
`graph_view` is second at 2.60M token-equivalent, or 9.70%, but it has an explicit no-row-caps operator ruling.
`search_http_history` is third at 2.48M token-equivalent, or 9.25%, and it is the largest implementable payload win.
The auth store is already fixed and is excluded from the savings below.

Two changes carry almost all of the available, low-risk win:

| Change | Payload reduction | Hunter input saved | Modeller input saved | Complexity |
|---|---:|---:|---:|---|
| Lean HTTP summary row | 492,911 -> 166,079 chars (66.3%) | 1.63M tokens (6.08%) | 1.82M tokens (5.18%) | Low |
| Required `skill_list` regex with parent/leaf cascade | 465,140 -> 19,240 chars (95.9%) | 2.93M tokens (10.91%) | n/a in this trial | Medium |
| **Combined** | | **4.56M tokens (16.99%)** | **1.82M tokens (5.18%)** | |

Both roles together save 6.38M token-equivalent, or 10.3% of their 62.0M input.
The estimates use the same provider-input scaling as the occupancy analysis.
The exact counts are token-equivalent shares, not a claim about a future provider bill.

I recommend four decisions:

1. Implement the lean HTTP summary and correct its contract.
2. Implement the required `skill_list` filter, the parent/leaf cascade, and a per-tool entry cap.
3. Do not add first-class HTTP filter fields in this iteration; the existing filter DSL is adequate.
4. Defer lazy list stubbing; it adds about 2% of role input on top of the lean row, with medium-high complexity and a cache-prefix cost.

I also recommend a follow-up, not this iteration, for `graph_view` and `exec` output.
Both are larger than the HTTP win in raw token-equivalent, but each needs a separate design decision.

## 1. Evidence and correction

### 1.1 Data and method

I read the Langfuse v2 observation API for the trial window.
The crawl returned 1,437 generation records across 9 roles and 83 sessions.
The hunter and modeller roles account for 561 generations and 316 tool calls.
For each generation I joined every `role: tool` message to the assistant `tool_calls` entry by tool-call id.
Where a response repeats across turns, I kept the longest occurrence.
That is necessary because Langfuse stores at most about 261,236 characters of each generation input.

The lifecycle figure for a tool response is:

```
token_equivalent = provider_input_tokens * tool_response_chars / generation_input_chars
```

This is the same char-share method as `audit_context_occupancy.py`.
It is deliberately conservative: the JSON envelope and the truncated tail stay in the denominator.
The per-tool totals therefore differ slightly from the report's absolute totals.
The deltas between two projections are the useful quantity.

### 1.2 The attribution error

The raw records show the following.

| Role | Tool | Calls | Response chars | Max | Token-equivalent | Share of role input |
|---|---|---:|---:|---:|---:|---:|
| hunting_threat_modeller | `auth_store` | 1 | 74,649 | 74,649 | 8,436,447 | 23.99% |
| hunting_threat_modeller | `search_http_history` | 2 | 33,419 | 22,302 | 2,731,305 | 7.77% |
| hunting_hunter | `auth_store` | 6 | 452,469 | 76,188 | 1,726,286 | 6.43% |
| hunting_hunter | `search_http_history` | 57 | 459,492 | 44,423 | 2,481,067 | 9.25% |

The modeller's 74,649-character response starts with `{"ok": true, "command": "read", "value": {"overview": ...`.
Its `search_http_history` 50-row response starts with `{"summaries": ...` and is 22,302 characters.
The join is unambiguous.

The occupancy analysis says:

> The 50-row HTTP-history page alone carries 11.5M chars over 154 turns from one 74,649-char response.

That sentence attributes the 74,649-character payload to HTTP.
The payload is the auth store.
The prior follow-up plan's "Evidence corrections" section then says the 74,649-character message is the HTTP search result and the auth store is 22,302 characters.
That is the same swap in the opposite direction.
Both statements are wrong for this trial.

The correction matters for three reasons:

- The HTTP page is 22,302 characters in the modeller, not 74,649. The HTTP win is still large, but it is not the largest single remaining offender.
- The auth store is the largest single payload in the trace. The summary default has already removed it from the current code, so its 10.16M token-equivalent across both roles is not available as new work.
- `skill_list` is the largest remaining hunter payload. The prior ranking hid it because the report did not break it out.

### 1.3 Why the old report under-counted `skill_list`

The report's tool-response inventory lists `skill_list` but does not attribute its carry.
It says "the skill body about 1.3M carry".
That figure matches the modeller's single `load_skill` response, not the hunter's `skill_list`.
The hunter's `skill_list` calls are ten identical 46,514-character responses.
They carry 9.49M characters, and they are 11.4% of hunter input.
The report's "skill body" label therefore describes a different, much smaller payload.

## 2. Use cases and call legitimacy

### 2.1 Threat modeller

The modeller's intended use of HTTP history is the attack-surface view.
It needs the recorded methods, URLs, statuses, sizes, and artifact ids to name evidence and choose a baseline.
It has no `graph_view` tool on its surface in this trial.
Its tools are `hunts_store`, `notes`, `search_http_history`, `get_http_artifact`, `exec`, `skill_list`, and `skill_load`.

The trace has two modeller HTTP calls:

- one unfiltered `limit=50` inventory call, 50 rows, 22,302 characters;
- one `url prefix http://t-1618c524.target/api/` call, 25 rows, 11,117 characters.

Both calls are legitimate.
The unfiltered call is the first surface inventory.
The filtered call narrows to the API prefix.
Neither call can be replaced by the graph, the notes, or the KB:

- the graph view is not bound on the modeller surface;
- the graph carries endpoint metadata, not recorded transactions;
- the notes are the modeller's own text, not evidence;
- the KB is conceptual knowledge, not this project's traffic;
- only the HTTP store carries `artifact_id` baselines and recorded headers, statuses, and sizes.

The modeller's high HTTP cost is therefore a payload-shape problem, not a legitimacy problem.

### 2.2 Hunter

The hunter's intended use is narrower:

- load the suite class named by the loop payload;
- confirm whether a candidate request already exists;
- harvest payload vectors, parameter names, and privilege signals;
- choose a recorded baseline for `provenance.baseline_ref`;
- optionally list the suite for a sibling leaf when the class skill does not cover an assumption.

The hunter's first message already carries `web-vulnerability suite class: <name>`.
The trace shows 10 `skill_list` calls with no filter.
Every one is followed by a `skill_load` for a class the hunter already knew.
The initial full listing is therefore not needed for the class load.
It is at best a menu, and at worst 46.5k characters to confirm a name that arrived in the prompt.

The HTTP calls are legitimate.
There are 57 hunter calls:

| Row bucket | Calls |
|---|---:|
| 0 rows | 12 |
| 1-9 rows | 15 |
| 10-29 rows | 14 |
| 30-59 rows | 15 |
| 60+ rows | 3 |

The 12 empty calls are cheap, 51 to 73 characters each.
The 3 large calls are deliberate inventories: 100 unfiltered rows, 60 `static/js` rows, and 60 `/login` rows.
The rest use precise `url`, `method`, `status`, or header filters.
The pattern is a legitimate candidate search that is forced to carry too many columns.

The 39 `get_http_artifact` calls are small, 1,686 characters on average and 2,048 maximum.
The two-step chain is sound: a list of candidates, then one inspection.
The defect is that the candidate row is almost a full record.

### 2.3 Can upstream stores replace the calls?

No, not for either role.

The graph view can answer "which endpoint exists".
It cannot answer "which recorded request instance has this header, this status, this body size, and this artifact id".
The hunter needs the instance for payload vectors and replay.
The modeller needs the instance for evidence and baselines.
The notes are not evidence.
The KB is not project traffic.

The correct upstream change is not a replacement.
It is a narrower HTTP row and a filtered suite menu.
The tool family should stay.

## 3. HTTP-history assessment

### 3.1 What the 1,103 rows actually contain

Across 59 calls the hunter and modeller received 1,103 summary rows.
The value characters by field are:

| Field | Value chars | Share of value chars | Distinct values | Empty or constant |
|---|---:|---:|---:|---|
| `url` | 46,753 | 21.2% | 421 | no |
| `project_id` | 41,914 | 19.0% | 1 | constant |
| `artifact_id` | 36,399 | 16.5% | 1,103 | no |
| `host` | 20,942 | 9.5% | 2 | near constant |
| `created_at` | 19,619 | 8.9% | 421 | no |
| `http_version` | 11,030 | 5.0% | 1 | constant |
| `timing_ms` | 7,009 | 3.2% | 420 | no |
| `method` | 6,003 | 2.7% | 3 | no |
| `status_class` | 5,515 | 2.5% | 3 | derived from `status` |
| `tls` | 5,515 | 2.5% | 1 | always `false` |
| `error_type` | 4,412 | 2.0% | 1 | always `null` |
| `derived_from` | 4,412 | 2.0% | 1 | always `null` |
| `replay_kind` | 4,412 | 2.0% | 1 | always `null` |
| `status` | 3,309 | 1.5% | 5 | no |
| `response_size` | 2,597 | 1.2% | 45 | no |
| `request_size` | 1,315 | 0.6% | 21 | no |

The constants are the story.
Every row repeats the same `project_id`, `http_version`, and `tls` value.
Every row carries three null lineage fields.
`host` is already inside `url`.
`status_class` is a prefix of `status`.
`created_at` and `timing_ms` matter for a single inspected artifact, not for a candidate menu.

The first eight fields above account for 86% of the value characters.
The constant, near-constant, and derived fields account for about 45%.
That is why the current row is 445 characters on average when the decision needs about 150.

### 3.2 The lean summary

The lean projection is:

- always: `artifact_id`, `method`, `url`, `status`;
- when non-zero: `request_size`, `response_size`;
- when non-null: `derived_from`, `replay_kind`, `error`.

`host` is dropped because `url` carries it.
`project_id` is dropped because the search is project-bound and every row repeats it.
`created_at` is dropped because paging is deterministic and `get_http_artifact` carries it.
`status_class` is dropped because it is derivable from `status`.
`http_version`, `tls`, `timing_ms`, and `error_type` move to `get_http_artifact`.
The sparse lineage fields stay only when they carry information.

The measured result over the 59 calls is:

| Variant | Total chars | Saving vs actual |
|---|---:|---:|
| Actual page, default JSON | 492,911 | - |
| Actual page, compact JSON | 457,347 | 7.2% |
| Lean page, default JSON | 177,265 | 64.0% |
| **Lean page, compact JSON** | **166,079** | **66.3%** |
| Lean minimal (identity and status only) | 145,557 | 70.5% |

The lean page keeps the sizes and the sparse lineage fields.
It still saves two thirds of the payload.
The compact JSON alone saves 7.2%, so the HTTP tools should use compact separators.

The lifecycle effect is:

| Role | Actual HTTP token-equivalent | Lean | Saved | Share of role input |
|---|---:|---:|---:|---:|
| Hunter | 2,481,067 | 848,481 | 1,632,585 | 6.08% |
| Threat modeller | 2,731,305 | 909,906 | 1,821,399 | 5.18% |
| **Both** | **5,212,372** | **1,758,387** | **3,453,985** | **5.57% of both** |

The sample session below shows how the reduction reaches the prompt.

### 3.3 First-class filters are not the defect

The trace does not support adding first-class filter fields.

The existing DSL is `{side, namespace, key, op, value}`.
It is conjunctive and expressive.
The models used it correctly in 55 of 59 calls.
The broad calls are deliberate inventories, not failed filters.
The errors are model errors, not missing dimensions:

- one `op: "present_placeholder"` hallucination, despite the description saying there is no `present` op;
- one `side: response, key: url` call, which returned zero rows because `url` is a request field.

Adding `method`, `status`, `host`, or `path_prefix` as first-class fields would not stop a model from asking for 100 rows.
It would add schema and description surface to every turn.
It would create a second filter vocabulary beside the one that already works.

A future change can add `present` or validate core key/side pairs if the same errors recur.
Do not add first-class fields in this iteration.

### 3.4 Lazy list stubbing

The lazy idea is to replace a prior search response with its identifying keys after a small number of turns.
The model would keep `artifact_id` and use `get_http_artifact` for detail.

The simulation used a stub of the form:

```json
{"artifact_ids": ["http_..."], "stub": "rows elided; inspect one with get_http_artifact"}
```

After the lean projection, stubbing after two turns adds:

| Role | Lean saving | Lean + stub saving | Extra | Extra share |
|---|---:|---:|---:|---:|
| Hunter | 1,632,585 | 2,178,883 | 546,297 | 2.04% |
| Threat modeller | 1,821,399 | 2,505,195 | 683,796 | 1.94% |

The extra is about 2% of role input.
The cost is not small:

- it rewrites messages in the checkpointer history;
- it breaks the provider's cached prefix at the rewritten message;
- it must preserve assistant/tool pairing;
- it must decide per tool which keys are sufficient;
- it can remove status or size context the model needs later.

The existing compaction middleware already offloads tool bodies under window pressure.
A second, always-on rewrite lane is a separate experiment.
Defer it until the lean row and the filtered listing are measured in a new trial.

### 3.5 The contract has a false row claim

`SEARCH_HTTP_HISTORY_DESCRIPTION` says:

> Each row carries `capture_state`, `derived_from`, and `replay_kind`.

The actual summary has no `capture_state`.
It has `derived_from` and `replay_kind`, but both are null in this trial.
The model is told to read a field that does not exist.
That is a specification-quality defect, not only a payload defect.

The fix is to describe the actual lean row and point `capture_state` to `get_http_artifact`.
Do not add `capture_state` to the row.
The replay decision belongs to the inspected artifact, and the get view already carries it.

## 4. `skill_list` assessment

### 4.1 Current payload

The live suite has 165 entries:

- 41 class parents;
- 124 variant leaves.

The listing response is 46,514 characters:

- 4,007 characters of names;
- 37,030 characters of descriptions;
- about 5,477 characters of JSON and field overhead.

The trial has 10 hunter calls, all with `{}` arguments.
Every call returns the same 46,514-character listing.
The calls carry 9.49M characters and 3.06M token-equivalent, or 11.4% of hunter input.
No modeller call occurs in this trial, but the tool is bound on the modeller surface too.

All 10 calls are followed by a `skill_load`.
The loaded class is already in the hunter's first message.
The listing is used as a menu, not as a source of new class names.

### 4.2 The filter and the cascade

The proposed contract is:

- `filter` is required;
- `filter` is a case-insensitive Python regex searched against skill names;
- a matching class parent also returns its variant leaves;
- a matching variant leaf also returns its class parent;
- the response is grouped as a parent-first cascade;
- missing filter returns `skill_filter_required`;
- invalid regex returns `skill_filter_invalid`;
- no match returns an empty `skills` list with the filter echoed;
- the response is capped at 20 entries with an `omitted` count.

The cascade is not cosmetic.
The suite contains leaves whose names do not contain the parent name:

- `bfla-alternate-path`, `bfla-client-identity-trust`, and `bfla-deferred-execution` are leaves of `broken-function-level-authorization`;
- `information-disclosure-excessive-data-exposure` is a leaf of `information-disclosure`.

A pure name regex for `broken-function-level-authorization` would return only the parent.
A pure name regex for `bfla` would return leaves without their class parent.
The parent map is required for correctness, not for presentation.

### 4.3 Measured reduction

I replayed each of the 10 calls against the live 165-entry catalogue.
I used the class of the skill the session actually loaded, and I rendered that parent plus its subtree.

| Session | Loaded skill | Exact entry | Parent subtree |
|---|---|---:|---:|
| ReverseProxy-nginx-1.31.6 loop 3 | `proxy-techniques-relay-forwarding` | 594 | 5,298 |
| IntegrationSystem-cross-origin-policy loop 2 | `defence-bypass-edge-origin-differential` | 477 | 4,042 |
| IntegrationSystem-cross-origin-policy loop 3 | `csrf` | 189 | 1,686 |
| Service-sign-in loop 3 | `session-management` | 289 | 289 |
| Service-sign-in loop 2 | `rate-limit-bypass` | 461 | 461 |
| Service-navigation-menu loop 1 | `information-disclosure` | 207 | 1,502 |
| Service-navigation-menu loop 2 | `information-disclosure-excessive-data-exposure` | 441 | 1,502 |
| Service-sign-in loop 6 | `insecure-deserialization` | 255 | 1,241 |
| Service-sign-in loop 5 | `csrf`, `csrf-navigation-get` | 469 | 1,686 |
| Service-navigation-menu loop 3 | `broken-function-level-authorization` | 216 | 1,533 |

Totals:

| Projection | Chars over 10 calls | Saving | Hunter token-equivalent | Saved | Share of hunter input |
|---|---:|---:|---:|---:|---:|
| Current full listing | 465,140 | - | 3,059,249 | - | 11.40% |
| Exact-name filter | 3,712 | 99.2% | 24,400 | 3,034,849 | 11.31% |
| Parent-subtree filter | 19,240 | 95.9% | 132,554 | 2,926,695 | 10.91% |

The parent-subtree projection is the conservative one.
It keeps the class parent and all of its leaves, so the model can still choose a sibling.
It still removes 95.9% of the payload.

A broad regex such as `.*` would select all 165 entries.
The 20-entry cap bounds that case at about 6 to 9k characters and reports the omitted count.
A filter such as `auth|session|csrf` would select several subtrees and still stay under the cap.
The current 46.5k full dump is never the only option under the new contract.

### 4.4 Call legitimacy and upstream replacement

The initial class load does not need `skill_list`.
The class name arrives in the loop payload.
The legitimate uses are:

- the modeller mapping a free canonical class onto a suite class;
- the hunter finding a sibling leaf for an assumption check.

Both uses need a filtered list, not a full catalogue.
The required filter turns the tool into a targeted lookup.
A prompt change could also tell the hunter to load the class directly.
That is a separate prompt workstream; the contract fix is safe on its own.

The graph and the KB cannot replace the suite.
The suite is the canonical class mapping and the procedure bodies.
The graph carries endpoints, not vulnerability procedures.

## 5. Other tools

The following table uses the same method as the named targets.

| Tool | Role | Calls | Payload chars | Max | Token-equivalent | Share |
|---|---|---:|---:|---:|---:|---:|
| `graph_view` | hunter | 50 | 343,692 | 82,039 | 2,602,850 | 9.70% |
| `skill_load` | hunter | 19 | 252,231 | 19,109 | 1,452,966 | 5.41% |
| `auth_store` | hunter | 6 | 452,469 | 76,188 | 1,726,286 | 6.43% |
| `auth_store` | modeller | 1 | 74,649 | 74,649 | 8,436,447 | 23.99% |
| `exec` | modeller | 17 | 74,152 | 37,670 | 6,704,545 | 19.06% |
| `load_skill` | modeller | 1 | 8,567 | 8,567 | 970,343 | 2.76% |
| `get_http_artifact` | hunter | 39 | 65,776 | 2,048 | 338,150 | 1.26% |
| `kb_query` | hunter | 14 | 23,283 | 2,302 | 116,091 | 0.43% |
| `hunts_store` | both | 29 | 21,810 | 12,150 | 323,687 | small |
| `notes` | both | 59 | 10,477 | 2,934 | 42,503 | small |

### 5.1 `graph_view`

`graph_view` is the second-largest remaining hunter payload.
The worst single response is 82,039 characters, from:

```cypher
MATCH (s:L1System) WHERE ... RETURN s.kind, s.discriminator, labels(s), properties(s) LIMIT 20
```

The 82k response comes from returning whole nodes and whole property maps, not from a row cap.
The contract already tells the model to project fields and to always use `LIMIT`.
The trace shows three responses over 16k and 88 generation occurrences over 16k.
Those occurrences carry about 1.28M token-equivalent, or 4.8% of hunter input.

A response cap could recover most of that, but the graph-view contract has an explicit no-row-caps operator ruling (#197 Q6).
Do not change it without operator approval.
Record it as the next high-yield candidate.

### 5.2 `exec`

The modeller's `exec` is 19.06% of its input.
One 37,670-character probe carries 117 generation occurrences over 16k, about 4.22M token-equivalent.
That is larger than the HTTP win.
But the output is live evidence.
A blind cap can hide the result the modeller needs.

The right follow-up is output discipline, not a global truncation:

- the probe contract should tell the model to pipe through `head`, `grep`, or a summary;
- the tool can return a bounded head and tail with a clear `truncated` marker;
- the full output can stay in the exec record for the evidence chain.

That is a separate design decision.
Do not implement it in this iteration.

### 5.3 `auth_store`

The summary default is already in the current code.
The trial predates the fix.
The 74,649-character modeller response and the 76,188-character hunter responses are historical.
Exclude their 10.16M token-equivalent from all new-work totals.
The code should not be changed again for this task.

### 5.4 `skill_load`, `get_http_artifact`, and the small tools

`skill_load` is a procedure body the agent explicitly requested.
The payload is the work product.
Do not cap it in this iteration.

`get_http_artifact` is already small.
Its 2,048-character maximum is the right size for an inspection step.
Do not add lazy stubbing or field projection to it.

`kb_query`, `hunts_store`, and `notes` are small.
They are not candidates.

### 5.5 A global word cap

A single global cap is the wrong instrument.

- It would truncate `skill_load` procedure bodies, which are the point of the call.
- It would truncate `exec` evidence, which may be the only proof of a probe result.
- It would truncate valid large artifact inspections.
- It would not fix the cause of the HTTP page, which is a wide row.
- It would interact badly with JSON: a blind character cut can produce invalid JSON.

Use per-tool structured budgets instead:

- `skill_list`: required filter plus a 20-entry cap and `omitted`;
- `search_http_history`: lean rows, default `limit=50`, and the existing cursor;
- `graph_view`: a future row/byte cap with a projection hint, subject to approval;
- `exec`: a future bounded-output contract with a truncation marker;
- `skill_load`: no cap.

The only new cap in this iteration is the `skill_list` entry cap.

## 6. Sample hunter session walkthrough

Session: `5c9590ff-9a83-4cea-9aff-be1bd51e2667:Service-sign-in__loop-2:hunting_hunter`.
It has 33 generations and 2,052,573 input tokens.
It used `skill_list`, `skill_load`, five HTTP searches, and several `get_http_artifact` calls.

The first turns show the payload jumps:

| Turn | Time | Input tokens | New tool response | Response chars |
|---:|---|---:|---|---:|
| 3 | 00:45:50 | 27,724 | `graph_view` | 1,604 |
| 4 | 00:46:32 | 37,283 | `skill_list` | 46,514 |
| 5 | 00:46:42 | 40,471 | `skill_load` | 14,279 |
| 6 | 00:48:33 | 54,085 | `search_http_history` | 26,385 |
| 7 | 00:48:54 | 54,588 | `search_http_history` | 51 |
| 8 | 00:49:10 | 55,170 | `search_http_history` | 923 |
| 9 | 00:51:07 | 56,117 | `get_http_artifact` | 1,720 |

The `skill_list` call alone adds about 9,559 input tokens on the next turn.
The 26,385-character HTTP page adds another large jump.
The rest of the session pays for both payloads on every later turn.

The session's filters and loads were:

- `skill_list({})`, then `skill_load("rate-limit-bypass")`;
- `search_http_history(filters=[url contains "/login"], limit=60)`, 60 rows;
- four small follow-up searches, 0 to 2 rows;
- `get_http_artifact` calls for the selected baselines.

The counterfactual uses:

- `skill_list(filter="rate-limit-bypass")` -> 461 characters;
- the lean HTTP rows, with the 60-row page at 9,423 characters instead of 26,385;
- the small pages at their lean sizes.

Measured over the whole session:

| Scenario | Target token-equivalent | Saving vs baseline | Share of session |
|---|---:|---:|---:|
| Baseline | 1,972,121 | - | - |
| Lean HTTP plus filtered `skill_list` | 1,447,669 | 524,452 | 25.55% |
| Lean plus two-turn HTTP stub | 1,387,021 | 585,100 | 28.51% |

The two targeted changes remove a quarter of the session's input tokens.
The lazy stub adds only 2.95 percentage points.
That is the clearest evidence for the priority order: fix the row and the filter first, and treat stubbing as a separate experiment.

## 7. Feasibility and risk

| Change | Main files | Complexity | Main risk | Mitigation |
|---|---|---|---|---|
| Lean HTTP summary | `kali/http_history/sanitize.py`, `http_history_contract.py`, `hunter_tools.py` | Low | a model wants a dropped field | `get_http_artifact` carries the full record; the description says so |
| Compact HTTP JSON | `hunter_tools.py` | Low | none material | valid JSON; tests parse it |
| Required `skill_list` filter | `threat_modeller_tools.py`, `skills.py`, `hunter_tools.py`, `hunting_agent.py`, `llm.py`, `runtime.py` | Medium | the seam lacks parent data | add `suite_parents()` to the catalogue and thread it through |
| Parent/leaf cascade | `threat_modeller_tools.py` | Medium | a parent match hides an abbreviated leaf | expand a matched parent to its subtree; add a leaf to its parent |
| `skill_list` cap | `threat_modeller_tools.py` | Low | a broad pattern hides a relevant entry | 20 entries plus `omitted`; the model narrows |
| Lazy HTTP stubbing | compaction or a new middleware | Medium-high | cache-prefix break and lost context | defer; measure the lean row first |
| Graph-view cap | `graph_view_tool.py` | Medium | conflicts with #197 Q6 | operator approval first |
| Exec output cap | `hunter_tools.py` / probe contract | Medium | hides evidence | bounded head/tail plus a record; separate decision |

The skill filter needs a small interface change.
`VulnerabilitySuiteSeam` currently receives only `classes` and `read_fn`.
It cannot tell a parent from a leaf, and it cannot know that `bfla-*` belongs to `broken-function-level-authorization`.
Add a `parents` mapping to the seam and a `suite_parents()` catalogue method.
The mapping is derived from the live directory tree, so it stays correct when the suite gains leaves.

The regex is standard-library `re`.
The names are short and the entry set is bounded.
A missing filter and an invalid regex are coded errors, not raises.
The filter is capped at 200 characters, and the result is capped at 20 entries.
This matches the existing `load_skill` listing discipline without adding a dependency.

## 8. Threats to validity

- This is one trial on one target. The field constants may differ on a target with TLS, HTTP/2, or multiple projects. The lean schema still carries `url`, `status`, and sizes, so the important variance survives.
- The token figures are char-share estimates. The deltas are robust; the absolute totals are not a billing prediction.
- Langfuse truncates long inputs at about 261k characters. A late response may be missing from some generations. The per-call payload sizes come from the longest occurrence.
- The filter simulation assumes the model chooses the class parent it later loaded. A broader regex would return more entries, but the 20-entry cap bounds it.
- The live catalogue matches the trial's 165 entries in this checkout. A future suite change can alter the sizes.
- The auth-store fix is post-trial. Its savings are excluded, not re-counted.
- No new trial was run. Discovery quality after the change is unmeasured; the plan includes a verification trial as a follow-up, not as part of this task.

## 9. Decisions

Implement now:

1. Lean HTTP summary and compact serialization.
2. Correct the HTTP summary contract.
3. Required `skill_list` regex, parent/leaf cascade, coded errors, and a 20-entry cap.
4. Tests and the targeted suites.

Do not implement now:

1. First-class HTTP filter fields.
2. Lazy HTTP list stubbing.
3. A global word cap.
4. A `graph_view` row cap.
5. An `exec` output cap.

Follow-ups, in order:

1. Measure the two changes in a new trial, if the operator authorises one.
2. `graph_view` projection/cap with operator approval.
3. `exec` output discipline.
4. A controlled n-turn stub experiment, only if the new trial still shows large repeated HTTP lists.
5. Core-key filter validation or a `present` op, only if the same filter errors recur.
   The core-key half is done (2026-10-23); the `present` op is still deferred.

The implementation plan is in `TOOL-RESPONSE-MINIMIZATION-PLAN.md`.

## 10. Row extension and dependency alignment (2026-10-23)

The lean row was extended with the triage headers, by operator decision.
The row now carries `request_headers` and `response_headers` when the transaction holds them: lowercased names, duplicates as a list, a 256-character value cap, and verbatim values.
`content-length` stays out because the size fields already carry it.
`location` is in the response set.

The first-class filter enhancement stays closed.
Section 3 records the three evidences: the selectors are already used in 57 of 59 calls, payload is driven by breadth and `limit`, and a `key:value` header grammar is lossy.
The one real defect - a wrong-side or unknown core key returning an empty page - is fixed with a side-bound core-key check and the existing `invalid_filter` mapping.

Cost of the header extension, projected from the 38 `get_http_artifact` payloads of the same project and trial window:

| Item | Value |
|---|---|
| Selected headers before the extension, with redaction | about 155 characters per row |
| Selected headers after the extension, verbatim and capped | about 155 to 260 characters per row |
| Row total after the extension | about 337k to 386k characters, or 22% to 32% below the 492,911 baseline |

The upper bound is an estimate.
The source search rows do not carry headers, so the only header sample is the 38 inspected artifacts.
The cached crawl was lost with the temporary directory, so the verbatim cost is not re-measured here.
A new trial is the right way to measure it.

The header taxonomy, the row shape, and the core-key rule are documented in `docs/design/http-proxy-history-design.md` section 2.5 and `docs/design/http-history-search-filter-plan-adr.md` section 6.
The dependency map and the execution plan are in `HTTP-HEADER-AND-DEPENDENCY-ALIGNMENT-PLAN.md`.

### 10.1 Three filter traps closed (2026-10-25)

A code review of the row against the query compiler found three ways to get an empty page that reads as "no such traffic".
All three are fixed in the store; no filter field, operator, or namespace was added.

| Trap | Cause in code | Fix |
|---|---|---|
| a numeric string on a numeric key | `status`, `total_ms`, and `body/size` are indexed with `numeric_value` and no `text_value`; `eq "404"` compared `text_value` and matched nothing | `eq` coerces a numeric string; a non-numeric string stays a text compare, so `status eq "none"` still finds a response-less artifact |
| a cookie key in the wrong case | cookie names are indexed as recorded (`JSESSIONID`) and only header keys were lowercased, so `jsessionid` matched nothing; the row carries no cookies to reveal the case | the cookie key folds case on both sides, and `LOWER(a.key)` also matches rows written before the change |
| a sanitized URL beside a raw-URL predicate | the index matches `artifact.request.url`; the row rendered `sanitize_url(...)` | the summary carries the recorded URL verbatim |

The third trap decides the URL question the operator asked: because the sanitization exists to redact sensitive data, it is removed from the summary row.
`sanitize_artifact` keeps it, and the full view cuts or changes these URL parts:

| URL part | Full view |
|---|---|
| userinfo (`user:password@`) | dropped entirely |
| a query value whose name looks sensitive | replaced with `[redacted]` |
| percent-escapes in query names and values | decoded (`a%20b` becomes `a b`) |
| a bare query parameter | gains `=` (`?flag` becomes `?flag=`) |
| scheme case | lowercased by `urlsplit` |

The host, port, path, `;params`, query order, duplicate query keys, and fragment are preserved.
The row now matches the indexed string byte for byte, so a filter value is always visible in the row that matched it.
