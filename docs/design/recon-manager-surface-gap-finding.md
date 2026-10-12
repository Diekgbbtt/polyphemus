# Finding (W-c): why the ComfyUI-Manager API is absent from L0

Status: diagnostic, 2026-10-12. No code change in W-c; a follow-up ticket is filed.

## Question

Is a recon change required to capture the ComfyUI-Manager API, or does a clean
capture (W-a) already suffice?
The operator's premise: recon quality is already good.

## Evidence

- `eval/data/webexploitbench/comfyui/surface-map.md` states the Manager routes
  are `/manager/*` and the mirrored `/api/manager/*`
  (`POST /manager/queue/install` == `POST /api/manager/queue/install`).
- The comfyui project graph holds 290 Endpoints and the raw history 110,741
  flows; neither contains `/manager`, `/api/manager`, `/customnode`, or
  `comfyworkflows`.
- So the crawl reached the core surface (`/prompt`, `/object_info`, `/settings`,
  `/extensions`, ...) but never the Manager surface.
- The recon job chain is katana (`-d $KATANA_DEPTH -jc -kf robotstxt -fx -td`,
  a static crawler), `arjun` (parameter mining), `steel_crawl` (browser),
  `ffuf`, `httpx`, and friends.
- The Manager UI is a client-side tab of the ComfyUI frontend: its routes are
  fired by XHR when the tab is opened, not by any static link katana follows.

## Conclusion

Recon quality is good for the STATIC surface.
The Manager API is XHR-only, behind a client-side navigation, so it is invisible
to the static crawler and appears only if the browser crawler exercises the
Manager tab.
The absence is therefore a NAVIGATION-COVERAGE gap, not a crawler-quality
defect, and not something the W-a capture gate can fix (W-a removes noise from
the surface that was reached; it cannot add a route the crawl never touched).

The smallest change that makes the Manager API reachable is a crawl HINT, not a
crawler rewrite:
either seed the known Manager UI route into the crawl frontier, or instruct the
`steel_crawl` agent to walk the application's own named navigation (the tabs and
menus), since an XHR-only route is only ever discovered by exercising its
trigger.

This is filed as a follow-up ticket; it is deliberately not built in this
change, because it needs a live analysis run to verify and it is orthogonal to
the capture-integrity and degradation work.

## Consequence for the assigner

Until the navigation gap is closed, a Service whose surface lives behind a
client-side tab (the nine Manager Services) cannot be mapped by any analysis
query.
This is exactly the case the assigner's degradation branch (W-b) must handle
gracefully: bounded search, then an explicit `no_surface`, never a firehose
escalation.
