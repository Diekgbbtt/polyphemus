# P0: Steel CLI and a passive CDP sidecar

**Date:** 2026-10-31.
**Status:** passed on the local Steel deployment.

## Environment

- Host: `dj-viscon-workshop-1.vsos.ethz.ch`.
- Local Steel API: `polymerhus-steel-steel-api-1`, version `0.5.3`.
- Chromium: `155.0.8059.39`.
- Pinned CLI: `0.5.0-preview.6`, downloaded from the GitHub release and checksum-verified on the host.
- The macOS CLI `0.4.4` failed against the same local API with `Daemon disconnected unexpectedly`.
- Second client: macOS `.venv`, Python 3.13, `websockets 16.1.1`.

## Network change

The image exposes two Chromium ports.

- `9222` binds `127.0.0.1` inside the container. A published `9222:9222` mapping is reset by the kernel.
- `9223` binds `0.0.0.0` inside the container and returns the same raw CDP `json/version` payload.

The `steel-api` service in `/home/ubuntu/polymerhus-steel/docker-compose.steel.yml` now publishes `9223:9223`.
The stale comment that called 9223 container-internal is corrected.
The control path on 3000 is unchanged.

## The run

- The pinned CLI started the local session `p0-raw-cdp` with `--api-url http://127.0.0.1:3000/v1`.
- The session was `mode=local`, `remainingMs=298937`.
- The raw CDP page target was `ws://localhost:9223/devtools/page/238EB177A6BE9B1C157C65580DF1ABE1`.
- The second client enabled `Page`, `Network`, and `Runtime`.
- The CLI navigated to a `data:` fixture with a button that fetches a public URL.
- The CLI clicked `#b`.
- The CLI `get url` returned the fixture URL.

## Captured evidence

- Request: `GET https://httpbin.org/get?p0=1`.
- Initiator: `type=script`, `lineNumber=0`, `columnNumber=61`, `scriptId=10`.
- Response: `200`, `application/json`.
- Body: 686 bytes, with `args.p0 = "1"`.
- The document request for the `data:` fixture was also captured with status 200.

This is one CLI-triggered XHR captured end to end by the passive sidecar.

## Consequence

The passive CDP sidecar is viable on the local deployment when the raw CDP port is published.
The crawl prototype uses `9223` through an SSH tunnel on the macOS side.
The local session was stopped and the catalogue returned `{"data":[]}`.

## Session hygiene

- No target secret was recorded.
- The session name was owned by the run and stopped by name.
- The temporary connect and page files were removed after the run.
