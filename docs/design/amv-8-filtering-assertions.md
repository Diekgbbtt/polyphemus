# Assertions - work-item "AMV-8 end filtering system (crawl/parse noise gate)"

**Source:** `docs/design/after-mvp-work-items.md` AMV-8; the six tracer-bullet slices agreed 2026-07-23.
**Seams under assertion:**
- `classify_endpoint(path, has_params)` - the pure path classifier (unit seam, extended by every slice).
- `filter_deltas(deltas, scope_domain)` - the central curator-gate hard filter, the "end filtering system" observable (contract seam).
- `katana_parser.parse` / `jsluice_parser.parse` -> `filter_deltas` - a real tool stdout flowing through the gate to a terminal node census (walkthrough seam).

These predicates are the verification GATE for AMV-8.
They are derived from the operator's stated junk taxonomy, not from the code, and stay RED until every slice they range over is built.
Expected kept/dropped sets are the operator intent (an independent source of truth), never recomputed the way the classifier computes them.

## Reconciliation notes (bind the ambiguous decisions before mechanising)

- **Drop model:** hard-drop at the gate, no new Endpoint prop/label (operator, Q2).
  The "distinct static-asset class" is internal to the classifier: a generated chunk is *treated* differently from a primary bundle, but the outcome is still keep-or-drop.
- **Media / archive extensions (category 1):** join the D15 recall-biased class (like images), NOT the hard-static class.
  A `.mp4`/`.pdf`/`.zip` under a drop-path or otherwise-static context drops; the same extension under a `PRESERVE_SEGMENT` (`/upload/`, `/downloads/`) or at an ambiguous root is KEPT, because those can be user-uploaded content (SSRF / stored-file surface).
  Truly-presentational families (fonts, stylesheets, sourcemaps) stay hard-static as they already are.
- **Primary vs generated JS (category 2 / ticket 3):** refine the D17 "never drop `.js`" exemption.
  A `.js`/`.mjs` is KEPT (jsluice's recon target) unless it carries a *generated/vendor* structural signal - a drop-segment (`node_modules`, `_next`, `chunks`, `vendor`, `dist`, `build`), a bundler/chunk marker (`chunk`, `runtime`, `polyfill(s)`, `vendor`), a content hash, a numeric-only chunk name, or a known third-party vendor-bundle name - in which case it drops.
- **CDN / third-party hosts (category 5):** already dropped by the existing `scope_domain` out-of-scope gate; asserted only as a regression that the new rules COMPOSE with scope.

## Contract predicates (gate)

C1  filter_deltas, cache-bust outlier (ticket 1): an Endpoint whose only query is a
    cache-bust key (`/main.css?v=15`, url in props) no longer escapes the static
    drop via the has-params short-circuit - it is classified static and DROPPED
    (0 Endpoints kept), while `/api/users?id=5` (a real param) is KEPT; and the
    cache-bust key mints NO `Parameter` delta (a `v`/`cb`/`t`/`hash` param is not
    surface), whereas `id` still mints exactly one Parameter.

C2  filter_deltas, static media/archive (ticket 2): given `/assets/promo.mp4`,
    `/downloads/report.pdf`, `/clip.webm`, exactly one survives - `/downloads/
    report.pdf` (under the `downloads` PRESERVE segment); `/assets/promo.mp4`
    drops (under `assets` drop-path) and `/clip.webm` at root is KEPT (recall
    bias). Kept Endpoint paths == {`/downloads/report.pdf`, `/clip.webm`}.

C3  filter_deltas, primary-vs-generated JS (ticket 3, the sharp one): given
    `/main.js`, `/app.js`, `/chunks/3458.js`, `/_next/static/chunks/abc.js`,
    `/runtime.js`, `/polyfills.js`, `/vendor.js`, exactly two survive -
    `/main.js` and `/app.js` (primary bundles, jsluice input); the other five
    drop as generated/vendor. Kept == {`/main.js`, `/app.js`}, dropped count 5.

C4  filter_deltas, browser + analytics junk (ticket 4): given `/favicon.ico`,
    `/robots.txt`, `/manifest.json`, `/site.webmanifest`, `/browserconfig.xml`,
    `/apple-touch-icon.png`, `/gtag/js`, `/collect`, `/beacon`, `/pixel`, and
    `/api/login`, exactly one survives - `/api/login`. The other ten drop.

C5  filter_deltas, jsluice concat fragment (ticket 5): an Endpoint minted from a
    jsluice string-concatenation pseudo-path (`/'+_(i[8])+'`, `/%27+_%28i%5B11%5D`)
    is DROPPED (never a node), while a genuine jsluice path (`/api/data`) is KEPT.
    Kept == {`/api/data`}.

C6  filter_deltas, idempotency + no-orphan + empty-valid (cross-cutting): running
    a junk-laden batch through filter_deltas twice yields the identical kept set
    (idempotent, pure); a dropped static Endpoint is param-less by construction so
    no `Parameter` delta is orphaned by its removal (a `/assets/app.css` batch
    keeps 0 Parameters); and an empty batch yields `[]` (a zero result is a
    result, not an error).

C7  curate, scope composition regression (ticket coverage of category 5): a CDN /
    third-party host Endpoint (`https://cdnjs.cloudflare.com/x.js`) is dropped by
    the existing `scope_domain` gate even though it is a `.js`, and the new
    category drops compose with it - within-scope junk still drops, in-scope real
    surface still survives. curate returns merged==(count of in-scope survivors).

## Walkthrough predicates (end-to-end: real parser -> gate -> census)

E1  grounds AMV-8 "junk never becomes an Endpoint", katana path.
    Input: a katana `-jsonl` stdout of 12 crawled requests against
      `scope_domain="juice-shop.test"`, one line each:
      `/juice-shop/node_modules/express/lib/router/index.js`,
      `/main.js`, `/polyfills.js`, `/chunk-3458.js`,
      `/soljson-v0.8.21+commit.a1b2c3d4.js`, `/ethers.js`,
      `/assets/logo.svg`, `/favicon.ico`, `/robots.txt`,
      `/main.css?v=14`, `/api/Products`, `/rest/user/login`.
    Path:
      katana_parser.parse -> 12 Endpoint(+BaseURL) deltas
        -> filter_deltas(scope_domain="juice-shop.test"):
           node_modules path -> drop (segment);
           polyfills.js / chunk-3458.js -> drop (bundler/chunk marker);
           soljson-...a1b2c3d4.js -> drop (content hash);
           ethers.js -> drop (known vendor-bundle name);
           /assets/logo.svg -> drop (image under drop-path);
           favicon.ico / robots.txt -> drop (browser-generated basename);
           /main.css?v=14 -> drop (cache-bust stripped, static css);
           /main.js -> KEEP (primary bundle);
           /api/Products, /rest/user/login -> KEEP (real API surface).
    Terminal:
      kept Endpoint paths == {`/main.js`, `/api/Products`, `/rest/user/login`}
        (3 Endpoints); 9 dropped; the surviving BaseURL(s) intact; 0 orphaned
        Parameters; noise fraction of emitted Endpoints == 0.

E2  grounds ticket 5 "jsluice concat fragments never become Endpoints", with
    secrets preserved.
    Input: a jsluice `urls`/`secrets` interleaved stdout:
      `{"url":"https://juice-shop.test/api/graphql","method":"POST","type":"fetch"}`,
      `{"url":"https://juice-shop.test/'+_(i[8])+'","method":"GET"}`,
      `{"kind":"aws-access-key","data":{"secret":"AKIAEXAMPLE..."},
        "base_url":"https://juice-shop.test"}`.
    Path:
      jsluice_parser.parse -> [Endpoint(/api/graphql), Endpoint(concat), Secret]
        -> concat pseudo-path rejected at parse OR at the gate
        -> filter_deltas.
    Terminal:
      kept Endpoint paths == {`/api/graphql`} (1 Endpoint); the concat fragment
      appears in 0 deltas; exactly 1 Secret (redacted, `value_hash` set) kept.

E3  grounds AMV-8 "on a re-run the noise fraction stays dropped" (MERGE
    convergence over the cleaned surface).
    Input: E1's katana sample run through curate(merge_fn capture) TWICE.
    Path: katana_parser.parse -> curate -> merge_fn; replay the identical batch.
    Terminal:
      both runs merge the identical set; the second run adds 0 new Endpoint
      identities (idempotent MERGE); merged Endpoint count == 3 on both runs.

## Mechanisation

`tests/recon/test_amv8_filtering_gate.py` realises C1-C7 and E1-E3 against the
real classifier, gate, and parsers.
Each test cites the predicate id it realises.
The tests are the AMV-8 completion gate: RED until the slice they range over is
built, GREEN when the end filtering system drops the operator's junk taxonomy.
