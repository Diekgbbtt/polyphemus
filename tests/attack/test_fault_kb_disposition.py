"""The fault-KB disposition guard (T10 #383, S1 9.1).

The workbench Q17(a)/R2-7 and Q39/R2-16 retired the fault selection, the
tier ordering and the materialisation. T10 deleted the artifact and the
modules and recorded the disposition. This test fails if a retired module or
the data file returns, or if the app boot grows a consumer of the retired
path again.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RETIRED_MODULES = (
    "polymerhus.attack.hunting.fault_kb",
    "polymerhus.attack.hunting.fault_source",
    "polymerhus.attack.hunting.fault_risk",
    "polymerhus.attack.hunting.symptom_kb",
)


def test_the_retired_fault_kb_modules_are_absent():
    for module in RETIRED_MODULES:
        assert importlib.util.find_spec(module) is None, (
            f"{module} is retired (docs/design/hunting-383-fault-kb-disposition-adr.md)"
        )


def test_the_fault_kb_artifact_is_deleted():
    assert not (REPO_ROOT / "data" / "hunting" / "fault-kb.yaml").exists()


def test_the_app_boot_no_longer_consumes_the_fault_kb():
    source = (REPO_ROOT / "src" / "polymerhus" / "app" / "main.py").read_text(
        encoding="utf-8")
    for retired in ("fault_kb", "fault_source", "fault_risk", "fault-kb"):
        assert retired not in source, f"app boot still names {retired!r}"


def test_the_disposition_is_recorded_and_names_every_deleted_surface():
    adr = REPO_ROOT / "docs" / "design" / "hunting-383-fault-kb-disposition-adr.md"
    text = adr.read_text(encoding="utf-8")
    for surface in (
        "data/hunting/fault-kb.yaml",
        "fault_kb.py",
        "fault_source.py",
        "fault_risk.py",
    ):
        assert surface in text, f"the disposition record does not name {surface}"
