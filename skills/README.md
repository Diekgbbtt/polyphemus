# polymerhus skills

Genuine progressive-disclosure skills, loadable on demand through the shared loader (`src/polymerhus/app/llm/skills.py::skill_for`) or at runtime through the shared tool (`build_load_skill_tool()::load_skill`, which calls `skill_for` internally so the two paths can never diverge).
Each skill's `SKILL.md` carries Agent-Skills-spec frontmatter: `name` == its directory, `description` = what + when, `metadata` string map carrying `version`.
This is distinct from `docs/superpowers/skills/` (meta-skills for Claude-the-developer); these are the product's skills.

See `docs/design/jobs-tools-skills-taxonomy.md` for the full jobs/tools/skills model and `docs/design/agent-context-architecture.md` for how skills compose with the `asset_context` channel.

## Layout

```
skills/web-vulnerability-testing/<group>/SKILL.md          # a suite group parent
skills/web-vulnerability-testing/<group>/<leaf>/SKILL.md   # a suite variant
skills/internal/tools/<tool>/SKILL.md                      # a tool-usage skill
skills/internal/<specialisation>/SKILL.md                  # a single-agent specialisation
skills/meta/<meta-skill-name>/SKILL.md                     # the meta family
skills/target-specific-procedure/<project_id>/<name>/      # per-project procedures
```

The live root carries four top-level branches (operator topology ruling, 2026-10-20).
A branch is a namespace, never a skill, so no branch root carries a `SKILL.md`.

- `web-vulnerability-testing/` holds the well-formed suite: a class or technique-family parent at level 1 and its variants at level 2 (165 skills across 41 groups: 38 classes - 28 decomposing class parents, 9 new standalone classes, and the standalone `graphql` - the R7 cross-cutting group `two-principal-authz`, never counted among the classes, and the `defence-bypass` and `proxy-techniques` families).
  The stream that produced it is W0-W7; its records live in `skills-unspurious/`.
- `internal/` holds the six product skills the agents load directly: the two tool wrappers under `internal/tools/` (`lightrag-query`, `steel-browser`) and the four single-agent specialisations (`authorization-pyramid`, `webapp-clientside-semantic-model`, `webpage-analysis`, `webpage-profile`).
  The 33 tool, technology, and Windows corpus skills that the #232 copy brought into the live root were stale copy artifacts and were removed by the same ruling.
- `meta/` holds the meta family, whose path-shaped names are part of the loader contract.
- `target-specific-procedure/` holds the per-project procedures: the bootstrapper-authored `authn`/sign-in/sign-up procedures, the evolved skill versions, and the newly mined project-specific skills.
  The branch is project data; the catalogue never indexes it, and the project seam resolves it project-first.
  See `target-specific-procedure/README.md`.

Role prompts are NOT skills and do not live here: each role's system prompt lives with its owning module in a `prompts/` dir (`src/polymerhus/recon/domain/prompts/`, `src/polymerhus/recon/crawl/prompts/`, `src/polymerhus/attack/hunting/prompts/`, `src/polymerhus/analysis/prompts/`) and is read directly by its module (fail-closed, memoized, no cross-module imports).
The meta family (`skills/meta/`) holds the skills exempt from the usage-protocol append, by a path rule (`is_meta_skill`: any loader path under `skills/meta/`), never a per-skill list: the two protocol/authoring skills `meta/meta-write-skill` (authoring rules) and `meta/meta-usage-skill` (usage protocol), plus task-specific meta-authoring skills such as `meta/authn-skill-writing`.

## Loader contract (`src/polymerhus/app/llm/skills.py::skill_for`)

`skill_for(name)` resolves the loader name through the lazy live-root `SkillCatalogue` over `skills/` (W4, now the default): a suite leaf loads by its flat leaf name whichever group holds it, an internal skill loads by its directory name, and the meta family keeps its path-shaped name (`meta/meta-usage-skill`).
It strips the YAML frontmatter, caches the body, and degrades to the caller-supplied fallback on a missing or unreadable bundle.
Only on-demand skill readers call it; no role prompt loads through here.

The catalogue indexes every `SKILL.md`-bearing directory at any depth and reports loader names only, so every client stays agnostic to the branch layout: a bundle under `meta/` keeps its path-shaped name (the path-based meta rule holds), a bundle under `target-specific-procedure/` stays out of the shared index and resolves project-first, and every other bundle reports its flat leaf directory name (R3).
It refuses a duplicate name loudly with both colliding paths named (R4), refuses a `SKILL.md` at a branch root, and resolves `references/` and `scripts/` inside the owning leaf (R8; rules R1-R4 and R8 in `docs/design/skills-taxonomy.md`, whose flat live-root layout is superseded by the topology ruling).
`skill_for`/`list_skills`/`skill_meta`/`validate_skill` share that one index, so the loader, the data-section reads, and validation cannot disagree.

An explicit catalogue remains an index over an explicit root: `SkillCatalogue(root)` mounts any tree, and a call passing `catalogue=` resolves through that mount instead of the live root (`skill_for(name, catalogue=...)`, `list_skills(catalogue=...)`, and so on).
Mounting one never changes the live root's index.

The default live mount is fail-open: a malformed live tree (a duplicate name, a `SKILL.md` outside the two levels, or an unreadable scan) is logged once at ERROR and degrades to an empty catalogue, so no read raises into an agent turn.
An explicit `SkillCatalogue(root)` mount is fail-loud: the same defect raises at construction, so a test or an operator mounting a tree sees it immediately.
The repo checks and the catalogue tests fail the malformed tree either way.

## Runtime loading (`build_load_skill_tool()::load_skill`)

The single loader made agent-reachable: `load_skill(name)` returns the skill body with its YAML frontmatter stripped - identical semantics to the shared `skill_for` loader (cached, fail-open to `''` on an unknown skill) - plus the `meta-usage-skill` reading protocol appended after a `---` separator (body, separator, protocol).
A missing protocol appends nothing, an unknown skill still degrades to `''`, and loading a meta-family skill (any loader path under `skills/meta/`) returns its bare body (no protocol on the protocol skills: no blackloops).
The appended protocol always reads from the shared catalogue - a per-project bundle never shadows it.
The protocol is delivered by the read path itself, never by the prompt or compaction domain.
`refresh` clears the cache first (the development hot-reload path only - never set it mid-run).
The usage contract rides the tool's description verbatim from `SKILL_LOAD_CONTRACT` in the loader module - this README and that constant are the same wording, kept in sync by hand; update both together.

## Skill-usage lessons (`build_record_lesson_tool()::record_skill_lesson`)

Every bound role also carries `record_skill_lesson`, the one append-only observation surface that is safe to bind universally (#232 D232-4).
It records ONE reusable observation an executing agent made about a skill it used, grounded in the run's evidence, into the project's per-skill lesson shard.
The record contract rides the tool's description verbatim from `RECORD_LESSON_CONTRACT` in the loader module; the constant, verbatim:

> Record ONE skill-usage lesson: a reusable observation about a skill you used, grounded in this run's evidence, persisted in the project's lesson shard for that skill.
>
> FIELDS - `skill`: the skill the lesson is about (one flat name). `type`: `specification` (knowledge specific to the target's attack surface), `extension` (an extension of the procedure: new steps, an optimised grouping, an anti-pattern - steps that must not be done - or an extension of the technique's scope), or `defect` (a genuine error in the illustrated procedure). `lesson`: the reusable lesson in prose. `expected`: what the skill states or implies, extracted as close to its wording as possible. `evidence`: concrete identifiers from this run (http-history artifact ids, request/response entries, run ids).
>
> THE STORE STAMPS the key, the skill's base version, the writing agent's identity, and the timestamp - never supply them. A skill whose version does not resolve is refused.
>
> OUTCOMES - one in-band envelope: `{ok: true, key, base_version}` or `{ok: false, error, detail}` with error one of `lesson_invalid`, `skill_unknown`, `store_unavailable`. Nothing raises into the turn.
>
> Record once per material observation; the SkillEvolver consumes the accumulated lessons, so not every step needs one.

Consumption is key-encoded: the SkillEvolver marks a lesson consumed by rewriting its key with the reserved `:consumed` suffix, so selection needs no cursor.
This README and that constant are kept in sync by hand; update both together.

## Per-project skill bundles (`SkillStore` + `build_write_skill_tool()::write_skill`)

An executing agent records what it learned using a procedure - a blocking condition, a new role, a privilege-escalation path - into its own project's bundle, so sibling and later agents start from accumulated ground truth:

```
skills/target-specific-procedure/<project_id>/<skill>/
├── SKILL.md
├── references/
├── scripts/
├── assets/
└── revisions/
skills/target-specific-procedure/<project_id>/lessons/<skill>.yaml   # the skill-usage lesson shard
skills/target-specific-procedure/<project_id>/evolution/<pass>.yaml  # an evolution pass record
```

There is no canonical shared original; a project's copy is its original, created lazily on first write.
The project's skill area is the `target-specific-procedure/` branch of the live `skills/` root, so the bootstrapper's procedures and the evolved or newly mined project-specific skills share one layout with the catalogue bundles.
`write_skill(skill, target, content)` writes one whole file per call: `procedure` carries the `SKILL.md` **body** alone, `references/<name>` writes one bulky reference file (endpoint snapshots, header dumps, role matrices) so the procedure stays compact behind a pointer.
The factory binds the project - an agent writes through its own project's bundle, and any skill in it is writable (the future SkillEvolver writes any skill, so there is no per-skill writable set).
The store owns the frontmatter: `name` (the bundle directory), `description`, and `metadata.version` bumped one minor per write.
The metadata is operator-bootstrapped - the project bundle carries its own on later writes, and by the first update the shared catalogue skill's frontmatter is copied over; a skill with no bootstrapped metadata refuses rather than inventing any.
Every write lands atomically under a per-project lock.
Outcomes arrive as coded in-band envelopes (`skill_invalid`, `skill_target`, `store_unavailable`); nothing raises into the turn.
The write contract rides the tool's description verbatim from `WRITE_SKILL_CONTRACT` in the skills module - this README and that constant are the same wording, kept in sync by hand; update both together.
Reads resolve the per-project bundle first, then the shared catalogue, through the same store seam - loader, writer, and protocol injection share one store and can never diverge.
Agent owners collect the surface through `skill_agent_binding(role_id)`: it returns the L1 index middleware, the skill tools (`load_skill` + `record_skill_lesson` for every agent, plus project-bound `write_skill` only for agents whose procedure evolves a skill - the `with_write_skill` flag), and the invocation context carrying the role's bounded skill set. One call binds the whole surface, so it can never be half-wired.

## L1 skill index (`skill_index_middleware`) and the phase-gating convention

Two tiers. L1 discovery: every agent that BINDS the skill surface carries its BOUNDED skill set's frontmatters in its system message (one `- name: description` line per skill under a header naming `load_skill` as the L2 move), rendered by the shared `dynamic_prompt` middleware from the SAME store seam the loader uses - the per-project bundle first, then the shared catalogue - never hand-written, so it cannot drift from what resolves, and each line's `description` is the skill's frontmatter text verbatim. A project-authored skill (e.g. `authn`) is collected only when its bundle exists at the designed location `skills/target-specific-procedure/<project_id>/<name>/SKILL.md`, so a bundle that is missing or not at that location never renders in the index. The bounded set is DECLARED once per role in `ROLE_SKILLS` (`app/llm/skills.py`) and travels in the native invocation context alongside the project id (`context={"skills": [...], "project_id": "..."}`); without a project id the render is catalogue-only. A role with no bearing skill is declared EXEMPT and binds nothing at all, and an undeclared role id is refused. L2 activation: the agent calls `load_skill` for a listed skill when its discipline bears on the turn; the result re-enters context through the native tool loop, no custom forwarding.
The roster is a bounded set in the same sense as a role's tool surface: only the skills whose discipline bears on that role's turn, never the whole catalogue - and an exemption rather than an empty index, so no agent pays for a surface it cannot use. A stale or forgotten roster entry fails the suite (`test_every_declared_role_skill_resolves_in_the_catalogue`, `test_every_tool_calling_role_declares_its_skill_set`, `test_the_roster_is_exactly_the_bound_plus_the_exempt_roles`), never a run.

## The web-vulnerability-testing suite

The suite produced by the W0-W7 stream now lives at this live root; `skills-unspurious/` keeps its records only.

**Authorities.** `docs/design/skills-variant-boundary.md` is the variant boundary (how a class decomposes, the decision procedure, the explicit non-discriminators).
`docs/design/skills-ontology.md` is the ontology and section contract (the two layers, the canonical layout, the entity-to-section mapping).
`docs/design/skills-taxonomy.md` is the naming and taxonomy spec (the logical root, group levels, flat-leaf loader identity, global name uniqueness, the leaf naming convention, the suite map).
Every naming or placement question is answered there.

**Taxonomy and naming.** The nested path is the taxonomy target (`web-vulnerability-testing -> <class> -> <variant>`, folded under the parent class directory).
A class or family parent is a level-1 group directory carrying its own `SKILL.md`; a variant is a level-2 leaf (`<group>/<variant>/SKILL.md`).
A family leaf is named `<family>-<discriminator>` (rule R5), where the discriminator is the variant's first bent step.
The loader name of a skill is its flat leaf sub-directory (R3); its frontmatter `name` equals that directory, and the global name space is unique (R4).
`references/` and `scripts/` resolve inside the owning leaf, at level 1 or level 2 (R8).

**What is there.** 165 skills across 41 groups: 38 classes (28 decomposing class parents, 9 new standalone classes, and the standalone `graphql`), the R7 cross-cutting group `two-principal-authz` (never counted among the classes), and the `defence-bypass` and `proxy-techniques` families.
Each of the 30 groups carrying a `## Variants` set - the 28 decomposing class parents and the two family parents - lists a line set equal to its own leaves (R9); `graphql` stands as one skill with no `## Variants` (R10).
The families carry 16 variant leaves between them (`defence-bypass` 7, `proxy-techniques` 9).
The suite map in `docs/design/skills-taxonomy.md` is the authoritative placement; the counts and the enrichment record are in `skills-unspurious/INVENTORY.md`, `skills-unspurious/DECOMPOSITION-REPORT.md`, and `skills-unspurious/SCREAMING-REPORT.md`.

**Conventions.** No em dashes; plain dashes.
In authored Markdown, one full sentence per line.
Skills stay abstract: no concrete product, version, endpoint, host, parameter, or payload literal; concrete assets are parametrised at runtime from the attack-surface graph, the knowledge base, and the HTTP history.
Duplicated content becomes a cross-reference, never a copy.
Skills must not specify identified vulnerabilities.

**Checks and records.** The suite-scoped machine checks live in `skills-unspurious/_completion/verify.sh` and target the 41 group directories under this root (the layout scan, R9/R10, the family prefix rule, the extended-reading pointer, the frontmatter name==directory sweep, and the em-dash scan).
The script does not scan the non-suite live-root skills, which keep their old layouts.
The stream records (`_analysis/`, `_authoring/`, `_migration/`, `INVENTORY.md`, `DECOMPOSITION-REPORT.md`, `SCREAMING-REPORT.md`) and the script stay in `skills-unspurious/`.

## Data section

Every `SKILL.md` under the live root (flat or nested) carries a machine-readable frontmatter contract so the tool can index, validate, and report what was loaded.
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

The live root's other 9 skills - the six internal skills (the two tool wrappers and the four single-agent specialisations) and the three `meta/` skills - are governed by the same data-section conformance sweep.

Roadmap detail + priorities: `docs/design/jobs-tools-skills-taxonomy.md` section 6.
