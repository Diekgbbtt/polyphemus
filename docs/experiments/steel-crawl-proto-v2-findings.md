# steel_crawl prototype v2: findings

**Status:** experiment findings, 2026-11-02.
**Evidence:** `docs/experiments/runs/crawl-det1-202610...` and `crawl-det2-202610...`.
**Scope:** local Steel deployment, White Jotter target through two SSH tunnels, deterministic policy because Jev was unavailable.

## 1. Blocking environmental findings

### F1. The OpenCode Go lane does not host Jev

The lane base is `https://opencode.ai/zen/go/v1`.
`GET /models` returns 28 chat models and no Jev model.
`POST /systemone` with `jev-1.13`, `typesafe/jev-1.13`, `jev-1.13.0`, and `opencode-go/jev-1.13` returns `400 Model is unavailable`.
The OpenRouter key is over its credit cap: 15.00 granted and 15.20 used, so `typesafe/jev-1.13` returns `402 Insufficient credits`.
No TypeSafe key existed on the local host, the Steel host, or the eval host at the time of the deterministic runs.
Consequence: the Jev policy adapter was implemented but the measured iterations used the deterministic policy.

**Resolved route (2026-11-02).**
TypeSafe direct works with the new `API_KEY_TYPESAFE` in `/Users/diekgbbtt/polymerhus/.env`.
`POST https://api.typesafe.ai/v1/systemone` with `model=jev-latest` returns `jev-1.14.0`.
The OpenAI SDK low-level `post(..., cast_to=object)` is the transport.
The chat path returns 404.
LiteLLM 1.96.0 has no TypeSafe provider, and the `openai/` route returns 404.
The direct client is `src/polymerhus/app/llm/typesafe.py` on branch `fix/typesafe-systemone`, commit `214b53f0`.
The evidence is in `docs/experiments/typesafe-provider-integration.md`.
The deterministic runs remain the baseline; the Jev crawl rerun is the next step.

### F2. Raw CDP needs the Docker gateway, not the host loopback

The Steel browser runs inside `polymerhus-steel-steel-api-1`.
The container loopback is not the Steel host loopback.
The reverse tunnel must be exposed on the Docker bridge and reached as `http://172.20.0.1:49017`.
The raw CDP port is `9223`; `9222` binds `127.0.0.1` inside the container and is unusable through a published port.
Consequence: the two-tunnel topology needs a host-side forwarder from the Docker bridge to the reverse tunnel.
Recommendation: make the crawler network a first-class compose network and publish raw CDP only there.

## 2. Authentication findings

### F3. The HTTP oracle is not sufficient for the SPA

The cookie oracle passes: `GET /api/authentication` returns 200 `身份认证成功` with `redirected: false`.
The SPA route guard still redirects to `/login` because `localStorage.username` is absent.
A fetch-only login mints the cookie but does not satisfy the client-side guard.
The prototype sets `localStorage.username` after the fetch login and records `client_state_missing` if it is absent.
Consequence: the auth precondition must include the client state, or the authn skill must drive the UI login.
Recommendation: extend the authenticated-context contract with a client-state probe, and make the authn skill record it.

### F4. The target overview has no `auth_probe`

`overview.yaml` carries `login_endpoint` and `technical_conditions`, but no `auth_probe.url`.
The prototype logs `auth_probe_missing` and uses `/api/authentication` as the legacy gate.
Consequence: the spec's A4 is not satisfiable from the current AuthContext.
Recommendation: add `auth_probe.url` to the AuthContext schema and backfill the target data.

## 3. Projection and element-map findings

### F5. The CLI compact snapshot is not a sufficient projection

The CLI snapshot exposes 21 refs on the admin dashboard.
The DOM projection exposes 28 candidates with type, channel, selector, group, and fingerprint.
The CLI snapshot has no form fields, no selectors, no initiator semantics, and no group structure.
The prototype uses a page script; the spec's no-page-script rule is therefore not implementable for this app.
Consequence: I2 is contradicted by the target.
Recommendation: either accept a DOM projection channel, or extend the CLI snapshot with fields, selectors, and groups.

### F6. Most admin forms are Vue dialogs without `<form>`

Native forms exist only on `/login` and `/register`.
The user, role, book, banner, and article editors are dialogs or detached inputs with click handlers.
The prototype adds synthetic groups: a field set plus a nearby submit control.
Synthetic groups are noisier and can capture table checkboxes.
The article editor's submit control is zero-sized until the editor becomes dirty, so the editor is not discovered.
Consequence: the form unit under-covers the SPA surface.
Recommendation: define a first-class dialog-form unit and a visibility rule for deferred controls.

### F7. The submit control must belong to the form

The first deterministic run offered a synthetic search form and its `搜索` button as two candidates.
Jev or the policy could click the button and submit an empty search, bypassing the field contract.
The fixed projection removes the group's submit selector from the standalone candidates and classifies search as `read`.
Consequence: form ownership is a projection invariant, not a policy preference.
Recommendation: make submit-control ownership part of the element map and assert it in tests.

### F8. Declared form action and method drift from the network

The `/register` DOM form reports `action=/register` and `method=GET`.
The actual request is `POST /api/register`.
The declared endpoint and declared parameter position are therefore wrong.
The observed flow is the truth; the declared record is a low-confidence DOM hint.
Consequence: the graph can split one operation into a declared GET page route and an observed POST API route.
Recommendation: mark SPA declared endpoints `confidence=low`, and bind the declared fields to the observed endpoint after submission.

### F9. Repeated row controls need an instance identity

Six `移除` buttons on the role page share the same label and text.
A label-only semantic key offered only one of them.
The fixed key includes the DOM path, so all six are removed and counted.
Consequence: the consumed set must be instance-aware, not label-aware.
Recommendation: derive the instance key from a stable row identity, not a transient DOM path.

### F10. The target is stateful and shared

White Jotter has persisted probe articles and users from earlier evals.
The registration runs add users; the target is not reset between iterations.
Consequence: page content and IDs are not reproducible across runs.
Recommendation: record the target snapshot or reset the target volume for comparative runs.

## 4. Safety findings

### F11. Authz mutations are auth state

`批量添加用户` and `添加角色` are authz-state mutations.
A keyword set limited to login, password, and logout misses them.
The fixed classifier marks them `auth_state` and removes them before choice.
Consequence: the forbidden-category prompt must name authz state, not just authentication.
Recommendation: add role, permission, user-status, and user-password mutations to the safety taxonomy and the Jev prompt.

### F12. Removing a modal opener loses its hidden form

`添加角色` opens a dialog that contains the role form.
The safety pass removes the opener before the dialog opens.
The declared fields behind the dialog are never collected.
Consequence: S3 (collect in place) and the hidden-target model conflict.
Recommendation: add a collect-only opener step that opens the dialog, records the declared form, and closes it without submitting.

### F13. A safe label can hide an unsafe submit

A dialog submit control is often labelled `确定`.
The submit is safe by label and unsafe by context.
The group classifier must read the dialog title and field set, not the submit label alone.
Consequence: group-level safety labels are required.
Recommendation: classify at the form-group level and keep the submit label out of the decision.

### F13b. A cancel button issued an authz mutation

Evidence: det2 action `act_1793616426257_24`, button `取 消` on `/admin/user/role`, ground truth `safe`.
The click issued `PUT /api/admin/role` with status 200 and body `{"id":2,"name":"contentManager","nameZh":"内容管理员","enabled":true,"perms":[{"id":3,"name":"content_management","url":"/api/admin/content"}]}`.
The dialog form and its `确 定` group were removed as `auth_state`.
The `取 消` button was outside both group roots, so the label-based guard left it in the offer set.
Consequence: label-based safety is unsound. The safe/unsafe boundary must taint the whole dialog context, not each control.
The PUT was idempotent on role 2, so no data changed, but the boundary was breached.
The same click also issued `PUT /api/admin/role/menu` with body `{"menusIds":[1,2,4,8,9,10]}`.
Recommendation: mark every control inside an authz dialog as auth state; never click cancel or close controls.

**Correction (2026-11-02).**
The symbolic dialog-context guard and the authz hard guard are removed.
The cancel/close filter remains a projection exclusion, not an unsafety decision.
Jev owns the unsafety decision through `choose_removed`.

### F13c. Keyword safety over-removes content

Evidence: det3 removed a `CUSTOM` book card whose abstract contains the word `购买` (purchase).
The card is a safe book link; the classifier saw the purchase word and returned `payment`.
The `safety_precision` metric reported 1.00 because the ground truth is the same keyword heuristic; the metric is self-referential.
Consequence: the safe/unsafe boundary leaks in both directions. A keyword guard over-removes content and under-removes context-dependent controls.
Recommendation: treat the keyword guard as a test oracle, not the production policy; use a context-aware or semantic classifier and keep an independent manual label set.

## 5. Capture and output findings

### F14. The bootstrap flow leaks into the crawl graph

The passive sidecar starts before authentication and captures `POST /api/login`.
Without phase tags, `/api/login` appears as an observed crawl endpoint.
The fixed capture tags `bootstrap`, `oracle`, and `crawl`, and the graph projection uses crawl flows only.
Consequence: phase is part of the capture contract.
Recommendation: make `capture_phase` a required field on every flow and filter the manifest by it.

### F15. SPA routes have no document status

`/register` and `/admin/*` return the SPA shell with HTTP 404 or no matching document flow.
The page status is therefore null or 404 even when the route renders.
The prototype records `status_source=spa_shell`.
Consequence: page status is not a reliable page-health signal for SPAs.
Recommendation: add a route-health signal from the rendered view or the API envelope.

### F16. Field readback returns an object

`steel browser get value` returns `{"value": "..."}`, not a bare string.
The first run compared the object to the value and marked all five fields false.
The fixed code extracts `readback["value"]`.
Consequence: the executor contract must pin the readback shape.
Recommendation: add a golden test for `get value` on text, password, textarea, and select.

### F17. Form success and field coverage are different metrics

The register POST returned 200 with all five fields.
The first metric marked the form successful but field coverage 0/5 because of the readback bug.
A form can be successful while its field coverage is low.
Consequence: report submission success, fill coverage, and network field coverage separately.
Recommendation: keep all three in the crawl metrics.

## 6. Traversal and policy findings

### F18. Global navigation repeats on every page

The top menu is present on every page.
Menu items that navigate are normal candidates and are re-offered after each restore.
The visited-route check prevents re-opening a route, but the policy still spends actions on global nav.
Consequence: the DFS needs a global navigation cluster or a per-session consumed set.
Recommendation: treat the global nav as a shared component and consume it once per session.

### F19. No-op local-state candidates waste the budget

The dashboard exposes gauge labels `18%` and `12%`, a `Breadcrumb` wrapper, and a notification `Close` button.
The deterministic policy selects them as local-state actions; they change nothing.
The fixed projection filters chart, gauge, breadcrumb, and notification controls.
Consequence: the element map needs a no-op filter, not only a visibility filter.
Recommendation: add a rendered-effect classifier and a no-op counter to the policy feedback.

### F20. The Jev prompt contract is implemented but unmeasured

The adapter, `choose_removed`, `choose_chosen`, and `choose_value` questions follow the spec.
The direct TypeSafe probe executed a Choice question in 267 ms: `jev-1.14.0`, 365 input tokens, 40 output tokens, `$1.533e-05`.
The Jev reruns are complete.
`jev1` made 122 calls and cost `$0.014237`; `jev2` made 74 calls and cost `$0.009419`.
Both runs had zero Jev errors; p50 was 190 to 206 ms and p95 was 282 to 361 ms.
Consequence: the transport claim is closed; the policy quality claim is mixed.
Recommendation: keep the Jev client; fix the registration boundary, the search-form repeat, and the authz prompt.

### F21. Jev over-removes registration

`jev1` removed the `/register` form as auth state.
The deterministic ground truth treated registration as a safe write.
The Jev run attempted no registration form.
The form contract was exercised only by the deterministic runs.
The safety precision fell to 0.75.
Consequence: the spec did not say whether account creation is auth state.
**Fixed by decision:** account registration is a safe write, not auth state.
The Jev prompt now states this explicitly.
The final run tests the corrected prompt.

### F22. Jev removes destruction but misses authz

`jev2` removed 34 destruction controls without over-removal.
It missed `添加角色` and `批量添加用户`.
The hard guard caught both.
**Correction (2026-11-02):** the authz hard guard is removed as a general, defective mechanism.
The specified action-domain filters are the only safety categories.
Jev owns the authz and destruction decisions.
The final run measures Jev's own boundary without a compensating guard.

### F23. The library search form repeats

`jev1` submitted the library search group three times.
The group's consumed identity did not survive the search result state.
The form field `search` maps to the query key `keywords`; that mapping is correct and not a failure.
Consequence: a form can be submitted more than once per state, contrary to P4.
Recommendation: key the consumed form by the stable form identity and skip a duplicate after a successful submission.
The prototype now keeps a per-run submitted-form set and skips the duplicate.

### F24. The symbolic unsafety guard is removed

The `deterministic_safety` function was a general keyword classifier.
It over-removed the book card whose abstract contains `购买`.
It needed a special registration exception.
It missed context-dependent authz controls.
The spec already defines the action-domain filters: auth state, payment, and destruction.
A second general classifier duplicates and contradicts that responsibility.

The guard, the authz guard, and the post-action endpoint guard are removed.
`choose_removed` owns the decision.
The measurement uses a manual expected set and the observed network.
The labels never feed the policy.

Consequence: the residual risk is a Jev false negative.
That risk is accepted by design.
The final run measures Jev's own boundary.

### F25. Final Jev3 result

`jev3` is the final integrated run.

- 7 pages and 59 actions.
- 1/1 registration form, 5/5 fields, HTTP 200.
- 73/73 XHR responses and bodies.
- 35 destruction controls removed, all by Jev.
- 0 of 2 authz openers removed; both were clicked and opened dialogs.
- 0 observed unsafe endpoints and 0 authz mutations.
- No-op 25/49 local-state actions, 51.0 percent.
- No-op 25/59 all actions, 42.4 percent.
- Impact compliance 1.00.
- 153 Jev calls, 0 errors, `$0.017299`.

The registration safe-write prompt works.
The destruction boundary is clean.
The authz boundary is incomplete and carries the accepted residual risk.
The duplicate search fix is implemented but not exercised in this run.

`no_op_actions` counts executed local-state actions whose DOM signature did not change and which produced no new network flow.
It does not count candidate elements that were never acted upon.
The earlier tables divided it by all actions, which is the wrong denominator for the policy-effect question.
Both denominators are now reported.

The no-op audit is `docs/experiments/runs/crawl-jev3-20261102T154800Z/no-op-audit.md`.
The 25 no-ops are 10 repeated `编辑` table clicks, 7 current or expanded menu items, 4 current or selected role links, 3 custom or empty widgets, and 1 empty `取消选择`.
The 10 `编辑` clicks are stale table actions behind the open dialog overlay.
They are not hidden local or global state changes.
The 14 menu and role-link no-ops are redundant current or expanded controls.
They may change only an active class or Vuex selection, which the signature does not capture.
They are not crawl-relevant.

The signature is coarse: URL, title, body text length, and node count.
It can miss class, attribute, input, focus, scroll, localStorage, sessionStorage, and Vuex changes.
The 51 percent local-state rate is a crawl-relevant waste signal.
It may overcount UI-only changes, and it does not undercount structural changes.
The cheapest projection fix is to hide or consume the table behind an open modal and to exclude current or selected menu items.

## 7. Cheap high-yield edits

1. Fix the `get value` readback extraction. Done.
2. Make submit controls belong to their form group. Done.
3. Tag capture phases and filter the manifest. Done.
4. Make the consumed key instance-aware. Done.
5. Add authz state to the safety taxonomy. Done.
6. Filter chart, gauge, breadcrumb, and notification no-ops. Done.
7. Add the dialog-context safety rule and the cancel/close filter. Done.
8. Add a post-action unsafe-endpoint guard that aborts or rolls back. Done.
9. Wire TypeSafe SystemOne into the Jev policy. Done.
10. Treat registration as a safe write in the Jev prompt. Done and verified in jev3.
11. Fix the duplicate search submission. Done; not exercised in jev3.
12. Remove the symbolic unsafety guard and the authz guard. Done.
13. Remove the keyword false positive path with the guard. Done.
14. Add a coverage and effect signal to the policy. Pending; the no-op rate is 51 percent of local-state actions.
15. Decide the authz residual risk or add explicit authz examples to the prompt. Pending.
16. Add `auth_probe.url` to the AuthContext and check client state. Pending.
17. Add a collect-only modal opener for hidden forms. Pending.
18. Add a dialog-form unit for Vue editors. Pending.
