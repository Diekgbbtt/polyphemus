# ADR: arjun rides the endpoint-batch packing seam (#37)

## Status
Accepted (2026-10-05).

## Context
- On the jetlinks-1 eval target, arjun's consumption set after route-cluster
  dedup still held 168 distinct endpoints (127 of them `.js`). `_path_template`
  collapses only pure-numeric / long-hex segments, and the D15 curator gate
  keeps `.js` for jsluice, so neither filter catches these paths.
- arjun was `pack="none"`: one pod per endpoint. At `--rate-limit 5` each URL
  costs ~21-52s, so 168 pods is the dominant cost of the phase.
- The deployed kali MCP server was still the pre-`9119348` blocking build, so
  the 20-wide pod fan-out serialized on one event loop; the job ran 62+ minutes.
- The jsluice batching seam (`build_batch_assets` -> `reduce_endpoints` +
  `build_batches`) already reduced and packed a high-volume per-item job into
  `<= MAX_PODS` pods.

## Decision
1. arjun's `JobSpec.consumption.pack` is `batches` (was `none`).
2. The reduction is endpoint-generic: `bundle_url`/`reduce_bundles` are renamed
   `endpoint_url`/`reduce_endpoints`, and the module takes any list of asset
   dicts that carry a URL.
3. The batch-command seam is `build_batch_command(job, batch, *, session_id,
   extra)`; it dispatches to `build_jsluice_command` or the new
   `build_arjun_command`.
4. `build_arjun_command` runs arjun once per batch pod over `-i <import file>`
   (one URL per line). It seeds `printf '{}'` (arjun writes no `-oJ` file on a
   zero-findings batch) and suppresses stdout (`>/dev/null`), and serializes the
   auth feed's flat projection to arjun's `--headers` flag.

## Consequences
- arjun's per-pod batch is bounded to `max_batch_size` (4) URLs, and the derived
  set to `max_batch_size * MAX_PODS` (one wave), so every pod finishes under
  `EXEC_TIMEOUT_S=300`.
- The bound is load-bearing, not cosmetic: the first cut used jsluice's
  unbounded round-robin and packed ~250 URLs into one pod on jetlinks (1236
  endpoints / `MAX_PODS=5`), so every pod timed out (3x300s) and the job came
  out `degraded`.
- The reduction now applies the first-party filter and the exact-URL /
  fingerprinted-basename dedup to arjun, previously jsluice-only.

## Alternatives considered
- **A `max_assets` cap** (slice the derived set to N pods): rejected - it drops
  endpoints instead of covering them.
- **Removing arjun from PHASES**: rejected - loses all parameter discovery.
- **A fuzzy / similarity path dedup**: rejected - no such logic ever existed in
  the repo. The recalled fix is this seam.

## References
- #37 (arjun consumption set), #320 (MCP non-blocking fix), #321 (analysis L1 gap).
