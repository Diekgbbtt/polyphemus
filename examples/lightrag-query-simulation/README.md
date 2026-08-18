# LightRAG query simulation fixtures

These files are mock inputs standing in for the QuerySpec the Polyphemus
attack-engineering agent will send to `POST /lightrag/query`. They mirror the
Phase 6B scenario classes:

| Fixture | Class | What it exercises |
| --- | --- | --- |
| `P6B-EASY-01.json` | supported/easy | GraphQL object-level authorization, R-A naive |
| `P6B-AMB-01.json` | ambiguous/multi-technique | token storage + client-side flow, L1 synthetic evidence |
| `P6B-INS-01.json` | insufficient evidence | weak SQLi signal, R-B mix |
| `P6B-NEG-04.json` | negative control | inert injection text, `expected_no_hypothesis: true` |

Field provenance contract (who supplies what):

- Polyphemus attack engineer agent: `scenario_id`, `attack_goal`, `concern`,
  `technology_stack`, `target_refs`, `input_vectors`, `known_facts`,
  `evidence` (L0/L1 refs), `expected_no_hypothesis`.
- Ontology/tuning (this side): `acceptable_technique_families`,
  `unsupported_claims`, `retrieval`.
- Never in the payload: retrieved corpus text, live credentials, or anything
  that should be treated as instructions.

Run one through the simulator:

```bash
.venv/bin/python scripts/simulate_lightrag_query.py \
  --scenario examples/lightrag-query-simulation/P6B-EASY-01.json --mock --direct
```
