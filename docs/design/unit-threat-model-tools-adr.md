# ADR: the threat modeller binds live-evidence tools (HTTP-history reads, exec probes, skills)

> **Vocabulary note (2026-10-25).** The artifact called a **loop** in this historical document is now a **threat** in the module and the current documentation.

## Status
Accepted (design phase, 2026-10-15).
Bound to the unit threat model grilling (`docs/design/unit-threat-model-workbench.md`, R1-5 and the Q10-Q17 answers).
Nothing here is built yet.

## Context
- The hunt-orchestrator is rewritten in place into the threat modeller (R1-2).
  The modeller builds a formal trust model per L1 unit and publishes a ranked set of research loops.
- The DataItem layer and the trust-boundary or trust-assumption L1 nodes were retired (2026-10-15).
  The trust model can therefore no longer be read off a pre-computed substrate: its material is the unit projection, the application surface, the recorded request traffic, and live interaction with the running target.
- The R1-5 amendment withdrew the fault-KB aid tool: fault hypothesisation is trust-model driven, never copied from an outside repository.
- The operator added a task on 2026-10-15: the workflow phases integrate effective probing actions that back or falsify the trust assumptions and the technical fault hypotheses, iterating until the assumption space is sufficiently explored.

## Decision
The threat modeller binds, and the workflow phases reference explicitly:

1. `hunts_store` for the per-gate threat-model writes, and `notes` for the model-level dedup and reflection, with the episodic-notes framing: notes are episodic memories of the execution, taken at the end of each reasoning phase that used tools, capturing the decision nodes and the rationales of the taken branches.
2. HTTP-history reads (search and get, never replay), so a claim can cite request records.
3. `exec` for live probes against the target, so an assumption can be evidenced or falsified instead of remaining induction.
4. The auth store and the per-project skill, coupled by replicating the recon-orchestrator pattern (the shared auth tool plus a concise verbatim in the system prompt on when and how to use it; `load_skill` for the skill).
5. The web-vulnerability skills suite surface (`skill_list` and `skill_load`), delivered by the parallel skills worktree and written here against its assumed names and data contracts as client components; the suite lands in the codepath that already gives it to the hunting agents, the threat modeller included.

Not bound: `graph_view` (the agent is fed the graph data for the unit under analysis), and the fault-KB aid tool (withdrawn).

Cost: no probe cap is scoped to the modeller alone.
The execution-wide cap is the token budget; the threat-modelling cap is the risk budget, whose functional requirement is a qualitative risk-scoring framework with scales (see the workbench, R3-2 and R2-5).

## Rationale
- Factual proof from the prototype run (`docs/experiments/unit-threat-model-prototype/`, 2026-10-15, White Jotter `Service:article-publishing`): the headline interface of the unit (the article-submission request, and the producer of its `rendered html` field) was unevidenced, so much of the fault set rested on induction that a single request record or probe could invalidate, and two chains (server-render sanitising bypass, SSTI) were dropped citing "not technically feasible from this perspective" although the criterion is that no evidence could be collected.
  With HTTP-history reads and live probes those questions are answered or falsified directly.
- The acceptance scenarios of the change (a product-submission unit ranking stored XSS high; a file-upload API unit ranking RCE high) depend on live interface facts (who renders, what is stored, what the upload path accepts); without the tools the ranking would be patterned induction, not evidence.
- Live interaction is the only remaining source for boundary material after the DataItem retirement; the HTTP-history store is the only source for traffic the modeller did not generate itself.

## Consequences
- Probing discipline: probes are non-destructive where feasible, prior state is restored after a mutating probe, and black-box discipline holds (HTTP surface only).
  Attack engineering (payload construction, exploitation depth) stays with the hunters.
- A model's claims carry request records and note references as evidence; the attack-surface knowledge of the modeller is bounded by what it can observe and probe.
- The modeller's raw capability is broad (a live shell against a running target); the containment is the phase prompts, the probe discipline, and the downstream review, not a sandbox.

## Lacks and risks (to map into the design spec)
- LACK-1 - the SSRF angle behind file and reference inputs.
  The prototype's cover-reference reading missed the server-side-fetch angle when the reference resolves server-side.
  The operator's framing: "unsafe upload" can be the final impact, `TOCTOU` a fault, and `SSRF` the technique that exploits the vulnerability yielded by the fault (an arbitrary URL resolving to an unsafe file), with further failure modes such as arbitrary requests to internal endpoints.
  This lack maps to a risk item later in the design spec: server-side fetch classes must be probed behind file, reference, import and URL-shaped inputs.
- LACK-2 - the drop criterion reads as a breadth filter when misapplied.
  A chain was dropped because the sharpening did not evidence a mechanism, although evidence was collectable (an HTTP-history record, a probe); the operator's criterion is: drop only when no evidence can be collected from the HTTP-history store or from target interaction.
  Breadth is a feature of this phase: the kept set maps research directions, and the hunters deepen them.

## References
- `docs/design/unit-threat-model-workbench.md` (R1-5, R2-9..R2-13, R3-2, R3-6; Q10-Q17 answers).
- `docs/design/unit-threat-model-workflow.md` (the five-state workflow contract).
- `docs/experiments/unit-threat-model-prototype/output/trace.md` (the prototype's underspecification list).
- `docs/experiments/unit-threat-model-prototype/trials/` (the two live-target trials added by this decision).
