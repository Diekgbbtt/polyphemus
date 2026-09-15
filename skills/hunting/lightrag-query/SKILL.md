---
name: lightrag-query
description: >-
  Compact operational guide to the `query_lightrag` / `kb_query` tool for the hunting agent: when to use it, how to build a `QuerySpecV1` by deriving the fields from the HuntConfig, and how to treat the validated `AnswerBundle` (methodology and provenance, never a vulnerability confirmation). The KB is a testing-methodology knowledge base - retrieve concepts from it, never use it to verify or adjudicate a bug.
metadata:
  version: '1.0'
---

# query_lightrag

## When to use it

Use `query_lightrag` when specific methodology knowledge is missing from your
reasoning - the target stack's mechanisms or shape, a payload family and its
vectors, a technique or methodology gap, or the shape of a verification
symptom. If the KB already covers the case, do not call the tool.

The tool is a methodology knowledge base: retrieve ontology concepts from it to
ground your technique, payload, and verification-symptom reasoning. It is not a
verifier - the returned bundle is methodology plus provenance references, never
a judgment that a target response constitutes a vulnerability. Decide that on
the target, on your own grounding.

## How to build `QuerySpecV1`

Derive the fields from the HuntConfig. Do not introduce retrieved text or
invented fields.

- `scenario_id`: identifies the current hunt or hypothesis.
- `attack_goal`: the attack objective declared by the HuntConfig.
- `concern`: the security concern under investigation.
- `technology_stack`: the technology stack of the testable unit.
- `target_refs`: references to the target (components/surfaces).
- `input_vectors`: presumed input vectors, from `supposed_payload_vectors`.
- `known_facts`: known and verified facts (e.g. L0).
- `acceptable_technique_families`: technique families acceptable for the methodology.
- `unsupported_claims`: claims the tool must not treat as confirmed.
- `evidence`: L0/L1 references with summaries, the provenance constraint.
- `expected_no_hypothesis`: true when the absence of a hypothesis is expected.

## Response

The tool returns a validated `AnswerBundle`. Use it as methodology and as a
provenance constraint, never as a vulnerability confirmation.

## Failure

If the tool fails, proceed with the grounding available and report the gap in
your feedback.