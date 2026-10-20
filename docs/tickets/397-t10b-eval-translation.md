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

A replacement LIVE replay-lineage gate was a separate follow-up, not a T10b
deliverable; it is delivered below. T10a deleted the gate as a forced
consequence of the `hunting_pod.py` removal; T10a also deleted
`tests/e2e/test_hunting_agent_walkthrough.py`, which was restored (it
collects and its two carried skeletons skip) because it imports neither
removed module.

## Delivered follow-up - the live replay-lineage gate

`tests/e2e/test_pod_replay_lineage.py` replaces the retired
`tests/e2e/test_http_proxy_history.py`.
It is the live acceptance gate for the production replay path, which now lives
on the test-executor pod's runner:

- execute a safe authenticated POST through the Kali MCP;
- find the baseline by method/header/cookie/query/status/body marker and assert
  its request body `capture_state == "captured"` (the only replayable state);
- author the reduced D4 with `provenance.baseline_ref` and no
  `payload_vector_space`;
- drive `runner_react_tools(...).replay`, bound to the real capture-plane
  `default_replay_fn`, with a declared `query.q` mutation;
- assert the new artifact's `derived_from` / `replay_kind`, the untouched
  request attributes, the unchanged baseline, cross-project `not_found`, and
  sanitized evidence.

The old live policy is kept: the test fails when the Kali MCP or capture plane
is unavailable, unless `KALI_HTTP_E2E_ALLOW_SKIP=1` is set (then it skips).
The production replay path keeps its unit and contract coverage in
`tests/attack/pod/test_react_seams.py` and `tests/attack/pod/test_request_ref.py`.

## Pre-mined retarget hazard (T10b review)

The launch mints the hunting run id, so `retarget_premined` can only rebind a
pre-mined threat-model tree AFTER `POST /hunting` returns.
The run's intake freeze runs at boot, so it can observe the model's SOURCE run
id before the rebind.

- A source id that names a real TERMINAL run is classified `stale` by
  `freeze_intake`; the model can be archived to `abandoned/` before the rebind.
- A synthetic or unknown source id has no readable run status, so the freeze
  treats it as `in-flight` and the model survives the rebind.

Intended convention: a pre-mined model tree carries a SYNTHETIC source run id
(for example `pre-mined`), never the id of a real terminal run.
The trial rebinds both the model document and its loop files to the launched
run id immediately after the launch returns.
An operator copying a real terminal run's model into a pre-mined seed is
exposed to the archive hazard and should not do it.
