# T2 run log - mock hunter, TestImplementationSpecs sets (S4)

Trial T2, loops 1-9. Payloads read from `qa/t2/input/`; class skills loaded as files from `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`. No live probing, no test execution, no lightrag query. Overlap and coverage checks run per loop, honestly.

Entry fields: loop id - skills loaded (files) - discrimination boundary chosen - overlap/coverage result - degradations.

## loop-1 (csrf: unauthenticated state-changing GET preference routes)

- Skills loaded: `csrf/SKILL.md`, `csrf/csrf-navigation-get/SKILL.md`, `csrf/csrf-form-post/SKILL.md`, `csrf/csrf-parser-differential/SKILL.md`, `csrf/csrf-login-fixation/SKILL.md`, `csrf/csrf-websocket-handshake/SKILL.md`.
- Discrimination boundary: delivery proxy x preference-route family (click navigation -> channel identity; silent markup -> db mode; script no-cors -> preview/policy; ordered pair -> composed state). No payload-string variants.
- Overlap: none. Coverage: exhaustive over TA-4's preference-route mutation space; out-of-unit POST queue actions (CF-6) and non-browser peer delivery named as exclusions/aspects.
- Degradations: (1) class-skill mismatch - the csrf ontology presumes cookie ambient authority while these routes require no cookie/session at all, so its SameSite/parser/websocket entities do not apply and the reasoning is carried structurally; (2) `/manager/policy/*` subroute names not observed in the payload, named as an assumption in loop-1-s3.

## loop-2 (xss: record fields title/author/version/id interpolated into shell markup)

- Skills loaded: `xss/SKILL.md`, `xss/xss-stored/SKILL.md`, `xss/xss-dom/SKILL.md`.
- Discrimination boundary: record field x escaping regime x sink element (raw untransformed author/version -> row formatters; transformed title -> title element and failure dialog; getmappings node records -> flyover bodyHtml). No payload-string variants.
- Overlap: none. Coverage: partial - the payload evidences no sink locus for the `id` field and no HTML sink for the DF-6 merge fields, so both are named as uncovered rather than covered speculatively.
- Degradations: (1) `id` field uncovered (no evidenced sink); (2) flyover/dialog sink wiring known only at template level per the payload evidence; exact element paths assumed and named in loop-2-s2/s3.

## loop-3 (xss: stored HTML/JS injection through description markup)

- Skills loaded: `xss/SKILL.md`, `xss/xss-stored/SKILL.md`, `xss/xss-dom/SKILL.md`.
- Discrimination boundary: injection context of the converter-generated markup (URL value vs attribute value) plus the retrieval stance (store-then-render). No payload-string variants.
- Overlap: none. Coverage: exhaustive over the description pipeline's reachable markup contexts; inert converter output and the closed raw-tag path named as non-regions.
- Degradations: (1) converter regex capture permissiveness is INFERRED in the payload, so the quote-breakout spec names it as an assumption; (2) cache freshness semantics evidenced only at TTL level, so the persistence spec keeps its claim at "later retrieval view".

## loop-4 (xss: URL-scheme injection into navigation links)

- Skills loaded: `xss/SKILL.md`, `xss/xss-stored/SKILL.md`, `xss/xss-dom/SKILL.md`.
- Discrimination boundary: consumption context of repository/reference (DOM-property href vs string-markup attribute) crossed with the record provenance route (remote channel vs local/installed metadata). No payload-string variants.
- Overlap: none. Coverage: exhaustive over V-3's navigation-binding surface as instantiated; out-of-unit queue consumption named as an exclusion.
- Degradations: (1) no string-built sink for the fields is directly evidenced, so the attribute-breakout spec is assumption-named with an explicit empty-region outcome; (2) the local DB's carriage of the fields is inferred from DF-2's metadata wording and named as an assumption.

## loop-5 (xss: third-party/transit injection through the notice fetch)

- Skills loaded: `xss/SKILL.md`, `xss/xss-stored/SKILL.md`, `xss/xss-dom/SKILL.md`.
- Discrimination boundary: control point of the notice trust failure (transport TLS verification, extraction framing, authored content). No payload-string variants.
- Overlap: none. Coverage: exhaustive over DF-4's notice flow from external source to shell DOM; the single shared client sink is undifferentiated.
- Degradations: (1) the extraction's exact parsing is unobserved, so the framing spec names a structural assumption; (2) the wiki's write controls are external to the unit and named as an authorship precondition rather than asserted as an edit vector.

## loop-6 (business-logic: catalogue identity / source state confusion)

- Skills loaded: `business-logic/SKILL.md`, `business-logic/async-boundary-abuse/SKILL.md`, `business-logic/concurrent-duplication/SKILL.md`; secondary: `race-conditions/SKILL.md` (TOCTOU window vocabulary only).
- Discrimination boundary: which unbound-identity clause the spec exercises (request-shape binding, display freshness across opens, the single-operator premise). No payload-string variants.
- Overlap: none. Coverage: exhaustive over TA-6/A-6's binding claims; decision-attribute misattribution (TA-8) rides as a consequence inside each spec; the mutation vector is preconditioned from the preference-write loop.
- Degradations: (1) window boundaries are stated in state terms (S1/S2/S5), not observed timings; (2) the client's reconciliation behaviour is inferred from assets, and a hidden refresh path is named as the falsifier for each spec.

## loop-7 (class-less: content-cache poisoning persistence)

- Skills loaded: none - the suite has no cache-poisoning class skill (`header-injection` covers HTTP cache/CRLF territory, not this server-side content cache). Structural reasoning from the payload's T5/S6/DTV-4 transitions (serve path, write-to-retrieve binding, revocation lifetime).
- Discrimination boundary: which cache trust step the spec exercises (serve/staleness, write provenance, revocation lifetime). No payload-string variants.
- Overlap: none. Coverage: exhaustive over the cache's trust steps; hash-collision behaviour named as outside the evidenced slice.
- Degradations: (1) no class skill matches (stated above); (2) cache internals evidenced at behaviour level only, so the specs keep behaviour-level claims.

## loop-8 (class-less: input validation / unhandled exception)

- Skills loaded: none - the suite has no input-validation class; closest neighbours (`information-disclosure`, `http-method-tampering`) cover other invariants and were not used. Structural reasoning from TA-7/DTV-6 and the observed 500.
- Discrimination boundary: input shape of `mode` (absent, malformed value, parser-ambiguous shape) crossed with route scope of the direct-indexing pattern. No payload-string variants.
- Overlap: none. Coverage: exhaustive over TA-7's evidenced parameter surface; traceback/error leakage named as the information-disclosure loop's territory, not a sub-slice here.
- Degradations: (1) no class skill matches; (2) the 500 reproduction is OBSERVED once and response stability plus per-route handler sharing are named assumptions.

## loop-9 (class-less: reverse tabnabbing through named-target anchors)

- Skills loaded: none - the suite has no reverse-tabnabbing class (`open-redirect` is the nearest name and does not cover opener-mediated navigation). Structural reasoning from IA-7/IA-8 markup evidence, DF-4, and browser context semantics carried as named assumptions.
- Discrimination boundary: anchor family (catalogue converter-generated vs notice third-party) crossed with target form (named 'blank' vs keyword '_blank'). No payload-string variants.
- Overlap: none. Coverage: exhaustive over the evidenced clickable markup families rendered by the shell; other shell links carry no evidenced attacker-influenced markup path.
- Degradations: (1) no class skill matches; (2) named-target opener retention is browser/spec dependent, so each spec reads actual context state and treats mechanism negatives as baselines; (3) the click requirement and markup influence are named per spec.

## Run closure

- All 9 loops completed: GROUND -> CLASS-SKILL -> PARAMETRISE -> SLICE -> DISCRIMINATE -> SPEC-WRITE -> AGGREGATE+CHECK -> CLOSE, one spec set per loop, per the output contract.
- Every output file re-parsed after writing; schema keys present; size caps honoured (`sub_slice`/`discrimination_note`/`proxy_technique`/`rationale` <= 500, `interpretation_guidance` <= 700, `chaining_advanced_note` present exactly when the axis is chaining-advanced).
- No probe, no test execution, no lightrag query, no read of the trial models, the measurement document, or the trial report. Writes confined to `qa/t2/output/` and this log.
