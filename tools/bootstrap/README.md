# tools/bootstrap - the external bootstrap module

The canonical home of the external bootstrapping workflow: it builds a target's pre-eval data dependencies (AuthContext, authn skill, L1 surface) and places them into the platform or the eval harness.

Recovered 2026-10-16 from the uncommitted `eval-data-dependencies` worktree copy (where the sources lived under `eval/`), so they survive independently of that worktree and become parametrizable.

## Contents

- `DATA-DEPENDENCIES.md` - the operator-facing contract: layout, the two L1 renderings, the phase order (authn first, L1 second).
- `prompts/data-dep-authn.md` - phase 1 creator prompt (the AuthContext and the authn skill).
- `prompts/data-dep-l1.md` - phase 2 creator prompt (the L1 surface and the operator KB).
- `prompts/data-dep-critic.md` - the batch critic prompt (mined-run reference; not part of the mechanised loop).
- `validate_data_dependencies.py` - the shape validator for the three work items.
- `assessment/` - the graded measurement framework (added in W1): criteria, rubric, LLM judge, baseline.
- `run_external_bootstrap.py` - the mechanised runner (added in W2, spec: Diekgbbtt/polyphemus#358).
- `runner/` - the runner module: CLI, config, harness adapter, environment drivers, wrappers, gates, state, orchestrator.
- `run.example.yaml` - a working eval-server regeneration config.

## Usage

```
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py <target_dir> [<target_dir> ...]
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --all <kbs_root>
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --auth-only --staging <staging_root> <project_id>
```

The validator parses the KB through the real platform scaffold (`src/polymerhus/analysis/scaffold.py`), so its checks can never drift from the parser the platform runs.

## The runner

One command regenerates a set of targets' data dependencies end to end:

```
python3 tools/bootstrap/run_external_bootstrap.py plan   --config tools/bootstrap/run.example.yaml
python3 tools/bootstrap/run_external_bootstrap.py run    --config tools/bootstrap/run.example.yaml
python3 tools/bootstrap/run_external_bootstrap.py status --rundir .bootstrap-runs/<run_id>
python3 tools/bootstrap/run_external_bootstrap.py resume --rundir .bootstrap-runs/<run_id>
```

Per target, serial: bring the target up and wait for readiness from accurate signals, move any pre-existing KB and staging bundle for that target aside (the run regenerates from scratch), drive one opencode worker session through the authn phase and then the authenticated L1 crawl, gate every phase with the validator (bounded verbatim repair on a red gate), verify teardown by observation, and persist a resumable run state. Design and decisions: `docs/design/external-bootstrap-architecture.md`; environment facts: `docs/design/external-bootstrap-dependency-audit.md`.

Quality instruments: the two validator gates above (a phase never advances on red) and the assessment framework (`assessment/assess.py`) after the run.
