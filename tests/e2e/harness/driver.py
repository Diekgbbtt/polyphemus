# The in-container driver for the pod e2e tier (#84, E5-E8). Runs INSIDE the
# sibling agent container (docker compose exec pod-e2e-agent python driver.py).
#
# It drives the pod exactly as the parent HuntingAgent would in production:
#   - the run is wrapped in `hunt_session(run_id, hunt_id)` so the pod's
#     D84-7 session binding resolves the real session/checkpointer stack
#     (the pod roles are session/high, registered in T1),
#   - `kb_retrieve` is the MOCKED seam: the symptom-technique KB workstream is
#     not merged, so the driver injects a canned SymptomTechniqueResult set
#     (POD_E2E_MOCK_KB=1) instead of a live KB call - the one mocked
#     collaborator, taints realism, acknowledged,
#   - the pod roles are wired to muse-spark by the compose overlay,
#   - the driver persists to /srv/tests/e2e/fixtures/runs/<POD_RUN_ID>/
#     the artifacts the NFR scorer reads: envelope.json (the IA-4 D5+D6), plus
#     the pod-memory notes (D84-32) for note-detail scoring.
#
# A single PASS is one spec through the pod: env POD_SPEC_PATH points at the
# YAML fixture (the worktree is mounted at /srv, so the path matches).
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/srv")
RUNS = ROOT / "tests" / "e2e" / "fixtures" / "runs"
RUN_ID = os.environ.get("POD_RUN_ID", "pod-unset")
SPEC_PATH = os.environ.get("POD_SPEC_PATH", "")


def _load_spec() -> dict[str, Any]:
    if not SPEC_PATH:
        raise SystemExit("POD_SPEC_PATH unset")
    with open(SPEC_PATH, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    # The typed base the pod's verification ranges over: keep only the D4 keys
    # (the fixture carries extra name/comments).
    keep = {"target_identity", "verification_symptoms", "testing_pattern",
            "assumptions", "payload_vector_space", "rationale",
            "interpretation_guidance"}
    return {k: spec[k] for k in keep if k in spec}


def _mocked_kb(query: str, *, fault_id: str = "", technological_axis=()) -> dict:
    """The canned KB (POD_E2E_MOCK_KB=1): keyword-substring match against the
    mock-kb.yaml entries; a no-match returns the empty result (fail-open O13)."""
    kb_file = os.environ.get("POD_E2E_MOCK_KB_FILE",
                             "/srv/tests/e2e/fixtures/mock-kb.yaml")
    with open(kb_file, encoding="utf-8") as fh:
        kb = yaml.safe_load(fh).get("symptom_kb", {})
    q = (query or "").lower()
    for key, entry in kb.items():
        if key.lower() in q:
            return {"symptoms": entry.get("symptoms", []),
                    "techniques": entry.get("techniques", []),
                    "source": entry.get("source", "mock-kb")}
    return {"symptoms": [], "techniques": [], "source": "mock-kb"}


def _persist(name: str, data: Any) -> None:
    out = RUNS / RUN_ID
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(data, indent=2, default=str))


async def _run_pod(spec: dict) -> dict[str, Any]:
    """Wrap `arun_pod` in the hunt_session context - exactly the parent
    HuntingAgent's `_pod_loop` shape (IA-3/IA-4)."""
    from polymerhus.attack.hunting.llm import hunt_session
    from polymerhus.attack.hunting.pod import arun_pod

    run_id = f"pod-e2e-{RUN_ID}"
    try:
        with hunt_session(run_id, f"hunt-{RUN_ID}"):
            return await arun_pod(spec, run_id=run_id, kb_fn=_mocked_kb,
                                  trace_fn=None)
    except Exception as exc:  # noqa: BLE001 - the pod must never raise
        _persist("driver_error.json", {"error": str(exc)})
        return {"verdict": "unsuccessful", "evidence": {"error": str(exc)}}


def _read_notes(spec: dict) -> list[dict]:
    """Read the pod's run notes back from the fixed memory-store root the
    production lane wrote (D84-28 `data/pod-memory` under the hunting module),
    keyed by the spec's canonical id - the N3 note-detail evidence source."""
    try:
        from polymerhus.attack.hunting.pod.pod_memory import (
            PodMemoryStore,
            canonical_spec_id,
        )

        store = PodMemoryStore()
        return store.read_notes(canonical_spec_id(spec))
    except Exception:  # noqa: BLE001 - a missing store yields [], never a raise
        return []


def main() -> None:
    spec = _load_spec()
    _persist("spec.json", spec)
    out = asyncio.run(_run_pod(spec))
    _persist("envelope.json", out)
    _persist("notes.json", _read_notes(spec))
    print(json.dumps({"run_id": RUN_ID, "verdict": out.get("verdict"),
                      "terminal_reason": out.get("evidence", {}).get(
                          "terminal_reason")}, indent=2))


if __name__ == "__main__":
    main()