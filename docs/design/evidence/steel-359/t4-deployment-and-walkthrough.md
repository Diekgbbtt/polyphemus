# T4 (#393) - deploy the Steel runtime and prove internal reachability

Date: 2026-10-19. Host: `dj-viscon-workshop-1.vsos.ethz.ch` (192.33.91.87).

## Deployment

- Artifact: `eval/deploy/steel/docker-compose.steel.yml` (copied to `~/polymerhus-steel` on the host).
- Image: `ghcr.io/steel-dev/steel-browser-api@sha256:eb8567bac2221d2856923184cf693a08df9a488680431ebded73cab63aa181eb`.
- Container: `polymerhus-steel-steel-api-1`, up, publishing `0.0.0.0:3000->3000/tcp` and `[::]:3000`; 9223 container-internal.
- `DOMAIN=192.33.91.87:3000`; the API reports `websocketUrl = ws://192.33.91.87:3000/`.
- Volume `polymerhus-steel_steel-cache` mounted at `/app/.cache`.
- Target alias: `STEEL_TARGET_HOST=t-1fc05262.target`, `STEEL_TARGET_IP=46.224.225.245`.

Local check on the host:

```
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/v1/sessions   -> 200
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/v1/health     -> 200
```

## Destructive changes (operator-approved for T4)

- `docker stop juice-shop && docker rm juice-shop` (held `127.0.0.1:3000`).
- `systemctl stop nginx && systemctl disable nginx` (held 80/443, answered 502).

After: ports 80, 443, and 3000 free; no other container, image, or volume was removed. No prune ran.

## Allowlist (TCP 3000 at DOCKER-USER)

```
sudo ~/polymerhus-steel/allowlist.sh 46.224.225.245 213.55.240.40 2a04:ee40:214a:f500:9ce6:f07f:fafd:4b6b
```

Rendered rules:

```
-A DOCKER-USER -j POLYMERHUS-STEEL
-A POLYMERHUS-STEEL -s 46.224.225.245/32 -p tcp --dport 3000 -j ACCEPT
-A POLYMERHUS-STEEL -s 213.55.240.40/32 -p tcp --dport 3000 -j ACCEPT
-A POLYMERHUS-STEEL -p tcp --dport 3000 -j DROP
ip6tables:
-A POLYMERHUS-STEEL -s 2a04:ee40:214a:f500:9ce6:f07f:fafd:4b6b/128 -p tcp --dport 3000 -j ACCEPT
-A POLYMERHUS-STEEL -p tcp --dport 3000 -j DROP
```

Eval server probe: `200`. The admin IPv4 is the operator's egress address; the admin IPv6 is the SSH source.

## Negative probe (E1)

With a temporary top-of-chain drop in place:

```
sudo iptables -I DOCKER-USER 1 -p tcp --dport 3000 -j DROP
# from the eval server:
curl -sS -m 6 http://192.33.91.87:3000/v1/sessions
# -> exit 28, "Connection timed out after 6002 milliseconds"
sudo iptables -D DOCKER-USER -p tcp --dport 3000 -j DROP
# from the eval server: 200
```

## Internal reachability walkthrough

Target: `comfyui` on the eval server, reached through `ph-eval-front` (host :80) via the synthetic Host `t-1fc05262.target`.

- `ph-eval-front` gained `eval-target-t-1fc05262.target.conf` proxying to `host.docker.internal:48257`.
- The Steel container resolves the synthetic host to `46.224.225.245` and answers `200` through the front.

A Steel session started from the kali container (API create + CDP over the session `websocketUrl`):

```
SESSION_ID 933405fd-d09d-4312-b87a-787378a729ed
WEBSOCKET_URL ws://192.33.91.87:3000/
NAVIGATE {"frameId": "470529BC77AC2446D4CBCE943991F3F3", ...}
FINAL_URL http://t-1fc05262.target/
TITLE *Unsaved Workflow - ComfyUI
BODY 'Introducing Nodes 2.0 ... Unsaved Workflow ... Queue ... Manager ... 100%'
SCREENSHOT docs/design/evidence/steel-359/comfyui-session.png
RELEASED 933405fd-d09d-4312-b87a-787378a729ed
```

The CLI path to the same target also works for one-shot reads:

```
steel scrape http://t-1fc05262.target/ --local --json
-> success:true, title "ComfyUI", markdown "Queue size: X ... Batch count ..."
```

## The instance value

`/opt/polymerhus-dev/eval/instances/eval-server-1/.env`:

```
STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1
```

The file was backed up before the edit. The value is the CLI canonical form; the CLI reads it and the SDK resolver strips the one terminal `/v1`.

## Discovered blocker: the CLI interactive daemon against the local API

`steel browser start --local` (and every interactive action that rides it) fails against the pinned API image:

```
{"error":"Connection reset by peer (os error 104)","error_code":"internal_error","success":false}
```

Root cause, read from the steel CLI v0.4.4 source:

- The API's create response carries `timeout: 0` (the local runtime is single-session and has no session-timeout concept; `CreateSession` has no timeout field).
- `lifecycle.rs::get_session_timeout` returns `Some(0)` for that field.
- `daemon/server.rs` computes `expires_at = created + timeout`; with `timeout = 0` the expiry is "now", so the daemon exits on its first loop iteration with `[daemon] Session timeout reached, shutting down`. The front-end then reads the daemon socket after it closed and reports the reset.

`steel scrape` does not use the daemon, so it works. The API create/release and the CDP connection work when driven directly (see the walkthrough above).

This blocks only the CLI's interactive session path, not the deployment, the address seam, or the SDK path. It needs an upstream fix: treat `timeout == 0` as unlimited (or have the API echo a requested timeout). Tracked as #395.
