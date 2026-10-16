# tools/bootstrap - the external bootstrap module

The canonical home of the external bootstrapping workflow: it builds a target's pre-eval data dependencies (AuthContext, authn skill, L1 surface) and places them into the platform or the eval harness.

Recovered 2026-10-16 from the uncommitted `eval-data-dependencies` worktree copy (where the sources lived under `eval/`), so they survive independently of that worktree and become parametrizable.

## Contents

- `DATA-DEPENDENCIES.md` - the operator-facing contract: layout, the two L1 renderings, the phase order (authn first, L1 second), the batch critic.
- `prompts/data-dep-authn.md` - phase 1 creator prompt (the AuthContext and the authn skill).
- `prompts/data-dep-l1.md` - phase 2 creator prompt (the L1 surface and the operator KB).
- `prompts/data-dep-critic.md` - the batch critic prompt.
- `validate_data_dependencies.py` - the shape validator for the three work items.

## Usage

```
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py <target_dir> [<target_dir> ...]
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --all <kbs_root>
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --auth-only --staging <staging_root> <project_id>
```

The validator parses the KB through the real platform scaffold (`src/polymerhus/analysis/scaffold.py`), so its checks can never drift from the parser the platform runs.

## Planned (W2, `feat/external-bootstrap`)

Environment adapters (attach to a reachable target, local Docker, remote eval server with teardown), orchestration assets for opencode as the agent harness, the assessment framework (`assessment/`, added in W1), and the execution workflow model.
