# HTTP summary headers and dependency alignment plan

> **For agentic workers:** execute this plan task by task.
> Keep the checkbox state current.
> Do not add work outside the listed tasks.
> If a task reveals a blocking defect outside the listed files, record it in "Deferred findings" and continue.

**Goal:** extend the HTTP-history summary row with the triage headers, reject wrong-side core keys with a coded error, and align every consumer and design document that depends on the HTTP-history and `skill_list` contracts.
**Baseline:** `white-jotter-1-20261022T030303-1618c524`.
**Branch:** `fix/tool-response-minimization`.
**Worktree:** this checkout.
**No new trial.** All verification uses tests and the existing trace aggregates.

## Operator decisions

These decisions are settled.
Do not reopen them inside this plan.

- The summary row carries compact nested header maps: `request_headers` and `response_headers`.
- Header names are lowercased; only present keys are rendered.
- Duplicate header names keep every value as a list.
- A header value is capped at 256 characters.
- Header values are rendered VERBATIM.
  There is no redaction in the summary row.
- `content-length` is omitted because `request_size` and `response_size` already carry it.
- `location` is included in the response set.
- Filter validation rejects an unknown core key and a core key on the wrong side.
- The description teaches the request and response header families.
- No first-class filter fields are added.

## Why the first-class filter enhancement is closed

The operator asked for three drastic evidences against the proposed `url`, `method`, `status`, and `header:value` fields.
The evidence is in `TOOL-RESPONSE-OCCUPANCY-ASSESSMENT.md` section 3.
It is summarised here so this plan is self-contained.

1. **The selectors already exist and are used.**
   57 of 59 calls already carry a selector: 44 `filters`-only, 12 `text`-only, 1 both.
   Only 2 calls are broad.
   The trace already contains 25 URL `contains` calls, 11 header calls, 3 status calls, and 2 method calls.
   The proposed fields are aliases for capabilities the model already uses.
2. **Payload is driven by breadth and `limit`, not by filter syntax.**
   Nine calls with `limit >= 50` carry 174,785 characters, or 35.5% of the payload.
   Three calls carry 19.8% on their own: 100 broad rows, 60 `static/js` rows, 60 `/login` rows.
   A first-class filter does not cap `limit`, force a narrower query, or shrink a row.
   The lean row projection is the real lever.
3. **A `key:value` header filter is lossy.**
   14 of 38 sampled artifacts carry duplicate header names.
   There are 29 `Set-Cookie` occurrences.
   `Date`, `Origin`, `Location`, and `Access-Control-Allow-Origin` values contain colons.
   One `key:value` string cannot express duplicate values, side, operator, or `absent` without a second grammar.

The structured `{side, namespace, key, op, value}` DSL already expresses every one of them.
The enhancement therefore stays closed.
The one real defect is a wrong-side or unknown core key returning an empty result.
Task 2 fixes that defect without new filter fields.

## Impact map

Every component that reads or teaches the two changed contracts.

| Component | Current dependency | Change | Kind |
|---|---|---|---|
| `kali/http_history/sanitize.py::sanitize_summary` | produces the search row | add the two header maps | code |
| `kali/http_history/store.py::_filter_sql` | validates side, namespace, op | add core-key and side validation | code |
| `kali/http_history/service.py::search` | wraps the store page | none, it passes the row through | none |
| `kali/mcp_server.py::search_http_history` | maps `ValueError` to `invalid_filter` | none, the existing mapping carries the new error | none |
| `src/polymerhus/app/clients/kali_http_history.py::_call_tool` | passes the MCP payload through | none | none |
| `src/polymerhus/attack/hunting/http_history_contract.py` | the one model-facing contract | header taxonomy, row fields, validation | code |
| `src/polymerhus/attack/hunting/hunter_tools.py` | search/get tools and args | args field description | code |
| `src/polymerhus/analysis/graph_tools.py` | reuses the hunter classes | none, it inherits the change | none |
| `src/polymerhus/app/llm/prompts/skill_evolver.md` | lists the HTTP tools | none, it reads the shared contract | none |
| `src/polymerhus/analysis/prompts/technical-system.md` | teaches the read pair | none, no row shape named | none |
| `src/polymerhus/analysis/prompts/assigner.md` | teaches the read pair | none, no row shape named | none |
| `src/polymerhus/attack/hunting/prompts/hunting-agent.md` | says `skill_list` with no filter | require a name regex | prompt |
| `src/polymerhus/attack/hunting/prompts/threat-modeller.md` | says `skill_list` with no filter, 3 places | require a name regex and the cascade | prompt |
| `src/polymerhus/attack/hunting/threat_modeller.py::GATE_HINTS` | names the suite pair | name the filtered listing | code |
| `src/polymerhus/attack/hunting/threat_modeller_tools.py` | the suite seam, filter, cap | none, already implemented | none |
| `src/polymerhus/app/llm/skills.py` | catalogue and parent map | none, already implemented | none |
| `tests/kali/test_http_history_sanitize.py` | asserts the lean row | add header tests | test |
| `tests/kali/test_http_history_search.py` | asserts filter behaviour | add validation tests | test |
| `tests/kali/test_http_history_mcp_tools.py` | asserts the coded errors | add the wrong-side case | test |
| `tests/attack/test_http_history_tools.py` | asserts the contract text | add the header clause | test |
| `tests/attack/test_tool_description_budget.py` | caps the 12 descriptions at 8,500 | raise the cap, with the reason | test |
| `docs/design/http-proxy-history-design.md` | states the query contract | document the row projection and validation | doc |
| `docs/design/http-history-search-filter-plan-adr.md` | states the filter contract | record the validation change | doc |
| `docs/design/tool-call-failure-modes.md` | FM-B teaches the filter vocabulary | add the wrong-side class | doc |
| `docs/design/hunting-67-threat-modeller-spec.md` | states the suite binding | filtered listing and cascade | doc |
| `docs/design/hunting-67-hunting-agent-spec.md` | states the suite binding | filtered listing | doc |
| `docs/design/unit-threat-model-workflow.md` | states the suite binding | filtered listing | doc |
| `docs/design/unit-threat-model-abduction-research.md` | states the suite binding | filtered listing | doc |
| `docs/design/analysis-unit-enrichment-data-modeller-subproblems.md` | states the row shape | add the header maps | doc |
| `src/polymerhus/attack/hunting/CONTEXT.md` | describes both contracts | amend both paragraphs | doc |
| `docs/experiments/.../TOOL-RESPONSE-OCCUPANCY-ASSESSMENT.md` | the payload assessment | add the header-cost addendum | doc |

Deployment note, not a code change: `kali/**` rides the Kali image.
A production rollout needs a Kali image rebuild and `docker restart kali`.
`src/polymerhus/**` rolls with the app image.

## Task 1: extend the summary row

### 1.1 Add the header sets and the projection

- [x] In `kali/http_history/sanitize.py`, add:

  ```python
  SUMMARY_REQUEST_HEADERS = frozenset({
      "authorization", "content-type", "cookie", "origin", "referer",
      "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
      "x-forwarded-protocol", "x-real-ip",
  })
  SUMMARY_RESPONSE_HEADERS = frozenset({
      "access-control-allow-credentials", "access-control-allow-headers",
      "access-control-allow-methods", "access-control-allow-origin",
      "access-control-expose-headers", "access-control-max-age",
      "content-security-policy", "content-security-policy-report-only",
      "content-type", "location", "server", "set-cookie",
      "www-authenticate", "x-cache", "x-cache-lookup", "x-frame-options",
      "x-powered-by",
  })
  SUMMARY_HEADER_VALUE_MAX = 256
  ```

- [x] Add the projection helper:

  ```python
  def _summary_headers(headers, selected: frozenset[str]) -> dict[str, list[str]]:
      """Only the selected keys, lowercased, every value kept, value capped."""
      out: dict[str, list[str]] = {}
      for name, value in headers or []:
          key = str(name).strip().lower()
          if key not in selected:
              continue
          text = str(value)
          if len(text) > SUMMARY_HEADER_VALUE_MAX:
              text = text[:SUMMARY_HEADER_VALUE_MAX - 3] + "..."
          out.setdefault(key, []).append(text)
      return out
  ```

- [x] In `sanitize_summary`, after the size fields, add:

  ```python
      request_headers = _summary_headers(
          artifact.request.headers, SUMMARY_REQUEST_HEADERS)
      if request_headers:
          summary["request_headers"] = request_headers
      if response is not None:
          response_headers = _summary_headers(
              response.headers, SUMMARY_RESPONSE_HEADERS)
          if response_headers:
              summary["response_headers"] = response_headers
  ```

- [x] Rewrite the module docstring.
  It currently promises "no raw secrets".
  State the operator exception for the summary row and that `sanitize_artifact` still redacts.
- [x] Update the `sanitize_summary` docstring to name the two header maps and the verbatim rule.

### 1.2 Tests

- [x] In `tests/kali/test_http_history_sanitize.py`, add:

  - a selected header appears lowercased under the right side;
  - an unselected header (`vary`, `content-length`, `date`, `user-agent`) is absent;
  - a duplicate name keeps both values in order;
  - a side with no selected header omits the map entirely;
  - a value longer than 256 characters is truncated to 256 and ends with `...`;
  - `authorization` and `set-cookie` render verbatim, with no `[redacted]`.

- [x] Keep the existing lean-row assertions.

## Task 2: validate the core key against the side

### 2.1 The rule

- [x] In `kali/http_history/store.py`, beside `ALLOWED_SIDES`, add:

  ```python
  CORE_KEYS_BY_SIDE = {
      "request": frozenset({"http_version", "method", "url"}),
      "response": frozenset({"http_version", "status", "reason"}),
      "connection": frozenset({"client_address", "server_address",
                               "protocol", "error_type"}),
      "context": frozenset({"session_id", "run_id", "spec_id",
                            "variant_ref", "exec_id"}),
      "timing": frozenset({"total_ms"}),
  }
  ```

  The map mirrors `kali/http_history/index.py::_project_message` and the connection, context, and timing projections.
  `index.py` stays the single writer; the map is the reader-side guard.

- [x] In `_filter_sql`, after the op check and before the header key is lowered, add:

  ```python
              if namespace == "core" and key not in CORE_KEYS_BY_SIDE[side]:
                  allowed = ", ".join(sorted(CORE_KEYS_BY_SIDE[side]))
                  raise ValueError(
                      f"core key {key!r} is not valid on side {side!r}; "
                      f"allowed: {allowed}"
                  )
  ```

- [x] Add a comment that the existing `ValueError` path already maps to `invalid_filter`, so the tool layer returns the coded error with no new branch.

### 2.2 Tests

- [x] In `tests/kali/test_http_history_search.py`, add a store-level test that asserts `request/core/host` raises `ValueError` with the allowed keys in the message.
- [x] Add the mirrored case `response/core/url`.
- [x] Add the positive cases: `request/core/url`, `response/core/status`, `context/core/run_id`, and `timing/core/total_ms` still search.
- [x] In `tests/kali/test_http_history_mcp_tools.py`, assert `search_http_history` returns `{"error": "invalid_filter"}` for `request/core/host`, and that `detail` names the allowed keys.

## Task 3: teach the contract

### 3.1 Add the header taxonomy

- [x] In `src/polymerhus/attack/hunting/http_history_contract.py`, add one sentence to `SEARCH_HTTP_HISTORY_DESCRIPTION`:

  > Header keys are side-bound: request has authorization, cookie, referer, origin, x-forwarded-*, x-real-ip; response has set-cookie, location, access-control-*, content-security-policy, x-frame-options, www-authenticate, server, x-powered-by, x-cache{,-lookup}; content-type is on both.

- [x] Widen the error sentence to name the core key:

  > A misspelled op/side/namespace or a bad core key is `invalid_filter`, not an empty result.

- [x] Replace the row sentence with:

  > Rows are candidate summaries: `artifact_id`, `method`, `url`, `status`, sizes, `request_headers`/`response_headers` (verbatim), and non-null `derived_from`/`replay_kind`/`error`; `capture_state` is on `get_http_artifact`.

- [x] Keep every clause the contract test asserts:

  - `conjunctive`
  - `next_cursor`
  - `absent`
  - `provenance.baseline_ref`
  - `TWO DIFFERENT AXES`
  - `no \`present\` op`
  - `does not accept booleans`
  - `candidate`
  - `artifact_id`, `capture_state`, `derived_from`, `replay_kind`

- [x] Trim the same description by about 60 characters so the growth stays near 260:

  - drop "recorded" from the opening clause;
  - drop "paging is deterministic" (the cursor clause survives);
  - use "URL/body markers".

- [x] Do not append the taxonomy to `GET_HTTP_ARTIFACT_DESCRIPTION` or `REPLAY_HTTP_REQUEST_DESCRIPTION`.
  Both already carry the full header list and redact.

### 3.2 Add the args field description

- [x] In `src/polymerhus/attack/hunting/hunter_tools.py`, give `HttpHistorySearchArgs.filters` a `Field(description=...)` with:

  - the request family and the response family;
  - the statement that a core key on the wrong side or an unknown core key is `invalid_filter`;
  - the statement that only present header keys are rendered and duplicates are a list.

  This is the machine contract the schema carries on every turn.
  It is not a second prose copy.

### 3.3 Raise the description budget

- [x] In `tests/attack/test_tool_description_budget.py`, raise the cap from 8,500 to 8,800.
  Add a comment: the HTTP contract gained the new header taxonomy and the core-key rule; this is new contract content, not duplication.

- [x] Record the measured total in the verification record.

## Task 4: align the runtime consumers

- [x] `src/polymerhus/attack/hunting/prompts/hunting-agent.md` line 64: require a name regex on `skill_list`.
- [x] The same file line 190: say the listing is filtered by a required name regex and the cascade applies.
- [x] `src/polymerhus/attack/hunting/prompts/threat-modeller.md` line 116: require a name regex.
- [x] The same file line 150: require a name regex and state that a parent match includes its leaves.
- [x] The same file line 218: replace "list the suite skills" with the filtered listing, the cascade, and the coded errors.
- [x] `src/polymerhus/attack/hunting/threat_modeller.py::GATE_HINTS[VULNERABILITIES_WRITTEN]`: say `skill_list` with a name regex, then `skill_load`.
- [x] Grep again after the edits:

  ```bash
  grep -rn "skill_list" src/polymerhus --include='*.md' --include='*.py'
  ```

  Every remaining mention must either name the filter or be a tool-name constant.

- [x] Grep for stale row fields:

  ```bash
  grep -rn "status_class\|timing_ms\|http_version" src/polymerhus docs/design
  ```

  No design document may describe a summary field that the row no longer carries.

## Task 5: align the design documentation

- [x] `docs/design/http-proxy-history-design.md`: document the summary projection (`artifact_id`, `method`, `url`, `status`, sizes, the two header maps, lineage, error) and the core-key/side rule.
- [x] `docs/design/http-history-search-filter-plan-adr.md`: add a change section for the header projection and the core-key validation.
- [x] `docs/design/tool-call-failure-modes.md`: extend FM-B with the wrong-side and unknown-core-key class and the coded error.
- [x] `docs/design/hunting-67-threat-modeller-spec.md`: the suite section states the required filter, the parent/leaf cascade, the 20-entry cap, and the coded errors.
- [x] `docs/design/hunting-67-hunting-agent-spec.md`: the same, for the hunter binding.
- [x] `docs/design/unit-threat-model-workflow.md`: the suite mention names the filtered listing.
- [x] `docs/design/unit-threat-model-abduction-research.md`: the suite mention names the filtered listing.
- [x] `docs/design/analysis-unit-enrichment-data-modeller-subproblems.md`: the row description names the two header maps.
- [x] `src/polymerhus/attack/hunting/CONTEXT.md`: amend the HTTP tool-family paragraph and the suite mention.
- [x] `docs/experiments/.../TOOL-RESPONSE-OCCUPANCY-ASSESSMENT.md`: add the header-cost addendum and the revised net projection.
- [x] Use a plain dash, never an em dash.
  Keep one full sentence per line.

## Task 6: verification

- [x] Run the HTTP suites:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q \
    tests/kali/test_http_history_sanitize.py \
    tests/kali/test_http_history_search.py \
    tests/kali/test_http_history_mcp_tools.py \
    tests/attack/test_http_history_tools.py \
    tests/attack/test_http_history_wiring.py
  ```

- [x] Run the suite and contract suites:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q \
    tests/attack/test_threat_modeller.py \
    tests/attack/test_hunter_tools.py \
    tests/attack/test_hunting_agent_prompt.py \
    tests/attack/test_threat_modeller_prompt.py \
    tests/attack/test_tool_description_budget.py \
    tests/recon/test_skill_listing.py \
    tests/integration/test_hunter_harness_memory_contracts.py
  ```

- [x] Run the affected area:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q tests/attack tests/kali tests/recon tests/analysis
  ```

- [x] If a test fails, first decide whether this change caused it.
  A pre-existing failure is recorded in "Deferred findings"; it is not fixed by changing this plan.
- [x] Record every count in the verification record.

## Task 7: do not do

These items are constraints, not work.
Keep the boxes unchecked to record that they stayed undone.

- [ ] Do not add first-class `url`, `method`, `status`, or `header:value` filter fields.
- [ ] Do not add redaction to the summary row.
- [ ] Do not add row caps or lazy stubs.
- [ ] Do not change the `get_http_artifact` or `replay` projections.
- [ ] Do not edit tool descriptions owned by the parallel compression workstream, other than the budget constant.
- [ ] Do not start a new trial.
- [ ] Do not fix the pre-existing `test_llm_providers` baseline mismatch.

## Verification record

| Check | Command | Result |
|---|---|---|
| HTTP suites | `pytest tests/kali/test_http_history_sanitize.py tests/kali/test_http_history_search.py tests/kali/test_http_history_mcp_tools.py tests/kali/test_http_history_summary_headers.py tests/attack/test_http_history_tools.py tests/attack/test_http_history_wiring.py` | 46 passed |
| Suite and contract suites | `pytest tests/attack/test_threat_modeller.py tests/attack/test_hunter_tools.py tests/attack/test_hunting_agent_prompt.py tests/attack/test_threat_modeller_prompt.py tests/attack/test_tool_description_budget.py tests/recon/test_skill_listing.py tests/integration/test_hunter_harness_memory_contracts.py` | 119 passed |
| Affected area | `pytest tests/attack tests/kali tests/recon tests/analysis` | 2,715 passed, 18 skipped |
| Description total | measured on the 12 hunter tools | 8,650 of 8,800 |

One test changed because it pinned the old boundary:
`tests/kali/test_http_history_service.py::test_search_returns_sanitized_summaries` asserted that no secret appears in the search page.
It now asserts the operator contract: the triage `authorization` value is verbatim, the URL query stays redacted, and no body content appears.

## Measured projections

| Item | Value |
|---|---|
| Summary row before this change | 492,911 chars over 1,103 rows |
| Lean row after the earlier change | 166,079 chars (66.3% below baseline) |
| Selected headers, measured on 38 artifacts, with redaction | about 155 chars per row |
| Selected headers, verbatim and capped at 256 | about 155 to 260 chars per row, unmeasured upper bound |
| Projected row total with headers | about 337k to 386k chars, or 22% to 32% below baseline |
| Description budget | 8,650 measured, cap raised to 8,800 |

The header figure is an estimate.
The cached Langfuse crawl was lost with the temp directory, and the summary rows do not carry headers in the source trace.
The 38 `get_http_artifact` payloads are the only header sample from the same project and trial window.

## Deferred findings

Record anything found but not fixed here.

- The summary row now renders `authorization`, `cookie`, `set-cookie`, and the raw `url` verbatim by operator decision.
  That is a deliberate exception to the module's model-boundary rule.
  Revisit if the trace is shared outside the operator's control.
- `kali/**` changes need a Kali image rebuild and `docker restart kali` on rollout.
- The header-cost estimate is unmeasured because the crawl cache was lost.
  A new trial should measure the actual row size.
- The `get_http_artifact` view still redacts the same headers the summary now shows verbatim.
  That asymmetry is a design follow-up.
- The description budget is now 8,800.
  The parallel compression workstream owns the next reduction.
