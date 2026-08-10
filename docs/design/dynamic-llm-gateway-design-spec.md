# Dynamic Capability-Aware LLM API Gateway — High-Level Design Spec

**Status:** Draft / architecture-level
**Audience:** Platform/infra engineers building or operating the gateway layer underneath one or more agent harnesses
**Explicitly out of scope:** any specific agent harness's internals (planning, memory, tool-execution loop). This document treats "the harness" as an unspecified consumer of a standard API.

---

## 1. Problem Statement

Agent harnesses need accurate, per-model × per-provider metadata to make correct runtime decisions:

- **Context window** (max input / max output tokens) — for trimming, chunking, routing
- **Cost** — for budgeting, routing, spend tracking
- **Capabilities** — tool/function calling, structured output, reasoning/effort tiers, modalities (vision, audio, video, PDF), prompt caching support

Two structural facts make this hard, and drive every design decision below:

1. **No provider exposes this data via a live API.** Model-listing endpoints (`/v1/models` and equivalents) typically return an ID and little else — not context length, not capability flags. This is true even for aggregator/relay providers (e.g. curated multi-model gateways) whose own client tooling turns out to read a *separate* static registry rather than introspecting the backend model at request time.
2. **Existing LLM gateways solve this with static, manually-curated data**, scoped to the providers their maintainers have explicitly added. Any provider reached through a generic OpenAI-compatible passthrough (self-hosted models, curated relay gateways, niche regional providers) has **no entry**, and the gateway's own capability-check functions either return nothing or default to an unverified guess.

**Conclusion:** there is no dynamic capability handshake to build against, anywhere in this ecosystem, today. The system must be designed around **static, versioned, source-attributed metadata**, kept fresh by an explicit sync process — not around runtime discovery.

---

## 2. Design Principles

| Principle | Implication |
|---|---|
| **Harness-agnostic** | Harnesses talk only to the gateway's standard (OpenAI-compatible) surface. No harness integrates with the registry or the sync component directly. |
| **Gateway-implementation-agnostic where feasible** | The data model and sync logic are defined independently of any one gateway's schema. A gateway-specific *mapping layer* is the only place product-specific field names live. |
| **Separation of "what exists" from "what it can do"** | A provider's own live model list is authoritative for *existence*. A separate registry is authoritative for *capability*. These are never conflated into one call. |
| **Conservative on unknowns** | A model with no registry entry is `unknown`, not `assumed true` and not `assumed false`. Silent optimistic defaults are the specific failure mode this system exists to eliminate. |
| **Idempotent, diffable sync** | Every sync run recomputes desired state and pushes only deltas. Re-running is always safe. |
| **Full provenance** | Every field the gateway holds must be traceable to (source registry, source record, timestamp of last sync). |
| **No single vendor as a hard dependency** | Both the registry and the gateway are swappable behind their respective boundaries. Given how fast this vendor landscape consolidates, treat every named product as a reference implementation, not a foundation. |

---

## 3. System Components

```
 ┌────────────────────┐      ┌────────────────────┐
 │ Provider Existence  │      │  Capability/Cost/   │
 │ Source(s)           │      │  Context Registry    │
 │ (e.g. a relay's own │      │ (e.g. models.dev-    │
 │ /v1/models)         │      │  style JSON schema)  │
 └──────────┬──────────┘      └──────────┬──────────┘
            │  "what exists"              │ "what it can do"
            └─────────────┬───────────────┘
                           ▼
              ┌─────────────────────────┐
              │   Capability Sync       │
              │   Component (glue)      │
              │  fetch → join → map →   │
              │  validate → diff → push │
              └────────────┬────────────┘
                           │ pushes normalized
                           │ Capability Records
                           ▼
              ┌─────────────────────────┐
              │   Gateway (runtime)     │
              │  format translation,    │
              │  routing/fallback,      │
              │  cost + context guard,  │
              │  capability gating,     │
              │  MCP / A2A, guardrails  │
              └────────────┬────────────┘
                           │ standard OpenAI-compatible
                           │ (+ optional capability query) surface
                           ▼
              ┌─────────────────────────┐
              │   Harness(es)           │
              │  (unspecified — any     │
              │  consumer of the above  │
              │  surface)               │
              └─────────────────────────┘
```

### 3.1 Provider Existence Source
Read-only. One per upstream provider/relay that isn't already a first-class, natively-integrated provider in the gateway. Returns: which model IDs are currently servable. Nothing else is trusted from this source.

### 3.2 Capability/Cost/Context Registry
Read-only, external, versioned. Defines the canonical schema for what can be known about a model: context/output limits, per-token costs (including cache read/write), and a **closed set** of capability fields (tool calling, structured output, reasoning + its effort/budget shape, modalities in/out, temperature support, open-weights flag). Community-maintained registries in this space commonly support **inheritance** (a provider-specific record overriding/omitting fields from a canonical base record) — this is the mechanism that explains why the same underlying model can carry different capability flags depending on which relay is serving it, and the sync component must respect that per-provider override rather than assuming one global truth per model.

### 3.3 Capability Sync Component (the piece being newly designed)
The only component that talks to both the existence source and the registry. Responsibilities:

1. **Fetch** both sources. The running cadence is **bootstrap-only** (at every container bootstrap); there is no out-of-band scheduler — see §6.
2. **Join** by model ID, per provider namespace.
3. **Map** registry fields into the gateway's native metadata schema (unit conversions included — e.g. per-million-token pricing into per-token pricing). This is the **only place product-specific field names live**; the mapping layer is also where per-provider registry inheritance (a provider-specific record overriding/omitting fields from a canonical base record) is **resolved before push**, so one global truth per (provider × model) lands in the gateway and the reader never re-resolves inheritance at read time.
4. **Validate** — sanity-check the fetched registry data before trusting it, with **two distinct failure modes and two distinct exit codes**: (a) **source failure** (fetch/parse/refusal) — skip the push, keep the gateway's last-known-good records, exit soft-non-zero; the entrypoint logs and starts the agent anyway (fail toward staleness, item 9). (b) **implausible collapse** (desired-set count < 50% of the last-known-good snapshot, or zero records) — abort the entire push, exit hard-non-zero; the entrypoint **halts before starting the agent** (cold stop — fail-loud, never run on a freshly-collapsed registry).
5. **Diff** against the gateway's current declared state (`GET /model/info` gives the registered set).
6. **Push** only the delta, via the gateway's live management API (add/update/remove model records without a restart). An update pushes the **full** `model_info` (all fields authored explicitly), never a partial merge — a stale record can never partially shadow a fresh one.
7. **Record provenance** — every pushed field tagged with (source registry, source record, sync timestamp) under keys the client reader can gate trust on.
8. **Handle absence explicitly** — a model live on the existence source but missing from the registry is still registered for routing (existence is real) but pushed with **no capability fields** and a provenance tag marking it unknown; the client reader then resolves it as unknown. Gap notification is **runtime logs only** for now (the cold-stop in item 4 is the strong signal for the collapse case; an unknown-model gap is per-model data quality, not a sync failure). A recorded forward step adds configuration checks in `settings.recon` for curated overrides.
9. **Fail toward staleness, not toward guessing** — if the registry is unreachable, keep the last-known-good Capability Records (with an increasing staleness marker) rather than falling back to optimistic defaults.

The gateway merges its **own** bundled cost-map defaults into `model_info` for models it recognises; the client reader trusts a record's capability fields **only when it carries our provenance tag** — a record without the tag, or a field absent from a tagged record, is `unknown` (treated as `false` for gating, §5), and `unknown` is never encoded as a value, it is the **absence of an authored field**.

This component is a **small, stateless CLI** (`python -m polymerhus.app.llm.sync`) invoked once at container bootstrap — not a long-running scheduled service, not a cron job. Its job is reconciliation at bootstrap, not request-path involvement.

### 3.4 Gateway (runtime layer)
Owns everything request-path: protocol translation, routing/load-balancing/fallback, cost and context-window enforcement, capability gating, tool/MCP federation, agent-to-agent federation, guardrails, spend tracking, and **prompt caching** — configured as `cache_control_injection_points` (auto-injection of `cache_control` annotations on the stable system-prompt breakpoint) plus passthrough of client-sent `cache_control` / `prompt_cache_key`. The KV cache itself lives only at the provider; the gateway influences hit rate via annotations and routing hints, never by doing its own KV caching. The `LITELLM_CACHE_TYPE` response cache (identical-request caching) is explicitly **not enabled** — it risks stale tool results and corrupted observability in a stateful agent loop, and litellm's own docs warn against it for multi-turn agentic traffic. It **consumes** Capability Records; it does not originate them. This is the load-bearing separation of concerns in the whole design — swapping the gateway product later should only require rewriting the mapping step in §3.3, not any of the runtime logic.

### 3.5 Harness Contract Layer
The only surface any harness ever touches: the gateway's standard request API, plus (optionally) a read endpoint for the enriched per-model metadata if a harness wants to make its own capability-aware decisions (e.g., choosing whether to attempt tool calling before sending a request). Harnesses are never coupled to the registry schema, the sync cadence, or the specific upstream relay's quirks — that is precisely what makes the system harness-agnostic.

---

## 4. Canonical Data Model (Capability Record)

Defined independently of any one gateway's field names, so the mapping layer in §3.3 is the only place a gateway swap touches:

| Field | Type | Notes |
|---|---|---|
| `model_id` | string | joined key across existence source + registry |
| `provider_namespace` | string | which relay/provider this record applies to |
| `context_limit` | int | max input tokens |
| `output_limit` | int | max output tokens |
| `cost_input` / `cost_output` | decimal (per-token) | converted from registry's native unit |
| `cost_cache_read` / `cost_cache_write` | decimal (per-token) | omitted if provider doesn't support caching |
| `supports_tool_calling` | bool \| unknown | |
| `supports_structured_output` | bool \| unknown | |
| `supports_reasoning` | bool \| unknown | plus effort-tier shape if applicable |
| `modalities_in` / `modalities_out` | set | text / image / audio / video / pdf |
| `open_weights` | bool | |
| `source` | string | registry + record identity |
| `synced_at` | timestamp | |
| `staleness` | enum: fresh / stale / unknown | |

---

## 5. Runtime Decision Policy for Capability Gaps

A model with `supports_tool_calling = false` or `unknown` is a first-class, expected state, not an error condition. The system must make an explicit choice per such case rather than let it fall through to an unverified default:

| State | Policy |
|---|---|
| `true` | Send native request as-is. |
| `false` | Either (a) refuse the capability-requiring request with a clear error, or (b) explicitly opt into a documented emulation path (e.g. prompt-injected tool definitions + response parsing) — but only as a deliberate, observable choice, never silent, since emulation of this kind is known to be unreliable in production. |
| `unknown` | Treat as `false` by default (conservative), and surface the gap so it can be closed by adding the model to the registry or setting a manual override. |

This policy belongs conceptually at the boundary between the gateway and the harness — whichever side actually owns the decision in a given deployment, it must be made explicitly and logged, not inferred silently mid-request.

---

## 6. Operational Concerns

- **Sync cadence:** **bootstrap-only** — the sync runs once at every container bootstrap (after the gateway health-check, before the agent ASGI starts); there is no out-of-band scheduler. The spec's earlier "on the order of tens of minutes" is superseded by this running cadence (a model change is a deploy-class event in this system, so restart-on-deploy is the natural refresh). Stale records between restarts surface via the staleness field and the conservative-unknown policy (§5).
- **Environments:** each deployment environment (dev/staging/prod) syncs independently, against its own gateway instance, so a bad registry pull can't silently propagate straight to production.
- **Credentials:** the sync component needs elevated (admin-level) access to the gateway's management API; scope and rotate that credential like any other privileged service account.
- **Observability:** every sync run should emit a diff summary (added/updated/removed/unknown-flagged models) and alert on repeated fetch failures or validation rejections.
- **Versioning:** the mapping logic in §3.3 is itself an artifact that changes over time as the registry's schema evolves — version it and keep it under review, since a silent mapping bug is indistinguishable from a data problem otherwise.

---

## 7. Extensibility

- **Swapping the registry:** only §3.3's fetch + mapping steps change; the Capability Record schema (§4) and everything downstream is unaffected.
- **Swapping the gateway:** only §3.3's push step and mapping-to-native-fields change; the registry, the Capability Record schema, and the harness contract are unaffected.
- **Onboarding a new harness:** requires nothing from this system — the harness contract (§3.5) is already generic. This is the practical test of whether "harness-agnostic" actually held: adding a harness should be a zero-change event for everything in this document.

---

## 8. Known Limitations (carried forward honestly, not resolved by this design)

- The registry itself remains community-curated, not provider-certified — this system reduces *staleness and blind guessing*, it does not eliminate *inaccuracy at the source*.
- There is currently no dynamic capability-discovery mechanism anywhere in this ecosystem to fall back on if the registry approach fails; the whole design accepts that constraint rather than working around it.
- Emulation of missing capabilities (§5) is inherently best-effort; this document specifies that the choice must be explicit, not that the emulation itself is reliable.
- Any named product referenced as a "reference implementation" for the registry or the gateway role should be treated as replaceable — this vendor category has shown a high rate of acquisition and shutdown, which is precisely why §3–§4 insist on the abstraction boundary in the first place.
