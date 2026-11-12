#!/usr/bin/env python3
"""Build the monitor scope file for the modeller-only pass."""
import json
import sys

intake_path, response_path, out_path, data_root = sys.argv[1:5]
intake = json.load(open(intake_path, encoding="utf-8"))
response = json.load(open(response_path, encoding="utf-8"))
scope = {
    "project_id": "10e451a3-025c-4648-a21e-0eec5cf9ebb8",
    "run_id": response["run_id"],
    "baseline_capped": 7010520,
    "token_budget": 7000000,
    "data_root": data_root,
    "order": intake["order"],
    "excluded": intake["excluded"],
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(scope, handle, indent=1)
print("scope written", len(scope["order"]), scope["run_id"])
