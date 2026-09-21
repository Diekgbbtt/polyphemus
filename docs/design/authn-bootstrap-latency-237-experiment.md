---
artifact: experiment-results
version: "1.0"
created: 2026-09-21
status: draft
---

# Experiment Results: magnific browser-bootstrap latency (D237-13 fast path)

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | magnific-bootstrap-latency-237 |
| **Experiment Name** | Does the D237-13 browser fast path cut browser-bootstrap latency? |
| **Status** | Inconclusive (confounded by a target-side reCAPTCHA escalation) |
| **Duration** | 2026-09-20 (baseline) to 2026-09-21 (treatment), single run each |
| **Traffic Allocation** | n/a (n=1 control, n=1 treatment - not a statistical test) |
| **Total Sample Size** | 2 runs, 1 target (`magnific.com`) |
| **Owner** | operator session |
| **Design Doc** | `docs/design/authn-antiblock-replayability-237-decisions.md` D237-13 |

---

## Hypothesis Recap

**Original Hypothesis:**

> We believed that inlining the browser fast path in the authn skill and citing the steel-browser mechanics skill (D237-13) would cut browser-bootstrap latency, because the baseline run spent ~60-70 s on primitives the bootstrapper re-derived live from `steel --help`: a 26 s `networkidle` navigate timeout, three stale-ref snapshot round-trips (~35 s), and fixed `sleep`s.

**Success Criteria:**

- Primary metric: wall-clock to completion falls materially (target: the ~60-70 s of avoidable primitive cost).
- Guardrail: functional outcome identical (same `anti-bot`, same `http-client-replayability`, same account shape, same skill written, e2e predicates green).
- Guardrail: no new failure mode introduced.

---

## Results

### Primary Metric: wall-clock to completion

| Variant | Wall (s) | Tool exec (s) | Model gaps (s) | Human wait (s) |
|---------|----------|---------------|----------------|----------------|
| Control (run 1, baseline) | 394 | 108 (56 calls) | 153 | 0 |
| Treatment (run 2, fast path) | 1168 | 499 (64 calls) | 403 | 251 |

**Observed Difference:** +774 s raw (+196%). Human-wait-adjusted: 394 s -> 918 s (+133%).

**Statistical Significance:**
- Not applicable: one run per arm, and the environment changed between arms (see Confound).
- Confidence: LOW for the latency claim; HIGH for the primitive-usage claim.

**Interpretation:**

The raw wall-clock is **not a valid latency measurement of the fix**: run 2 faced a target-side reCAPTCHA escalation that run 1 did not, adding 251 s of human-in-the-loop solving plus a 90 s recovery loop of `wait --url /app` timeouts (three, 30 s each) while the challenge was open.
Stripping all reCAPTCHA-attributable time still leaves run 2 slower than run 1, so the fix does **not** show a wall-clock win in this comparison - the confound is larger than the effect the fix targets.

---

### Secondary Metrics - primitive usage (the fix's actual fingerprint)

These dimensions are confound-resistant: they count how the agent worked, not how long the target made it wait.

| Metric | Control | Treatment | Difference | Direction |
|--------|---------|-----------|------------|-----------|
| `steel --help` re-derivation calls | 5 | 0 | -5 | improved |
| `navigate --wait-until networkidle` uses | 1 | 0 | -1 | improved |
| Live stale-ref failures (`Unknown ref`) | 3 | 0 | -3 | improved |
| `batch` invocations | 0 | 8 | +8 | improved |
| `snapshot -i` uses | 0 | 6 | +6 | improved |
| Fixed `sleep` occurrences | 8 | 3 | -5 | improved |
| `wait --url/--text` condition uses | 0 | 5 | +5 | improved |
| Total tool calls | 56 | 64 | +8 | slightly worse |

**Interpretation:** Every primitive the fix targets moved in the intended direction. The agent stopped re-deriving the CLI (5 -> 0 `--help`), stopped using `networkidle` (1 -> 0), stopped failing on stale refs (3 -> 0), and adopted `batch` (0 -> 8), `snapshot -i` (0 -> 6), and condition waits (0 -> 5) while cutting fixed sleeps (8 -> 3). The tool-call count rose slightly (+8), explained by the reCAPTCHA recovery loop.

### Guardrail Metrics

| Metric | Control | Treatment | Threshold | Status |
|--------|---------|-----------|-----------|--------|
| e2e predicates | 6 passed / 1 skipped | 6 passed / 1 skipped | identical | Pass |
| `anti-bot` value | `waf:akamai` | `akamai_v3` | same classification family | Pass (see note) |
| `http-client-replayability` | false | false | identical | Pass |
| Account shape | 1 account, `procedure: sign-in` | identical | identical | Pass |
| Skill written at designed path | yes | yes | identical | Pass |
| Secret value leaked to skill/report | no | no | no leak | Pass |

---

## Segment Analysis

### By phase (tool-execution time)

| Phase | Control | Treatment | Note |
|-------|---------|-----------|------|
| Pre-login (probe, start, navigate) | ~50 s | ~162 s | treatment includes the `--help`-free read of the mechanics skill and more navigation |
| Login + verify | ~55 s | ~323 s | treatment dominated by reCAPTCHA retries (90 s of `wait --url` timeouts + human waits) |
| Post (store, skill, stop) | ~3 s | ~15 s | treatment verified the profile twice (extra session start/stop pairs) |

### Segment Insights

The regression is entirely inside the login/verify phase, and it tracks the reCAPTCHA gate, not the fast-path primitives (which improved in both phases where they applied).

---

## Learnings

### What We Learned

1. **The fix's primitive fingerprint is real and clean.**
   All seven targeted dimensions moved the intended way, and the three previously-measured failure modes (networkidle timeout, stale-ref retries, `--help` re-derivation) are gone.
   This is the strongest finding and it is confound-resistant.

2. **A target can escalate mid-experiment, and it did.**
   Run 1 hit an invisible challenge; run 2 hit a visible reCAPTCHA Enterprise image challenge requiring a human solve (twice).
   The bootstrap of a live, defended target is not a stable measurement substrate.

3. **`wait --url` before a human gate is a new failure mode.**
   The agent correctly replaced sleeps with `wait --url /app`, but because `/app` only appears after the reCAPTCHA is solved, the wait timed out three times (90 s) *waiting for a human step it could not see*.
   The mechanics rule "synchronise on an observable" needs a qualifier: do not synchronise on an outcome that depends on an out-of-band human action.

### Surprising Findings

- The stale-ref rate was reported as still-3 by a naive grep, but those hits were the *skill file text* documenting the `Unknown ref` rule; the true live failure count was 3 -> 0.
  Instrumentation must exclude document echoes.
- `akamai_v3` (run 2) vs `waf:akamai` (run 1): the treatment named the defence more precisely, using the `akbm_svc`/`ak_bmsc` evidence.
  Not a regression, but it means the two runs are not byte-comparable on that field.

### What We Still Don't Know

- Whether the fix yields a wall-clock win **absent** the reCAPTCHA confound. The primitive metrics say it should; this experiment cannot prove it.
- Whether the reCAPTCHA escalation is stable (every run now) or intermittent.

---

## Recommendation

### Decision: Iterate

**Rationale:**

The fix works at the level it was designed for (primitive usage and the three named failure modes), but this run cannot demonstrate a wall-clock improvement because the target's defence escalated and swamped the effect.
Do not claim a latency win on this evidence; do claim the failure-mode eliminations and the primitive adoption, which are directly observed and confound-resistant.

### If Iterating

- **What to change:** add the qualifier to the mechanics rule - a `wait` must not synchronise on a state reachable only through an out-of-band human action; where a human gate is possible, wait on the *challenge's own* marker (its iframe/selector) with a bounded timeout and escalate to the operator, rather than on the post-gate landing URL.
- **Next experiment:** re-run the same two arms when the target is not presenting a visible challenge, or measure **provider-side session/trace timestamps** (`steel sessions traces`) instead of agent wall-clock, so target-side human gates are excluded by construction.
- **Timeline:** next magnific touch, or a quieter WAF target (Cloudflare/DataDome variant) for a cleaner substrate.

---

## Next Steps

| Action | Owner | Due Date |
|--------|-------|----------|
| Add the "do not wait on an out-of-band human outcome" qualifier to the steel-browser mechanics skill | operator session | DONE - shipped in the mechanics skill's wait guardrail |
| Re-measure on a non-escalating target, using provider timestamps | operator session | next e2e |
| Keep D237-13 as shipped; do not claim a wall-clock win in the ledger | operator session | this change |

---

## Appendix

### Raw Data

- Run 1 (baseline) transcript: opencode session `ses_f3f19ffa6ffe2aYBs1wQH6pHhH`, project `602f457d-...`.
- Run 2 (treatment) transcript: opencode session `ses_f3d02c99fffefyimyuWcwwz3e5`, project `7854f57a-...`.
- Extracted metrics: `/tmp/magnific_parts.json`, `/tmp/run2_parts.json` (host scratch).
- Steel session (run 2): `219cb3bc-7d36-46b5-a5dc-1a68f9ad65e2` (viewer URL in the transcript).

### Statistical Methodology

- Not a controlled statistical test: n=1 per arm, single target, and a mid-experiment environmental change.
- Methodology used: deterministic transcript instrumentation (part-type timestamps from the opencode DB), identical for both arms; dimension counts are exact, not sampled.

### Known Issues

- The target's reCAPTCHA escalation is a confound that invalidates the wall-clock comparison.
- Run 2's agent and kali containers were bound to the #223 worktree while the fix lives in #237; the fix's live effect is in `skills/` (text the agent read from #237) and `kali/mcp_server.py` (not on the agent's raw-CLI path). The D19 tool guard was therefore **not exercised** by this run - the bootstrapper drives the raw `steel` CLI, so the `steel_exec` refusal never fires. The skill-text half of the fix is what this run measured.
- Wall-clock is agent-side and includes model latency, which varies by model load; provider-side timestamps would remove that variance.

---

*Results documented on 2026-09-21.*
