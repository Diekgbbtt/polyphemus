# Skills typed-surface spec

The contract for authoring, loading, and serving product skills in polymerhus: the typed surface of the loader, the skill lifecycle, and the decisions a future skill author must respect. Supersedes `jobs-tools-skills-taxonomy.md` sections 4-5 (the `skill_for(role, job)` selection model and module-routing layout, retired when role prompts moved to module `prompts/` dirs). Companion decision record: `skill-runtime-loading-222-decisions.md`. Convention single source: `skills/README.md`.

## Problem Statement

Two defects accumulated around product skills. First, agent ROLE PROMPTS (system prompts: the triager discipline, the crawl discipline, the hunting-agent/orchestrator prompts, the analysis proposer prompts) lived as `SKILL.md` files under `skills/`, forcing cross-module imports of a recon-owned loader and blurring "who the agent is" with "knowledge the agent loads". Second, the remaining genuine skills carried a repo-dialect frontmatter no external consumer understands, and loading them at runtime rested on convention rather than mechanism.

## Solution

A hard split, enforced by layout and tests. A role's system prompt lives with its owning module in a `prompts/` directory as plain markdown and is read directly by its module (fail-closed, memoized, no cross-module imports). `skills/` holds ONLY genuine progressive-disclosure skills: flat `skills/<name>/SKILL.md` files with Agent Skills spec frontmatter, served through one typed loader surface that is also the agent-callable `load_skill` tool, so bake-time and runtime loads can never diverge.

## User Stories

1. As a skill author, I want one layout rule (flat `skills/<name>/SKILL.md`, `name` == directory), so that I never decide where a skill lives.
2. As a skill author, I want the frontmatter schema stated once with examples, so that my skill validates first try.
3. As a skill author, I want to know that invocation context belongs in the body, not the frontmatter, so that I do not author schema stubs.
4. As a role owner, I want my agent's system prompt in my module's `prompts/` dir read directly, so that no other module's loader stands between my agent and its identity.
5. As a role owner, I want prompt loading to fail closed, so that a missing prompt file crashes loudly instead of running my agent identity-less.
6. As an agent owner binding tools, I want one `load_skill(name)` tool with a verbatim contract, so that every agent that binds the skill surface offers identical skill-loading semantics - and none is forced to carry a surface its discipline cannot use.
7. As an agent owner, I want the L1 skill index (all frontmatters) composed into the system message by shared middleware, so that I bind one middleware instead of editing my prompt.
8. As the loader maintainer, I want a catalogue-wide conformance sweep, so that a non-conforming skill fails tests rather than degrading a live run.
9. As a #220/#221 stream author adding skills, I want the typed surface and lifecycle documented, so that new skills plug into the existing mechanics with no new instrumentation.
10. As a reviewer, I want byte-identity between loader paths pinned by tests, so that no parallel implementation can silently diverge.

## Implementation Decisions

- The loader surface is five functions plus one contract constant in the skills loader module (`app.llm.skills`, grilled Q1 2026-09-11: co-located with the session seam, its primary consumer; a deprecating re-export shim stays at `recon.domain.skills` for one cycle): `skill_for(name, fallback="")` (read + strip + cache + fail-open), `skill_meta(name)` (parsed frontmatter mapping, `{}` on any failure, never raises), `validate_skill(name)` (violation list, never raises), `list_skills()` (sorted flat names), `clear_cache()` (test/hot-reload seam), `build_load_skill_tool()` (the `load_skill(name, refresh=False)` tool calling `skill_for` internally; `SKILL_LOAD_CONTRACT` rendered verbatim into its description).
- Flat names only: the loader path is the index key, the frontmatter `name` the reported identity, and the validator requires them equal. No module-routing layers under `skills/`.
- Frontmatter schema (Agent Skills spec subset): `name` (non-empty, == directory), `description` (non-empty: what + when, carrying trigger keywords), `metadata` string map with non-empty `version`. No other top-level keys; no structured `inputs`.
- Role prompts: `<owning-module>/prompts/<role>.md`, plain markdown, no frontmatter; read directly via a module-relative path, memoized on first call, no import-time I/O; missing file raises. No fallback constants anywhere (deleted as a design defect); no `skill_for` in role readers.
- Lifecycle of a skill: author (layout + schema + body) -> catalogue sweep green -> cached process-lifetime on first load -> `clear_cache()` in tests, `refresh=True` as the development hot-reload path only, never mid-run. Lifecycle of a role prompt: edited in place, byte-stability preserved per run (the provider prompt-cache prefix relies on it).
- Loading mechanics, two tiers: L1 discovery (the bounded skill set's frontmatters rendered into the system message by the shared `dynamic_prompt` skill-index middleware, bound per agent through the native invocation context) and L2 activation (`load_skill` bound on the agents that declare a skill set; the result re-enters context through the native tool loop, no custom forwarding). Non-`create_agent` loops keep direct reads through the same loader functions.
- Skill bounding is a per-role roster, not a per-site list (A9): `ROLE_SKILLS` (`app/llm/skills.py`) declares every tool-calling role in one of two states - a bounded skill set, or an explicit EXEMPTION (an empty tuple: the role binds no skill surface at all) - and `skill_agent_binding(role_id)` is the one call that binds a bounded set's whole surface: index middleware, skill tools, and the context carrying the set. An exemption binds NOTHING rather than rendering an empty index (no dead tool schema, no middleware, no context), and an UNDECLARED role id is refused at construction, because the roster is the considered decision for every role. The middleware itself carries no policy.
- Declaration vs execution planes: the model sees tools ONLY through the generation request `tools` parameter; harness-side executor registries (e.g. the hunting manual loop's name map) must agree by tool-name string. Declared-but-unregistered degrades to an unknown-tool rejection, never a silent skip.
- Phase discipline is grounded, not conventional: the bounded L1 index is composed by middleware (no model cooperation needed), bodies load on demand; speculative mid-reasoning loads are pointless because repeat loads are cache-identical.

## Testing Decisions

- Test external behavior only: served bodies, contract verbatim, catalogue conformance, tool-loop delivery - never loader internals.
- The catalogue sweep (`test_every_repo_skill_conforms_to_data_section`) fails on any offender; the catalogue must be non-empty or the pass is vacuous.
- Byte-identity between `skill_for` and `load_skill` output is pinned, with a mutation check (a broken tool must fail the test).
- Role-prompt moves are pinned by byte-size/content assertions against the prompt files (e.g. the steel readers serve the module prompt, frontmatter-free).
- The per-role roster carries its own hygiene sweep (`tests/recon/test_skill_seam.py`): every declared `ROLE_SKILLS` name must resolve in the catalogue, every session-mode role in `providers.py` must declare (the `crawler` gap is asserted explicitly, so closing it is a one-line change), the bound and exempt sets are pinned exactly (so an exemption is a deliberate two-place edit, never drift), an undeclared role id is refused, an exempt binding composes to nothing, and neither meta-skill may be advertised in an index. The rendered index is asserted through the middleware's real `wrap_model_call` hook, with the frontmatter description compared verbatim. Exempt agents are pinned from the CONSUMER side too: the analysis proposers' seam tests assert their turns carry no skill tool and no skill context (`tests/analysis/test_stateful_invoke_fns.py`).
- Prior art: the `graph_view` single-contract precedent (#197) for verbatim contract rendering; the assigner contract tiers for prompt-config arms.

## Out of Scope

- Body wordsmithing of any skill or prompt (the Q4 shaping pass, separate ticket).
- The hunting first-HumanMessage to `system_prompt=` conversion (ratified, separate change).
- MCP-served prompts (protocol-available, adapter-blocked - revisit when `langchain-mcp-adapters` loads prompts).
- Content of future #220/#221 skills (this spec is the mechanics they plug into).

## Further Notes

- `jobs-tools-skills-taxonomy.md` sections 4-5 are superseded by this spec (header pointer added there); its jobs/tools model is unaffected.
- The L1 index middleware, the `context` turn seam, and the hunter `system_prompt=` conversion are built (Q3); the per-role binding closed with A9 - every tool-calling role takes a roster state (a bounded set, bound through `skill_agent_binding`; or an exemption, binding nothing), so the index renders in production rather than merely being wired. The `crawler`'s manual loop is the recorded gap, and #223's stateful recon job agents must take a roster state when they land (A9 forward-wiring amendment).
- The L1 index renders each bound skill's frontmatter `description` **verbatim** - the rendered line is `- <name>: <description>` from `skill_meta`, so the when-to-use text an author writes in `description` is exactly what the agent reads; nothing in the pipeline paraphrases, truncates, or re-words it.
- Bodies of migrated role prompts were moved byte-identical and their verbatim is explicitly out of scope here; known stale line: `hunt-orchestrator.md` on the llm.py fallback lane.
