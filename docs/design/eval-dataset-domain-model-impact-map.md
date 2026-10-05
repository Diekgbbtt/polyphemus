# Impact Map: Benchmark Dataset and Target Configuration Domain Model

*Companion to the spec published as issue #301.
This map grounds the delta on the current implementation: every component that changes, every component that becomes obsolete and must be removed, and every new component, keyed by the `eval/` module it lives in.*

## 0. Executed

The migration landed on this branch (spec #301).
The components are `orchestrator/dataset.py` (`BenchmarkDataset`, `Target key`), `orchestrator/target_config.py` (`TargetConfiguration`), `orchestrator/datasets/base.py` (the compose-derived helper, canonical tags, and the readiness plan), `orchestrator/readiness.py` (bounded, non-blocking readiness), and `orchestrator/docker.py` (the store -> pull -> build provisioning precedence).
The keyed artifacts are `eval/datasets/<id>.yaml`, `eval/targets/<dataset>/<target>.yaml`, `eval/platform/<dataset>/`, and `eval/data/<dataset>/<target>/`.
The obsolete `TargetDataset` value object, the per-target lifecycle `params`, and the `eval/kbs/<target>/` and `eval/mock/webmock/` paths are removed.

## 1. The delta in one line

Replace the embedded `TargetDataset` value object and the per-target lifecycle `params` with a keyed, first-class dataset layer (`eval/datasets/`, `eval/targets/<dataset>/`, `eval/platform/`, `eval/data/`) plus a per-dataset helper that derives and canonically tags each target's images; drive `next_target` through store -> pull -> build, a bounded readiness checker, and an opt-in `reclaimable` teardown.

## 2. New components

| Component | Role |
|---|---|
| `eval/orchestrator/dataset.py` | `BenchmarkDataset` dataclass, `parse_benchmark_dataset` / `load_benchmark_dataset`, loud validation, and `resolve` of the `<dataset>/<target>` key onto the bank and data-dependency paths |
| `eval/orchestrator/target_config.py` | `TargetConfiguration` dataclass, loader, and validation (compose, images, pull, checker, reclaimable, runner) |
| `eval/orchestrator/datasets/__init__.py` | `helper_for` returns a dataset's own helper module when one exists (`orchestrator/datasets/<id>.py` exposing `helper(dataset)`), else the generic helper |
| `eval/orchestrator/datasets/base.py` | The generic compose-derived helper: derive the target's image set from the services declaring both `build:` and `image:`, bind each to its canonical tag, and resolve the bounded readiness plan (the compose poll for a healthchecked application, the composite front + compose plan otherwise, the port probe for a compose-less target); a dataset may add its own module for named checkers |
| `eval/orchestrator/readiness.py` | The bounded, non-blocking readiness plan: one or more `compose`/`http` probes, every one of which must answer ready, with the front HTTP builder and the published-port fallback |
| `eval/datasets/webexploitbench.yaml`, `eval/datasets/mock.yaml` | The per-dataset YAMLs |
| `eval/targets/webexploitbench/<target>.yaml` (15), `eval/targets/mock/webmock.yaml` | The per-target YAMLs |
| `eval/platform/mock/webmock/` | The mock platform bank entry (moved from `eval/mock/webmock/`) |
| `eval/data/webexploitbench/<target>/operator_kb.md` (5), `eval/data/mock/webmock/` | The per-target data dependencies (moved from `eval/kbs/<target>/`) |

## 3. Modified components

| Component | Current role | Disposition | New role |
|---|---|---|---|
| `orchestrator/setup.py` | `EvalSetup` + embedded `TargetDataset` + `TargetConfig.params` addressing + `TargetRun.images` | **Reshape** | `EvalSetup` keeps instances, artifact store, work items, alignment; `dataset` becomes a key (plus optional inline shared attrs); `TargetRun` carries the `<dataset>/<target>` key and the per-trial runtime fields only |
| `orchestrator/targets/__init__.py` | `build_strategy(run, paths, registry=...)` | **Reshape** | `build_strategy(target_config, dataset, paths, helper, ...)` selects the runner from the target config |
| `orchestrator/targets/base.py` | `wait_ready` + `READY_UNREACHABLE` + `TargetContext` | **Reshape** | `TargetContext` carries the dataset, target config, and helper; `wait_ready` delegates to `readiness.py` |
| `orchestrator/targets/targetctl.py` | Checkout, build, up, down, ps, `provision` (always build + declared images), `reclaim` (prefix) | **Reshape** | Checkout moves to dataset provisioning; `web_dir`/`repo_url`/`platform` come from the dataset; `provision`/`reclaim` come from the helper and `reclaimable`; readiness from the checker |
| `orchestrator/targets/image.py` | Single `docker run` target | **Reshape** | Config sourced from `TargetConfiguration`; canonical-tag provision and `reclaimable` |
| `orchestrator/targets/compose.py` | Compose stack target | **Reshape** | Config sourced from `TargetConfiguration`; canonical-tag provision and `reclaimable` |
| `orchestrator/docker.py` | `provision_images` (build -> pull -> present), `provisioned_references`, `remove` | **Reshape** | Precedence becomes store -> pull -> build; add canonical tagging and canonical-tag reclaim |
| `orchestrator/chain.py` | `_teardown`/`_pull`/`_front`/`_health`; `TargetStep` | **Reshape** | `_pull` becomes helper-driven provision; reclaim honors `reclaimable` (teardown and failed up); `_health` uses the bounded checker; add a delegated `bind_artifacts` stage; `TargetStep` fields updated |
| `orchestrator/orchestrator.py` | `_strategy` reads `setup.dataset.registry` | **Reshape** | Resolves the dataset key and target config per target; threads the helper |
| `orchestrator/cli.py` | `_run_next_target`, `_find_target_run`, `_trial_config` read params/images | **Reshape** | Resolve the `<dataset>/<target>` key; `next-target` output reflects the new step fields |
| `eval/setups/webexploitbench-chain.yaml` | 15 targets with `target_config.params` + `images` | **Rewrite** | Targets as `<dataset>/<target>` + per-trial runtime fields; dataset by key |
| `eval/setups/first.yaml`, `eval/setups/mock-local.yaml` | Same shape | **Rewrite** | Same as above |
| `eval/setups/comfyui-hunting.yaml`, `eval/setups/comfyui-hunting-long.yaml` | Same shape | **Rewrite** | Same as above |
| `tests/eval/conftest.py` | `sample_setup_dict`, `RecordingRunner` | **Reshape** | `sample_setup_dict` uses the new schema; fixtures for dataset/target configs |

## 4. Obsolete components (must be removed)

| Component | Why it is obsolete |
|---|---|
| `setup.py::TargetDataset` | Superseded by the first-class `BenchmarkDataset` in `dataset.py` |
| `setup.py::LIFECYCLE_PARAMS` / `REQUIRED_LIFECYCLE_PARAMS` | Per-target `params` addressing is replaced by the target YAML; validation moves to `target_config.py` |
| `setup.py::TargetConfig.params` (and the `target`, `web_dir`, `repo_url`, `platform`, `ready_retries`, `ready_interval_s`, `image`, `port`, `internal_port`, `name`, `ready_path`, `compose_file`, `project`, `cwd` keys) | Owned by the dataset (repo, registry, platform root) and the target config (compose, images, pull, checker) |
| `setup.py::TargetConfig.dockerfile` / `dockerfile_context` | Moved into `TargetConfiguration` |
| `setup.py::TargetRun.images` | Derived from the compose by the helper; no longer authored |
| `docker.py::provision_images` build-first branch and `provisioned_references` | Replaced by the store -> pull -> build algorithm and canonical-tag reclaim |
| `targetctl.py` prefix reclaim (`pentestbench-<target>*`) | Replaced by canonical-tag reclaim |
| `targetctl.py` checkout (`_checkout_cmd`, `repo_url`, `web_dir`) | Moved to dataset provisioning; the dataset owns repo and platform root |
| `eval/kbs/<target>/` | Moved to `eval/data/<dataset>/<target>/` |
| `eval/mock/webmock/` | Moved to `eval/platform/mock/webmock/` |

## 5. Retained unchanged

`front.py`, `routing.py`, `instances.py`, `commands.py`, `files.py`, `ids.py`, the artifact-store/assessment/diagnosis/surfer/alignment modules, and the `EvalSetup` instance, work-item, and alignment surfaces.

## 6. Test impact

| Test | Disposition |
|---|---|
| `test_orchestrator_setup.py` | Rewrite for the new schema (dataset key, target key, no params/images) |
| `test_orchestrator_targets.py` | Rewrite for the config-driven strategies |
| `test_orchestrator_chain.py` | Update for the new provision/reclaim/health stages |
| `test_orchestrator_docker.py` | Update for the store -> pull -> build precedence and canonical tagging |
| `test_orchestrator_cli_next_target.py` | Update for the new step fields |
| `test_eval_first_setup.py`, `test_eval_overlay.py` | Update for the rewritten setups |
| New: `test_orchestrator_dataset.py`, `test_orchestrator_target_config.py`, `test_orchestrator_datasets_helper.py`, `test_orchestrator_readiness.py` | Added |

## 7. Migration order

1. Add `dataset.py`, `target_config.py`, `readiness.py`, and the dataset helpers, with unit tests, without touching the existing chain (both schemas coexist).
2. Author the dataset/target YAMLs and migrate the data dependencies and platform bank.
3. Reshape `docker.py`, the strategies, and `chain.py` onto the new configs.
4. Rewrite the setups and the CLI wiring; remove the obsolete components.
5. Align the documentation.
