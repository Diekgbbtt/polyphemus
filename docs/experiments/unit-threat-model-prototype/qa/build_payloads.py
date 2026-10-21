#!/usr/bin/env python3
"""S1 - build the 22 per-loop hunter payloads from the two trial threat models.

Rendering (operator Q36 respecification):
- unit context
- technical sharpening overview (interface agreements, control flows, data flows)
- trust overview (trust boundary agreements, dynamic-state trust)
- the abduction chain: assumption(s) -> fault -> vulnerability
- likelihood + rationale, confidence degree, evidences
- NO failure modes anywhere.
"""

import os
import sys
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
WT = os.path.abspath(os.path.join(ROOT, "..", "..", "..", ".."))
MODELS = {
    "t1": os.path.join(
        ROOT, "..", "trials", "t1-service-model-download", "output",
        "threat-model-Service-model-download.yaml",
    ),
    "t2": os.path.join(
        ROOT, "..", "trials", "t2-system-catalog-manager-shell", "output",
        "threat-model-WebPresentation-custom-node-catalog.yaml",
    ),
}


def strip_failure_modes(obj):
    """Recursively drop any failure-mode key (defence in depth)."""
    if isinstance(obj, dict):
        return {
            k: strip_failure_modes(v)
            for k, v in obj.items()
            if k not in ("failure_modes", "failure_mode_refs", "runtime_failure_mode")
        }
    if isinstance(obj, list):
        return [strip_failure_modes(v) for v in obj]
    return obj


def collect_evidences(items):
    out = []
    for it in items:
        for ev in it.get("evidences") or []:
            if ev not in out:
                out.append(ev)
    return out


def build(trial, model_path):
    with open(model_path) as fh:
        m = yaml.safe_load(fh)

    assumptions = {a["id"]: a for a in m.get("assumptions") or []}
    faults = {f["id"]: f for f in m.get("faults") or []}
    vulns = {v["id"]: v for v in m.get("vulnerabilities") or []}

    env = m.get("environment") or {}
    unit = {
        "id": m["unit_id"],
        "kind": m["kind"],
        "base_url": env.get("base_url"),
        "deployment": env.get("deployment") or env.get("target"),
    }

    outdir = os.path.join(ROOT, trial, "input")
    os.makedirs(outdir, exist_ok=True)

    manifest = []
    for loop in m.get("loops") or []:
        fault = faults[loop["fault_ref"]]
        vuln = vulns[loop["vulnerability_ref"]]
        chain_assumptions = [
            a for a in assumptions.values() if a.get("induced_fault") == fault["id"]
        ]
        payload = {
            "loop_id": loop["loop_id"],
            "unit": unit,
            "technical_sharpening": m.get("technical_sharpening") or {},
            "trust_model": m.get("trust_model") or {},
            "abduction_chain": {
                "assumptions": chain_assumptions,
                "fault": fault,
                "vulnerability": vuln,
            },
            "likelihood": loop.get("likelihood"),
            "likelihood_rationale": loop.get("likelihood_rationale"),
            "confidence_degree": loop.get("rung"),
            "evidences": collect_evidences(chain_assumptions + [fault, vuln]),
        }
        payload = strip_failure_modes(payload)
        path = os.path.join(outdir, f"{loop['loop_id']}.yaml")
        with open(path, "w") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, width=140)
        manifest.append(
            {
                "loop_id": loop["loop_id"],
                "fault": fault["id"],
                "vulnerability": vuln["id"],
                "suite_class": vuln.get("suite_class"),
                "likelihood": loop.get("likelihood"),
                "confidence_degree": loop.get("rung"),
            }
        )
        print(f"{trial}: {loop['loop_id']} -> {path}")

    with open(os.path.join(outdir, "manifest.yaml"), "w") as fh:
        yaml.safe_dump(manifest, fh, sort_keys=False, width=140)
    return manifest, outdir


def gate(trial, outdir):
    bad = []
    for name in sorted(os.listdir(outdir)):
        if not name.endswith(".yaml"):
            continue
        path = os.path.join(outdir, name)
        text = open(path).read()
        try:
            yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            bad.append((name, f"parse: {exc}"))
            continue
        for needle in ("failure_mode", "failure mode", "failure-mode", "runtime_failure"):
            if needle in text.lower():
                bad.append((name, f"contains {needle!r}"))
    return bad


def main():
    total = 0
    for trial, path in MODELS.items():
        manifest, outdir = build(trial, os.path.normpath(path))
        total += len(manifest)
        bad = gate(trial, outdir)
        status = "OK" if not bad else f"PROBLEMS: {bad}"
        print(f"{trial}: {len(manifest)} payloads; gate {status}")
    print(f"total loops: {total}")


if __name__ == "__main__":
    sys.exit(main())
