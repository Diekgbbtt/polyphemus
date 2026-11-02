# Jev3 no-op audit

**Run:** `crawl-jev3-20261102T154800Z`.
**Metric:** `no_op_actions`.
**Count:** 25.
**Denominator:** 49 local-state actions, 59 all actions.

## What the metric measures

`no_op_actions` counts an executed local-state action when all three hold.

- The action did not navigate.
- The DOM signature did not change.
- No new network flow arrived after the action started.

The signature is:

```text
sha256(location.href | document.title | document.body.innerText.length |
       document.querySelectorAll("*").length)
```

The metric does not use the network log to decide.
It uses the DOM signature.
The network log only suppresses the no-op when a flow arrived.

The metric does not count candidate elements that were never acted upon.
It counts actions the policy chose and executed.

## Composition

| Action type or name | Count | Classification |
| - | - | - |
| `编辑` | 10 | Repeated table edit clicks |
| `MENU_ITEM` | 7 | Current or already-expanded menu items |
| `ROLE_LINK` | 4 | Current or selected menu links |
| `CUSTOM` | 3 | Wrapper or empty widgets |
| `取消选择` | 1 | No selection to clear |
| Total | 25 | |

## The 10 `编辑` no-ops

The book page exposed 23 `编辑` buttons.
The policy clicked 23 of them.
The first clicks opened the edit dialog or changed the table state.
The last 10 clicks produced no state change.
The projection still reported 110 elements and no new network flow.

The table sits behind the open dialog overlay.
The later clicks are stale or occluded table actions.
They are not a hidden local or global state change.
They are ineffective attempts on a control that should have been consumed or hidden.

The defect is projection visibility: the table behind the modal is still offered.

## The 7 `MENU_ITEM` and 4 `ROLE_LINK` no-ops

These clicks target the current page, a selected menu, or an already-expanded parent.
The URL does not change.
The body text length and DOM node count do not change.
No network flow arrives.

They may change only an active CSS class or a Vuex menu selection.
The signature does not capture classes, attributes, focus, or Vuex state.
That UI-only change is not a crawl-relevant state change.
It does not reveal new surface, a new form, a new route, or a new flow.

## The 3 `CUSTOM` and 1 `取消选择` no-ops

The custom controls are a wrapper, an empty widget, and a submenu container.
The `取消选择` button has no selection to clear.
None changes a crawl-relevant state.

## What the signature can miss

The signature is structural and textual.
It can miss:

- class or attribute changes;
- input value and checkbox changes;
- visibility toggles with the same node and text lengths;
- focus and scroll position;
- `localStorage` and `sessionStorage` changes;
- Vuex or other in-memory global state.

A legitimate UI-only state change of those kinds would be counted as a no-op.
It would not be a crawl-relevant change.

The signature is also length-based for body text.
A content change with exactly the same text length would be missed.
That is unlikely for the 10 edit dialogs, which change the node count when they open.

## Conclusion

The 25 no-ops are not "local or global changes that the network failed to record".
The network is not the detector.
The 10 `编辑` no-ops are stale or occluded table clicks with no dialog change.
The 14 menu and role-link no-ops are redundant current or expanded controls.
The one `取消选择` no-op has nothing to clear.

The 51 percent local-state no-op rate is a real policy-waste signal for crawl-relevant effects.
It may overcount UI-only active-class or storage changes.
It does not undercount structural DOM or network changes.
It does not measure unacted candidates.

The effect signal in the implementation phase should use a richer fingerprint:

- full DOM or ARIA hash, not text length;
- visible dialog and overlay count;
- `aria-expanded`, checked, value, and focus state;
- `history.length` and the URL;
- `localStorage` and `sessionStorage` hashes.

The element map should also hide or consume the table behind an open modal and the current or selected menu items.
Those two projection fixes would remove most of the 25 no-ops without a policy change.
