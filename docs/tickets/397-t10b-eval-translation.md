# #397 - T10b: eval translation, e2e translation, final docs sweep

*Status: implemented on `feat/unit-threat-model` (T10b). Split from #383 (T10a, committed as `daff1b63`). The implementation plan records both tickets.*

## Scope

- Translate the eval fixtures, trial records, evidence chain, and the assessor and diagnoser prompts to the loop and spec-set vocabulary; add the pre-mined-config guard.
- Translate the e2e harness driver and the fixture specs to the reduced D4.
- Remove the integration fixtures' vacuous config assertions and restore a true E1 seed premise.
- Finish the remaining documentation sweep and the final no-live-obsolete-verbatim check.

## Carried disposition - the #196 live e2e gate

T10a deleted `tests/e2e/test_http_proxy_history.py` together with the legacy
`hunting_pod.py`. The gate exercised the retired
`payload_vector_space.request_ref` replay path through that pod, so it could
not survive the module removal.

The production pod's replay path keeps its unit and contract coverage in
`tests/attack/pod/test_react_seams.py` and
`tests/attack/pod/test_request_ref.py`.

A replacement LIVE replay-lineage gate is a separate ticket, not a T10b
deliverable. T10a deleted the gate as a forced consequence of the
`hunting_pod.py` removal; T10a also deleted
`tests/e2e/test_hunting_agent_walkthrough.py`, which was restored (it
collects and its two carried skeletons skip) because it imports neither
removed module.

## Proposed follow-up (not built)

A replacement LIVE replay-lineage gate is proposed as a separate ticket:
it drives the production pod's recorded-baseline replay end to end against a
live target and asserts the replayed artifact's lineage (`derived_from`,
`replay_kind`).
T10b does not build it.
The production replay path keeps its unit and contract coverage in
`tests/attack/pod/test_react_seams.py` and `tests/attack/pod/test_request_ref.py`.
