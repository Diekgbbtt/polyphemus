# #395 - the local interactive daemon failure: root cause and fix

*Recorded 2026-10-19 during the #395 diagnosis. The pin change is in `kali/postrun.sh` and `kali/mcp_server.py`; the regression guard is `tests/e2e/test_steel_interactive_local.py`.*

## Symptom

Against the pinned local Steel API, `steel browser start --local` answered:

```
{"error":"Connection reset by peer (os error 104)","error_code":"internal_error","success":false}
```

The daemon log held one line:

```
[daemon] Session timeout reached, shutting down
```

`steel scrape --local` worked, and the SDK path worked.

## Feedback loop

The loop ran the real pinned binary against the real deployed API and asserted the exact symptom.
It reproduced in about 1.7 s on the eval server's `kali` container:

```
docker exec ph-dd131acc-kali-1 steel browser start --session ph-repro1 \
  --session-timeout 300000 --local \
  --api-url http://192.33.91.87:3000/v1 --json
# exit 1, the ECONNRESET above
```

The same command with the same image and the same key is the regression guard.
`0.4.4` exits 1, `0.5.0-preview.6` exits 0 and serves a follow-on `navigate`.

## Instrumented evidence

### The wire request and response

Captured with `tcpdump -i lo port 3000` on `dj-viscon-workshop-1` while the pinned CLI ran.
The CLI sends a requested timeout:

```
POST /v1/sessions HTTP/1.1
content-length: 45

{"inactivityTimeout":120000,"timeout":123000}
```

The API answers `200` and reports `timeout: 0`:

```
{"id":"478b0463-...","createdAt":"2026-10-19T14:26:02.797Z","status":"live",
 "duration":0,"eventCount":0,"timeout":0,...,"websocketUrl":"ws://192.33.91.87:3000/"}
```

The next request in the capture is the CLI releasing the session it just created, 14 ms later (14:26:03.792 to 14:26:03.806).
That is the daemon giving up on its first loop.

### The server code path

The running image is `ghcr.io/steel-dev/steel-browser-api@sha256:eb8567ba...` (package version `0.5.3`).
`POST /v1/sessions` destructures the create body without `timeout`, and `CreateSession` in `sessions.schema.ts` has no such field.
`session.service.ts` initializes every session from a module-level `sessionStats` object whose `timeout` is `0`.
`resetSessionInfo` spreads that object last, so a requested timeout could not survive even if it were passed.
The API has no server-side expiry loop. `SessionDetails.timeout` is therefore always `0`.
Upstream tracks this server gap as steel-dev/steel-browser#350 (open) and PR #353 (open).

### The client code path

CLI `0.4.4`, `src/browser/lifecycle.rs::get_session_timeout` returns `Some(0)` for the response.
`src/browser/daemon/server.rs` computes `expire_epoch = createdAt + 0`, subtracts the 30 s `EXPIRY_BUFFER`, sees a deadline in the past, and sets `expires_at` to `Instant::now()`.
The `select!` resolves `expiry_sleep` on its first iteration, logs `Session timeout reached, shutting down`, drops the `UnixListener`, and releases the session.
The front-end's first socket write then sees a closed socket and reports `os error 104`.
Upstream fixed the mapping in steel-dev/cli PR #95 (merged 2026-07-06): both timeout helpers now collapse `0` to `None`.
No stable release contains that fix. `0.5.0-preview.6` (2026-09-12) is the first release that does.

## Falsification experiments

### The network is not involved

The same binary and command failed identically on the API host itself, over loopback:

```
./steel browser start --session diag-loop --session-timeout 300000 --local \
  --api-url http://127.0.0.1:3000/v1 --json
# {"error":"Connection reset by peer (os error 104)",...}
# [daemon] Session timeout reached, shutting down
```

No eval-server-to-dj-viscon path, NAT rule, or allowlist sits on that loopback call.
The deployed path uses the same TCP/HTTP protocol; it is not a cause.

### Only the `timeout` field is load-bearing

A throwaway HTTP proxy listened on `127.0.0.1:13000` and forwarded to the API.
It rewrote one byte sequence in JSON responses, `"timeout":0` to `"timeout":300000`; everything else passed through.
The daemon opens its CDP socket against `websocketUrl` directly, so the proxy did not touch the browser traffic.

With that single rewrite and the unmodified `0.4.4` binary:

```
steel browser start --session diag-rewrite --session-timeout 300000 --local \
  --api-url http://127.0.0.1:13000/v1 --json
# {"data":{"connectUrl":"ws://192.33.91.87:3000/",...,"remainingMs":299700},"success":true}
# exit 0; the daemon stays alive
steel browser navigate --session diag-rewrite ... http://192.33.91.87:3000/
# {"data":{"title":"","url":"http://192.33.91.87:3000/"},"success":true}
```

`navigate` then `snapshot` both succeeded over the same daemon.
Changing only the timeout field turned red into green, so the field is the cause and the daemon is the failing component.

### The browser process is healthy

While a preview-binary session was live on the internal target, the API container showed a live CDP page target:

```
$ docker exec polymerhus-steel-steel-api-1 curl -s http://127.0.0.1:9222/json/list
[ { "title": "ComfyUI", "type": "page",
    "url": "http://t-1fc05262.target/", ... } ]
```

The API log for the same window shows the normal lifecycle: `Launching new browser instance`, `Attached instrumentation`, `Navigation` to `http://t-1fc05262.target/`, and `request completed` with status 200.
The page errors in that log (`importScripts` on a `blob:` URL) come from ComfyUI's own workers, not from Steel.
The browser is not the failing component.

## The fix

The pin moved to `0.5.0-preview.6`, the first release containing upstream PR #95.
The requested `--session-timeout` now falls through to the daemon, which enforces it and releases the session when it exits.
The API still does not expire a session itself (upstream #350); a single-session local runtime accepts that residual until a stable release carries the server fix.
The regression guard is `tests/e2e/test_steel_interactive_local.py`: it starts a named session, asserts a positive `remainingMs`, then navigates `about:blank` over the same daemon socket.

## Side observation, not part of this fix

The API container held about 170 zombie Chromium processes (`ps` state `Z`, parent PID 1) after repeated session launches.
Node runs as PID 1 and does not reap orphaned Chromium children.
This is a resource-leak risk for a long-lived local runtime and is independent of the timeout failure.
