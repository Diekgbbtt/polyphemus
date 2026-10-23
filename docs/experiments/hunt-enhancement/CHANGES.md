# Hunt enhancement trunk changes

## Summary

This branch implements the safe context dedup and attention cuts across the four hunting agents.
It does not run a trial.
It leaves the system-prompt cut at the minimal decision: the hand-written tool summary and the direct-reference line stay.
The branch is `fix/hunt-context-dedup`, based on `hunt-enhancement-trunk`.

## Trunk

The trunk `hunt-enhancement-trunk` was created from `fix/context-lifecycle-followup`.
It merged `docs/comfyui-hunting-retest`.
The only merge conflict was the `FAILURES.md` union; it was resolved without dropping either side.
The trunk is pushed to origin.

## Changes

### Hunter

| Change | Before | After | Effect |
|---|---:|---:|---:|
| Loop tool surface | 22,470 chars | 0 | 5,361 uncached first-call tokens removed |
| First human messages | overview + loop, 2 messages | one instance-context message | the compaction pin preserves both |
| System prompt | 27,085 chars | 28,965 chars | generated spec table, writing rules, and the complete tool list |
| Spec body | 2,004-char partial prose | 2,675-char generated projection | every writable field, `skills`, and the bound `run_id` |
| Tools section | 7 names | 12 names | the stale subset is closed |
| Phase hint | "each tool result may carry" | transition-only wording | removes a false universal claim |
| Sharpening block | full evidence dump | id, statement, confidence | evidence detail no longer repeated |
| Tool descriptions | 22,775 chars | 8,478 chars | -14,297 chars (-62.8%) |
| Auth store | full write contract | read-only | no write capability on the hunter |

The 22,470-char loop tool surface was an exact copy of the request tool descriptions.
It sat in the first human message, after the system prompt, so it was uncached on the first call.
Removing it is the strongest measured win.

The generated spec body is sourced from `SpecWrite`, `SpecProvenance`, `TargetIdentity`, and `SkillProcedure`.
It names `skills` as the pod-runner skill list.
It marks `run_id` as bound and `spec_id` as derived.
This closes the semantic join failure that omitted `skills` and four provenance fields.

The request tool descriptions are now one dense contract per tool.
The schemas are unchanged in meaning.
The critical clauses are pinned by `tests/attack/test_tool_description_budget.py`.

### Threat modeller

| Change | Before | After | Effect |
|---|---:|---:|---:|
| Tool descriptions | 18,594 chars | 6,847 chars | -11,747 chars (-63.2%) |
| System prompt | 23,297 chars | 22,887 chars | -410 chars |
| Auth store | full write contract | read-only | no write capability |
| Tools list | 9 named | 10 named | `record_skill_lesson` is no longer hidden |
| 5xx rule | 715-char exact copy | shared pointer | one source for the rule |

The 5xx paragraph was byte-identical to the hunter paragraph.
It is now a short pointer that keeps the 502, 503, 504, and 404 semantics.

### Pod runner and triager

| Change | Runner before | Runner after | Triager before | Triager after |
|---|---:|---:|---:|---:|
| Tool descriptions | 12,979 | 5,098 | 12,715 | 4,834 |
| System prompt | 9,446 | 8,124 | 11,724 | 10,764 |
| Auth store | full | read-only | full | read-only |
| Tool list | 7 named | 8 named | 4 named | 6 named |

The runner now names `auth_store`.
The triager now names `graph_view` and `auth_store`.
The triager no longer carries the write contract on a role that never writes the store.
The shared conciseness directive is shortened once and embedded everywhere.

### Compaction

`compact_pass` now accepts `pin_first_human`.
The four hunting roles enable it through `PIN_FIRST_HUMAN_ROLES`.
The first human message through compaction stays byte-identical.
The hunter sends one instance-context message, so the pin covers the application overview and the loop.
The modeller, runner, and triager pin their first human context.
Analysis roles keep the previous fold behavior.

## Measured cache effect

The tool-description metric is the sum of `len(tool.description)` over the bound surface.
It is not the audit's request-schema character count.

| Role | Fixed cut | First-call effect | Warm-session effect |
|---|---:|---|---|
| Hunter | about 3,408 cached tokens plus 5,361 uncached loop tokens | miss share falls from 35.1% to about 20.9% | cached occupancy falls; runtime misses remain |
| Modeller | about 3,158 cached tokens | warm miss share rises from 16.0% to 19.7% | about 514,754 fewer input tokens over 163 calls; uncached unchanged |
| Runner | about 2,189 uncached cold tokens | cold miss tokens fall from 8,810 to 6,621 (-24.8%) | warm miss share rises slightly |
| Triager | about 2,230 uncached cold tokens | cold miss tokens fall from 11,712 to 9,482 (-19.0%) | warm miss share rises from 33.7% to about 36.6% |

The important correction is that removing cached fixed text lowers occupancy but can raise the miss share.
The hunter is the exception because the loop surface was uncached.
The modeller and pod fixed cuts are occupancy wins, not progressive-miss-ratio wins.
The progressive miss ratio is driven by runtime payloads.

## Test evidence

Focused suites:

- `tests/attack/test_hunting_agent.py`
- `tests/attack/test_hunting_agent_prompt.py`
- `tests/attack/test_hunter_tools.py`
- `tests/attack/test_tool_description_budget.py`
- `tests/attack/test_hunting_status.py`
- `tests/attack/test_http_history_tools.py`
- `tests/attack/test_graph_view_tool.py`
- `tests/attack/test_threat_modeller_prompt.py`
- `tests/attack/pod`
- `tests/app/test_auth_seams.py`
- `tests/app/test_auth_store_tool_readonly.py`
- `tests/test_llm_compaction.py`
- `tests/lightrag/test_tool_description.py`
- `tests/lightrag/test_kb_query_contract.py`
- `tests/recon/test_skill_lessons.py`
- `tests/recon/test_skill_protocol.py`
- `tests/recon/test_skill_data_section.py`

The focused runs passed 283, 397, and 607 tests in the three main batches.
The combined non-e2e run passed 6,135 tests, skipped 126, and xfailed 1.
It reported 25 failures and 3 errors.
Three of those failures reproduce on the untouched trunk and are not caused by this branch:

- `test_tool_contract_rejects_foreign_params`
- `test_thinking_baselines_are_set_on_the_reasoning_agents`
- `test_chat_model_for_carries_the_roles_thinking_baseline`

The remaining failures are environment or order dependent:

- Docker is not running, so the Kali, Steel, Neo4j, Postgres, and stack-smoke tiers fail;
- the live assigner tier needs its database;
- one eval overlay test passes in isolation but fails in the full order;
- the e2e blackloop tier needs the sibling agent container.

The full run with `tests/e2e` included stopped on the missing sibling-agent container.
That is an environment block, not a code failure.

## No trial

No new trial ran.
The next trial runs only after this branch is merged into the trunk, the trunk is merged into `dev`, CD reaches the eval server, and the operator authorizes the run.
The experiment score is `capped_tokens / confirmed_symptoms`, reported separately for ground-truth and non-ground-truth confirmations.

## Next work

- Merge the latest `docs/comfyui-hunting-retest` tip into the trunk.
- Merge this branch into the trunk.
- Generate the modeller state, gate, and reference tables from the typed models.
- Generate the pod variant and terminal tables from `VARIANT_BASES` and the validator.
- Bound the HTTP-history, auth-store, KB-answer, replay, and skill-body payloads at the source.
- Run the authorized trial and measure the score.
