# polymerhus recon skills

Runtime role-prompts for the recon LLM agents, authored and tested with the `superpowers:writing-skills` TDD discipline (RED baseline -> write skill -> GREEN verify).
Each skill's `SKILL.md` body is loaded verbatim as a recon role's system prompt.
This is distinct from `docs/superpowers/skills/` (meta-skills for Claude-the-developer); these are the product's skills.

See `docs/design/jobs-tools-skills-taxonomy.md` for the full jobs/tools/skills model and `docs/design/agent-context-architecture.md` for how skills compose with the `asset_context` channel.

## Layout

```
skills/recon/<role>/<skill-name>/SKILL.md
```

Roles: `triager` (always active), `crawler` (agentic crawl), `configurator` (agent mode only), `job-orchestrator` (LLM distribution path, deferred).

## Selection contract (proposed `agent/recon/skills.py::skill_for`)

`skill_for(role, job)` resolves most-specific-first:
1. `skills/recon/{role}/{job.skill}/SKILL.md` - job-family specialisation (`job.skill` is the family label, e.g. `http_probe`).
2. `skills/recon/{role}/{default}/SKILL.md` - role default.

Strips YAML frontmatter, returns the body. Defaults: `triager -> writing-observations`, `crawler -> steel-crawl`.

## Skills

| Role | Skill | Status | Governs |
|---|---|---|---|
| triager | `writing-observations` | **authored + RED/GREEN verified** | anchor allowlist, observations-not-vulnerabilities, no asset restatement |
| crawler | `steel-crawl` | roadmap (port from redamon-agent, verify) | agentic crawl budget/frontier discipline |
| job-orchestrator | `asset-distribution` | roadmap (deferred to LLM path) | asset cleaning/dedup/distribution over MAX_PODS |
| configurator | agent-mode playbooks | roadmap (deferred) | non-crawl agentic configuration |

Roadmap detail + priorities: `docs/design/jobs-tools-skills-taxonomy.md` section 6.
