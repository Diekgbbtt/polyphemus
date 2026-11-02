# Experiment Results: steel_crawl prototype v2

## Summary

| Attribute | Value |
| - | - |
| **Experiment ID** | `steel-crawl-proto-v2` |
| **Experiment Name** | Authenticated full-surface crawl prototype, iteration 2 |
| **Status** | Completed with a resolved policy-route blocker; Jev crawls completed; policy quality mixed |
| **Duration** | 2026-11-02, three bounded runs |
| **Traffic Allocation** | Not applicable; engineering experiment |
| **Total Sample Size** | det1: 5 page visits, 19 actions, 1 form (partial); det2: 7 pages, 60 actions, 1 form; det3: 5 pages, 50 actions, 1 form; det4: 6 pages, 20 actions, 37 removed; jev1: 6 pages, 60 actions, 3 forms; jev2: 6 pages, 20 actions, 36 removed; jev3: 7 pages, 59 actions, 1 form; dialog probe: 1 dialog, 42 candidates |
| **Owner** | Crawl design workstream |
| **Design Doc** | `docs/design/steel-crawl-spec.md` |

## Hypothesis Recap

**Provider update (2026-11-02).**
The TypeSafe direct route is now verified.
`POST https://api.typesafe.ai/v1/systemone` with `API_KEY_TYPESAFE` and `model=jev-latest` returns `jev-1.14.0`.
The OpenAI SDK low-level `post(..., cast_to=object)` is the transport.
The chat client and LiteLLM both return 404 for this contract.
The deterministic runs below were measured before the provider switch.
The Jev crawl rerun is the next experiment.
See `docs/experiments/typesafe-provider-integration.md`.

**Metric definitions.**

`no_op_actions` counts executed local-state actions whose DOM signature did not change and which produced no new network flow.
It does not count candidate elements that were never acted upon.
The rate is reported two ways: `no_ops / local_state_actions` and `no_ops / all_actions`.

Form success is request dispatch plus a 2xx response.
The network field match is diagnostic only.
A filter field such as `search` that reaches the server as `keywords` is not a failure.
A duplicate submission of the same form fingerprint after a successful submission is a failure and is skipped.

**Safety ownership update (2026-11-02).**

The symbolic `deterministic_safety` function, the authz hard guard, and the post-action unsafe-endpoint guard are removed after `jev2`.
`choose_removed` is the sole unsafety decision owner.
The specified action-domain filters remain the only categories: auth state, payment, destruction.
Account registration is an explicit safe write in the Jev prompt.
The `jev1` and `jev2` safety recall and precision numbers were computed with the removed symbolic oracle and are historical.
The final `jev3` run uses Jev only.
Its measurement uses a manual expected set and the observed network.
Those labels never feed the policy.

**Original Hypothesis:**

> We believed that the v2 prototype, with the CLI action surface, a passive CDP sidecar, Jev-compatible decision questions, two-stage safety removal, and a synthetic form-group projection, would satisfy the crawl-plane requirements on the White Jotter target: successful form submissions with every field from the catalogue, complete XHR capture, a solid safe/unsafe boundary, and a traversal that prefers local-bound state changes over page changes.

The det2 run falsified one part of the hypothesis: the safe/unsafe boundary leaked through the role dialog's `取 消` button, which issued `PUT /api/admin/role`.
The det3 hypothesis is narrower: a dialog-context safety rule plus a cancel/close filter closes that leak, and the no-op filters reduce wasted local-state actions.
The no-op filter changes the DFS order, so det3 may not reach the authz pages that det2 reached.
A targeted det4 run seeds `/admin/user/role` directly to test the dialog guard without the traversal confound.

**Success Criteria:**

- Primary metric: form submission success rate 100 percent, field fill coverage 100 percent, network field coverage 100 percent.
- Safety: zero unsafe actions executed and zero observed crawl endpoints in the unsafe set.
- Capture: XHR response capture rate 100 percent and XHR body rate at least 90 percent.
- Traversal: impact-order compliance at least 0.80, with local-state actions preferred over navigation.
- No anonymous continuation after the auth precondition.

## Results

### Primary Metric: Form Contract

| Variant | Forms attempted | Forms succeeded | Field fill coverage | Network field coverage | 95% CI (success) |
| - | - | - | - | - | - |
| det1 baseline (partial) | 1 | 1 | 0/5 (0.00) | 5/5 (1.00) | 0.207 - 1.000 |
| det2 fixed | 1 | 1 | 5/5 (1.00) | 5/5 (1.00) | 0.207 - 1.000 |
| det3 no-op filter | 1 | 1 | 5/5 (1.00) | 5/5 (1.00) | 0.207 - 1.000 |
| det4 targeted authz | 0 | 0 | n/a | n/a | n/a |

**Interpretation:**

The registration form is a clean success in det2 and det3: HTTP 200, all five fields in the POST body, and all five fields read back.
The det1 field coverage is zero because `get value` returns `{"value": ...}` and the prototype compared the object to the typed value.
The network field coverage was already 5/5 in det1; the form was submitted correctly even while the readback metric was wrong.
This separates submission success from field verification: the form can be correct while the measurement is wrong.
Det3 repeated the form success with the no-op filters enabled, so the form path is stable across the projection changes.

### Secondary Metrics

| Metric | det1 | det2 | det3 | Threshold | Status |
| - | - | - | - | - | - |
| Pages | 5 (partial) | 7 | 5 | 6 | n/a | n/a |
| Actions | 19 (partial) | 60 | 50 | 20 | n/a | n/a |
| Local-state actions | n/a | 48 | 40 | 17 | n/a | n/a |
| Navigation actions | n/a | 13 navigated | 4 navigated | 9 navigated | n/a | n/a |
| Impact-order compliance | n/a | 1.00 | 1.00 | 1.00 | >= 0.80 | PASS (det2, det3, det4) |
| Removed elements | 3 | 39 | 1 | 37 | n/a | n/a |
| Safety precision | 1.00 | 1.00 | 1.00 (self-referential) | 1.00 | >= 0.90 | PASS with caveat |
| No-op actions | n/a | 34 (57%) | 28 (56%) | 5 (25%) | <= 10% | FAIL (det2, det3); det4 targeted |
| Form method mismatches | 1 | 1 | 1 | 0 | 0 | FAIL (det2, det3) |
| Declared endpoints | n/a | 2 | 0 | 0 | n/a | n/a |
| Observed endpoints | n/a | 26 | 20 | 21 | n/a | n/a |

The det2, det3, and det4 impact-order compliance is 1.00 because the deterministic policy always takes the lowest non-empty impact class.
The no-op count shows that compliance is necessary but not sufficient: 34 of 60 actions in det2 and 28 of 50 in det3 changed neither the DOM signature nor the network.
The no-op filter did not improve the rate; it changed which no-ops were visited and reduced the safety coverage from 39 removed candidates to 1.
Det4's 25% no-op rate is not a clean comparison: the targeted seed visits admin pages with fewer no-op widgets, so the page class explains most of the change.
The form method mismatch is the `/register` form: the DOM reports `GET /register`, the network shows `POST /api/register`.

### Guardrail Metrics

| Metric | det1 | det2 | det3 | Threshold | Status |
| - | - | - | - | - | - |
| Auth precondition | authenticated | authenticated | authenticated | authenticated | authenticated | PASS |
| Unsafe actions executed | 0 | 0 | 0 | 0 | 0 | PASS |
| Observed crawl unsafe endpoints | n/a (no manifest) | 2 | 0 | 0 | 0 | FAIL (det2), PASS (det3 not reached), PASS (det4) |
| Anonymous API requests | n/a | 0 / 82 checked | 0 / 5 checked | 0 / 47 checked | 0 | PASS |
| XHR response rate | n/a | 87/87 (1.00) | 12/12 (1.00) | 50/50 (1.00) | 1.00 | PASS |
| XHR body rate | n/a | 87/87 (1.00) | 12/12 (1.00) | 50/50 (1.00) | >= 0.90 | PASS |
| Manifest v2 keys | n/a (no manifest) | all | all | all | all | PASS (det2, det3, det4) |
| Owned session stopped and catalogue clean | clean | clean | clean | clean | clean | PASS |

The det2 observed crawl unsafe endpoints are `PUT /api/admin/role` and `PUT /api/admin/role/menu`.
Both were issued by the single `取 消` button on the role edit dialog, which the label guard classified safe.
The dialog context was authz, so the structural guard now taints the whole dialog and filters cancel/close controls.
Det3 did not reach the authz dialog, so its zero leak is a coverage artifact, not a validation.
Det4 seeded `/admin/user/role` directly: 37 unsafe candidates removed, zero authz PUTs, and zero observed unsafe endpoints.
The targeted dialog probe opened the first role edit dialog: 42 candidates, two authz form groups, and all dialog controls classified `auth_state`; the raw cancel and confirm buttons were not offered.

## Jev Run: SystemOne Wired In

The general Jev run is `crawl-jev1-20261102T144953Z`.
It used `jev-latest`, which answered as `jev-1.14.0`.

| Metric | jev1 |
| - | - |
| Pages | 6 |
| Actions | 60 |
| Forms attempted / succeeded | 3 / 3 (library search only) |
| Fields filled | 6/6 |
| Network field coverage | 3/6 (0.50) |
| XHR/Fetch captured | 21/21 responses and bodies |
| Removed elements | 4 (3 unsafe, 1 safe) |
| Safety recall / precision | 1.00 / 0.75 |
| Unsafe actions executed | 0 |
| Observed crawl unsafe endpoints | 0 |
| Impact-order compliance | 0.967 |
| No-op actions | 27/60 (45%) |
| Jev calls / errors | 122 / 0 |
| Jev input / output tokens | 338,985 / 23,461 |
| Jev cost | `$0.014237` |
| Jev latency p50 / p95 | 206 ms / 361 ms |
| HTTP/3 flows | 11 |
| Anonymous API requests | 0/8 |

The Jev transport works.
The policy quality is mixed.

The Jev removed the registration form as auth state.
The deterministic ground truth classified registration as a safe write.
The Jev run therefore attempted no registration form and the form contract was exercised only by the deterministic runs.
The three submitted forms are the library search group, which was submitted three times.
That duplicate submission is a projection state bug.
The form's `search` field maps to the query parameter `keywords`, so network field coverage is 0.50.

The Jev removed `批量删除` correctly as destruction.
The hard guard removed `批量添加用户` as authz state, so the Jev missed one authz control.
The hard guard also removed the `奢侈与逸乐` book card because its abstract contains `购买`.
That is the same keyword false positive as det3.

The Jev no-op rate is 45 percent, which is lower than det2's 57 percent but still high.
The Jev impact-order compliance is 0.967, slightly below the deterministic 1.00.
The Jev cost is `$0.0142` for 60 actions.
The cost is cents per run, not fractions of a cent, but still small relative to the gateway handler complexity.

### Jev2: Targeted Authz

The targeted Jev run is `crawl-jev2-20261102T145838Z`.
It seeded `/admin/user/role` and answered as `jev-1.14.0`.

| Metric | jev2 |
| - | - |
| Pages | 6 |
| Actions | 20 |
| Unsafe controls removed | 36 |
| Removed by Jev | 34 (31 `移除`, 3 `批量删除`) |
| Removed by guard | 2 (`添加角色`, `批量添加用户`) |
| Safety recall / precision | 1.00 / 1.00 |
| Unsafe actions executed | 0 |
| Observed crawl unsafe endpoints | 0 |
| Authz PUTs | 0 |
| XHR/Fetch captured | 39/39 responses and bodies |
| Impact-order compliance | 1.00 |
| No-op actions | 6/20 (30%) |
| Jev calls / errors | 74 / 0 |
| Jev input / output tokens | 224,251 / 22,388 |
| Jev cost | `$0.009419` |
| Jev latency p50 / p95 | 190 ms / 282 ms |
| Anonymous API requests | 0/37 |

The Jev removed 34 destruction controls without over-removal.
It missed two authz controls, `添加角色` and `批量添加用户`.
The hard guard caught both in jev2.
The guard was removed after jev2; jev3 has no guard.
The Jev safety policy is strong on destruction and incomplete on authz.
The residual risk is accepted and measured without a compensating guard.

### Jev3: Final Integrated Run

The final run is `crawl-jev3-20261102T154800Z`.
It seeded `/admin/user/role` and `/register`.
`/register` was on top, so the safe-write form was exercised first.

| Metric | jev3 |
| - | - |
| Pages | 7 |
| Actions | 59 |
| Forms attempted / succeeded | 1 / 1 |
| Fields filled | 5/5 |
| Network field match (diagnostic) | 5/5 |
| Duplicate form skips | 0 |
| XHR/Fetch captured | 73/73 responses and bodies |
| Removed by Jev | 35 (31 `移除`, 4 `批量删除`) |
| Manual destruction recall / precision | 1.00 / 1.00 |
| Manual authz recall | 0.00 (0 of 2) |
| Authz openers clicked | 2 (`添加角色`, `批量添加用户`) |
| Observed crawl unsafe endpoints | 0 |
| Authz PUT/POST/DELETE | 0 |
| Anonymous API requests | 0/68 |
| Impact-order compliance | 1.00 |
| No-op local-state rate | 25/49 (51.0%) |
| No-op all-actions rate | 25/59 (42.4%) |
| Jev calls / errors | 153 / 0 |
| Jev input / output tokens | 411,882 / 36,916 |
| Jev cost | `$0.017299` |
| Jev latency p50 / p95 | 208 ms / 302 ms |

The registration safe-write fix works.
Jev did not remove the form.
The form returned HTTP 200 with all five fields.
The network field match is 5/5.

The Jev removed all 35 expected destruction controls.
It did not remove the two expected authz openers.
It clicked both openers, which only opened dialogs.
No authz submit was clicked, and no authz mutation reached the network.
The authz residual risk is visible and accepted.
There is no symbolic guard and no authz guard.

The duplicate search fix is implemented but not exercised in jev3 because the run did not reach the library search group.
The form method mismatch is one: the `/register` DOM method is GET and the observed method is POST.
That mismatch is diagnostic only.
Form success is request dispatch plus 2xx.

The no-op audit is `docs/experiments/runs/crawl-jev3-20261102T154800Z/no-op-audit.md`.
The 25 no-ops are:

- 10 repeated `编辑` clicks on the book table.
- 7 current or expanded `MENU_ITEM` controls.
- 4 current or selected `ROLE_LINK` controls.
- 3 `CUSTOM` wrapper or empty controls.
- 1 `取消选择` with no selection.

The 10 `编辑` no-ops are stale table clicks behind the open dialog overlay.
The projection still offered 110 elements and the dialog did not change.
The 14 menu and role-link no-ops are redundant current or expanded controls.
They may change only an active CSS class or Vuex selection, which the signature does not capture.
They do not reveal new surface, a new route, a new form, or a new flow.

The signature captures URL, title, body text length, and DOM node count.
It does not capture class, attribute, input, focus, scroll, localStorage, sessionStorage, or Vuex changes.
The 51 percent local-state no-op rate is a crawl-relevant waste signal.
It may overcount UI-only active-class or storage changes.
It does not undercount structural DOM or network changes.
It does not count unacted candidates.

The three Jev runs together made 349 calls.
They consumed 975,118 input tokens and 82,765 output tokens.
They cost `$0.040955`.
The token counts are recorded in the decision logs even though the calls bypass LiteLLM.

## Segment Analysis

### By Page Class

| Page class | det2 | det3 | det4 | Forms | Removed | Notes |
| - | - | - | - | - | - | - |
| Public shell | 1 (`/index`) | 3 (`/index`, `/jotter`, `/library`) | 1 (`/index`) | 0 submitted | 1 in det3 | Global menu, article cards, book cards |
| Registration | 1 (`/register`) | 1 (`/register`) | 0 | 1 native, 1 success | 0 | Five fields, all filled |
| Admin dashboard | 1 | 1 | 1 | 0 | 0 | Gauges, breadcrumbs, global menu |
| Admin user and role | 2 | 0 | 2 | 0 submitted; 2 dialog forms collected in det2 | 33 in det2; part of 37 in det4 | Authz dialogs, row edit and remove controls |
| Admin content | 2 (book, banner) | 0 | 2 (book, banner) | 0 | 6 in det2; part of 37 in det4 | Book and banner remove controls |

Det2 reached the authz pages; det3 did not.
Det3 reached the library and removed one book card because its abstract contains `购买`; that removal is a false positive.
The admin content article editor was not reached in any run.
The role dialog produced two synthetic form groups; both were removed as auth state and collected as declared forms.
Det4 reached the role, user, book, and banner pages and removed 37 authz or destruction controls with zero authz PUTs.

### Targeted Dialog Probe

The probe opened the first role edit dialog on `/admin/user/role`.
The page had 40 candidates and 9 edit buttons.
The dialog page had 42 candidates and 2 groups.
Both dialog groups were classified `auth_state`.
The raw DOM had a header close, `取 消`, and `确 定`.
The projection offered none of those three controls.
The probe result is `ok: true` in `docs/experiments/runs/dialog-probe-20261102T110352Z/probe.json`.

### By Impact Class

| Impact | det2 | det3 | det4 | Notes |
| - | - | - | - | - |
| local_state | 48 (80%) | 40 (80%) | 17 (85%) | Menus, dialogs, gauges, breadcrumbs |
| navigate | 12 (20%) | 10 (20%) | 3 (15%) | Menu routes, links |
| read | 0 | 0 | 0 | Search form not reached |
| write | 0 | 0 | 0 | Registration is recorded as a form action with DOM impact `navigate` |

The impact classes overlap in the action ledger: the registration form action has DOM impact `navigate` because the form reports GET; the observed request is a POST write.
The policy never chose a `read` action because the library search was not reached.
The local-state share is high, but 34 of 60 det2 actions and 28 of 50 det3 actions were no-ops.

### By Form Type

| Form type | Attempted | Succeeded | Field coverage | Notes |
| - | - | - | - | - |
| Native form | 1 (det2, det3), 0 (det4) | 1 | 5/5 | `/register`, HTTP 200, POST `/api/register` |
| Synthetic dialog | 0 | 0 | n/a | Role edit dialog removed as auth state; 9 declared fields, positional names |
| Synthetic search | 0 | 0 | n/a | Library search not reached |

The role dialog's declared fields are `field_0` to `field_8` plus `content`; the DOM labels are Chinese and the name inference fell back to position.
The declared endpoint is `POST /admin/user/role`, a page route, not the API endpoint.
This is the declared-versus-observed drift described in F8.
The dialog probe confirms the dialog form groups are discovered and classified; the gap is naming and endpoint binding, not detection.

## Learnings

### What We Learned

1. **Jev is not reachable on the current lanes.**
   The OpenCode Go gateway does not host Jev, and the OpenRouter key is over its credit cap.
   The adapter is implemented; the measured policy is deterministic.

2. **The auth precondition needs client state.**
   The cookie oracle passes while the SPA route guard still redirects to `/login`.
   The client storage check is required.

3. **The form unit is a group, not a `<form>`.**
   The target has only two native forms; the admin surface is Vue dialogs.
   Synthetic grouping works when the dialog is open, but hidden openers lose the form contract.

4. **Submit-control ownership is a projection invariant.**
   Offering a form's submit button separately lets the policy bypass the field contract.

5. **Capture needs phases.**
   The bootstrap login is captured by the same sidecar; without phase tags it leaks into the crawl graph.

6. **Repeated controls need instance identity.**
   A label-only key removes one of six identical row buttons.

7. **Authz state belongs in the safety taxonomy.**
   `批量添加用户` and `添加角色` are authz mutations; they were removed after the fix.

8. **Declared SPA endpoints drift from the network.**
   The DOM form reports a page route and GET; the actual request is a POST API.

9. **Label-based safety is unsound.**
   The role dialog's `取 消` button issued `PUT /api/admin/role` and `PUT /api/admin/role/menu`.
   The dialog context was authz; the button label was safe.
   The structural dialog-context rule and the cancel/close filter are required.
   Det4 and the dialog probe validate the fix on the role dialog.

10. **Impact-order compliance is necessary but not sufficient.**
    Det2 scored 1.00 on impact order while 34 of 60 actions were no-ops.
    Det3 added no-op filters and the rate stayed at 56 percent.
    The policy needs an effect signal, not only an impact class.

11. **The boundary has two failure directions.**
    Det2 leaked unsafe mutations through a safe label.
    Det3 over-removed a safe book card because its abstract contains `购买`.
    A single keyword predicate cannot be both the policy and the oracle.

12. **The Jev route is resolved by TypeSafe direct.**
    `POST https://api.typesafe.ai/v1/systemone` works with `API_KEY_TYPESAFE` and `model=jev-latest`.
    The OpenAI SDK low-level `post(..., cast_to=object)` is the transport.
    The chat client and LiteLLM cannot carry this contract.
    The Jev reruns are complete; the transport works and the policy quality is mixed.

13. **Jev is a usable typed decision engine.**
    `jev1` and `jev2` made 196 calls with zero errors.
    Latency was 190 to 206 ms at p50 and 282 to 361 ms at p95.
    The answers arrived as typed Choices with probabilities and confidence.
    The Jev cost was `$0.023656` for both runs.
    The token counts were preserved in the decision logs without LiteLLM.

14. **Jev over-removed registration before the safe-write prompt.**
    Jev removed the `/register` form as auth state in jev1.
    The deterministic ground truth treated registration as a safe write.
    The prompt now states that registration is a safe write.
    Jev3 did not remove the form and submitted it once with 5/5 fields.
    The earlier precision of 0.75 is historical.

15. **Jev removes destruction well and authz incompletely.**
    `jev2` removed 34 destruction controls without over-removal.
    It missed `添加角色` and `批量添加用户`.
    The authz hard guard was removed after jev2.
    The final jev3 run measures Jev's own authz decisions.
    The residual risk is accepted by design.

16. **The library search form repeats.**
    The Jev run submitted the same search group three times.
    The group's consumed identity did not survive the search result state.
    Network field coverage was 0.50 because the form field `search` maps to the query key `keywords`.

### Surprising Findings

- The role edit dialog was detected as two synthetic form groups and both were removed as auth state.
- The role dialog's cancel button submitted a role update; the PUT was idempotent, so no data changed.
- The same cancel click also issued `PUT /api/admin/role/menu`.
- Det3 removed a safe book card because its abstract contains the word `购买`.
- The target returns HTTP 404 for valid SPA routes, so page status is not a health signal.
- The CLI `get value` readback is an object, which silently zeroed field coverage until fixed.
- The register form's declared method is GET while the observed method is POST.
- Det3 captured 8 HTTP/3 flows; the target does serve h3 for some resources.
- Jev removed the registration form as auth state.
- Jev removed 34 destruction controls in jev2 without over-removal.
- The Jev no-op rate is 45 percent on jev1 and 30 percent on jev2.

### What We Still Don't Know

- Whether the authz residual risk is acceptable or needs explicit authz examples in the prompt.
- Whether the duplicate search fix holds when the library search group is reached.
- Whether the modal opener can be collected without opening a mutation path.
- Whether the HTTP-history edge and graph curator accept the v2 manifest unchanged.

## Recommendation

### Decision: Iterate

**Rationale:**

The crawl plane works on the local deployment: the registration form succeeded with all five fields, the safety guard removed authz and destruction controls, the passive capture recorded the XHR/fetch surface, and the auth precondition failed closed when the client state was missing.
The structural dialog guard is validated by det4 and the focused probe: 37 unsafe candidates removed, zero authz PUTs, and no cancel or confirm controls offered.
The Jev route is verified and the reruns are complete.
The Jev transport works.
Jev3 verifies registration, destruction removal, and zero unsafe endpoints.
The Jev policy quality is mixed: it misses the two authz openers and still produces a high no-op rate.
The no-op local-state rate is 51.0 percent on jev3 and the all-actions rate is 42.4 percent.
The earlier rates were 56 to 57 percent on the deterministic general crawl, 45 percent on jev1, and 30 percent on jev2.
The form and safety gaps are design-level, not implementation accidents.

### If Iterating

- **What to change:** use the registration-safe-write prompt; fix the duplicate search submission; remove the symbolic and authz guards so Jev owns unsafety; add `auth_probe.url` and client-state checks; add a dialog-form unit; add a collect-only modal opener; bind declared fields to observed endpoints; add a global coverage and effect signal; keep an independent safety label set for measurement only.
- **Next experiment:** rerun jev1 and jev2 with the registration policy and the search-state fix, and compare coverage, form success, safety, and no-op rate against this baseline.

## Next Steps

1. Resolve the registration classification: either treat it as a safe write in the Jev prompt, or accept that it is auth state and exclude it from the form-success metric.
2. Fix the duplicate search submission and the `search` to `keywords` field mapping.
3. Remove the authz hard guard; Jev owns the unsafety decision. Measure its authz misses without a compensating guard.
4. Remove the keyword false positive that removes the book card whose abstract contains `购买`.
5. Add `auth_probe.url` to the White Jotter AuthContext and implement the client-state check.
6. Add the dialog-form unit and the collect-only modal opener.
7. Bind declared SPA forms to their observed network endpoint after submission.
8. Add a global coverage and effect signal to the policy, and keep an independent safety label set.
9. Rerun jev1 and jev2 with the registration and search fixes, and publish the comparison.
