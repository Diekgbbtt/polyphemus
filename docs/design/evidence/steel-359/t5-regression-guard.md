# T5 (#394) - reachability regression guard, red then green

Date: 2026-10-19. Host: the operator workstation (on the runtime allowlist), worktree `steel-local-359`.

## The guard

- Contract tier: `tests/integration/test_steel_endpoint_contract.py` (4 tests).
- Live tier: `tests/e2e/test_steel_internal_reachability.py` (1 test).

The contract test composes the resolver, the CLI gateway's `--local` injection, and the SDK provider over one `STEEL_BROWSER_API_URL` value.
The live test opens a real Steel session with the SDK (`base_url` plus `session.websocket_url`), navigates the internal `comfyui` target through the eval front, and asserts the final URL plus a rendered-title marker.

The live test never skips: a missing endpoint fails with a clear message.

## Green

```
STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1 \
STEEL_LOCAL_TARGET_URL=http://t-1fc05262.target/ \
STEEL_API_KEY=<key> \
PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_steel_internal_reachability.py -q
```

```
1 passed, 1 warning in 6.00s
```

## Red - runtime stopped

```
docker stop polymerhus-steel-steel-api-1
```

Same command as above:

```
E   steel.APIConnectionError: Connection error.
FAILED tests/e2e/test_steel_internal_reachability.py::test_local_steel_session_reaches_the_internal_target
1 failed, 1 warning in 1.85s
```

## Red - endpoint missing (never a skip)

```
env -u STEEL_BROWSER_API_URL STEEL_LOCAL_TARGET_URL=http://t-1fc05262.target/ \
  PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_steel_internal_reachability.py -q
```

```
Failed: STEEL_BROWSER_API_URL is required for the local reachability guard.
Set it to the deployed runtime (the CLI form, http://<host>:<port>/v1).
This live test never skips: a missing endpoint is a coverage failure.
1 failed
```

## Green - runtime restored

```
cd ~/polymerhus-steel && STEEL_DOMAIN=192.33.91.87:3000 \
  STEEL_TARGET_HOST=t-1fc05262.target STEEL_TARGET_IP=46.224.225.245 \
  docker compose -f docker-compose.steel.yml up -d
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/v1/sessions   # 200
```

Same live command again:

```
1 passed, 1 warning in 5.19s
```

## Contract tier

```
PYTHONPATH=src:kali .venv/bin/python -m pytest tests/integration/test_steel_endpoint_contract.py -q
```

```
4 passed, 5 warnings in 1.04s
```

## Cloud path unchanged

The guards do not touch the cloud assertions: `steel_provider` passes no `base_url` when the value is unset, and the existing provider/CLI suites stay green (see the T2 review record).
