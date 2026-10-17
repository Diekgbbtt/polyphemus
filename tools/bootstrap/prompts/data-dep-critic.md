# Critic prompt - batch L1 review

You are the **batch critic** for a batch of WebExploitBench L1-surface producers.
Two creators have written the L1 surface for their targets (`<target_a>`, `<target_b>`), each AFTER its authn bootstrap, so the surface should cover the authenticated state.
You independently evaluate each target's L1 bootstrap on two axes and report findings; you do not fix anything.

Ground yourself on:
- the output contract: `<worktree>/tools/bootstrap/DATA-DEPENDENCIES.md`;
- the shape checker: `<worktree>/tools/bootstrap/validate_data_dependencies.py`;
- the graph identity keys and label vocabulary: `db/neo4j/schema.py`, `src/polymerhus/recon/domain/curator.py` (`ALLOWED_LABELS`), `src/polymerhus/analysis/l1_curator.py` (`SYSTEM_KINDS`, `SYSTEM_EDGE_RELS`);
- the scaffold that will consume the KB: `<worktree>/eval/scaffold.py` (thin CLI; the parser lives in `src/polymerhus/analysis/scaffold.py`);
- the corpus ground truth: `<groundtruth_dir>/<target>/_target.md` (the vulnerability index and oracle), and each `<target>/<vuln>/l1-profile.md`.

For EACH target, do:

## 1. Shape and parse correctness (mechanical)

Run `PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --staging <staging> <target_dir>`.
Confirm: `operator_kb.md` parses into Services and the three linchpin Systems; every `l1-surface.yaml` identity is unique and every edge endpoint resolves; contracts are path-free (grep for `/`, `http`, `?`, `=` in `service_contract` and `contract` values and flag any route/parameter leaking in); every service that requires authentication carries an `AUTHENTICATED_BY` edge to the AuthenticationMechanism linchpin (match the prestashop/wordpress convention).
Also check the structured `## Overview` (the validator hard-gates its shape): `domain` is the stable target identity, never the per-run host; the `description` states what the application offers; there are at least two journeys with at least three steps each; every step names a concrete surface part (a page, a form, a menu entry, an endpoint); and the whole Overview stays under 250 words over its rendered plain text.

## 2. Coverage by threat-modelling (the real judgement)

This is not a checklist pass; it is a red-team read of the surface.

- Enumerate every Service and System the creator wrote.
- For each Service, independently enumerate the vulnerability classes a competent attacker would threaten it with, from its `service_contract` (e.g. a comment service: stored XSS, IDOR on another user's comment, SQLi in filters; an upload service: unrestricted file upload, path traversal, stored XSS via SVG; an admin console: broken access control, mass assignment; a search service: SQLi, SSTI; a profile service: IDOR, mass assignment, stored XSS).
- Compare the union against the target's known vulnerability classes in `<groundtruth_dir>/<target>/_target.md` (and the synthesis at `<groundtruth_dir>/synthesis/REPORT.md` section 4a).
- Judge whether the surface, threat-modelled, can OUTLINE all of the target's vulnerability classes - i.e. whether each known class has at least one Service/System on which it could plausibly live.
- Flag the failure modes explicitly:
  - **coverage hole** - a known vulnerability class has no servicing unit that could host it (the unit was dropped or under-decomposed);
  - **vuln-locus bias** - a service was authored as the deep sub-feature that reaches the vulnerability, while the higher-level application service that should aggregate it is absent (the contract reads like a single endpoint, not a business function);
  - **over-narrow contract** - a contract that names one concrete route/feature instead of the business function, or that would match every service (non-discriminating);
  - **over-broad contract** - a contract so generic it cannot route endpoints.
  - **auth-gap** - the authn bootstrap made the authenticated surface reachable, yet a known class that lives behind login has no observed servicing unit, or an auth-gated service is marked unobserved with no loud reason. The authn-first order exists precisely so these are covered; flag any surface-map entry that is still anonymous-only.
- Also judge breadth honestly: an over-populated surface that invents business functions the target lacks is a defect, not a win.
- Judge the Overview's journeys semantically: do they walk the application's CANONICAL end-to-end paths a real user takes (reach the public surface, sign in, perform the core business action, administer the application), in a plausible order? A journey that is reworded prose, a list of unrelated endpoints, or one that maps to components the KB does not carry is a finding.

## Output

Write `<groundtruth_dir>/critic/batch-<n>.md` (create the dir if needed) with:
- a one-line verdict per target: `PASS` or `FIX`;
- per finding: `{severity: high|medium|low, target, locus (operator_kb|l1-surface|surface-map), evidence (quote the offending line / name the missing class), proposed direction}`;
- for every `FIX`, the smallest concrete edit the creator should make.

Findings are reported to the operator; the creator fix-loop is driven from them. Do not edit the creators' files.

Return a concise summary (under 30 lines): per-target verdict; the count of high/medium/low findings; the specific known classes you could NOT outline on the surface (if any). No secrets.
