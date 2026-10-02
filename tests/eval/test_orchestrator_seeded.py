"""The seeded-project hunting entry (#277).

An e2e trial may hunt directly against a pre-recon'd project whose L0/L1 already
exists (queried from a local volume and transferred onto the eval instance),
instead of re-running recon/analysis. The trial then skips project creation,
settings, the `AuthContext` mutation, and the L1 scaffold; the hunting-entry
predicate asserts the seeded project and its L1 and the trial proceeds at
hunting exactly as the normal path (cap, pre-mined placement).

Every effect is injected: the recording `ApiRunner` fails on any unlisted call,
so a seeded test proves the skip by the calls that are *not* made, not only by
the ones that are.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator import cli, predicates, setup as setup_mod, trial
from orchestrator.files import FileStore, hunt_configs_dir
from orchestrator.setup import PreloadedArtifacts

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SETUP = REPO_ROOT / "eval" / "setups" / "comfyui-hunting.yaml"

SEED = "12da8565-a266-4610-9968-9ebfb86dd563"
GRAPH_L1 = {"nodes": [{"type": "L1Service"}], "links": []}


class RecordingApi:
    """An exact-route recording `ApiRunner`.

    A route key is the exact `METHOD path`; an unlisted call is a hard failure,
    so "the trial made no call that creates or mutates the project" is proven by
    the fake refusing such a call outright, plus the explicit forbidden-set
    check below.
    """

    def __init__(self, routes: dict | None = None):
        self.routes = routes or {}
        self.calls: list = []

    def __call__(self, call):
        self.calls.append(call)
        key = f"{call.method} {call.path}"
        if key not in self.routes:
            raise AssertionError(f"unexpected API call {key}")
        return self.routes[key]

    @property
    def methods_paths(self) -> list[tuple[str, str]]:
        return [(c.method, c.path) for c in self.calls]


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class SeqListFileStore(FileStore):
    """A `FileStore` whose consumed-hunt-config listing pops a scripted sequence.

    The trial-scoped poll reads the consumed listing once per iteration; every
    other directory (and `count_files`, the entry gate's pre-mined presence
    check) reads the real tree. See `test_orchestrator_trial.py` for the same
    seam.
    """

    def __init__(self, listings, consumed_dir):
        super().__init__()
        self._listings = [list(names) for names in listings]
        self._consumed = Path(consumed_dir)

    def list_files(self, directory):
        if Path(directory) != self._consumed:
            return FileStore.list_files(self, directory)
        if self._listings:
            return [Path(name) for name in self._listings.pop(0)]
        return []

    def count_files(self, directory) -> int:
        return len(FileStore.list_files(self, directory))


def _config(tmp_path, **overrides) -> trial.TrialConfig:
    base = dict(
        instance_id="eval-server-1",
        target_id="comfyui-1",
        start_phase="hunting",
        existing_project_id=SEED,
        data_root=tmp_path / "data",
        runs_root=tmp_path / "runs",
        budget_s=100.0,
        poll_s=10.0,
    )
    base.update(overrides)
    return trial.TrialConfig(**base)


def _trial(tmp_path, api_runner, *, files=None, clock=None, **overrides) -> trial.Trial:
    clock = clock or FakeClock()
    return trial.Trial(
        _config(tmp_path, **overrides),
        api_runner=api_runner,
        files=files if files is not None else FileStore(),
        clock=clock,
        sleep=clock.sleep,
    )


def _seeded_routes(pid: str = SEED, *, graph=None, hunting_status: str = "complete") -> dict:
    return {
        "GET /projects": {"projects": [{"project_id": pid}]},
        f"GET /projects/{pid}/graph": graph or GRAPH_L1,
        f"POST /projects/{pid}/hunting": {"hunting_run_id": "h1"},
        f"GET /projects/{pid}/hunting/h1": {"status": hunting_status},
    }


def _forbidden_project_calls(pid: str) -> set[tuple[str, str]]:
    """The API calls that create or mutate the project; a seeded trial makes none."""
    return {
        ("POST", "/projects"),
        ("PUT", f"/projects/{pid}/settings"),
        ("PUT", f"/projects/{pid}/auth"),
        ("POST", f"/projects/{pid}/bootstrap"),
    }


# --- the seeded run: skip creation/scaffold, assert, enter hunting ------------


def test_seeded_trial_enters_hunting_without_creating_or_mutating(tmp_path) -> None:
    api_runner = RecordingApi(_seeded_routes())

    record = _trial(tmp_path, api_runner).run()

    assert record.terminal == "complete"
    assert record.project_id == SEED
    assert record.seeded is True
    assert [p.phase for p in record.phases] == ["hunting"]
    assert record.phases[0].entered is True
    assert record.phases[0].run_id == "h1"
    # No create/mutate call was made (the fake would have raised) and no recon
    # or analysis was launched.
    assert set(api_runner.methods_paths).isdisjoint(_forbidden_project_calls(SEED))
    assert not any("/recon" in c.path for c in api_runner.calls)
    assert not any("/analysis" in c.path for c in api_runner.calls)
    # The hunting entry asserted the seeded project through a read of the
    # listing and the graph.
    assert ("GET", "/projects") in api_runner.methods_paths
    assert ("GET", f"/projects/{SEED}/graph") in api_runner.methods_paths


def test_seeded_trial_does_not_bring_up_the_instance(tmp_path) -> None:
    calls: list[str] = []

    def bring_up() -> None:
        calls.append("bring_up")
        raise AssertionError("a seeded trial must not bring up the instance")

    record = _trial(tmp_path, RecordingApi(_seeded_routes())).run(bring_up=bring_up)

    assert record.terminal == "complete"
    assert calls == []


def test_seeded_trial_records_the_reused_project_and_seeded_marker(tmp_path) -> None:
    record = _trial(tmp_path, RecordingApi(_seeded_routes())).run()

    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())

    assert written["project_id"] == SEED
    assert written["seeded"] is True
    assert written["start_phase"] == "hunting"


def test_seeded_trial_blocks_on_a_missing_project(tmp_path) -> None:
    # No graph/hunting routes: if the trial fell back to creating a project or
    # reading the graph, the fake would raise and the test would fail loudly.
    api_runner = RecordingApi({"GET /projects": {"projects": [{"project_id": "other"}]}})

    record = _trial(tmp_path, api_runner).run()

    assert record.terminal == "blocked"
    assert record.seeded is True
    assert [p.phase for p in record.phases] == ["hunting"]
    assert record.phases[0].entered is False
    assert any(
        f"seeded project not found: {SEED}" in block
        for block in record.phases[0].blocks
    )
    # No silent fallback: no create, no mutation, and no graph read for a
    # missing project.
    assert set(api_runner.methods_paths).isdisjoint(_forbidden_project_calls(SEED))
    assert not any(c.path.endswith("/graph") for c in api_runner.calls)
    assert not any(c.path.endswith("/hunting") for c in api_runner.calls)


def test_seeded_trial_blocks_on_a_missing_l1(tmp_path) -> None:
    api_runner = RecordingApi(_seeded_routes(graph={"nodes": [], "links": []}))

    record = _trial(tmp_path, api_runner).run()

    assert record.terminal == "blocked"
    assert record.phases[0].entered is False
    assert any("L1" in block and "0 services" in block for block in record.phases[0].blocks)
    # The project was found; hunting never launched.
    assert ("GET", "/projects") in api_runner.methods_paths
    assert not any(c.path.endswith("/hunting") for c in api_runner.calls)
    assert set(api_runner.methods_paths).isdisjoint(_forbidden_project_calls(SEED))


def test_seeded_trial_runs_the_cap_and_places_premined_artifacts(tmp_path) -> None:
    source = tmp_path / "premined"
    source.mkdir()
    (source / "unit_CWE-1_sqli.yaml").write_text("id: a\n")

    routes = _seeded_routes(hunting_status="running")
    routes[f"POST /projects/{SEED}/hunting/h1/stop"] = {"stopping": True}
    api_runner = RecordingApi(routes)
    # The poll's consumed listing: the empty baseline snapshot, then the
    # pre-mined config appears in consumed (the pipeline's lazy read), then the
    # re-read after the stop. The pre-mined presence check reads the real tree.
    files = SeqListFileStore(
        [[], ["unit_CWE-1_sqli.yaml"], ["unit_CWE-1_sqli.yaml"]],
        hunt_configs_dir(tmp_path / "data", SEED, "consumed"),
    )

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        preloaded_hunting_artifacts=PreloadedArtifacts(configs=str(source)),
        hunt_config_budget=1,
    ).run()

    assert record.terminal == "stopped"
    assert record.cap == 1
    assert record.stop_count == 1
    assert record.final_count == 1
    assert record.overshoot == 0
    produced = hunt_configs_dir(tmp_path / "data", SEED, "produced")
    assert [p.name for p in files.list_files(produced)] == ["unit_CWE-1_sqli.yaml"]
    assert set(api_runner.methods_paths).isdisjoint(_forbidden_project_calls(SEED))


# --- dry-run: the plan shows the skip and the hunting entry -------------------


def test_seeded_plan_shows_the_skip_and_the_hunting_entry(tmp_path) -> None:
    plan = trial.Trial(_config(tmp_path)).plan()

    labels = [step.label for step in plan.steps]
    assert "project" not in labels  # no create
    assert "L1 scaffold" not in labels  # no scaffold
    assert "seeded project reuse" in labels
    assert "hunting entry + launch" in labels

    seeded = next(step for step in plan.steps if step.label == "seeded project reuse")
    assert seeded.calls, "the seeded step must show its entry assertions"
    assert {call.method for call in seeded.calls} == {"GET"}
    assert {call.path for call in seeded.calls} == {"/projects", f"/projects/{SEED}/graph"}


# --- the hunting-entry predicate's seeded arm --------------------------------


def _routed(**routes) -> RecordingApi:
    return RecordingApi(routes)


def test_hunting_entry_seeded_blocks_a_missing_project() -> None:
    state = predicates.PhaseState(project_id=SEED, seeded=True)

    result = predicates.hunting_entry(
        _routed(**{"GET /projects": {"projects": []}}), FileStore(), state
    )

    assert not result.ok
    assert any(f"seeded project not found: {SEED}" in block for block in result.blocks)


def test_hunting_entry_seeded_blocks_a_zero_service_l1() -> None:
    state = predicates.PhaseState(project_id=SEED, seeded=True)

    result = predicates.hunting_entry(
        _routed(
            **{
                "GET /projects": {"projects": [{"project_id": SEED}]},
                f"GET /projects/{SEED}/graph": {"nodes": [], "links": []},
            }
        ),
        FileStore(),
        state,
    )

    assert not result.ok
    assert any("0 services" in block for block in result.blocks)


def test_hunting_entry_seeded_permits_when_services_are_present() -> None:
    state = predicates.PhaseState(project_id=SEED, seeded=True)

    result = predicates.hunting_entry(
        _routed(
            **{
                "GET /projects": {"projects": [{"project_id": SEED}]},
                f"GET /projects/{SEED}/graph": GRAPH_L1,
            }
        ),
        FileStore(),
        state,
    )

    assert result.ok


# --- setup validation: TargetRun.existing_project_id --------------------------


def _target(sample_setup) -> dict:
    return sample_setup["instances"][0]["targets"][0]


def test_existing_project_id_is_optional(sample_setup) -> None:
    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.instances[0].targets[0].existing_project_id is None


def test_existing_project_id_defaults_start_phase_to_hunting(sample_setup) -> None:
    target = _target(sample_setup)
    target.pop("start_phase", None)
    target["existing_project_id"] = SEED

    parsed = setup_mod.parse_eval_setup(sample_setup)

    run = parsed.instances[0].targets[0]
    assert run.existing_project_id == SEED
    assert run.start_phase == "hunting"


def test_existing_project_id_with_hunting_start_phase_parses(sample_setup) -> None:
    target = _target(sample_setup)
    target["start_phase"] = "hunting"
    target["existing_project_id"] = SEED

    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.instances[0].targets[0].start_phase == "hunting"


def test_existing_project_id_with_contradictory_start_phase_is_named(sample_setup) -> None:
    target = _target(sample_setup)
    target["start_phase"] = "recon"
    target["existing_project_id"] = SEED

    with pytest.raises(setup_mod.SetupError, match="start_phase"):
        setup_mod.parse_eval_setup(sample_setup)


def test_duplicate_existing_project_id_is_named(sample_setup) -> None:
    targets = sample_setup["instances"][0]["targets"]
    targets[0]["start_phase"] = "hunting"
    targets[0]["existing_project_id"] = SEED
    targets.append({**targets[0], "target_id": "other-1"})

    with pytest.raises(setup_mod.SetupError, match="existing_project_id"):
        setup_mod.parse_eval_setup(sample_setup)


def test_path_unsafe_existing_project_id_is_named(sample_setup) -> None:
    target = _target(sample_setup)
    target["start_phase"] = "hunting"
    target["existing_project_id"] = "../escape"

    with pytest.raises(setup_mod.SetupError, match="existing_project_id"):
        setup_mod.parse_eval_setup(sample_setup)


# --- CLI: the flag, the env var, and the contradictory-phase refusal ----------


def _write_setup(tmp_path, payload) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def _explode_runner():
    raise AssertionError("dry-run must never construct a runner")


def _explode_api(base):
    raise AssertionError("dry-run must never construct an API runner")


def _common(tmp_path) -> list[str]:
    return [
        "--repo",
        str(REPO_ROOT),
        "--instances-root",
        str(tmp_path / "instances"),
        "--state",
        str(tmp_path / "alignment.yaml"),
    ]


def test_trial_flag_drives_the_seeded_plan(sample_setup, tmp_path, capsys) -> None:
    sample_setup["instances"][0]["targets"][0]["start_phase"] = "hunting"
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(
        [
            "trial",
            setup_path,
            "arm-a",
            "jetlinks-1",
            "--existing-project-id",
            SEED,
            "--dry-run",
            *_common(tmp_path),
        ],
        runner_factory=_explode_runner,
        api_factory=_explode_api,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "seeded project reuse" in out
    assert SEED in out
    assert "L1 scaffold" not in out


def test_trial_env_var_drives_the_seeded_plan(
    sample_setup, tmp_path, monkeypatch, capsys
) -> None:
    sample_setup["instances"][0]["targets"][0]["start_phase"] = "hunting"
    setup_path = _write_setup(tmp_path, sample_setup)
    monkeypatch.setenv("EVAL_EXISTING_PROJECT_ID", SEED)

    code = cli.main(
        ["trial", setup_path, "arm-a", "jetlinks-1", "--dry-run", *_common(tmp_path)],
        runner_factory=_explode_runner,
        api_factory=_explode_api,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "seeded project reuse" in out
    assert SEED in out


def test_trial_rejects_existing_project_id_with_a_contradictory_phase(
    sample_setup, tmp_path, capsys
) -> None:
    # The sample setup starts at recon; reusing a project there is contradictory.
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(
        [
            "trial",
            setup_path,
            "arm-a",
            "jetlinks-1",
            "--existing-project-id",
            SEED,
            "--dry-run",
            *_common(tmp_path),
        ],
        runner_factory=_explode_runner,
        api_factory=_explode_api,
    )

    assert code == 1
    assert "start_phase" in capsys.readouterr().err


def test_trial_rejects_a_path_unsafe_existing_project_id(
    sample_setup, tmp_path, capsys
) -> None:
    sample_setup["instances"][0]["targets"][0]["start_phase"] = "hunting"
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(
        [
            "trial",
            setup_path,
            "arm-a",
            "jetlinks-1",
            "--existing-project-id",
            "../escape",
            "--dry-run",
            *_common(tmp_path),
        ],
        runner_factory=_explode_runner,
        api_factory=_explode_api,
    )

    assert code == 1
    assert "existing_project_id" in capsys.readouterr().err


# --- the committed example setup ----------------------------------------------


def test_example_hunting_setup_parses_with_a_seeded_project() -> None:
    parsed = setup_mod.load_eval_setup(EXAMPLE_SETUP)

    (instance,) = parsed.instances
    (run,) = instance.targets
    assert run.existing_project_id == SEED
    assert run.start_phase == "hunting"
    assert run.hunt_config_budget == 3
    # A seeded project needs no L1 projection; no pre-mined artifacts are set.
    assert run.preloaded_hunting_artifacts is None


def test_example_hunting_setup_dry_run_shows_the_seeded_path(tmp_path, capsys) -> None:
    parsed = setup_mod.load_eval_setup(EXAMPLE_SETUP)
    instance = parsed.instances[0]
    target = instance.targets[0]

    code = cli.main(
        [
            "trial",
            str(EXAMPLE_SETUP),
            instance.instance_id,
            target.target_id,
            "--dry-run",
            *_common(tmp_path),
        ],
        runner_factory=_explode_runner,
        api_factory=_explode_api,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "seeded project reuse" in out
    assert SEED in out
    assert "hunting entry + launch" in out
    # No project creation and no scaffold on the seeded path.
    assert "L1 scaffold" not in out
    assert "# project" not in out
