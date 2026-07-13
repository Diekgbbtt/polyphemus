> **SUPERSEDED.** Retained for historical trace only.
> The authoritative doc is `recon-pipeline-design.md` §4.2 (job registry + phase DAG) and §10.2 (module map), which fold in this document's job/tool/skill conceptual model and 17-job table, with the `skills/` layout status corrected against the live filesystem (partially realized: the triager skill file exists but is not wired; no `skill_for` resolver exists).

# Jobs / Tools / Skills Taxonomy

*Companion to `agent-context-architecture.md`.
Defines the three-way relationship between a recon **job**, the **tool** it wraps, and the **skill** that guides an LLM role for it; how skills are organised, named, versioned, and selected; and the `skills/` layout.
Design + recommendation only; live modules under `agent/recon/` are owned by the orchestration stream.*

---

## 1. The three concepts, precisely

| Concept | What it is | Where it lives today | Cardinality |
|---|---|---|---|
| **Job** | A unit of recon work: a `JobSpec` placed in the phase DAG, with an IO contract (`consumes`/`produces`) and an execution recipe. | `agent/recon/jobs.py::JOBS` (17 jobs) | one per fleet capability |
| **Tool** | The executable capability a job runs: a Kali binary invoked via the single `execute_command` MCP tool, **or** an MCP tool *surface* (the `steel_*` tools). | Kali container / Steel MCP; named by `JobSpec.tool` | one per binary/surface |
| **Skill** | The LLM prompt/playbook that guides one **role** for a job: the discipline the model applies. | `JobSpec.skill` (a bare label today); one inline triager prompt; the ported `steel_crawl` prompt | one per (role, job-family) |

The clean mental model:

- A **job** is the *what* and *when* (this recipe, at this phase, consuming X, producing Y).
- A **tool** is the *how it executes* (this binary, this canonical invocation).
- A **skill** is the *how the agent thinks* (this role, this discipline, this playbook).

A job binds exactly one tool and, for each LLM role it activates, at most one skill.

### 1.1 Job -> Tool binding

Every `JobSpec` names one `tool`, and `tool` must byte-match a parser key in `PARSERS` (the deterministic `stdout -> list[AssetDelta]` function).
For the flat default, the tool is a Kali binary and the binding is the `command_template` (the tool's canonical invocation with `{placeholders}`).
For the agentic exception (`configurator_mode="agent"`), the tool is the Steel MCP surface and there is no `command_template`; the ReAct loop *is* the invocation.

The `command_template` is not the tool; it is the tool's **canonical parameterised invocation**.
Format-affecting flags (`-json`, `-jsonl`, `-oJ`) are baked into the template because the deterministic parser depends on them; the configurator fills only target/session/auth placeholders.
This is why the flat default is safe: the template pins the output shape the parser expects.

### 1.2 Job -> Skill binding, by role

A job activates zero, one, or two LLM roles, each of which may load a skill:

| Role | Activated when | Skill today | Skill it should have |
|---|---|---|---|
| `configurator` | `configurator_mode="agent"` only (deterministic mode is template-fill, no LLM, no skill) | none for deterministic; the crawler's `steel_crawl` prompt for agent mode | per-agentic-job crawl/ReAct playbook |
| `triager` | every job (always) | **one generic inline prompt** for all 17 jobs | a shared `writing-observations` discipline, optionally specialised per job-family |
| `job_orchestrator` | `preprocess` LLM path (stub in MVP) | none (deterministic 1:1 default) | an `asset-distribution` playbook when the LLM path is enabled |
| `crawler` | the Steel agentic-crawl job | the ported `steel_crawl` prompt | same (already a real skill) |

The critical gap today: the **triager runs one generic prompt for all 17 tools**, and that prompt does not encode the anchor allowlist, the observations-not-vulnerabilities rule, or the do-not-restate-assets discipline.
That is the single highest-value skill to author (see `agent-context-architecture.md` section 3 for the latent bug it fixes), and it is the one authored TDD-style in this deliverable.

`JobSpec.skill` today is a **job-family label** (`"subdomain_discovery"`, `"http_probe"`, `"crawl"`), not a loaded prompt.
It groups jobs (subfinder + amass both have `skill="subdomain_discovery"`) but nothing loads a file from it.
The taxonomy below gives that label a real referent.

---

## 2. Two senses of "skill" - and why they converge here

There is a naming collision to resolve up front.

1. **Authoring-time agent skill** (the `writing-skills` sense): a `SKILL.md` with `name`/`description` frontmatter, discovered and loaded by an agent, authored TDD-style against baseline failures.
2. **Runtime role prompt**: a system-prompt/playbook injected into a recon LLM role (triager/crawler) at pod runtime, like `steel_crawl.md`.

These are the **same artifact** in polymerhus.
`steel_crawl.md` is simultaneously a well-structured markdown skill *and* the crawler's runtime system prompt.
So a polymerhus skill is: a markdown playbook, authored and tested with the `writing-skills` discipline, whose body is loaded verbatim as a recon role's system prompt.
The frontmatter `description` says *when the skill applies* (which role/job-family); the body *is* the playbook the LLM receives.

This convergence is deliberate and load-bearing: it means every runtime prompt is testable (RED/GREEN against a subagent) and versioned as a file, rather than being an inline string buried in `pod.py` (as the triager prompt is today).

---

## 3. `skills/` layout

Skills live in a new top-level `skills/` directory, organised by **role** (the consumer), then by **skill name** (active, verb-first), each a directory with a `SKILL.md`:

```
skills/
  README.md                              # index + selection contract
  recon/
    triager/
      writing-observations/
        SKILL.md                         # the shared triager discipline (authored here)
      # future: per-family specialisations, e.g. auth-surface-observations/
    crawler/
      steel-crawl/
        SKILL.md                         # ported from redamon-agent steel_crawl.md
    configurator/
      # future: agent-mode configurator playbooks (non-crawl)
    job-orchestrator/
      # future: asset-distribution/cleaning playbook (when LLM path enabled)
```

Rationale for role-first, then skill-name:
- The consumer (role) is the primary axis of selection at runtime (`skill_for(role, job)`), so it is the top directory.
- Skill names are active and describe the discipline (`writing-observations`, `steel-crawl`), per `writing-skills` naming rules.
- One directory per skill leaves room for supporting files (few-shot examples, a rendered flowchart) without cluttering the role directory.

This is distinct from `docs/superpowers/skills/` (the meta-skills for Claude-the-developer, like `writing-skills` itself).
`skills/` at repo root is the **product's** skills: runtime prompts for the recon agents.

---

## 4. Skill selection: `skill_for(role, job)`

Selection is a pure function of `(role, job)`, resolved at pod build / role-invocation time:

```python
# PROPOSED interface (recommendation). Home: agent/recon/skills.py

def skill_for(role: str, job: JobSpec) -> str:
    """Return the system-prompt body for `role` on `job`.

    Resolution order (most specific wins):
      1. skills/recon/{role}/{job.skill}/SKILL.md      (job-family specialisation)
      2. skills/recon/{role}/{default_skill(role)}/SKILL.md   (role default)
    Strips YAML frontmatter; returns the markdown body verbatim.
    Cached; the file is the single source of truth (no inline prompts).
    """
```

Defaults per role:
- `triager` -> `writing-observations` (shared across all jobs unless a family specialises).
- `crawler` -> `steel-crawl`.
- `configurator` -> no default (deterministic mode loads no skill); `agent`-mode non-crawl jobs would name one.
- `job_orchestrator` -> no default until the LLM distribution path is enabled.

The specialisation seam (`{job.skill}` overriding the role default) is why `JobSpec.skill` stays a job-family label: `skill="http_probe"` can, in future, resolve `skills/recon/triager/http_probe/SKILL.md` if that probe needs a specialised triager discipline; otherwise it falls back to the role default.
For the MVP, only the defaults exist, so all 17 jobs' triagers share `writing-observations`.

### Versioning

- Skills are versioned by **git** (the file is the source of truth), not by embedded version numbers.
- A skill's `description` frontmatter is its contract for *when it applies*; changing behavior means editing the body and re-running its RED/GREEN tests (the `writing-skills` Iron Law applies to edits too).
- Breaking changes to a role's output contract (e.g. the Observation shape) are coordinated with the consuming code (the triager's structured-output schema), not made unilaterally in the prompt.

---

## 5. The 17 jobs mapped to (tool, roles, skill)

| Job | Tool | Mode | LLM roles active | Triager skill |
|---|---|---|---|---|
| subfinder, amass | subfinder/amass | det | triager | writing-observations |
| whois | whois | det | triager | writing-observations |
| dnsx, puredns | dnsx/puredns | det | triager | writing-observations |
| subdomain_takeover | subzy | det | triager (+ deterministic findings parser) | writing-observations |
| naabu | naabu | det | triager | writing-observations |
| httpx | httpx | det | triager | writing-observations |
| gau, paramspider | gau/paramspider | det | triager | writing-observations |
| katana | katana | det | triager | writing-observations |
| ffuf, kiterunner | ffuf/kr | det | triager | writing-observations |
| jsluice | jsluice | det | triager | writing-observations |
| graphql-cop | graphql-cop | det | triager (+ deterministic findings parser) | writing-observations |
| arjun | arjun | det | triager | writing-observations |
| steel_crawl | Steel MCP `steel_*` | agent | crawler + triager | writing-observations |

Two jobs (`subdomain_takeover`, `graphql-cop`) additionally feed the triager **deterministic** findings via `parse_findings -> finding_to_observation` (a non-LLM Observation source the triager node merges alongside LLM output).
The `writing-observations` skill governs only the LLM-derived observations; the deterministic findings are already contract-shaped by `findings.py`.

This table is the concrete payoff of the taxonomy: 16 deterministic tools + 1 agentic tool, all sharing exactly one triager skill today, with a clear seam to specialise per family later, and exactly one agentic job carrying its own crawler skill.

---

## 6. Prioritised skill roadmap

Ordered by value = (impact on graph quality) x (baseline failure severity) / (authoring cost).

1. **`triager/writing-observations` - AUTHORED in this deliverable.**
   Highest value: it runs on all 17 jobs, and its baseline failures (illegal anchors silently dropped, observations-as-vulnerabilities, restating assets) directly corrupt or waste the graph.
   RED/GREEN evidence in the skill's directory.
2. **`crawler/steel-crawl` - verify.**
   `steel_crawl.md` is battle-tested; the work is adding a RED/GREEN test that a crawler without it wastes budget on `.js`/static URLs and fails to flush form-hidden endpoints.
   Medium cost, high value (the only agentic job).
3. **`job-orchestrator/asset-distribution` - author when the LLM preprocess path is enabled.**
   Currently the deterministic 1:1 default is correct for the MVP, so this is deferred until asset volumes make cleaning/dedup/grouping worthwhile.
   Baseline failure to test: an orchestrator that fans one pod per near-duplicate asset (e.g. `www.x.com` and `x.com` resolving identically) wasting the `MAX_PODS` budget, or that mis-groups assets a single pod could batch.
4. **`configurator/agent-mode` playbooks (non-crawl) - deferred.**
   Only needed if a non-crawl job adopts `configurator_mode="agent"` (the flexible configurator the design explicitly defers).
   No baseline to test until such a job exists.

The roadmap respects the `writing-skills` Iron Law: no skill is authored without first watching an agent fail without it.
Items 2-4 name the baseline failure to reproduce first, so a future author starts at RED, not at the prose.

---

## 7. Relationship back to the context architecture

Skills are *how a role thinks*; `asset_context` is *what a role knows*.
They are complementary and both minimal-by-design:
- The `writing-observations` skill tells the triager to anchor on a legal broad element and not restate assets.
- `asset_context` gives the triager the legal anchor and the existing observations so it *can* comply.

Neither works alone: a perfect skill with no anchor context still guesses the anchor; perfect context with no skill still frames findings as vulnerabilities.
The two deliverables (this taxonomy + the context architecture) are one system.
