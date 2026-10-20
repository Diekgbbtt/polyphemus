---
name: lightrag-query
description: >-
  Compact operational guide to the `query_lightrag` / `kb_query` tool for the hunting agent: when to use it, how to build a `QuerySpecV1` by deriving the fields from the HuntConfig, and how to treat the validated `AnswerBundle` (methodology and provenance, never a vulnerability confirmation). The KB is a testing-methodology knowledge base - retrieve concepts from it,   never use it to verify or adjudicate a bug.
metadata:
  version: '1.0'
---

# query_lightrag

## When to use it

Use `query_lightrag` when methodology knowledge missing from your reasoning
blocks the turn - the target stack's mechanisms or shape, a payload family and
its vectors, a technique or methodology gap, or the shape of a verification
symptom. Call once per gap; where the methodology you need is already in hand,
skip the call.

This is a methodology knowledge base. Retrieve ontology concepts from it to
ground technique, payload, and verification-symptom reasoning. The returned
bundle is methodology plus provenance references - decide on the target, on
your own grounding, whether a response constitutes a vulnerability. It never
confirms one.

## How to build `QuerySpecV1`

Derive every field from the HuntConfig. Pass ONLY the fields below - the tool
binds the real QuerySpecV1, and a field outside it is not part of the query
contract. In particular, the config's vulnerability class and fault class are
not top-level query fields: fold them into the concern and the attack goal. No
retrieved text, no invented fields.

- `scenario_id`: identifies the current hunt or hypothesis.
- `attack_goal`: the attack objective, from the config's research direction.
- `concern`: the security concern under investigation - the config's
  vulnerability class plus its rationale.
- `technology_stack`: the technology stack of the testable unit.
- `target_refs`: references to the target (components/surfaces).
- `input_vectors`: presumed input vectors, read from the target surface.
- `known_facts`: known and verified facts (e.g. L0 evidence).
- `acceptable_technique_families`: technique families acceptable for the methodology.
- `unsupported_claims`: claims the tool must not treat as confirmed.
- `evidence`: L0/L1 references with summaries, the provenance constraint.
- `expected_no_hypothesis`: true when the absence of a hypothesis is expected;
  leave it out normally (it defaults to false).
- `retrieval`: optional retrieval parameters; omit to use the defaults.

## Response

The tool returns a validated `AnswerBundle`. Treat it as methodology and
provenance constraint.

## Failure

If the tool fails, proceed on the grounding you hold and report the gap in
your feedback.