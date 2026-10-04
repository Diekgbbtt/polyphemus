"""The first live EvalSetup, exercised as a dry run (#276).

The live end-to-end run is deferred to the final e2e phase, so this tier proves
the implementable half: `eval/setups/first.yaml` parses against the real schema,
the whole cycle is plannable in order through the CLI's dry-run verbs with no
runner or API constructed, and the ground-truth wiring resolves the chosen
target from a fixture WebExploitBench directory.

No live call: every verb runs in its `--dry-run`/plan form, and the injected
factories raise if anything tries to execute.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from orchestrator import assessment, cli, routing
from orchestrator.setup import load_eval_setup

REPO_ROOT = Path(__file__).resolve().parents[2]
FIRST_SETUP = REPO_ROOT / "eval" / "setups" / "first.yaml"

INSTANCE = "eval-server-1"
TARGET = "comfyui-1"
EVAL_SHA = "eval-sha-1"
FINGERPRINT = "fp-1"


def _explode_runner():
    raise AssertionError("dry-run must never construct a command runner")


def _explode_api(base):
    raise AssertionError("dry-run must never construct an API runner")


def _explode_dispatch(argv):
    raise AssertionError("dry-run must never construct a dispatcher")


def _common(tmp_path) -> list[str]:
    """Isolated roots so a dry run never reads or writes the live eval state."""
    return [
        "--repo",
        str(REPO_ROOT),
        "--instances-root",
        str(tmp_path / "instances"),
        "--state",
        str(tmp_path / "alignment.yaml"),
    ]


def _fixture_trial_dir(tmp_path):
    """A minimal, already-produced trial the assessment/diagnosis/store verbs read."""
    trial_dir = tmp_path / "runs" / TARGET / "trial-1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "trial_id": "trial-1",
                "instance_id": INSTANCE,
                "target_id": TARGET,
                "project_id": "pid",
                "start_phase": "recon",
                "terminal": "complete",
                "phases": [],
                "started_at": "t",
                "finished_at": "t",
                "eval_sha": EVAL_SHA,
                "stack_fingerprint": FINGERPRINT,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (trial_dir / "verdicts.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "vuln_id": "comfyui-001",
                    "identified": "missed",
                    "confidence": 0.0,
                    "matched": {"unit": "u", "fault_class": "fc", "symptom": "s"},
                    "eval_sha": EVAL_SHA,
                    "stack_fingerprint": FINGERPRINT,
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return trial_dir


# --- the setup parses and validates -------------------------------------------


def test_first_setup_parses_against_the_real_schema() -> None:
    parsed = load_eval_setup(FIRST_SETUP)

    assert parsed.schema_version == 1
    assert parsed.artifact_store == "/srv/eval-artifacts"
    assert parsed.datasets == ("webexploitbench",)
    assert [w.name for w in parsed.work_items] == [
        "auth-bootstrap",
        "l1-surface",
        "hunting-artifacts",
    ]
    assert parsed.alignment is None  # no migrations/rebuilds declared yet

    (instance,) = parsed.instances
    assert instance.instance_id == INSTANCE
    assert instance.env_file == f"{INSTANCE}/.env"
    (run,) = instance.targets
    assert run.target_key == "webexploitbench/comfyui"
    assert run.target == "comfyui"  # ground-truth name gt.py resolves
    assert run.target_id == TARGET
    assert run.start_phase == "recon"
    assert run.hunt_config_budget == 10
    assert run.preloaded_hunting_artifacts is None
    assert run.target_config.operator_kb == (
        "eval/data/webexploitbench/comfyui/operator_kb.md"
    )
    assert run.target_config.target_seed is None  # derived from the synthetic Host


def test_first_setup_references_the_committed_operator_kb() -> None:
    parsed = load_eval_setup(FIRST_SETUP)
    run = parsed.instances[0].targets[0]

    assert (REPO_ROOT / run.target_config.operator_kb).is_file()


def test_only_required_work_items_are_gated() -> None:
    parsed = load_eval_setup(FIRST_SETUP)
    gated = [w.name for w in parsed.work_items if w.required and w.status != "complete"]

    assert gated == []  # the first run's required data dependencies are ready


# --- the dry-run plan covers the whole cycle in order -------------------------


def test_dry_run_covers_the_cycle_in_order(tmp_path, capsys) -> None:
    trial_dir = _fixture_trial_dir(tmp_path)
    common = _common(tmp_path)
    synth = routing.synthetic_host(f"{INSTANCE}/{TARGET}")
    assert synth == "t-1fc05262.target"  # the documented routing discriminator

    def run_plan():
        return cli.main(
            ["plan", str(FIRST_SETUP), "--dry-run", *common],
            runner_factory=_explode_runner,
        )

    def run_trial():
        return cli.main(
            ["trial", str(FIRST_SETUP), INSTANCE, TARGET, "--dry-run", *common],
            runner_factory=_explode_runner,
            api_factory=_explode_api,
        )

    def run_assess():
        return cli.main(
            [
                "assess",
                str(FIRST_SETUP),
                "--trial",
                str(trial_dir),
                "--dry-run",
                *common,
                "--command",
                "opencode run {prompt} {trial_record} {ground_truth} {data_root} {destination}",
            ],
            runner_factory=_explode_runner,
            dispatch_factory=_explode_dispatch,
        )

    def run_diagnose():
        return cli.main(
            [
                "diagnose",
                str(FIRST_SETUP),
                "--trial",
                str(trial_dir),
                "--dry-run",
                *common,
                "--diagnose-command",
                "opencode run {prompt} {trial_record} {verdicts} {ground_truth} "
                "{data_root} {destination} {vulns} {trace_id}",
            ],
            runner_factory=_explode_runner,
            diagnose_dispatch_factory=_explode_dispatch,
        )

    def run_render_sync():
        return cli.main(
            ["store", "render-sync", str(FIRST_SETUP), "--dry-run", *common],
            runner_factory=_explode_runner,
        )

    def run_materialize():
        return cli.main(
            [
                "store",
                "materialize",
                str(FIRST_SETUP),
                "--trial",
                str(trial_dir),
                "--dry-run",
                *common,
            ],
            runner_factory=_explode_runner,
        )

    # The live cycle: instance up, target routed, trial, assessment, diagnosis,
    # store materialization. Each verb is plannable now; the ordered labels
    # assert the cycle shape the live run will follow.
    cycle = [
        ("instance up + target routed", run_plan, (
            "worktree add --detach",
            "env_preflight.py",
            "scripts/targetctl up comfyui",
            f"eval-target-{synth}.conf",
            "> /tmp/hosts.tmp",  # the kali /etc/hosts alias write
        )),
        ("trial pipeline", run_trial, (
            "POST /projects",
            f'"target_seed": "{synth}"',  # derived, not invented
            "data-dependencies/l1",  # the deterministic L1 surface endpoint
            "recon entry + launch",
            "hunting entry + launch",
        )),
        ("assessment dispatch", run_assess, (
            "assessment.md",
            "opencode run",
            "verdicts.yaml",
        )),
        ("diagnosis dispatch", run_diagnose, (
            "diagnoser.md",
            "opencode run",
            "diagnoses.yaml",
            "comfyui-001",
        )),
        ("store sync render", run_render_sync, (
            f"eval-store-{INSTANCE}.conf",
            f"eval-store-{INSTANCE}.service",
        )),
        ("store materialize", run_materialize, (
            f"{TARGET}/{INSTANCE}/trial-1",
            "verdicts.yaml",
            "run-manifest.yaml",
        )),
    ]

    observed: list[str] = []
    for label, invoke, markers in cycle:
        code = invoke()
        out = capsys.readouterr().out
        assert code == 0, f"{label} dry-run exited {code}"
        for marker in markers:
            assert marker in out, f"{label}: missing {marker!r}\n{out}"
        observed.append(label)

    assert observed == [label for label, _, _ in cycle]


# --- the ground-truth wiring resolves the chosen target -----------------------


def test_ground_truth_wiring_resolves_the_chosen_target(tmp_path, monkeypatch) -> None:
    web_dir = tmp_path / "WebExploitBench"
    challenge = web_dir / "comfyui"
    vuln_dir = challenge / "vulnerability" / "comfyui-001"
    vuln_dir.mkdir(parents=True)
    (challenge / "challenge.json").write_text(
        json.dumps(
            {
                "id": "pb-comfyui",
                "vulnerabilities": [{"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]}],
            }
        ),
        encoding="utf-8",
    )
    (vuln_dir / "metadata.json").write_text(
        json.dumps(
            {
                "Location": "http://comfyui-manager:8288/",
                "Vulnerability Type": "Arbitrary File Read",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVAL_WEB_DIR", str(web_dir))

    parsed = load_eval_setup(FIRST_SETUP)
    run = parsed.instances[0].targets[0]

    # The target segment of the key is the same name gt.py resolves; the CLI's
    # `_ground_truth_for` calls exactly this seam.
    resolved = assessment.resolve_ground_truth(run.target)
    assert resolved == challenge
