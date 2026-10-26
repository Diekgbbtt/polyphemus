# 438 - Project scope attribute and REST surface

**What to build:** Add `Project.threat_model_scope` as a free-text posture statement. Persist it in `settings.hunting.threat_model_scope`. Expose it through the existing hunting config REST pair. Read it at run start and append it verbatim to the threat-modeller prompt. Apply it at the assumptions layer.

**Blocked by:** 436.

**Status:** ready-for-agent

**Seams:** `project_management/api.py`, `project_management/repository.py`, `app/clients/pg.py`, `attack/hunting/runtime.py`, `attack/hunting/threat_modeller.py`, `attack/hunting/prompts/threat-modeller.md`

## Context

The spec is `docs/design/impact-assessment-system-spec.md` section 6.

The scope is a project assumption, not a hidden prompt rule. The target is assumed to have a posture. A threat whose only enabling condition is the absence of that posture is not modelled. The exclusion happens at the assumptions layer: the excluded trust boundary is never modelled, so the excluded assumption and fault are never made. The model does not record a per-row exclusion.

The REST surface is:

```http
GET /projects/{project_id}/hunting/config
PUT /projects/{project_id}/hunting/config
{"threat_model_scope": "The target is assumed to have ..."}
```

`HuntingConfigUpdate` gains `threat_model_scope: str | None` with `extra="forbid"`. The PUT is a partial deep merge. A PUT that sets only the scope preserves `pipeline_sync` and `risk_threshold`.

The run reads the string once at start. It appends the string verbatim to the modeller prompt under `## Project scope (verbatim)`. It does not duplicate the string in the run record. An empty string appends nothing.

The assumptions phase receives the scope as a binding constraint: do not model a boundary the scope excludes; do not make the excluded assumption or fault.

## Acceptance criteria

- [ ] The project domain model exposes `threat_model_scope`.
- [ ] The hunting settings store and the REST pair round-trip the string.
- [ ] A partial PUT preserves the sibling hunting settings.
- [ ] The run reads the string and appends it verbatim to the prompt.
- [ ] The run record does not duplicate the string.
- [ ] The assumptions phase is bound by the scope.
- [ ] An empty string appends nothing.
- [ ] The prompt does not paraphrase the string.

## Verification

- `tests/project_management/test_hunting_config_api.py`
- `tests/project_management/test_settings_api.py`
- `tests/attack/test_threat_modeller_prompt.py`
- `tests/attack/test_hunting_runtime.py`
