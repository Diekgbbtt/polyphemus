# ADR: the target-front 5xx is an upstream-availability signal, not a route verdict

*Status: RATIFIED (2026-10-04). New record. It supersedes no earlier decision; it corrects the implicit assumption that a hunting probe may read a target-front `5xx` as route-absence, and it retires the pod's conflated `{429, 503}` defence set.*

## Context

A live comfyui hunting trial (`comfyui-1`, eval SHA `919d40b`) produced intermittent `502 Bad Gateway` responses from the shared target front (`ph-eval-front`, nginx) on `/extensions`, `/features`, `/api/manager/...`, `/models` and other paths that recon's L0 layer had recorded as `200` earlier.
The hunter then looped on retries.

The diagnosis was grounded in the live artifacts:

- All `693` `502`s in the front's history are the nginx `502` produced by a genuinely unavailable upstream.
  The error log shows the exact sequence: `upstream prematurely closed connection while reading response header`, then `connect() failed (111: Connection refused)` for the whole outage window.
- The trigger was a hunter probe to `GET /api/manager/reboot` at `20:02:13`.
  That is ComfyUI-Manager's documented restart route (`manager_server.py::restart`); with `__COMFY_CLI_SESSION__` unset it takes the legacy `os.execv` path, replacing the ComfyUI process and closing the listening socket for roughly two minutes.
- Recon's own L0 `httpx` probe had already recorded the identical `502` page at `01:07:43` and interpreted it correctly: "a reverse proxy whose upstream backend is currently unreachable".
- The hunter's subsequent probes (`/users`, `/queue`, `/`, `/system_stats`, ...) were `502` only because the backend was restarting, never because those routes are absent (absent routes returned clean `404`s: `/cloud/login`, `/customers`, ...).

So the `502` is EXPECTED front behaviour for a down or restarting upstream, and the front and the target are not defective.
The defect is behavioural: the hunter had no single-sourced rule distinguishing "the target is temporarily unavailable" from "the route is absent", so it re-probed a target that was simply down.

## Decision

### 1. The target-front availability rule is single-sourced

`attack/hunting/hunting_status.py` (env-free, the `conciseness.py` #292 pattern) is the one home of:

- `TARGET_UNAVAILABLE_STATUSES = frozenset({502, 503, 504})` - the gateway-family statuses that mean "the upstream is not answering".
- `TARGET_UNAVAILABLE_DIRECTIVE` - the load-bearing rule, stating that a `5xx` from the target front is the upstream being down/restarting (a restart can be self-inflicted by probing a destructive control route), NOT route-absence; a `404` is the route-absence signal.
- `is_target_unavailable(status)` - the typed predicate.

### 2. The rule reaches the hunter where the 502 arrived

The hunter's `exec` tool description and the `hunting-agent.md` role prompt embed `TARGET_UNAVAILABLE_DIRECTIVE` verbatim.
The drift guards in `tests/attack/test_hunting_status.py` assert the exact text at both sites, so the rule can never drift between the tool and the reasoning prompt.

### 3. The pod reuses the rule; the conflated defence set retires

`hunting_pod._defence_signal` classifies the gateway family through `is_target_unavailable` (a `server-error`, i.e. inconclusive - never `allowed`/`denied`).
`503 Service Unavailable` is an availability signal, not rate limiting, so the old `DEFENCE_STATUSES = {429, 503}` set is retired; only `429` is `rate-limited`.

## Consequences

- A hunter that sees a target-front `5xx` records the target as temporarily unavailable and stops probing, instead of looping.
- The pod and the hunter classify the gateway family identically, from one constant.
- The `502` is documented as expected front behaviour in `eval/CONTEXT.md` under **Target front**, so a future reader does not re-open it as a defect.

## Alignment

`src/polymerhus/**` ships in the agent image; the change takes effect on the next image build (the eval environment's alignment action for `src/**`).
No harness or front configuration changes.
