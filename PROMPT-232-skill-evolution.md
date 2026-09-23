# PROMPT - #232 skill evolution (lessons + SkillEvolver + notes layout)

Handoff first prompt for issue #232, grounded on `dev` @ `3af0f14` (the merged #222/#234/#220/#221/#223 workstreams) and on `docs/design/skill-evolution-232-design.md`.

---

ROLE
You are the implementation agent for issue #232 ("Extend procedural knowledge
with generalized skill authoring and evolution") in the polymerhus repository.
You are a senior Python engineer working inside a DDD codebase with strict
layering, one-domain-one-owner rules, TDD, and an app-owned data root.
You do not summarise; you build, and you prove it with tests.

BASE AND WORKTREE
- Repo: /Users/diekgbbtt/polymerhus
- Base branch: dev at 3af0f14 (the integrated tip; do not branch off the
  feat/222-skill-load-tool worktree, which is at the same commit today).
- Create one fresh git worktree off dev: branch `feat/232-skill-evolution`.
- One PR per ticket against main; a verifier APPROVAL authorises opening it;
  merging to main is a human action; never push to main or dev.

MISSION
Deliver the intended end production system in three increments:
  (A) the skill-usage lesson layer (store + tool + universal binding),
  (B) the SkillEvolver agent (profile, harness, trigger, lifecycle),
  (C) the layout refactor of the persisted notes layer.
The transitory #234 system (per-project bundles + write_skill) is already
merged and is NOT to be redesigned.

ABSTRACT WORKFLOW - copy this line, keep it single, load the named skill per phase
wayfinder -> grill -> prototype -> to-spec -> to-tickets -> to-assertions -> implement -> code-review
  wayfinder      /Users/diekgbbtt/.claude/skills/wayfinder/SKILL.md
  grill          /Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md
  prototype      /Users/diekgbbtt/.claude/skills/prototype/SKILL.md
  to-spec        /Users/diekgbbtt/polymerhus/.agents/skills/to-spec/SKILL.md
  to-tickets     /Users/diekgbbtt/.claude/skills/to-tickets/SKILL.md
  to-assertions  /Users/diekgbbtt/.claude/skills/to-assertions/SKILL.md
  implement      /Users/diekgbbtt/.claude/skills/tdd/SKILL.md
  code-review    /Users/diekgbbtt/.claude/skills/code-review/SKILL.md
Phases are sequential; do not skip to implement. The grill phase is where the
open questions in GROUNDING 1, section 1.5 and section 2 must be closed with
the operator before a single line of code.

GROUNDING - read in this order, then verify every claim against the code
1. docs/design/skill-evolution-232-design.md      <- YOUR SPEC (the gaps)
2. docs/design/progressive-skill-lifecycle-adr.md (ADRs, parts A/B)
3. docs/design/skill-writing-primitives-spec.md
   docs/design/skill-writing-primitives-234-decisions.md
4. docs/design/skills-typed-surface-spec.md
   docs/design/skill-runtime-loading-222-decisions.md
5. src/polymerhus/app/data_root.py
   src/polymerhus/app/llm/skills.py
   src/polymerhus/app/auth/{store,seams,tool,records}.py
6. src/polymerhus/attack/hunting/hunt_store.py, hunter_memory.py,
   hunter_tools.py, pod/pod_memory.py, pod/note_tool.py   (the note surfaces)
7. CODING_STANDARD.md, CONTEXT-MAP.md, loop-constraints.md,
   docs/agents/{issue-tracker,domain,triage-labels}.md
8. gh issue view 232 --repo Diekgbbtt/polyphemus
Import rule: src/polymerhus/recon/domain/skills.py is a DEPRECATING SHIM.
Never import it. All skill access imports from polymerhus.app.llm.skills.

CURRENT SYSTEM - trust but verify (feed-forward from the #234 agent)
- One skills-access module: src/polymerhus/app/llm/skills.py (skill_for,
  load_skill, SkillStore, write_skill, meta-usage-skill protocol injection,
  skill_index_middleware, skill_agent_binding, build_skill_tools).
- Catalogue is FLAT: skills/<name>/SKILL.md; meta family at skills/meta/.
  Frontmatter is exactly name (== directory), description, metadata.version.
- Role prompts are NOT skills: src/polymerhus/<module>/prompts/<role>.md,
  read directly, fail-closed, memoised. Never add a role prompt under skills/.
- DATA_ROOT = <codebase_root>/data; per project
  <DATA_ROOT>/<project_id>/{skills,auth,hunting,...}. app/data_root.py owns it
  (PROJECT_SCAFFOLD, ensure_data_root, ensure_project, project_dir).
  Module stores write only files they own; lazy mkdir is a safety net only.
- Per-agent seam: skill_agent_binding(role_id) -> SkillAgentBinding
  (middleware + tools + context). build_skill_tools(project_id,
  with_write_skill=...) returns load_skill [+ write_skill].

EXTERNAL DEPENDENCY - the skills repository (operator-provided, NOT yet landed)
The operator will provide a SKILLS REPOSITORY (a directory or git URL of
Agent-Skills-conformant skills). It is the source of canonical catalogue
content and the reference corpus the SkillEvolver generalises toward.
Before you wire any ingestion or provider:
  1. Ask the operator for: location (path/URL), whether it is read-only or
     pull-updated, the sync direction (repo -> catalogue or catalogue -> repo),
     and the skill-spec version it conforms to.
  2. Until it lands, build against the local skills/ catalogue plus a fixture
     repo under tests/; NEVER hard-code an external path or invent its layout.
  3. The existing conformance sweep governs its contents; do not fork a
     validator for it.

THE GAPS - diagnosis, proposed solution, stub, pattern to copy
For each component: confirm the diagnosis with evidence, then implement the
stub shape below (or argue in the grill why the shape is wrong).

A. Lesson store (skill-scoped, cross-module) - MISSING
   Diagnosis: no skill-scoped lesson storage exists. The three note surfaces
   are hunting-scoped and cannot accept a skill key:
   - NotesTool requires fault_key validated against a HuntStore
     (hunter_tools.py:514, _fault_key_violation), kind is a hunt enum;
   - HunterMemoryStore._validate_fault_key demands the 3-part config key
     (hunter_memory.py:267-279);
   - PodNoteTool is spec_id + variant-order keyed (pod/note_tool.py:81);
   - PROJECT_SCAFFOLD (data_root.py:41) has no recon/analysis bucket at all;
   - D234-13 records "source_note_ids ... no notes system behind it".
   Solution: a LessonStore in the SAME domain as SkillStore, rooted through
   app.data_root.project_dir, one append-only lessons.yaml per project.
   Key: "skill:<skill_name>:<lesson_header>". The STORE stamps base_version
   (resolved via SkillStore.meta) and provenance; the agent never supplies them
   (D234-13: the reader sees skill text, never frontmatter).
   Pattern to copy: SkillStore (_dump_text_atomic, _lock_for, _PROJECT_LOCKS);
   HunterMemoryStore.write_note/read_notes (append + keyword read);
   app/auth/store.py (server-stamped fields).
   Stub:
     class LessonStore:
         def __init__(self, root_dir=None) -> None: ...
         def _lessons_file(self, project_id) -> Path:
             return project_dir(project_id, "skills", root=self._root) / "lessons.yaml"
         def append(self, project_id, *, skill, lesson_header, lesson,
                    observed_vs_expected="", evidence="", outcome="divergence",
                    provenance=None) -> str: ...
         def read(self, project_id, *, skill=None, key_keyword=None,
                  body_keyword=None, unconsumed_only=False) -> list[dict]: ...
         def mark_consumed(self, project_id, keys, *, revision_id) -> int: ...

B. record_skill_lesson tool - MISSING
   Solution: a factory beside build_load_skill_tool/build_write_skill_tool, one
   verbatim contract constant, coded in-band envelopes, never a raise.
   Pattern: build_write_skill_tool (factory + args schema + envelopes),
   NotesTool (BaseTool + _run + coded teaching rejection).
   Stub:
     RECORD_LESSON_CONTRACT = "..."
     def build_record_lesson_tool(project_id: str, store: LessonStore | None = None):
         class RecordLessonArgs(BaseModel):
             skill: str
             lesson_header: str
             lesson: str
             observed_vs_expected: str = ""
             evidence: str = ""
             outcome: Literal["divergence", "extension", "confirmation"] = "divergence"
         @tool(args_schema=RecordLessonArgs)
         def record_skill_lesson(...) -> dict:
             # {ok: True, key, base_version} | {ok: False, error:
             #  lesson_invalid|skill_unknown|store_unavailable}
         return record_skill_lesson

C. Universal binding - MISSING
   Solution: add record_skill_lesson to the read-only pair in build_skill_tools
   so EVERY bound role gets it in one edit; write_skill stays gated.
   Pattern: SkillAgentBinding composition (skills.py:263-328).
   Stub (diff):
     def build_skill_tools(project_id=None, with_write_skill=False,
                           store=None, lesson_store=None):
         tools = [build_load_skill_tool(project_id, store=store),
                  build_record_lesson_tool(project_id, store=lesson_store)]
         if with_write_skill:
             tools.append(build_write_skill_tool(project_id, store=store))
         return tools

D. Cursor-free consumption - MISSING
   Solution: read(unconsumed_only=True) selects records with consumed_by null;
   the evolver stamps consumed_by=<revision id> when its revision cites them.
   Alternative to grill: derive consumption from the union of source_note_ids
   across revisions (no stamp). Pattern: atomic read-modify-write
   (hunt_store/_dump_yaml_atomic) + server-stamped facts (auth store).

E. SkillEvolver harness + role - MISSING
   Solution: a session-mode stateful agent in the skills domain; harness runs
   the #232 section 5 procedure per (project, skill) and writes the project
   bundle only.
   Pattern to copy: attack/hunting/actors.py + app/llm/actor.py (stateful actor,
   per-turn isolation, retries), pod/agents.py create_agent wiring,
   recon/control/orchestrator_agent.py (session seam + tools + binding),
   hunting/runtime.py start_hunting + project_management/api.py (trigger).
   Stub:
     # src/polymerhus/app/llm/evolver.py  (new, skills domain)
     async def arun_evolution_pass(project_id: str, skill: str, *,
                                   skill_store=None, lesson_store=None,
                                   model=None) -> EvolutionOutcome: ...
     def build_skill_evolver_agent(*, project_id, skill_store, lesson_store,
                                   model=None): ...
   Role prompt: src/polymerhus/app/llm/prompts/skill_evolver.md (role prompts
   live with the owning module, never under skills/).
   Roster: ROLE_SKILLS["skill_evolver"] = ("meta/meta-write-skill",).
   Trigger: runtime.schedule("skills", coro, name=f"skills:{project_id}:evolve:{skill}")
   behind a POST /projects/{project_id}/skills/{skill}/evolve endpoint, plus a
   module context/flush hook (app/llm/checkpoints.py).

F. Meta-usage-skill body migration - DEFERRED until E lands
   Solution: only the skill body changes, from "write directly via write_skill"
   to "emit a lesson via record_skill_lesson". Dispatch a specialised
   skill-writing subagent (the D234-9 precedent); do not fold it into the code
   pass and do not touch the tool contract.

G. Notes-layer layout refactor - PARTIAL
   Diagnosis: the hunting note files are domain-correct where they are (fault/
   spec keyed). The refactor is not to move them; it is to add the skill-scoped
   home through the ONE resolver and keep the scaffold honest.
   Solution: lessons.yaml resolves via project_dir(project_id, "skills"); no
   PROJECT_SCAFFOLD change for the single-file option; if the grill picks the
   per-skill shard, add exactly one entry ("skills/lessons") to PROJECT_SCAFFOLD
   in data_root.py - never a module-side mkdir.
   Pattern: D234-16 (one resolver, scaffold owns fixed dirs).

CONCRETE SEAMS YOU MUST USE (do not invent parallel paths)
  app/data_root.py        DATA_ROOT, PROJECT_SCAFFOLD, ensure_data_root,
                          ensure_project, project_dir, validate_path_component
  app/llm/skills.py       skill_for, list_skills, skill_meta, validate_skill,
                          SkillStore.read/meta/write, SkillAgentBinding,
                          build_load_skill_tool, build_write_skill_tool,
                          build_skill_tools, skill_agent_binding,
                          skill_index_middleware, is_meta_skill,
                          ROLE_SKILLS, META_USAGE_SKILL, META_WRITE_SKILL,
                          PROTOCOL_SEPARATOR, SKILL_LOAD_CONTRACT,
                          WRITE_SKILL_CONTRACT, _dump_text_atomic, _lock_for
  app/auth/seams.py       auth_capable_binding (compose, do not fork)
  app/main.py             _startup (bootstrap hook)
  project_management/     repository.create_project -> ensure_project
  app/config.py           config.PROJECT_ID (project scope is tool-owned)
  app/llm/actor.py        stateful actor runtime (per-turn isolation, retries)
  app/llm/session.py      arun_session_turn (the one turn seam)
  app/llm/checkpoints.py  module_context, flush hooks
  app/runtime.py          schedule / cancel_run / hold_session
  app/observability/      Langfuse callbacks (fail-open; docs/observability-langfuse.md)

CONSTRAINTS
- One PR per ticket against main; branch `feat/232-skill-evolution` off dev
  (3af0f14) in a fresh worktree; NEVER push to main or dev. Merging is a human
  action.
- Fail-open reads, fail-loud writes; no I/O at import; atomic writes under a
  per-project lock; coded in-band envelopes for agent-facing tools.
- Do not change the hunting note contracts, the #234 write_skill contract, the
  catalogue frontmatter contract, or the meta-family exemption rule.
- Do not add role prompts under skills/; do not import the recon shim.
- Do not implement evaluation/admission or canonical promotion of revisions.

VALIDATION - before you claim done, confirm each line explicitly
[ ] record_skill_lesson reachable from every bound role via skill_agent_binding
[ ] live show-me: a recon role records a lesson; LessonStore.read returns it
[ ] the hunting NotesTool is untouched; its tests still pass
[ ] arun_evolution_pass on a seeded lesson set yields one revision + version bump
[ ] re-run with no new lessons yields NO write (zero-skip)
[ ] consumed lessons do not re-enter the next pass; unconsumed ones do
[ ] no path is hand-built outside project_dir; scaffold assertions pass
[ ] targeted suites green; report exact command + result
If any line is unproven, say so; never claim completion without the output.

ERROR RECOVERY
- Grilling contradicts the design doc: amend docs/design/skill-evolution-232-design.md
  and the ADR ledger in the same change; do not silently diverge.
- A seam you need does not exist as described: STOP and report the gap with
  file:line evidence before building a workaround.
- The operator's skills repository is not provided: proceed on fixtures, and
  mark the provider wiring as blocked in STATE.md High Priority.

OUTPUT FORMAT
- Phase 0: a written plan (files touched, tests added, stubs landed) before code.
- Each increment: failing test -> minimal implementation -> green -> commit.
- Final: the PR URL, the validation checklist with evidence, and a one-paragraph
  statement of what remains (canonical promotion, admission, provider wiring).
