# polymerhus skills

Runtime role-prompts for the product's LLM agents, authored and tested with the `superpowers:writing-skills` TDD discipline (RED baseline -> write skill -> GREEN verify).
Each skill's `SKILL.md` body is loaded as a role's system prompt - at bake time through the shared loader, or at runtime through the shared tool (both call `skill_for`, so the two paths can never diverge).
This is distinct from `docs/superpowers/skills/` (meta-skills for Claude-the-developer); these are the product's skills.

See `docs/design/jobs-tools-skills-taxonomy.md` for the full jobs/tools/skills model and `docs/design/agent-context-architecture.md` for how skills compose with the `asset_context` channel.

## Layout

```
skills/<area>/<role-or-family>/<skill-name>/SKILL.md
```

Areas: `recon`, `analysis`, `hunting`, `systems-analysis` (drafts only).
Recon roles: `triager` (always active), `crawler` (agentic crawl), `configurator` (agent mode only), `job-orchestrator` (LLM distribution path, deferred).

## Loader contract (`src/polymerhus/recon/domain/skills.py::skill_for`)

`skill_for(name)` loads `skills/<name>/SKILL.md` (e.g. `recon/triager/writing-observations`, `recon/crawler/steel-crawl`).
It strips the YAML frontmatter, caches the body, and degrades to the caller-supplied fallback on a missing or unreadable file.
Every per-role skill reader retro-points here (FR-SKILLIF single-loader discipline); no reader does its own file I/O.
Defaults: `triager -> writing-observations`, `crawler -> steel-crawl`.

## Runtime loading (`build_load_skill_tool()::load_skill`)

The single loader made agent-reachable: `load_skill(name)` returns the skill body with identical semantics to `skill_for` (cached, frontmatter-stripped, fail-open to `''`), plus a `refresh` flag that clears the cache first (the development hot-reload path only).
The usage contract rides the tool's description verbatim from `SKILL_LOAD_CONTRACT` in the loader module - this README and that constant are the same wording, kept in sync by hand; update both together.

## Phase-gating convention

PHASE-GATING CONVENTION - load at phase entry, once per thread, never speculatively mid-reasoning: call load_skill once when your phase starts for each skill your phase needs, then reason from the returned body.
Repeat loads are cache-cheap but a second load buys nothing new.
`refresh` is the development hot-reload path only - never set it mid-run.
Bake-time mounts follow the same rule: the hunting orchestrator's gate skill mounts once per thread as the run's one system message (never re-added per turn), and the crawl loop loads its skill once at loop start.

## Data section

Every `skills/**/SKILL.md` carries a machine-readable frontmatter contract so the tool can index, validate, and report what was loaded.
Mandatory keys: `name` (non-empty string, the skill's reported identity - deliberately not required to equal the loader path, which is the index key), `description` (non-empty string), `version` (non-empty string), `inputs` (a list, possibly empty, of strings or `{name, ...}` maps declaring the invocation context the skill expects).
Conformance is enforced by `tests/recon/test_skill_data_section.py::test_every_repo_skill_conforms_to_data_section`, which sweeps the catalogue and fails on any offender.
Only `SKILL.md` files are skills: drafts and notes elsewhere under `skills/` (e.g. `systems-analysis/[DRAFT]*.md`) are out of scope by construction, not silent exceptions.
Keep frontmatter valid YAML: an unquoted `: ` inside a plain-scalar description breaks parsing (seen twice), so prefer folded `>-` blocks for long descriptions.

## Skills

| Role | Skill | Status | Governs |
|---|---|---|---|
| triager | `writing-observations` | **authored + RED/GREEN verified** | anchor allowlist, observations-not-vulnerabilities, no asset restatement |
| crawler | `steel-crawl` | **authored + migrated (#222)** | agentic crawl budget/frontier discipline |
| job-orchestrator | `asset-distribution` | roadmap (deferred to LLM path) | asset cleaning/dedup/distribution over MAX_PODS |
| configurator | agent-mode playbooks | roadmap (deferred) | non-crawl agentic configuration |

Roadmap detail + priorities: `docs/design/jobs-tools-skills-taxonomy.md` section 6.
