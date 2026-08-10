# Implementer prompt - #100 dynamic LLM API gateway (LiteLLM + models.dev glueing)

*Feed this verbatim to the agent that will address #100. It specialises the agent on the workflow, grounds it in the domain/architecture/standard, states the component rationale, brainstorms the useful skills, and pins the loop's termination conditions.*

---

You are the implementer agent for ticket **#100 - "add llm api gateway(litellm) - dynamic with models.dev api client glueing"** in the polymerhus repo.

Read the ticket first (`gh issue view 100`): its body is deliberately a scaffold - "scaffhold logic to ease solutions for the two sub-issues" - and it carries the `wayfinder:grilling` label: the design is high-level and the grey points are yours to resolve with the operator before any code.

Read the design spec it stands on, `docs/design/dynamic-llm-gateway-design-spec.md`, in full: it is the architecture-level statement this ticket turns into a running system.

This is a **shared, cross-cutting subsystem** - the load-bearing piece two sub-issues depend on - build it with the care that implies.

## 1. Component rationale (the design intent to honour)

The system the spec describes, in one pass:

- A **Capability Sync Component** - a small, stateless, schedulable job (fetch -> join -> map -> validate -> diff -> push) that joins a **Provider Existence Source** ("what exists": a relay's `/v1/models`) with the **Capability/Cost/Context Registry** ("what it can do": a models.dev-style JSON), normalising into the **Canonical Capability Record** (spec §4: `model_id`, `provider_namespace`, context/output limits, per-token costs incl. cache read/write, a closed capability set, `source`, `synced_at`, `staleness`).
- A **Gateway (runtime)** that consumes Capability Records - it never originates them - and owns protocol translation, routing/load-balancing/fallback, cost and context-window enforcement, capability gating, and prompt caching. The spec's management API is how the sync pushes deltas (add/update/remove model records without a restart).
- A **Harness Contract** - the only surface any agent touches; harnesses are never coupled to the registry schema, the sync cadence, or upstream provider quirks.

The load-bearing design principles from the spec, all ratified - do not silently deviate:

- **Harness-agnostic** and **gateway-implementation-agnostic**: the Capability Record schema and the sync logic are defined independently of any one gateway's field names; a mapping layer is the only place product-specific names live.
- **Separation of "what exists" from "what it can do"**: a provider's live model list is authoritative for existence only; the registry is authoritative for capability. Never conflated into one call.
- **Conservative on unknowns**: a model with no registry entry is `unknown`, never assumed true and never assumed false (spec §5: `unknown` is treated as `false` for capability-gating, and the gap is surfaced for the operator). Silent optimistic defaults are the specific failure mode this system exists to eliminate.
- **Fail toward staleness, not toward guessing**: if the registry is unreachable, keep the last-known-good records with an increasing staleness marker.
- **Idempotent, diffable sync**: every run recomputes desired state and pushes only deltas; re-running is always safe.
- **Full provenance**: every pushed field tagged with (source registry, source record, sync timestamp).
- **No single vendor as a hard dependency**: registry and gateway are swappable behind their boundaries; named products are reference implementations, not foundations.

**The operator's core principle (binding).** LiteLLM is used **solely** for solving this problem set: gateway routing, capability/context/cost metadata, and prompt caching. Everything else stays external for now - memory, MCP, budget tracking, observability (Langfuse), A2A. That boundary is what makes the routing guarantee load-bearing: because the gateway is the only LLM-facing surface the agents use, it must route **consistently**, and the context-window management couples to it because per-model windows are read from the same gateway metadata the routing decides on.

**What this scaffold is for - the two sub-issues.** This ticket exists to ease the solutions of its two sub-issues. Read them (`gh issue view 99`, `gh issue view 95`) and treat their suggested solutions as inputs to adapt, not gospel - the new support this gateway provides means they partially overlap and must be re-shaped:

- **#99 - LLM client is not capability-adaptive across providers.** Its researched option (c) ("adopt a gateway/router lib (LiteLLM) - not recommended") **predates the operator's decision to build the LiteLLM gateway**; the operator-authoritative direction flips that calculus. Its recommended shape - a "session-scoped capability profile, seeded from a small known-model table, probe-on-miss" - must be re-shaped: the profile now resolves **from the gateway's metadata surface (the Capability Record)**, not from a local table plus runtime probes. Its non-negotiables survive intact: keep capability resolution **off the #73 timeout/retry axis** (resolve-and-hold at session construction; `invoke_with_escalating_timeout` wraps each resolved call - nesting a capability-retry inside the latency-retry re-creates the #32 multiplied-retry defect); P2 stateful sessions (langgraph `StateGraph`, `bind_tools`) are first-class, not an afterthought; the crawl tool-loop needs its own strategy-level answer, not a method swap.
- **#95 - context-window auto-compact.** It consumes the per-model context/output window **from this gateway** (models.dev-fed), never hardcoded, with a conservative 150k default for the miss (**SwissAI is not on models.dev, so it takes the default**). Its open grilling question 1 ("what retrieves context-window lengths dynamically?") is answered **by this ticket's gateway surface** - the exact field and access path must be decided here and be stable enough for #95 to build on. #95 is **blocked by #94** (the semi-stateful scaffold) - do not wire its consumers, but the gateway metadata surface for windows must exist regardless.

## 2. First step - a grilling session (reduce the key risks to a residual minimum)

Before any code, run a grilling session with the operator (the `grilling` skill, read from the filesystem - section 4).

The design spec is deliberately high-level; the `wayfinder:grilling` label means the first phase of this ticket IS the grilling. Drive it to a solution for each of the shaping points; these are the residual risks:

1. **Deployment shape: separate API gateway, or a module embedded in the system?** LiteLLM as a standalone gateway service (its own process/container with a management API - the `$HOME/.claude/skills/litellm` proxy-ops suite applies) vs a new module embedded in the system using the litellm SDK (`litellm.Router` etc., no proxy service). Weigh the spec's §3.3 push step ("the gateway's live management API"), the running-stack topology (docker-compose, built from `dev`), the "no vendor as hard dependency" principle, and the fact that the two sub-issues only need routing + metadata + caching, not the full proxy surface.
2. **Model-configuration freshness: bootstrap-only, or out-of-band refresh?** Do LLM configurations (which models route where, the capability records) update only at agent container bootstrap, or does the sync job refresh them async out-of-band - and with which frequency? (Spec §6 suggests "on the order of tens of minutes" for sync cadence - ratify what this system actually runs.) Decide what the container reads at boot vs what it re-reads, and how staleness is surfaced.
3. **Responsibility model: gateway vs llm client.** Build the responsibility model that draws the boundaries: what the gateway owns (routing/fallback, capability gating, context/cost enforcement, prompt caching, provider-key custody) vs what the client layer (`app/llm/providers.py` / `roles.py`) owns (per-role construction, the #73 escalating-retry as the SINGLE retry layer, the #93 role vocabulary, session vs one-shot seams, Langfuse callbacks). The spec's harness contract (§3.5) is the conceptual seam - decide how it lands in THIS codebase without becoming a second, competing client layer. Every responsibility lives in exactly one place (CODING_STANDARD §1).
4. **Blast radius across the langgraph agents.** Does this refactor require changing the client component in the lang-graph agents implemented across all modules - the crawl ReAct loop (`crawl_agentic.py:174` `bind_tools`), `job_agent.py`'s StateGraph (`job_agent.py:180`), steering's `resolve_model` (`recon/control/steering.py:59-69`), the orchestrator (`orchestrator_agent.py:65`), the hunting module's lazy-binding branch? Map which seams change, which stay, and whether the change is additive (a new base URL pointing at the gateway + metadata-driven construction) or invasive.

Also resolve in the grilling:

- The **Capability Record -> gateway-native schema mapping**: which LiteLLM-native fields carry context window, costs, and capability flags, and how `unknown` propagates through them. This mapping is the only place product-specific field names live (spec §3.3).
- The **exact surface #95 consumes**: the per-model context/output window field + access path, so #95's "open question 1" is closed by this ticket, not re-decided there.
- **How #99's capability-profile re-shape lands**: the client asks the gateway for a profile keyed by (provider, model, schema-class) instead of a local table + probe - and what happens to probe-on-miss for models the registry lacks (conservative `unknown`, per spec §5).
- **Prompt caching**: where LiteLLM's caching is configured (provider-side vs gateway-side), and that it stays in scope while budget tracking stays out.
- **Sync validation + provenance**: the spec's §3.3 validate step (reject a payload whose record count collapsed implausibly versus the last known-good snapshot), diffable push, provenance tagging, per-environment independence (dev/staging/prod sync independently), and the operator-notification path for unknown-flagged models.
- **Dependency plumbing**: litellm and a models.dev client are new runtime dependencies; the repo pins nothing (deps arrive via the `redamon-agent:latest` base image, `Dockerfile:1`; #99 flags the unpinned-SDK-versions risk as its own ticket). Decide how litellm enters the stack - the Dockerfile layered-requirements pattern (`requirements-observability.txt`) - and how versions get pinned.

Record the grilling outcome - the `grill-with-docs` variant writes the ADR + glossary entries in the same change. Do not start coding until the operator confirms a shared understanding.

## 3. Grounding - read these directly from the filesystem before designing

- `CLAUDE.md`, `CONTEXT-MAP.md`, `CODING_STANDARD.md` - the DDD paradigm, bounded contexts, sole-writer discipline, slim typed interface agreements, dependency injection for testability, no I/O at import (section 6), fail-open (section 12). NOTE the `CONTEXT-MAP.md` ruling: **llm-client is a helper module, never a context** - the gateway extends that shared kernel; it does not mint a new bounded context and gets no `CONTEXT.md`.
- `loop-constraints.md` (the sole work authority - read it verbatim), `loop-budget.md` (token cap; report-only at 80%), `STATE.md` (High Priority: kill switch, escalations).
- `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md` - branch naming, one PR per workflow ticket, verifier APPROVAL + operator green light authorise the PR, merging to `main` is human.
- `docs/design/dynamic-llm-gateway-design-spec.md` - the design spec; this is the system you are realising. Where the spec and the grey-point resolutions conflict, the grilling outcome wins and the spec must be corrected in the same change.
- `docs/design/context-window-manager-95-implementer-prompt.md` - the #95 sibling: #95 depends on the gateway's per-model window surface; keep the access path you build consistent with what #95's prompt already promises.
- `docs/design/llm-role-architecture-agent-prompt.md` - the #93 role vocabulary (role_id / model_key / agent_mode, one_shot vs resumable) your client changes must not regress.
- `src/polymerhus/app/llm/providers.py` and `roles.py` - the client seams you extend: `PROVIDERS` (`providers.py:148-153`), `build_chat_model`, `resolve_role`, `chat_model_for` (session path) vs `invoke_role` (one-shot path), `invoke_with_escalating_timeout` (`providers.py:110-145` - the SINGLE retry layer, never multiplied), the zen-family id handling (`providers.py:178-184`), Langfuse callbacks at construction (`providers.py:202-207`).
- The P2 langgraph sites - the blast-radius map for grey point 4: `src/polymerhus/recon/crawl/crawl_agentic.py:174` (`bind_tools`), `src/polymerhus/recon/control/job_agent.py:180`, `src/polymerhus/recon/control/orchestrator_agent.py:65`, `src/polymerhus/recon/control/steering.py:59-69` (`resolve_model`).
- The running stack: `Dockerfile` (base image `redamon-agent:latest`, layered requirements), `docker-compose.yml` / `docker-compose.dev.yml`, `requirements-observability.txt` (the pattern for adding a pinned litellm layer).
- The eval surface: `tests/e2e/fixtures/eval-targets.yaml` - target `settings` map onto `settings.recon`; provider/model arrive via the role env keys, not the target file - the gateway changes where those resolve.
- The tickets: `gh issue view 100` (this ticket), `gh issue view 99` and `gh issue view 95` (the sub-issues), `gh issue view 73` (the retry axis that must not entangle), `gh issue view 44` (absorbed by #99), `gh issue view 93` and `gh issue view 94` (the role vocabulary and the stateful migration #95 is blocked by).
- `docs/observability-langfuse.md` - observability stays external; Langfuse callbacks must keep flowing through whatever client construction the gateway introduces.

## 4. Skills - open each SKILL.md from the filesystem when its situation arises

Skills are user-invokable only; you cannot load them through a skill loader. Open each skill's `SKILL.md` directly from the filesystem when its situation arises:

- `grilling` - `/Users/diekgbbtt/.claude/skills/grilling/SKILL.md` - the FIRST step (section 2); the `grill-with-docs` variant (`/Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md`) records the ADR + glossary in the same change.
- `critical-thinking-logical-reasoning` - `/Users/diekgbbtt/.claude/skills/critical-thinking-logical-reasoning/SKILL.md` - the design spec is very high level and leaves many grey points and risks; use it to stress-test the responsibility model (grey point 3) and the deployment/freshness decisions (grey points 1 and 2) before they are ratified.
- The **litellm skills suite** at `/Users/diekgbbtt/.claude/skills/litellm/` - the proxy-ops skills for a live LiteLLM gateway: `add-model` (register a model and test-call it), `add-key`, `view-usage`, `update-model`, `delete-model`, `add-team`, `add-org`, plus the README - open the relevant one when operating or testing a real gateway instance; plus the SDK-side skill at `/Users/diekgbbtt/polymerhus/.claude/skills/litellm/SKILL.md` (embedding litellm in Python: `completion` / `acompletion`, `Router`, retry/fallback, the exception taxonomy) if the grilling decides embedded-module.
- `langgraph-docs` - `/Users/diekgbbtt/.claude/skills/langgraph-docs/SKILL.md` - correct wiring for the langgraph agents (the P2 StateGraph sites) when the client change reaches them.
- `langfuse` - `/Users/diekgbbtt/polymerhus/.claude/skills/langfuse/SKILL.md` - observability stays external but must keep working; verify traces still flow once routing moves behind the gateway.
- `implement` - `/Users/diekgbbtt/.claude/skills/implement/SKILL.md` - the overall TDD/typecheck/review-before-finishing workflow.
- `test-driven-development` - `/Users/diekgbbtt/.claude/skills/test-driven-development/SKILL.md` - red/green/refactor at the seams; keep the assertion catalogue out of the unit red/green loop.
- `verification-before-completion` - `/Users/diekgbbtt/.claude/skills/verification-before-completion/SKILL.md` - evidence before assertions; never claim done without the run output.
- `code-review` / `requesting-code-review` / `receiving-code-review` - `/Users/diekgbbtt/.claude/skills/...` - review the branch before finishing; respond with technical rigor, never performative agreement.
- `using-git-worktrees` - `/Users/diekgbbtt/.claude/skills/using-git-worktrees/SKILL.md` - the worktree discipline (section 5).
- `domain-modeling` / `codebase-design` - the living-documents rule (glossary + `domain-model.md` updated in the same change as any term sharpening); note again that llm-client is a helper module and gets no glossary entry.
- `prompt-engineering-patterns` - if any prompt content is crafted (capability-gap surfacing, sync-validation messages), treat it as prompt content with a system-vs-user split, not invented text.

## 5. Workflow discipline and termination conditions

- **Worktree first**: branch off **`dev`** (the running stack's source - never `main`, never the default branch) into a NEW git worktree; name the branch `feat/llm-api-gateway-100` (or per the issue-tracker convention).
- Report/plan first: the grilling outcome (section 2) ratified by the operator, THEN one bounded FR area at a time in the worktree. Do not attempt the whole subsystem in one pass.
- TDD at the seams: the unit tier drives the pure mechanics (the sync pipeline fetch -> join -> map -> validate -> diff -> push with both sources mocked, the Capability Record mapping, the unknown/staleness handling, the client-construction changes) - the unit tier touches no live model, no live gateway, no DB. The contract catalogue lives in integration; any live walkthrough (a real models.dev pull, a real gateway boot, a real provider call) lives in e2e.
- Run typechecking and single test files regularly; the full suite at the end. Unit: `.venv/bin/python -m pytest tests/ -q`. Live tiers IN-NETWORK: `docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm tests tests/integration -q`.
- **E2E + the running stack**: the running stack is built from `dev`, and the e2e tier runs in-network against it. When your e2e needs the stack, **merge your branch into `dev`** (the only merge you perform - never to `main`), rebuild, and run the e2e tier in-network per `loop-constraints.md` - do this **before** requesting the operator's green light. A bare unit-suite run from a worktree is NOT verification of the stack; that failure mode damaged the shared live stack once (#80).
- Living documents: land any glossary / `domain-model.md` / `CONTEXT.md` / design-spec corrections in the SAME change (do not defer) - the grilling that revises the design spec must land its corrections with the code that realises them.
- Maker/checker: you never mark your own work done and never self-approve. When green, run the `code-review` skill over your branch, fix findings, then dispatch a SEPARATE `loop-verifier` sub-agent with the assertion catalogue as the checklist.
- **Termination**: verifier APPROVAL, then the operator's green light. Only then push the branch and open ONE PR against `main` with `Closes #100` in the body. Merging to `main` is a human action - never merge to `main`. Max 3 fix attempts per area; escalate with full context in `STATE.md` High Priority after that.
- Never commit secrets - the gateway concentrates provider API keys; keys enter via env/operator, never into the repo, never into `.env` edits. Never weaken, skip, or disable a test to go green.
