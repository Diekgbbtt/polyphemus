# polymerhus skills

Genuine progressive-disclosure skills, loadable on demand through the shared loader (`src/polymerhus/app/llm/skills.py::skill_for`) or at runtime through the shared tool (`build_load_skill_tool()::load_skill`, which calls `skill_for` internally so the two paths can never diverge).
Each skill's `SKILL.md` carries Agent-Skills-spec frontmatter: `name` == its directory, `description` = what + when, `metadata` string map carrying `version`.
This is distinct from `docs/superpowers/skills/` (meta-skills for Claude-the-developer); these are the product's skills.

See `docs/design/jobs-tools-skills-taxonomy.md` for the full jobs/tools/skills model and `docs/design/agent-context-architecture.md` for how skills compose with the `asset_context` channel.

## Layout

```
skills/<skill-name>/SKILL.md
skills/meta/<meta-skill-name>/SKILL.md
```

Flat: one directory per skill, `name` == directory. There are no module-routing layers, with one structural family: the meta family under `skills/meta/`.
Role prompts are NOT skills and do not live here: each role's system prompt lives with its owning module in a `prompts/` dir (`src/polymerhus/recon/domain/prompts/`, `src/polymerhus/recon/crawl/prompts/`, `src/polymerhus/attack/hunting/prompts/`, `src/polymerhus/analysis/prompts/`) and is read directly by its module (fail-closed, memoized, no cross-module imports).
The meta family (`skills/meta/`) holds the skills exempt from the usage-protocol append, by a path rule (`is_meta_skill`: any loader path under `skills/meta/`), never a per-skill list: the two protocol/authoring skills `meta/meta-write-skill` (authoring rules) and `meta/meta-usage-skill` (usage protocol), plus task-specific meta-authoring skills such as `meta/authn-skill-writing`.

## Loader contract (`src/polymerhus/app/llm/skills.py::skill_for`)

`skill_for(name)` loads `skills/<name>/SKILL.md` (e.g. `webpage-profile`, `lightrag-query`).
It strips the YAML frontmatter, caches the body, and degrades to the caller-supplied fallback on a missing or unreadable file.
Only on-demand skill readers call it; no role prompt loads through here.

## Runtime loading (`build_load_skill_tool()::load_skill`)

The single loader made agent-reachable: `load_skill(name)` returns the skill body with its YAML frontmatter stripped - identical semantics to the shared `skill_for` loader (cached, fail-open to `''` on an unknown skill) - plus the `meta-usage-skill` reading protocol appended after a `---` separator (body, separator, protocol).
A missing protocol appends nothing, an unknown skill still degrades to `''`, and loading a meta-family skill (any loader path under `skills/meta/`) returns its bare body (no protocol on the protocol skills: no blackloops).
The appended protocol always reads from the shared catalogue - a per-project bundle never shadows it.
The protocol is delivered by the read path itself, never by the prompt or compaction domain.
`refresh` clears the cache first (the development hot-reload path only - never set it mid-run).
The usage contract rides the tool's description verbatim from `SKILL_LOAD_CONTRACT` in the loader module - this README and that constant are the same wording, kept in sync by hand; update both together.

## Per-project skill bundles (`SkillStore` + `build_write_skill_tool()::write_skill`)

An executing agent records what it learned using a procedure - a blocking condition, a new role, a privilege-escalation path - into its own project's bundle, so sibling and later agents start from accumulated ground truth:

```
<data_root>/<project_id>/skills/<skill>/
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

There is no canonical shared original; a project's copy is its original, created lazily on first write.
`write_skill(skill, target, content)` writes one whole file per call: `procedure` carries the `SKILL.md` **body** alone, `references/<name>` writes one bulky reference file (endpoint snapshots, header dumps, role matrices) so the procedure stays compact behind a pointer.
The factory binds the project - an agent writes through its own project's bundle, and any skill in it is writable (the future SkillEvolver writes any skill, so there is no per-skill writable set).
The store owns the frontmatter: `name` (the bundle directory), `description`, and `metadata.version` bumped one minor per write.
The metadata is operator-bootstrapped - the project bundle carries its own on later writes, and by the first update the shared catalogue skill's frontmatter is copied over; a skill with no bootstrapped metadata refuses rather than inventing any.
Every write lands atomically under a per-project lock.
Outcomes arrive as coded in-band envelopes (`skill_invalid`, `skill_target`, `store_unavailable`); nothing raises into the turn.
The write contract rides the tool's description verbatim from `WRITE_SKILL_CONTRACT` in the skills module - this README and that constant are the same wording, kept in sync by hand; update both together.
Reads resolve the per-project bundle first, then the shared catalogue, through the same store seam - loader, writer, and protocol injection share one store and can never diverge.
Agent owners collect the surface through `skill_agent_binding(role_id)`: it returns the L1 index middleware, the skill tools (`load_skill` for every agent, plus project-bound `write_skill` only for agents whose procedure evolves a skill - the `with_write_skill` flag), and the invocation context carrying the role's bounded skill set. One call binds the whole surface, so it can never be half-wired.

## L1 skill index (`skill_index_middleware`) and the phase-gating convention

Two tiers. L1 discovery: every agent that BINDS the skill surface carries its BOUNDED skill set's frontmatters in its system message (one `- name: description` line per skill under a header naming `load_skill` as the L2 move), rendered from the catalogue by the shared `dynamic_prompt` middleware - never hand-written, so it cannot drift, and each line's `description` is the skill's frontmatter text verbatim. The bounded set is DECLARED once per role in `ROLE_SKILLS` (`app/llm/skills.py`) and travels in the native invocation context; a role with no bearing skill is declared EXEMPT and binds nothing at all, and an undeclared role id is refused. L2 activation: the agent calls `load_skill` for a listed skill when its discipline bears on the turn; the result re-enters context through the native tool loop, no custom forwarding.
The roster is a bounded set in the same sense as a role's tool surface: only the skills whose discipline bears on that role's turn, never the whole catalogue - and an exemption rather than an empty index, so no agent pays for a surface it cannot use. A stale or forgotten roster entry fails the suite (`test_every_declared_role_skill_resolves_in_the_catalogue`, `test_every_tool_calling_role_declares_its_skill_set`, `test_the_roster_is_exactly_the_bound_plus_the_exempt_roles`), never a run.

## Data section

Every `skills/*/SKILL.md` carries a machine-readable frontmatter contract so the tool can index, validate, and report what was loaded.
Mandatory: `name` (non-empty string, EQUAL to the skill's directory), `description` (non-empty string: what the skill does + when to use it), `metadata` (string map carrying non-empty `version`).
No other top-level keys and no structured `inputs`: the body describes invocation context better than a schema stub.
Conformance is enforced by `tests/recon/test_skill_data_section.py::test_every_repo_skill_conforms_to_data_section`, which sweeps the catalogue and fails on any offender.
Keep frontmatter valid YAML: an unquoted `: ` inside a plain-scalar description breaks parsing (seen twice), so prefer folded `>-` blocks for long descriptions.

## Skills

| Skill | Status | Governs |
|---|---|---|
| `authorization-pyramid` | **authored** | reverse-engineering a service's role-to-permission structure via the inverse-pyramid probe |
| `lightrag-query` | **authored** | the hunting agent's methodology-KB query discipline (`query_lightrag` / `kb_query`) |
| `steel-browser` | **authored** | the browser operation mechanics over `steel_exec` (session lifecycle, ref flow, batch text entry, waiting, inline eval, bounded reads, one-shot scrape, spidering, profile mounts) |
| `webapp-clientside-semantic-model` | **authored** | client-side semantic modeling from browser-observable artifacts before security analysis |
| `webpage-analysis` | **authored** | web-application architectural profiling (navigation x rendering, independent) |
| `webpage-profile` | **authored + verified** | L1-spine webpage classification (L1D-31a: independent dimensions, fingerprint-insufficiency) |
| `meta/meta-usage-skill` | **authored (#234)** | assess the procedure against its observables; record improvements through `write_skill` |
| `meta/meta-write-skill` | **authored (#234, content-stable)** | procedure shape, frontmatter shape, references pointers |
| `meta/authn-skill-writing` | **authored** | authoring a project's per-project `authn` skill: posture probe, sign-in/sign-up execution, and the store/skill two-plane split |

Roadmap detail + priorities: `docs/design/jobs-tools-skills-taxonomy.md` section 6.
