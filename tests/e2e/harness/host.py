# Host-side driver for the test-executor pod holistic e2e tier (#84, E5-E8).
#
# The whole live tier runs from THIS WORKTREE directory with a three-file
# compose stack:
#   docker compose -f docker-compose.yml -f docker-compose.dev.yml \
#                  -f tests/e2e/harness/compose.pod-e2e.yml  <...>
# where `docker-compose.yml` + `docker-compose.dev.yml` come from the repo
# root (here: /Users/diekgbbtt/polymerhus/.claude/worktrees/hunting-84-test-executor-pod
# via REPO_ROOT) and the pod overlay re-declares the `agent` service with the
# pod-specific environment the base stack does not carry (the pod roles are
# not registered in the deployed .env yet).
#
# The overlay starts a SIBLING agent container (same polymerhus-agent:latest
# image) whose `/srv/src`, `/srv/db`, `/srv/skills` and `/srv/gateway` are
# bind-mounted from THIS WORKTREE, so the pod code under test is the edited
# regrounded tree, never the baked image layer (the same rule as the `tests`
# service). It then `docker compose exec`s a driver into that container which:
#   - wraps `arun_pod` in a `hunt_session` (the D84-7 session/checkpointer
#     stack, exactly as the parent HuntingAgent would),
#   - injects a MOCKED `kb_retrieve` (the symptom-technique KB workstream is
#     not merged; returning canned symptom/technique entries instead of a
#     live KB call - taints realism, acknowledged),
#   - wires the pod roles to the operator's chosen model
#     (opencode:muse-spark-1.2-contributor-free, matching the hunter),
#   - records the full run artifact set for the NFR pass: the returned
#     envelope, the experiment log (D6), the pod-memory notes, and the run id
#     so the coordinator can pull the Langfuse trace from the trace id.
#
# Every function here is a self-contained PASS primitive: it brings up the
# stack once, runs one spec through the pod, tears down, and leaves the run's
# artifacts under `tests/e2e/fixtures/runs/<run_id>/` for the NFR scorer.
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # the WORKTREE root
HARNESS_DIR = Path(__file__).resolve().parent

BASE_COMPOSE = str(REPO_ROOT / "docker-compose.yml")
DEV_COMPOSE = str(Path(os.environ.get(
    "POD_E2E_DEV_COMPOSE", str(REPO_ROOT / "docker-compose.dev.yml"))))
POD_COMPOSE = str(Path(os.environ.get(
    "POD_E2E_POD_COMPOSE", str(HARNESS_DIR / "compose.pod-e2e.yml"))))
COMPOSE = ["docker", "compose", "-f", BASE_COMPOSE, "-f", DEV_COMPOSE,
           "-f", POD_COMPOSE]

AGENT_SERVICE = os.environ.get("POD_E2E_SERVICE", "pod-e2e-agent")

RUNS_DIR = REPO_ROOT / "tests" / "e2e" / "fixtures" / "runs"

# The operator-chosen pod role models (muse-spark, matching the hunter).
POD_RUNNER_MODEL = "opencode:muse-spark-1.2-contributor-free"
POD_TRIAGER_MODEL = "opencode:muse-spark-1.2-contributor-free"


def _run(cmd: list[str], *, timeout: int = 600, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or REPO_ROOT, capture_output=True,
                          text=True, timeout=timeout)


def compose_up() -> None:
    """Bring the sibling pod-e2e agent container up (in the compose network,
    worktree source mounted, pod roles wired)."""
    res = _run(COMPOSE + ["up", "-d", "--no-deps", AGENT_SERVICE])
    if res.returncode != 0:
        raise RuntimeError(f"compose up failed: {res.stdout}\n{res.stderr}")


def compose_down() -> None:
    _run(COMPOSE + ["rm", "-sf", AGENT_SERVICE])


def driver_command(script: str, run_id: str) -> list[str]:
    """`docker compose exec` into the sibling container running `script` with
    the run id exported (the script reads POD_RUN_ID)."""
    return COMPOSE + ["exec", "-e", f"POD_RUN_ID={run_id}", AGENT_SERVICE,
                      "python", "-c", script]


def run_one_spec(spec_path: str, *, run_id: str | None = None) -> dict:
    """Drive ONE spec through the pod in the sibling container as a
    self-contained pass. `spec_path` is absolute (the container sees the mount
    at the same path). Returns the run's metadata (run_id, artifact dir)."""
    run_id = run_id or f"pod-{uuid.uuid4().hex[:8]}"
    out_dir = RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    # The driver script runs INSIDE the container; POD_RUN_ID + POD_SPEC_PATH
    # reach it via env. The script itself lives at
    # tests/e2e/harness/driver.py (mounted at the same path under /srv).
    driver = HARNESS_DIR / "driver.py"
    res = _run(COMPOSE + ["exec", "-e", f"POD_RUN_ID={run_id}",
                          "-e", f"POD_SPEC_PATH={spec_path}",
                          AGENT_SERVICE, "python", str(driver)],
               cwd=REPO_ROOT)
    if res.returncode != 0:
        raise RuntimeError(f"pod e2e run failed: {res.stdout}\n{res.stderr}")
    return {"run_id": run_id, "artifacts": str(out_dir)}


def read_run_artifacts(run_id: str) -> dict:
    """The run's recorded artifacts (envelope + D6 export + notes) for the NFR
    scorer, keyed by file name."""
    d = RUNS_DIR / run_id
    out = {}
    for f in d.glob("*.json"):
        out[f.stem] = json.loads(f.read_text())
    return out