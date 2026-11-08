# Tool-response minimisation plan

> **For agentic workers:** execute this plan task by task.
> Keep the checkbox state current.
> Do not add work outside the listed tasks.
> If a task reveals a blocking defect outside the listed files, record it in "Deferred findings" and continue.

**Goal:** cut tool-response occupancy in the hunter and threat-modeller sessions without losing the specification quality of the HTTP-history pair or the web-vulnerability suite.
**Baseline:** `white-jotter-1-20261022T030303-1618c524`.
**Assessment:** `TOOL-RESPONSE-OCCUPANCY-ASSESSMENT.md`.
**Branch:** `fix/hunt-context-dedup`.
**Worktree:** this checkout.
**No new trial.** All verification uses tests and the existing trace data.

## Execution status

Implemented on 2026-10-23.
All in-scope tasks are complete.
The targeted suites are green.
The measured projections are unchanged; they are still estimates from the existing trace, not a new-trial result.

Two deviations are recorded:

- The tool-description budget (`tests/attack/test_tool_description_budget.py`, 8,500 chars) forced a shorter contract text than the draft below.
  The HTTP summary still names every lean field.
  The `skill_list` top-level description is terse; the argument schema carries the full filter semantics.
  The total is 8,497 characters.
- The role prompts still say `skill_list` without the required filter.
  Prompt changes are out of scope; the coded error teaches the filter on the first call.
  This is a deferred finding.

## Scope

In scope:

- lean the `search_http_history` summary row;
- correct the HTTP summary contract;
- compact the HTTP tool JSON;
- require a regex filter on `skill_list`;
- render the matched suite as a parent/leaf cascade;
- cap the filtered suite listing at 20 entries with an `omitted` count;
- wire the parent map through the hunter and modeller seams;
- tests for every changed contract.

Out of scope:

- tool-description duplication;
- system prompts and loop payloads;
- first-class HTTP filter fields;
- lazy HTTP list stubbing;
- a global word cap;
- `graph_view` or `exec` caps;
- pod tools and pod transcripts;
- a new eval trial.

## Acceptance criteria

- `search_http_history` returns only the lean summary fields:
  `artifact_id`, `method`, `url`, `status`, `request_size`, `response_size`, and non-null `derived_from`, `replay_kind`, `error`.
- The HTTP summary contract describes the actual row and stops claiming that the row carries `capture_state`.
- The HTTP search and get tools emit compact JSON.
- `skill_list` without a filter returns `skill_filter_required` and no listing.
- `skill_list` with an invalid regex returns `skill_filter_invalid` and no listing.
- `skill_list` with no match returns an empty `skills` list and echoes the filter.
- A parent match returns the parent and its leaves.
- A leaf match returns the leaf and its class parent.
- `bfla-*` leaves return under `broken-function-level-authorization`.
- The listing is capped at 20 entries and reports `omitted`.
- The hunter and modeller surfaces receive the parent map in production.
- The targeted tests pass.
- The broader attack, kali, and recon suites pass.
- The new docs are linked from the plan and committed.

## Task 0: record the evidence and the plan

- [x] Add the assessment document `TOOL-RESPONSE-OCCUPANCY-ASSESSMENT.md`.
- [x] Add this plan `TOOL-RESPONSE-MINIMIZATION-PLAN.md`.
- [x] Add a correction banner to `CONTEXT-OCCUPANCY-ANALYSIS.md`.
  Banner text: the 74,649-character payload is `auth_store`; the modeller's 50-row HTTP page is 22,302 characters; see the assessment.
- [x] Add a correction banner to `CONTEXT-LIFECYCLE-FOLLOWUP-PLAN.md`.
  Banner text: the "Evidence corrections" section reverses the two payloads; see the assessment.
- [x] Commit the docs.
  Message: `docs(hunt-context): assess the tool-response payloads`.

## Task 1: lean the HTTP summary

### 1.1 Change the projection

- [x] Edit `kali/http_history/sanitize.py`.
  Replace `sanitize_summary` with:

  ```python
  def sanitize_summary(artifact: HttpArtifact) -> dict:
      """The candidate-row projection: identity, triage scalars, lineage.

      The search row is a menu, not a record. The full view is
      `sanitize_artifact`, which carries `capture_state`, timings, and the
      connection record. Do not add a field here unless the search decision
      needs it on every row.
      """
      response = artifact.response
      status = response.status if response is not None else None
      summary = {
          "artifact_id": artifact.artifact_id,
          "method": artifact.request.method,
          "url": sanitize_url(artifact.request.url),
          "status": status,
      }
      if artifact.request.body_size:
          summary["request_size"] = artifact.request.body_size
      if response is not None and response.body_size:
          summary["response_size"] = response.body_size
      if artifact.derived_from:
          summary["derived_from"] = artifact.derived_from
      if artifact.replay_kind:
          summary["replay_kind"] = artifact.replay_kind
      if artifact.error is not None:
          summary["error"] = artifact.error.type
      return summary
  ```

- [x] Remove the `urlsplit` host extraction if it is no longer used.
  Keep `sanitize_url` and the redaction logic.
- [x] Do not change `sanitize_artifact`.
- [x] Do not change the store schema or the index.

### 1.2 Correct the contract

- [x] Edit `src/polymerhus/attack/hunting/http_history_contract.py`.
  Replace the final sentence of `SEARCH_HTTP_HISTORY_DESCRIPTION` with:

  ```
  The row is the candidate projection: `artifact_id`, `method`, `url`,
  `status`, `request_size`, `response_size`, and non-null `derived_from`,
  `replay_kind`, and `error`. `capture_state`, timings, and the connection
  record are on `get_http_artifact`; the row does not carry them.
  ```

- [x] Keep the words `capture_state`, `derived_from`, and `replay_kind` in the search description.
  The shared-description test asserts them.
- [x] Do not add `host`, `project_id`, `created_at`, `status_class`, `http_version`, `tls`, or `timing_ms` to the row.
- [x] Keep `GET_HTTP_ARTIFACT_DESCRIPTION` unchanged.

### 1.3 Compact the JSON

- [x] Edit `src/polymerhus/attack/hunting/hunter_tools.py`.
  In `HttpHistorySearchTool._run`, return `json.dumps(result, separators=(",", ":"))`.
- [x] In `HttpHistoryGetTool._run`, return `json.dumps(result, separators=(",", ":"))`.
- [x] Leave the error bundles readable; compacting them is optional and not required.
- [x] Do not change the MCP server response shapes.

### 1.4 Tests

- [x] Update `tests/kali/test_http_history_sanitize.py`.
  Assert the lean shape:

  ```python
  summary = sanitize_summary(_artifact())
  assert set(summary) == {
      "artifact_id", "method", "url", "status", "request_size", "response_size",
  }
  assert summary["request_size"] == 10
  assert summary["response_size"] == 5
  assert "target.example" in summary["url"]
  assert _SECRET not in json.dumps(summary)
  ```

- [x] Add a sparse-lineage test.
  Build an artifact with `derived_from="http_parent"`, `replay_kind="mutated"`, and an error.
  Assert the summary carries `derived_from`, `replay_kind`, and `error`.
  Assert a clean artifact omits those keys.
- [x] Assert `"capture_state" not in summary` and `"project_id" not in summary`.
- [x] Update `tests/kali/test_http_history_mcp_tools.py` only if it asserts a dropped field.
  The current test asserts `artifact_id`; keep it.
- [x] Update `tests/attack/test_http_history_tools.py` only if the description assertions fail.
  Keep the `capture_state`/`derived_from`/`replay_kind` assertions satisfied.

### 1.5 Verify

- [x] Run:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q \
    tests/kali/test_http_history_sanitize.py \
    tests/kali/test_http_history_mcp_tools.py \
    tests/kali/test_http_history_search.py \
    tests/attack/test_http_history_tools.py \
    tests/attack/test_http_history_wiring.py
  ```

- [x] Expected: all pass.
- [x] Commit.
  Message: `fix(http-history): return lean candidate rows`.

## Task 2: require a filtered suite listing

### 2.1 Add the parent map to the catalogue

- [x] Edit `src/polymerhus/app/llm/skills.py`.
  Add `SkillCatalogue.suite_parents()`:

  ```python
  def suite_parents(self) -> dict[str, str]:
      """Map every suite skill to its class parent.

      A class parent maps to itself. A variant leaf maps to its level-1
      class directory. Names outside the suite are absent. The map is
      derived from the mounted tree, so an abbreviated leaf such as
      `bfla-alternate-path` still resolves to
      `broken-function-level-authorization`.
      """
      suite_root = (self._root / self._logical_root).resolve()
      parents: dict[str, str] = {}
      for name, bundle in self._bundles.items():
          resolved = bundle.resolve()
          if suite_root not in resolved.parents:
              continue
          if resolved.parent == suite_root:
              parents[name] = name
          else:
              parents[name] = resolved.parent.name
      return parents
  ```

- [x] Add the module-level helper next to `list_suite_leaves`:

  ```python
  def list_suite_parents(
      catalogue: "SkillCatalogue | None" = None,
  ) -> dict[str, str]:
      """Every suite skill's class parent, for the filtered listing cascade."""
      if catalogue is not None:
          return catalogue.suite_parents()
      return _live_catalogue().suite_parents()
  ```

- [x] Export the helper if `skills.py` has an `__all__` that lists the suite helpers.
- [x] Add a test in `tests/recon/test_skill_listing.py` over a synthetic suite:
  - a parent `alpha` with `SKILL.md`;
  - a leaf `alpha/alpha-variant/SKILL.md`;
  - a leaf `bfla/abbreviated-leaf/SKILL.md`;
  - assert `parents["alpha"] == "alpha"`;
  - assert `parents["alpha-variant"] == "alpha"`;
  - assert `parents["abbreviated-leaf"] == "bfla"`.

### 2.2 Extend the seam

- [x] Edit `src/polymerhus/attack/hunting/threat_modeller_tools.py`.
- [x] Add `import re` and `Mapping` to the imports.
- [x] Add the constants:

  ```python
  MAX_SKILL_FILTER_CHARS = 200
  MAX_SKILL_LIST_ENTRIES = 20
  ```

- [x] Add the `parents` field to `VulnerabilitySuiteSeam`:

  ```python
  parents: Mapping[str, str] = field(default_factory=dict)
  ```

- [x] Replace `list_classes` with a filtered cascade:

  ```python
  def list_classes(self, pattern: re.Pattern[str] | None = None) -> dict:
      """List the suite, optionally filtered by a compiled name regex.

      A matched class parent expands to its variant leaves. A matched leaf
      adds its class parent. The response is grouped parent-first and capped;
      `omitted` states how many selected entries the cap hid.
      """
      if not self.classes:
          self.record_gap("suite_unavailable: no suite class is resolvable")
          return {"skills": [], "suite_gap": True,
                  "error": "suite_unavailable",
                  "detail": "the web-vulnerability suite is not available; "
                            "keep the canonical classes and flag the gap"}
      matched = [
          name for name in self.classes
          if pattern is None or pattern.search(name)
      ]
      if pattern is not None and not matched:
          return {"skills": [], "suite_gap": False,
                  "detail": "no suite skill matches the filter"}
      selected: set[str] = set()
      for name in matched:
          parent = self.parents.get(name, name)
          selected.add(name)
          if parent != name:
              selected.add(parent)
          else:
              selected.update(
                  child for child, child_parent in self.parents.items()
                  if child_parent == name
              )
      ordered = sorted(selected, key=lambda name: (
          self.parents.get(name, name),
          0 if self.parents.get(name, name) == name else 1,
          name,
      ))
      omitted = max(0, len(ordered) - MAX_SKILL_LIST_ENTRIES)
      ordered = ordered[:MAX_SKILL_LIST_ENTRIES]
      entries = []
      for name in ordered:
          description = ""
          if self.read_fn is not None:
              try:
                  description = _frontmatter_description(self.read_fn(name))
              except Exception:  # noqa: BLE001 - a per-entry degrade
                  description = ""
          entry = {"name": name, "description": description}
          parent = self.parents.get(name, name)
          if self.parents:
              entry["kind"] = "parent" if name == parent else "leaf"
              if name != parent:
                  entry["parent"] = parent
          entries.append(entry)
      result = {"skills": entries, "suite_gap": False}
      if omitted:
          result["omitted"] = omitted
          result["detail"] = "narrow the filter; the cap hid the remaining matches"
      return result
  ```

- [x] Keep the fail-open behavior unchanged when the suite is empty.
- [x] Do not read descriptions for entries the cap hides.

### 2.3 Change the tool contract

- [x] Replace `class SkillListArgs(_SuiteArgs): pass` with:

  ```python
  class SkillListArgs(_SuiteArgs):
      filter: str = Field(
          default="",
          description=(
              "REQUIRED. Case-insensitive Python regex over suite skill names. "
              "A class-parent match also returns its variant leaves; a leaf "
              "match also returns its class parent."
          ),
      )
  ```

- [x] Keep `extra="forbid"` inherited from `_SuiteArgs`.
- [x] In `_SkillListTool._run`, validate before the seam:

  ```python
  filter_text = str(kwargs.get("filter") or "").strip()
  if not filter_text:
      return {"skills": [], "suite_gap": False,
              "error": "skill_filter_required",
              "detail": "pass filter, a case-insensitive regex over suite skill "
                        "names; for example 'session|csrf'"}
  if len(filter_text) > MAX_SKILL_FILTER_CHARS:
      return {"skills": [], "suite_gap": False,
              "error": "skill_filter_invalid",
              "detail": f"filter is longer than {MAX_SKILL_FILTER_CHARS} characters"}
  try:
      pattern = re.compile(filter_text, re.IGNORECASE)
  except re.error as exc:
      return {"skills": [], "suite_gap": False,
              "error": "skill_filter_invalid",
              "detail": str(exc), "filter": filter_text}
  result = self._suite.list_classes(pattern=pattern)
  result["filter"] = filter_text
  return result
  ```

- [x] Keep the `suite_list_failed` exception path.
- [x] Update `SKILL_LIST_DESCRIPTION`:

  ```
  "List the web-vulnerability suite, filtered by a required regex. `filter` "
  "is a case-insensitive Python regex over skill names (for example `session`, "
  "`csrf|auth`, or `broken-function-level-authorization`). A matched class "
  "parent also returns its variant leaves; a matched leaf also returns its "
  "class parent, so an abbreviated leaf (`bfla-*`) never loses its parent. "
  "The class parent is the directory name for `web_vulnerability_class`; a "
  "variant leaf is assumption-check material. Missing filter -> "
  "`skill_filter_required`; invalid regex -> `skill_filter_invalid`; no match "
  "-> an empty `skills` list. A suite that is unavailable degrades to "
  "`suite_gap`: keep the canonical name, leave `web_vulnerability_class` "
  "empty, never invent a class."
  ```

- [x] Do not add a default filter value that would list everything.

### 2.4 Thread the parent map

- [x] `src/polymerhus/attack/hunting/threat_modeller_tools.py`:
  - add `parents: Mapping[str, str] | None = None` to `build_vulnerability_suite_tools`;
  - pass `parents=dict(parents or {})` to `VulnerabilitySuiteSeam`;
  - add `suite_parents: Mapping[str, str] = field(default_factory=dict)` to `ModellerTools`;
  - in `build_modeller_tool_surface`, pass `parents=tools.suite_parents` to the seam constructor.
- [x] `src/polymerhus/attack/hunting/hunter_tools.py`:
  - add `suite_parents: Mapping[str, str] | None = None` to `build_hunter_tools`;
  - pass `parents=suite_parents` to `build_vulnerability_suite_tools`.
- [x] `src/polymerhus/attack/hunting/hunting_agent.py`:
  - add `suite_parents=None` to `build_hunting_agent`;
  - pass `suite_parents=suite_parents` to `build_hunter_tools`.
- [x] `src/polymerhus/attack/hunting/llm.py`:
  - add `suite_parents=None` to `build_actor_hunting_agent`;
  - the lazy import must also import `list_suite_parents`;
  - when any suite input is missing, fill all three;
  - pass `suite_parents=suite_parents` to `build_hunting_agent`.
- [x] `src/polymerhus/attack/hunting/runtime.py`:
  - import `list_suite_parents` beside `list_suite_leaves`;
  - set `tools.suite_parents = list_suite_parents()`.
- [x] Keep the fail-open path when the import fails: the seam gets no parents and the listing still works flat.

### 2.5 Tests

- [x] Update `tests/attack/test_threat_modeller.py`.
  The old `surface["skill_list"].invoke({})` assertions must now expect the missing-filter error.
  Add:

  ```python
  listing = surface["skill_list"].invoke({})
  assert listing["error"] == "skill_filter_required"
  assert listing["skills"] == []
  ```

- [x] Update the listing test to pass a filter:

  ```python
  listing = surface["skill_list"].invoke({"filter": "idor|xss"})
  assert [entry["name"] for entry in listing["skills"]] == ["idor", "xss"]
  ```

- [x] Add a cascade test with a synthetic parent map:

  ```python
  bodies = {
      "broken-function-level-authorization": "---\ndescription: bfla\n---\nbody",
      "bfla-alternate-path": "---\ndescription: alternate\n---\nbody",
      "bfla-client-identity-trust": "---\ndescription: client\n---\nbody",
      "idor": "---\ndescription: idor\n---\nbody",
  }
  parents = {
      "broken-function-level-authorization": "broken-function-level-authorization",
      "bfla-alternate-path": "broken-function-level-authorization",
      "bfla-client-identity-trust": "broken-function-level-authorization",
      "idor": "idor",
  }
  tools = build_vulnerability_suite_tools(
      classes=tuple(bodies), read_fn=bodies.__getitem__, parents=parents)
  surface = {tool.name: tool for tool in tools}
  listing = surface["skill_list"].invoke(
      {"filter": "broken-function-level-authorization"})
  names = [entry["name"] for entry in listing["skills"]]
  assert names == [
      "broken-function-level-authorization",
      "bfla-alternate-path",
      "bfla-client-identity-trust",
  ]
  ```

- [x] Add a leaf-match test:
  `filter="bfla-alternate-path"` returns the leaf and its parent.
- [x] Add a missing-filter test:
  `filter=""` -> `skill_filter_required`, no `skills`.
- [x] Add an invalid-regex test:
  `filter="["` -> `skill_filter_invalid`, no raise.
- [x] Add a no-match test:
  `filter="no-such-class"` -> `skills == []`, `filter` echoed, no error.
- [x] Add a cap test:
  use 25 synthetic leaves under one parent and `filter="cap-parent"`;
  assert `len(skills) == 20`, `omitted == 6`.
- [x] Add an injected-seam test:
  a seam with `parents` preserves the gap record and the cascade.
- [x] Update `tests/attack/test_hunter_tools.py`:
  `tools[names.index("skill_list")].invoke({})` now expects `skill_filter_required`;
  add a filtered call when a suite is bound.
- [x] Update any test that invokes `skill_list` with no args.
  Run `grep -rn "skill_list.*invoke({})" tests` and fix each.
- [x] Do not change `skill_load` behavior.

### 2.6 Verify

- [x] Run:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q \
    tests/attack/test_threat_modeller.py \
    tests/attack/test_hunter_tools.py \
    tests/attack/test_hunting_agent_prompt.py \
    tests/attack/test_tool_description_budget.py \
    tests/recon/test_skill_listing.py \
    tests/integration/test_hunter_harness_memory_contracts.py
  ```

- [x] Expected: all pass.
- [x] Commit.
  Message: `fix(skills): require a filtered suite listing`.

## Task 3: broader verification

- [x] Run the attack, kali, and recon suites:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q \
    tests/attack tests/kali tests/recon
  ```

- [x] If a test fails, first decide whether it is caused by this change.
  A pre-existing failure is recorded in "Deferred findings"; it is not fixed by changing this plan.
- [x] Run the whole suite if time permits:

  ```bash
  /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest -q
  ```

- [x] Record the counts in the "Verification record" section.
- [x] Update the checkboxes in this plan.
- [x] Commit the verification record.
  Message: `docs(hunt-context): record the minimisation verification`.

## Task 4: do not do

These items are constraints, not work.
They remained undone by design; the unchecked boxes record that.

- [ ] Do not add first-class HTTP filter fields.
- [ ] Do not add lazy HTTP list stubbing.
- [ ] Do not add a global word cap.
- [ ] Do not change `graph_view`.
- [ ] Do not change `exec`.
- [ ] Do not change the auth store.
- [ ] Do not start a new trial.
- [ ] Do not edit tool descriptions beyond the two contract changes above.

## Verification record

| Check | Command | Result |
|---|---|---|
| HTTP targeted | `pytest tests/kali/test_http_history_sanitize.py tests/kali/test_http_history_mcp_tools.py tests/kali/test_http_history_search.py tests/attack/test_http_history_tools.py tests/attack/test_http_history_wiring.py` | 34 passed |
| Suite targeted | `pytest tests/attack/test_threat_modeller.py tests/attack/test_hunter_tools.py tests/recon/test_skill_listing.py` | 65 passed |
| Contract and budget | `pytest tests/attack/test_tool_description_budget.py tests/attack/test_http_history_tools.py` | 12 passed; total description length 8,497 |
| Attack, kali, recon | `pytest tests/attack tests/kali tests/recon` | 2,305 passed, 18 skipped |
| Harness integration | `pytest tests/integration/test_hunter_harness_memory_contracts.py tests/recon/test_skill_evolver.py tests/analysis/test_graph_tools.py` | 58 passed |
| Whole suite | `pytest` | 6,191 passed, 220 skipped, 1 xfailed, 38 failed, 8 errors |

The whole-suite failures are outside the changed areas:

- the Docker daemon is not running (`test_kali_mcp`, `test_stack_smoke`, `test_agent_health`);
- the live Steel, Neo4j, Postgres, and e2e lanes cannot reach their services;
- `test_llm_providers` expects the hunter thinking baseline `high`, but the branch resolves `xhigh`.

None of the failures names the HTTP-history pair, the suite seam, the parent map, or the skill catalogue.
The changed areas pass in the targeted and the attack/kali/recon runs.

## Measured projections

These are the targets, not results from a new trial.

| Change | Current | Projected | Saving |
|---|---:|---:|---:|
| HTTP payload | 492,911 chars | 166,079 chars | 66.3% |
| HTTP hunter input | 2,481,067 tokens | 848,481 tokens | 1,632,585 tokens (6.08%) |
| HTTP modeller input | 2,731,305 tokens | 909,906 tokens | 1,821,399 tokens (5.18%) |
| `skill_list` payload | 465,140 chars | 19,240 chars | 95.9% |
| `skill_list` hunter input | 3,059,249 tokens | 132,554 tokens | 2,926,695 tokens (10.91%) |
| Combined hunter input | - | - | 4,559,280 tokens (16.99%) |
| Combined both roles | - | - | 6,380,679 tokens (10.3%) |

## Deferred findings

Record anything found but not fixed here.

- The role prompts still say `skill_list` without the required filter.
  The tool error teaches the filter on the first call.
  Update the prompt lines in the prompt workstream.
- The tool-description budget leaves only 3 characters of headroom after the two contract changes.
  A future contract edit must free space first.
  The parallel description-compression workstream should absorb this.
- `graph_view` 82,039-char whole-node response: needs operator approval because #197 Q6 says no row caps.
- `exec` 37,670-char probe output: needs an output-discipline decision with an evidence-retention design.
- Wrong-side core-key filter (`side=response`, `key=url`) returns an empty result instead of `invalid_filter`: a quality follow-up, not a token win.
- Hallucinated `present` op: a possible future `present` op, not a current contract gap.
- Lazy HTTP stubbing: defer until a new trial measures the lean row.
- The whole-suite Docker, Steel, Neo4j, Postgres, e2e, and `test_llm_providers` failures are pre-existing environment or branch-state failures.
  They are not caused by this change and are not fixed here.
