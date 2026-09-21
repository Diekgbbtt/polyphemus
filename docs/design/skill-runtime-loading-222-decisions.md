# Skill runtime loading decisions (#222)

*Status: SUPERSEDED IN PART by the operator-grilled rounds of 2026-09-11 (Q1 loader home, Q2 spec frontmatter, Q3 L1/L2 mechanics, the role-prompts design-hole move, the hunter system-prompt correction). Decided below in self-grill; the reversals are recorded here, the current contract in `skills-typed-surface-spec.md`.*
*Implements ticket #222: one agent-callable `load_skill(name)` tool plus a data-section convention every repo skill follows, with the steel skill readers consolidated onto the shared loader as the proof consumer.*

## Reversals (operator-grilled 2026-09-11)

- D1 (lenient shapes, name-need-not-equal-path): REVERSED. Frontmatter follows the Agent Skills spec - `name` == directory (enforced), `description` = what + when, extras under the `metadata` string map (`version`); no structured `inputs` in frontmatter.
- D3 (convention-only gating, deferred fleet binding): REVERSED. L1 index composed by the shared `dynamic_prompt` skill-index middleware (no model cooperation needed); `load_skill` + middleware wired on all stateful agents; bounded skill sets travel in the native invocation context - and (closed in #221, ADR A9) every tool-calling role takes a roster state in `ROLE_SKILLS`: a bounded set (bound by `skill_agent_binding(role_id)`, so the index actually renders) or an explicit exemption (binding nothing at all; see the A9 exemption amendment of 2026-09-17).
- D5 (steel moves to `skills/`, rest gain fields): SUPERSEDED by the design-hole move. Role prompts (steel included) live in module `prompts/` dirs as plain Markdown; `skills/` holds only flat genuine skills. Drafts promoted to `skills/<name>/SKILL.md` with minimal frontmatter instead of excluded.
- D6 (canonical constant in `skills.py`): location moved to `app/llm/skills.py` (Q1); the verbatim-mirror rule stands.
- D2 (tool contract), D4 (two-severity rejection), D7 (#220 alignment): STAND.

## Context

`skill_for` (`src/polymerhus/recon/domain/skills.py`) is a Python function: skills mount at prompt bake-time, and agents cannot load a skill mid-run.
The steel skill bypassed the loader entirely (a local `.md` with duplicate readers in `crawl_agentic.py` and `crawl_agent.py`), so there were two skill systems and no convention an agent could rely on to pull in knowledge mid-run.
The single-loader discipline (`FR-SKILLIF`) already exists; this change makes it agent-reachable instead of adding a second system.

## D1 - data-section schema (mandatory keys, lenient shapes)

Every `skills/**/SKILL.md` carries `name`, `description`, `version`, and `inputs` in its YAML frontmatter.
`name`, `description`, and `version` are non-empty strings; `inputs` is a list (possibly empty) of strings or `{name, ...}` maps.
Presence and shape are validated (`validate_skill`); semantics are not (no semver parsing, no controlled vocabulary on names).
The `name` is deliberately NOT required to equal the loader path: the path argument is the index key, the frontmatter name the reported identity.
Rejected alternative: path-equality enforcement would churn every skill's frontmatter for zero consumer benefit, since no reader joins on the frontmatter name today.
Rejected alternative: strict `{name, description}` input maps would over-specify a contract with no programmatic consumer; the lenient shape keeps authoring cheap while staying machine-readable.

## D2 - load_skill contract (string body, loader-identical, fail-open)

`build_load_skill_tool()` in the loader module returns the ONE shared `load_skill(name, refresh=False) -> str` tool.
The tool calls `skill_for` internally (never a parallel implementation), so bake-time mounts and runtime loads return byte-identical bodies (pinned by test).
An unknown skill degrades to `''` exactly like `skill_for`'s default fallback, per the loop-constraints fail-open invariant for skill errors.
`refresh=True` clears the cache first (the development hot-reload path); the convention forbids it mid-run.
The usage contract is the `SKILL_LOAD_CONTRACT` constant rendered verbatim into the tool description (the #197 `GRAPH_VIEW_CONTRACT` precedent); `skills/README.md` carries the same wording and both point at each other.
Rejected alternative: a `{content, meta, error}` dict return would break the "same semantics as `skill_for`" ticket requirement and every bake-time call-site shape; metadata stays available via the module-level `skill_meta` function instead.

## D3 - phase-gating is convention, demonstrated by reference flows (not enforcement)

Gating is by convention, as the ticket prescribes: load at phase entry, once per thread, never speculatively mid-reasoning.
Mechanical enforcement was rejected: the tool layer has no thread identity without framework coupling, the `skill_for` cache already bounds repeat-load cost to a dict hit, and binding a guard that rejects second loads would break legitimate multi-skill phase entries.
The reference flows demonstrate the convention three ways: the crawl loop loads its skill once at loop start, the hunting orchestrator's gate skill mounts once per thread as the run's one system message (unchanged #187 precedent), and the session-loop test loads through `tools=()` at a scripted phase entry.
Fleet-wide binding of `load_skill` on every session agent is deliberately deferred: binding an unneeded tool on every agent would itself bloat the context the gate exists to protect, so future disciplines bind it on demand as they acquire runtime-loading needs.
*Superseded on the first half by ADR A9 (2026-09-17): the fleet is now rostered in `ROLE_SKILLS`, and a role with no bearing skill binds nothing at all, which satisfies this paragraph's concern by construction rather than by deferral. The phase-gating convention above is unchanged.*

## D4 - rejection surfaces twice (fail-open at runtime, hard fail in repo hygiene)

A non-conforming skill is rejected in two places with opposite severity.
At runtime the loader stays tolerant: `skill_for` strips whatever frontmatter shape it finds (or none) and `skill_meta` degrades to `{}`, so a bad data section can never crash a run.
In repo hygiene the validator is strict: `test_every_repo_skill_conforms_to_data_section` sweeps `skills/**/SKILL.md` and fails on any offender, so non-conformance breaks the suite, not the run.
This split mirrors the #63 predicate-validator precedent (bad predicates caught at authoring, never at runtime).
Two latent YAML hazards were caught by the validator during backfill (unquoted colons in the `hunt-orchestrator` and `lightrag-query` descriptions) and fixed with folded `>-` blocks; the README records the rule.

## D5 - migration order (steel moves, the rest gain fields, drafts are out of scope)

The steel skill moves from `src/polymerhus/recon/crawl/steel_crawl_skill.md` to `skills/recon/crawler/steel-crawl/SKILL.md` (role `crawler`, matching the registered role id and the README role list).
Both duplicate readers become one-line `skill_for` delegations (the established triager/assigner/hunter retro-point shape, not dead readers: they do no file I/O of their own).
All other repo skills stay where they are and gain only `version: '1.0'` plus grounded `inputs` (names taken from the actual call sites, e.g. anatomy's `signals`, the bootstrapper's `operator_kb`, curation's `l1_inventory/index_cards/stale_pool`).
Only `SKILL.md` files are skills: `systems-analysis/[DRAFT]*.md` are excluded by construction (the validator enumerates `SKILL.md` only), documented in the README, so there is no silent non-conformance and no exception list to ticket.

## D6 - documentation placement (code constant canonical, README mirrors verbatim)

The canonical wording of the agent-facing contract is `SKILL_LOAD_CONTRACT` in `skills.py`; `skills/README.md` carries the same paragraphs verbatim with a cross-pointer, and the tool description is pinned by test to contain the constant.
Markdown cannot import Python, so verbatim duplication with pointers is the mechanism; paraphrase is the failure mode the test prevents.
The README's stale selection-contract section (a `agent/recon/skills.py` path that no longer exists, a "proposed" resolver signature, a crawler row still marked roadmap) is corrected in the same change.

## D7 - coordination with #220 (convention alignment, not code blocking)

#220 (the per-project auth store read/write tool) was open and unimplemented at decision time (it landed later on the #220 stream), so #222 established the factory shape #220 follows rather than following it: a `build_<x>_tool(...)` factory in the owning module, a contract constant rendered verbatim into the tool description, fail-open returns, injectable seams where side effects exist, no I/O at import.
This is the `graph_view_tool.build_graph_view_tool` shape, which #220's ticket already names as its pattern.
No code dependency runs either way; this ADR is the explicit alignment record.

## Follow-ups (deferred, not silent)

Fleet-wide `load_skill` binding stays per-discipline on demand (D3).
Cross-run skill versioning policy (when a bump is required, who approves) is unneeded while the catalogue versions in lockstep at `1.0`.
A `name`-equals-path lint remains available if a future indexer joins on the frontmatter name (D1 records why it was not enforced now).
