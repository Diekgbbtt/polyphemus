# Steel session lifecycle: process reaping and state-preserving teardown (#395)

*Status: recorded 2026-10-19. The deployment artifact is `eval/deploy/steel/docker-compose.steel.yml`; the client is `src/polymerhus/app/steel_session_state.py`; the tests are `tests/eval/test_steel_deployment_contract.py`, `tests/test_steel_session_state.py`, `tests/integration/test_steel_session_state_http.py`, and the CLI-scaffold tiers.*
*Parent: #359 (local Steel runtime). Companion: `steel-local-deployment-359-decisions.md` (D359-10).*

The local Steel runtime accumulated zombie Chromium processes across launch/release cycles.
This record fingerprints the control-plane capability that fixes it, fingerprints the state and teardown API, and fixes the client design.

## 1. The failure, measured

The API container runs `node ./api/build/index.js` as PID 1.
On release, `CDPService.shutdown` calls `browserInstance.close()` and `browserInstance.process().kill()`.
Chromium's crashpad handlers and helper processes are reparented to PID 1 and exit without a waiter.
Node does not reap children it did not spawn, so they remain in state `Z`.

Measured on `dj-viscon-workshop-1` with the pinned image, six create/release cycles each:

| container | PID 1 | zombies after 6 cycles |
|---|---|---|
| `docker run` (no init) | `node` | 108 |
| `docker run --init` | `docker-init` | 0 |

The leaked processes were `chrome_crashpad` and `chromium`.
The browser itself was healthy; this is a container process-lifecycle defect, not a browser failure.

## 2. The native control-plane capability

There is no Steel API endpoint whose job is "kill Chromium".
The teardown endpoint is the session release, and it already kills the browser process:

- `POST /v1/sessions/<id>/release` releases one session.
- `POST /v1/sessions/release` releases the active session.

What the stack did not have is an **init process**.
Docker's `init: true` compose field runs `docker-init` (tini) as PID 1.
Tini reaps every orphaned child and forwards signals, so the zombie tier stays at zero.

Decision D395-1: set `init: true` in the deployment artifact.
The contract test asserts it, and `eval/OPERATOR.md` records the check.
The alternative, a custom PID-1 wrapper inside the image, is larger and loses Docker's signal forwarding; a scheduled `pkill` would kill live browsers and is rejected.

## 3. The state capability, fingerprinted live

The local API has no profile store. State survives through `sessionContext`:

| capability | call | shape |
|---|---|---|
| capture | `GET /v1/sessions/<id>/context` | `{cookies, localStorage, sessionStorage, indexedDB}` while the session is live |
| restore | `POST /v1/sessions` body `{sessionContext: <captured>}` | same shape; cookies injected over CDP, storage grouped by origin |
| teardown | `POST /v1/sessions/<id>/release` | ends the session, closes and kills the browser |
| endpoint | `STEEL_BROWSER_API_URL` | CLI form `http://<host>:<port>/v1`; the client appends `/v1` to the SDK origin |

Verified on the pinned image (probe container, not the deployment):

1. Created session A with `sessionContext.cookies = [{name: ph_probe, value: v1, domain: t-1fc05262.target}]`.
2. `GET /v1/sessions/A/context` returned the cookie.
3. Released A.
4. Created B with the captured cookie; `GET /v1/sessions/B/context` returned it again.

`getBrowserState` needs a `userDataDir`; the default launch config sets one (`/tmp/steel-chrome` in the container), so the endpoint works without `persist`.
`localStorage` is applied on navigation, not at inject time, so a capture taken before any navigation is empty.
The captured JSON is the whole state; it carries cookie values and target secrets, so the store is caller-owned and must be protected like a credential.

The API also accepts `userDataDir` and `persist` on create.
Its default is `CHROME_USER_DATA_DIR`, falling back to `/tmp/steel-chrome`, which is container-local and not the durable volume.
This design deliberately does not make that directory durable: a shared implicit profile would carry one flow's cookies into the next, which is wrong for eval isolation.
The explicit `sessionContext` store is the reuse path; a caller that wants a durable Chrome profile can set `CHROME_USER_DATA_DIR` under `/app/.cache` and owns that trade-off.

## 4. Client design (D395-2)

`src/polymerhus/app/steel_session_state.py` is the one construction point:

- `capture_session_context(session_id)` reads the context endpoint.
- `save_session_context(path, context)` writes it atomically through `app.atomic_write`.
- `release_session(session_id)` calls the release endpoint.
- `teardown_with_state(session_id, store_path)` runs capture, store, release **in that order**, and **always releases** even when the capture fails; it then raises a typed `SteelStateError` naming the released-but-unsaved outcome.
- `restore_session(store_path)` reads the store and creates a session with `sessionContext`.
- `create_session(context, fields=...)` is the lower-level restore/create seam.

The endpoint comes from the shared resolver, so the client never owns an address.
`STEEL_API_KEY` rides the `Authorization` header when set; the local runtime ignores it.
Errors are typed, so a caller can distinguish "released but state lost" from "release failed".

The design is deliberately a caller-owned file store, not a server-side profile: the OSS API has no profile routes, and inventing one would fork the cloud contract.
The store path is the caller's policy: the `steel-cache` volume for a deployment-level store, or the session workdir for a per-flow store.

## 5. Residuals

- The API still ignores create-time `timeout` and reports `0`; that is upstream steel-dev/steel-browser#350 and is orthogonal to this fix (the CLI pin handles the client side, D359-10).
- Session state is only as fresh as the last capture; a capture after a navigation is required for localStorage and sessionStorage.
- The container init fixes reaping, not browser crashes; a crashed browser still surfaces through the release/health path.

## 6. Test tiers

- Unit: `tests/test_steel_session_state.py` (MockTransport; order, release-always, typed errors, resolver), `tests/test_steel_cli_scaffold.py` (scaffold fidelity, variadic fold).
- Integration: `tests/integration/test_steel_session_state_http.py` (a localhost stub API runs create, capture, teardown, restore over real HTTP).
- Mocked e2e: `tests/test_steel_exec_scaffold.py` drives the real gateway against the scaffold; `tests/e2e/test_steel_canonical_actions_mocked.py` runs the skill's `session-lifecycle.sh`, `interact-batch.sh`, and `catalogue.sh` verbatim against it.
- Live: `tests/e2e/test_steel_session_state_live.py` proves a cookie survives capture, store, release, and restore against the deployed runtime; it fails loud when the endpoint is unset.
- Deployment contract: `tests/eval/test_steel_deployment_contract.py` asserts `init: true`.
