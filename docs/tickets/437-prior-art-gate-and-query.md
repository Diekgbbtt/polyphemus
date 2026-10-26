# 437 - Prior-art gate and regex query contract

**What to build:** Add the `PRIOR_ART` gate and the `hunts_store` `cmd=query` surface. The query is a regex field filter over one record type. It reads the produced and consumed models, excludes the bound unit unless a filter names it, and returns summaries with the model state and the matched path/value pairs.

**Blocked by:** 436.

**Status:** ready-for-agent

**Seams:** `attack/hunting/threat_model.py`, `attack/hunting/threat_model_store.py`, `attack/hunting/threat_modeller_tools.py`, `attack/hunting/threat_modeller.py`, `attack/hunting/prompts/threat-modeller.md`

## Context

The spec is `docs/design/impact-assessment-system-spec.md` section 7. The prototype is `docs/design/impact-assessment-system-prototype.md`.

The modeller must query the store before the trust model. The query is the one grounding tool for previous threats, vulnerabilities, and precursors. The query is project-scoped. It searches the consumed and produced models. It returns summaries, never a full model. The `read` command remains for the full model.

The query contract:

```yaml
cmd: query
kind: precursor
filters:
  - path: capability
    regex: "session|credential"
    flags: i
limit: 20
```

- `kind` is required: `threat`, `vulnerability`, `precursor`, `assumption`, `impact`.
- `filters` is a non-empty list. The filters are AND. Each filter matches when `re.search(regex, value, flags)` matches a value at the dotted path. `*` iterates a list. A missing path is no match. An unknown path, an invalid regex, or an empty filter list is a coded teaching rejection.
- The path catalog covers every field of the threat file and the model records. The `threat` view merges the threat file with its impact row and precursors.
- The query excludes the bound unit unless a filter path is `unit_id`.
- The result carries the record's `state`, the summary, the evidence refs, and the `matched` path/value pairs.

The `prior_art` section records the queries and the reused records. The completion check requires at least one query for `threat`, one for `vulnerability`, and one for `precursor`, each with at least one filter, and a non-empty `notes`.

The prompt adds a `PRIOR_ART` phase after the technical sharpening and before the trust model. It requires the three queries and a `prior_art` note.

## Acceptance criteria

- [ ] `PRIOR_ART` is a tracked gate with the `prior_art` section.
- [ ] `hunts_store` accepts `cmd=query` with the typed `kind`, `filters`, and `limit`.
- [ ] The query applies AND across filters and `re.search` per value.
- [ ] The query rejects an empty filter list, an invalid regex, and an unknown path with a coded teaching rejection.
- [ ] The query excludes the bound unit unless a `unit_id` filter is present.
- [ ] The query reads produced and consumed models and returns the model `state`.
- [ ] The result includes the `matched` path/value pairs.
- [ ] The completion check requires the three prior-art query kinds and the notes.
- [ ] The prompt states the prior-art phase and the query contract.

## Verification

- `tests/attack/test_threat_model_query.py`
- `tests/attack/test_threat_model_store.py`
- `tests/attack/test_threat_modeller.py`
- `tests/attack/test_threat_modeller_prompt.py`
