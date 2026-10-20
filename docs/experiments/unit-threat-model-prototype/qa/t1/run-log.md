# T1 run log - mock hunter (S4 run, 2026-10-17)

Scope: 13 loops iterated; one spec set written per loop under `output/`.
Inputs read: `input/loop-*.yaml`, `input/manifest.yaml`, the mock package (`qa/mock/`), and the class skills under `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`.
No target probing, no test execution, no lightrag; nothing under `trials/` or the measurement documents was read.

## loop-1 (SSRF, VUL1/F2)
- Skills loaded: `ssrf/SKILL.md`, `ssrf/no-response-egress-inference`, `ssrf/scheme-translated-command-execution`, `ssrf/header-gated-cloud-credential-read` (last one read, unused - no header/method influence evidenced).
- Discrimination boundary: destination class at fixed F2 (internal address space x attributable external origin x non-HTTP scheme dispatch); address encodings inside the internal class.
- Overlap/coverage: none / exhaustive.
- Degradations: none (payload OBSERVED end-to-end).

## loop-2 (LFI, VUL2/F3)
- Skills loaded: `path-traversal-lfi-rfi/SKILL.md`, `traversal-read`, `rfi-remote-include`, `lfi-include-execution`; wrapper-read mechanics cross-referenced from `ssrf/scheme-translated-command-execution`.
- Discrimination boundary: the URL component that escapes the two-literal denylist (authority component vs scheme-token/separator spelling); fault fixed at F3.
- Overlap/coverage: none / exhaustive.
- Degradations: class skill lacks a scheme-dispatch entity (path joins only) - carried structurally; fetcher URL-parser normalization for spelling variants declared as assumption.

## loop-3 (insecure-file-uploads, VUL3/F5)
- Skills loaded: `insecure-file-uploads/SKILL.md`, `upload-pipeline-deferred-trust`, `upload-server-execution`, `upload-toolchain-execution`, `upload-client-execution`.
- Discrimination boundary: the dimension of the unrestricted write (where / what / consumed by what); fault fixed at F5.
- Overlap/coverage: none / exhaustive.
- Degradations: upload-endpoint vocabulary mapped to fetch-and-store pipeline; collision semantics assumed (truncating open); load-side effect inferred, not executed.

## loop-4 (business-logic, VUL4/F1)
- Skills loaded: `business-logic/SKILL.md`, `value-domain-manipulation`, plus `async-boundary-abuse`, `concurrent-duplication`, `quota-window-slicing` read.
- Discrimination boundary: suffix-as-selector (unchecked branch existence vs terminal-literal predicate boundary and name-resolution differential); fault fixed at F1.
- Overlap/coverage: none / exhaustive.
- Degradations: predicate implementation unobservable (raw terminal-literal test assumed per P47); selector-to-ruleset mapping carried structurally.

## loop-5 (LFI, VUL2/F3)
- Skills loaded: `path-traversal-lfi-rfi/SKILL.md`, `traversal-read` (proc/caches enumeration from the parent).
- Discrimination boundary: read-target artifact class (process-state secrets vs identity/system files); bypass mechanics left to loop-2.
- Overlap/coverage: none / exhaustive.
- Degradations: scheme-dispatch entity absent from class skill (as loop-2); secret usability deployment-specific and validated by content shape; loop-5/loop-2 same fault, differentiated on read targets.

## loop-6 (path-traversal, VUL5/F5)
- Skills loaded: `path-traversal-lfi-rfi/SKILL.md`, `traversal-read` (+ include-extraction chain reference for consumed destinations).
- Discrimination boundary: escape geometry (reach frontier vs destination semantics of the landing location); fault fixed at F5.
- Overlap/coverage: none / exhaustive.
- Degradations: join semantics unobserved (declared per candidate); custom_nodes consumption chain inferred from P17 + stack semantics; mock stops at placement, never executes.

## loop-7 (business-logic, VUL6/F12)
- Skills loaded: `business-logic/SKILL.md`, `value-domain-manipulation`, `async-boundary-abuse`.
- Discrimination boundary: check-to-use gap shape (checked-but-unbound cross-entry substitution vs skipped-check branch degeneracy); fault fixed at F12.
- Overlap/coverage: none / exhaustive.
- Degradations: no gate-binding entity in class skill - carried structurally; substitution inventory read from getlist rather than assumed.

## loop-8 (csrf, VUL7/F9)
- Skills loaded: `csrf/SKILL.md`, `csrf-navigation-get`; `csrf-parser-differential` read, unused (slice is GET-shaped).
- Discrimination boundary: delivery context (no-context participant crossing on the GET route binding vs browser-mediated cross-site delivery); endpoints and effect fixed.
- Overlap/coverage: none / exhaustive.
- Degradations: no login surface - CSRF half tested as forced state change on a shared instance; browser harness outside the mock, observation defined at server state.

## loop-9 (class-less DoS, VUL8/F7)
- Skills loaded: none - no suite skill covers worker-crash DoS/robustness; structural reasoning from TA7, ET6/ET7, ES6/ES7, V4.
- Discrimination boundary: trigger value-type space vs stall blast-radius/recovery closure over the dynamic-state trust; fault fixed at F7.
- Overlap/coverage: none / partial (uncovered: irreversible worker death absent the ES7 recovery evidence).
- Degradations: skill absence (declared); halt mechanism unobserved, specs bound to observable signatures; single-sample trigger family.

## loop-10 (business-logic, VUL9/F8)
- Skills loaded: `business-logic/SKILL.md`, `value-domain-manipulation`, `concurrent-duplication` (read).
- Discrimination boundary: which transition's accounting invariant fails (append / drain / reset); fault fixed at F8.
- Overlap/coverage: none / exhaustive (ET5 composition decomposes into owned specs).
- Degradations: queue/accounting entities absent from class skill - structural transition split; intended counter semantics read from the payload's side-effect statements.

## loop-11 (information-disclosure, VUL10/F15)
- Skills loaded: `information-disclosure/SKILL.md`, `stored-artifact-disclosure`, `differential-oracle-disclosure`; `error-verbosity-disclosure` read, unused (no verbose failure channel in evidence).
- Discrimination boundary: what the anonymous read concludes (inventory metadata / temporal activity attribution / content bytes via sibling surfaces); fault fixed at F15.
- Overlap/coverage: none / exhaustive.
- Degradations: core-route candidate names not in the payload - runtime-confirmed assumptions with refused-matrix negative; panels/observability entities of the class do not apply to this stack.

## loop-12 (improper error handling, VUL11/F6)
- Skills loaded: `business-logic/SKILL.md` and `value-domain-manipulation` (per the payload's suite_class mapping); `information-disclosure/error-verbosity-disclosure` read as a malformed-class taxonomy reference, not used as the class skill.
- Discrimination boundary: pipeline stage (decode vs extraction/use) plus delivery path (/api mirror and framing families); fault fixed at F6.
- Overlap/coverage: none / exhaustive (slice bounded to the install handler family).
- Degradations: no error-handling class exists in the suite - mapping and stage split declared structural; only status/error-body-level modes observable.

## loop-13 (race-conditions, VUL12/F14)
- Skills loaded: `race-conditions/SKILL.md`, `idempotency-dedup-bypass`; `cross-service-consistency-race`, `optimistic-guard-evasion`, `single-request-fanout` read (single-process scope).
- Discrimination boundary: which transition pair interleaves (start x start / install x start / install x install); fault fixed at F14.
- Overlap/coverage: none / partial (uncovered: reset x drain, no anchor in the fault statement).
- Degradations: F14 and VUL12 ASSUMED (no concurrency probe run); narrow event-loop windows make negatives weaker than positives; distributed/cross-service entities inapplicable.

## Closing note
- Every spec set: one spec per sub-slice, no overlap found, coverage honest per loop (11 exhaustive, 2 partial with named uncovered regions), and every interpretation_guidance reads falsifiability on the symptom-absent side.
- Overlap and coverage checks were run per loop from the written YAML; no defect required re-entering DISCRIMINATE after the initial passes.
