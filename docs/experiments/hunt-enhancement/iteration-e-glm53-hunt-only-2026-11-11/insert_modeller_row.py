#!/usr/bin/env python3
"""Insert the external orchestration row for a modeller-only pass.

The modeller-only launch writes no hunting_runs row. This row is the
orchestration handle: it makes GET /hunting/<id>, /threads, and the per-session
stop verb addressable without a product-code change.
"""
import datetime
import json
import sys

intake_path, run_id, out_path = sys.argv[1:4]
intake = json.load(open(intake_path, encoding="utf-8"))
stats = {
    "mode": "threat_model_only",
    "component": "threat_modeller",
    "intake_order": intake["order"],
    "intake_position": 0,
    "intake_excluded": intake["excluded"],
    "risk_threshold": 10000.0,
    "threshold_basis": "db",
    "risk_total": 0.0,
    "halt": False,
    "monitor": {
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "baseline_capped": 7010520,
        "token_budget": 7000000,
        "note": "external orchestration row for the modeller-only pass",
    },
}
payload = json.dumps(stats)
sql = (
    "INSERT INTO hunting_runs "
    "(hunting_run_id, project_id, status, started_at, stats) VALUES "
    f"('{run_id}', '10e451a3-025c-4648-a21e-0eec5cf9ebb8', 'running', now(), "
    f"$json${payload}$json$::jsonb) "
    "ON CONFLICT (hunting_run_id) DO NOTHING;"
)
with open(out_path, "w", encoding="utf-8") as handle:
    handle.write(sql)
print("sql written", len(sql))
