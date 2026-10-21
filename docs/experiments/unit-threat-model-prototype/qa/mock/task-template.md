# Loop task - human message template (mock v1, 2026-10-17)

You receive one loop payload rendered from a unit threat model (the abduction rendering).

The rendering contains:

- unit context: identity, kind, base URL, deployment stack;
- the technical sharpening overview: interface agreements, control flows, data flows;
- the trust overview: trust boundary agreements, dynamic-state trust;
- the abduction chain: assumption(s) -> fault -> vulnerability;
- likelihood with rationale, the confidence degree, and the chain evidences.

The failure modes are withheld by design; the payload never contains them.

## Task

1. Read the loop payload: `{payload_path}`
2. Execute the hunter workflow (system prompt): GROUND -> CLASS-SKILL -> PARAMETRISE -> SLICE -> DISCRIMINATE -> SPEC-WRITE -> AGGREGATE+CHECK -> CLOSE.
3. Write the spec set YAML to: `{output_path}`, conforming to `{output_contract_path}`.
4. Append a short run note to `{run_log_path}`: skills loaded, discrimination boundary chosen, overlap/coverage result, degradations.

## Environment facts for this run

- loop payload: `{payload_path}`
- skills directory (list it and load the matching class skill as fs files): `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`
- output contract: `{output_contract_path}`
- output file: `{output_path}`
- run log: `{run_log_path}`
