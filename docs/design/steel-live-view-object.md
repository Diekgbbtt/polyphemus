# Steel live-view object and addressability

Date: 2026-10-29.
Scope: the feature that returns a URL to a live Steel browser, and the client-side object that should own it across a session lifecycle.
Branch: `fix/395-runtime-stress-hardening`.

## 1. What the stack actually returns

The URL is an already-evaluated resource attribute.
No layer derives it from the session id.

| Layer | Field | What it is |
|---|---|---|
| CLI `steel browser sessions --json` | `viewerUrl` | The same base for every live session. |
| CLI `steel sessions get --session <name> --json` | `sessionViewerUrl` | The same base again. |
| Same record | `debugUrl` | `/v1/sessions/debug`, a working "Steel Session Player" page. |
| Same record | `debuggerUrl` | `/v1/devtools/inspector.html`, a DevTools redirect. |
| Same record | `websocketUrl` | The CDP WebSocket, also a shared base. |
| CLI `steel browser start --json` | `liveUrl` / `connectUrl` | The same viewer and WebSocket bases. |
| SDK `Session` | `session_viewer_url` / `websocket_url` | The attributes the crawl provider reads. |
| Crawl provider | `_steel_crawl_start(...)["viewer_url"]` | `getattr(session, "session_viewer_url", "")`. |

The provider is not computing a URL.
It is passing through the SDK resource attribute.

## 2. What the live probe showed

Two live sessions, `wj-viewer-a` and `wj-viewer-b`, returned the identical values:

```text
viewerUrl        http://192.33.91.87:3000/
sessionViewerUrl http://192.33.91.87:3000/
debugUrl         http://192.33.91.87:3000/v1/sessions/debug
debuggerUrl      http://192.33.91.87:3000/v1/devtools/inspector.html
websocketUrl     ws://192.33.91.87:3000/
```

HTTP checks against those values:

| Route | Result |
|---|---|
| `/` | 404 `Route GET:/ not found` |
| `/v1/sessions` | 200, the API session list |
| `/v1/sessions/debug` | 200, a 66 KB "Steel Session Player" page |
| `/v1/devtools/inspector.html` | 302 to `/devtools/devtools_app.html?...`, then 404 |
| `/v1/sessions/<id>/viewer` | 404 |
| `/v1/viewer/<id>` | 404 |
| `/v1/sessions/<id>/live` | 404 |
| `/v1/sessions/<id>/stream` | 404 |
| `/v1/sessions/<id>/cdp` | 404 |

The player page's WebSocket is:

```text
ws://<host>:3000/v1/sessions/cast
```

Its JavaScript adds `?pageId=<page>` or `?tabInfo=true`; it never adds a session id.
The only `URLSearchParams` read in the page is `clipboardBridge`.
The page is shared and follows the active session.

The cloud form is different.
The test scaffold records `https://app.steel.dev/sessions/<id>` as a per-session viewer URL.
The cloud CDP fallback also carries `sessionId=<id>`.

## 3. The conclusion

The base URL being equal does not imply a deterministic per-session URL.
The self-hosted runtime exposes no session-addressed viewer route in this build.
The working player is shared.
Appending `?sessionId=<id>` would be an invented contract: the page ignores it, and the API returns 404 for the plausible path variants.

The only reliable per-session key is the runtime `id`.
The object should carry the id, the name, the view candidate, and an explicit `addressable` flag.
It should not publish the base as if it names one session.

If a truly per-session live view is required, the runtime needs one of:

- a viewer URL that names the session (the cloud form);
- a session-addressed cast route, such as `/v1/sessions/cast?sessionId=<id>`;
- a viewer service whose URL is configured per session.

That is a runtime change, not a client-side derivation.

## 4. The object

`src/polymerhus/app/steel_session.py`:

- `SteelLiveView`: `url`, `kind` (`viewer`, `player`, `debugger`), `session_id`, `session_name`, `addressable`, `healthy`, `observed_at`.
- `SteelSession`: the identity pair (`name`, `session_id`), `status`, `viewer_url`, `debug_url`, `debugger_url`, `websocket_url`, `created_at`, `remaining_ms`, `inactivity_timeout_ms`, `source`, `observed_at`.
  - adapters: `from_cli_catalogue`, `from_cli_start`, `from_api`, `from_sdk`;
  - `merge` fills gaps without erasing a newer observation;
  - `live_view` prefers an addressable URL, then the shared player, then the shared viewer, then the debugger;
  - `public_view` returns identity, status, and the view candidate, with no secret material.
- `SteelSessionRegistry`: name-keyed observations from start, catalogue, API, and stop; `appeared`, `updated`, `vanished`, `released` transitions; `live()` and `views()`.
  - It never starts, stops, or releases a session.
  - The lifecycle owner calls the observations.

The addressability rule is strict: a URL is addressable only when a path segment or a query value equals the session id.
A substring match is not enough.
A shared base is never addressable.

## 5. Where it is wired

- `SteelCrawlProvider._session_payload` returns the `SteelSession` and a `live_view` payload next to the backward-compatible `viewer_url`.
  The crawl tool result now carries `{crawl_id, frontier, viewer_url, live_view, auth_required}`.
- The crawl prompt tells the model to use `live_view.addressable` and never rebuild the URL.
- `skills/internal/tools/steel-browser/references/session-records.py` reports the same `live_view` shape, with `scope: session` or `scope: active`.
- `references/contract.md` documents the rule; the skill pins `live_view` and `addressable`.

## 6. Live evidence

The record script against a live session returned:

```json
{
  "live_view": {
    "url": "http://192.33.91.87:3000/v1/sessions/debug",
    "kind": "player",
    "session_id": "a20e1832-3cd2-4b91-8ffc-f0d46044bf4c",
    "addressable": false,
    "scope": "active"
  }
}
```

The base `sessionViewerUrl` was the same shared `http://192.33.91.87:3000/`.
The player was the working page; the base was 404.
The session id is the publishable identity.

## 7. Tests

- `tests/test_steel_session.py`: adapters, strict addressability, merge, registry transitions, public view.
- `tests/recon/crawl/test_steel_provider_endpoint.py`: the shared player and the cloud-addressable viewer in the provider payload.
- `tests/test_steel_skill_scripts.py`: the record script's `live_view` player and addressability.
- `tests/test_steel_skill_rule.py`: the skill and contract pin the decision.
