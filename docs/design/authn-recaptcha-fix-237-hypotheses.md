---
artifact: hypothesis
version: "1.0"
created: 2026-09-21
status: draft
---

# Hypothesis: challenge-free browser bootstrap (reCAPTCHA fragility)

This document follows `define-hypothesis` for the claim and `debug-hypothesis` for the loop (Observations -> Hypotheses -> Experiments -> Conclude).
The fix landed once an experiment confirmed the cause: E1 confirmed H1 and D237-15 implemented the fix; see the Conclude section for the result.
Grounding: `docs/design/authn-antiblock-replayability-237-decisions.md` D237-14 (diagnosis), `docs/design/recon-auth-gateway-223-spec.md` (Design Risks), `tests/e2e/harness/recaptcha_challenge_probe.py` (the loop).

## Hypothesis Statement

**We believe that** making the bootstrap prefer mount-and-verify over a fresh login, and humanizing and pacing the browser on the paths that do log in

**for** the external authn bootstrapper and the runtime auth gateway (any agent that authenticates against a defended target through Steel)

**will** make the authenticated landing reachable without a reCAPTCHA challenge

**as measured by** the challenge-free completion rate of `recaptcha_challenge_probe.py` (GREEN runs / total runs) and the absence of the challenge frame in the run transcript.

## Background & Rationale

### Problem Context

Run 2's magnific bootstrap was held by a visible reCAPTCHA Enterprise challenge: 251 s of human solving plus a 90 s blind-retry loop (D237-14).
The operator read the proximate cause as a low score and excluded browser-TLS-fingerprint work, since a WAF block would be a straight 403, not a score-gated challenge.

### Supporting Evidence

- The mount-and-verify path is proven: mounting the stored `magnific-authn` profile read-only and navigating to `/app` reached the authenticated landing with **no login and no challenge** (measured 2026-09-21).
- Run 2 performed the fresh login anyway, on a **disposable scratch profile**, and never wrote back to `magnific-authn` (transcript).
- Every session egresses from a **different datacenter IP**: three sessions, three ASNs (`216.246.40.79` CacheFly, `152.233.48.155` Datacamp, `64.34.81.170` Latitude.sh), with and without the profile mounted.
- Steel's docs: "Profiles persist browser identity, not network identity - pair with a dedicated IP for account-based agents"; reuse without a stable origin is the "impossible travel problem".
- The CLI exposes `--stealth` (humanize plus auto-CAPTCHA), `--session-solve-captcha`, `--proxy`, and a `captcha` command family; the skill uses none of them.
- Run 2 submitted blindly four times (three clicks plus `requestSubmit()`), each followed by a 30 s `wait --url` timeout.

### Alternative Hypotheses Considered

- Browser TLS fingerprint or user-agent mismatch: excluded by the operator, and contradicted by the evidence (the browser passed the WAF; the UA is stable and `navigator.webdriver` is false).
- A hard account flag: contradicted - a controlled single-submit login reached `/app` three times after the failure.
- A deterministic cold-session trigger: contradicted - 0 of 3 controlled runs reproduced the challenge.

### Answer to the profile/network question

Mounting a profile does not reload the previous browser instance, and it does not carry IP, MAC, or any link-layer identity.
A profile is the Chromium user-data directory (cookies, storage, history) snapshotted on release and reloaded into a **new** cloud browser; the egress IP belongs to the session, not the profile (measured: different IP per session with the same profile mounted).
A MAC address is never exposed to a remote server - it does not survive the first router hop - so the site's observable network identity is the egress IP plus TLS and timing behaviour.
The design consequence: every mount is the same cookies from a new origin, and every fresh login is a new origin with no history.

## Target User Segment

### Definition

Agents that authenticate against a defended target through Steel: the external authn bootstrapper (by hand, #237) and the runtime auth gateway (#223).

### Segment Size

Two agent paths, one shared profile discipline; the target set is any WAF- or bot-managed site.

### Current Behavior

Pre-fix baseline: the bootstrap re-authenticated on every run, in a disposable browser, from a rotating datacenter origin, with default humanization and blind retries; a low score therefore blocked the run with no bounded recovery.

## Success Metrics

### Primary Metric

| Metric | Current Baseline | Target | Minimum Detectable Effect |
|--------|-----------------|--------|--------------------------|
| Challenge-free completion rate of the bootstrap (GREEN runs / runs) | 1 of 4 observed attempts (25%) | 100% on the mount-first path | Any challenge on the mount-first path invalidates the claim |

### Secondary Metrics

| Metric | Current Baseline | Expected Direction |
|--------|-----------------|-------------------|
| Fresh logins per bootstrap when a stored profile verifies | 1 | Decrease to 0 |
| Blind submit attempts per run | 4 | Decrease to <= 1 |
| Time to a bounded escalation when challenged | 90 s+ | Decrease to <= 30 s |
| Session lapses mid-flow | 1 | Decrease to 0 |

### Guardrail Metrics

| Metric | Current Value | Acceptable Range |
|--------|--------------|------------------|
| Functional bootstrap outcome (store facts, account, skill written) | complete | unchanged |
| Secret hygiene (no value in skill or report) | clean | unchanged |
| Store schema and seed-face contract | unchanged | unchanged |

## Validation Approach

### Method

A differential run of `recaptcha_challenge_probe.py`, one variable per arm, using the probe's flags.
H1 needs **no credentialed login** (mount-only), so it is cheap and safe to test first; the login arms (H2, H4) each burn one login and must be run sparingly.

### Sample Size & Duration

- H1 (mount-first): 3 runs, no logins, minutes.
- H2 (`--stealth` vs not) and H4 (warm vs scratch profile): 3 runs per arm, one login each - run only if H1 does not remove the need for a login.
- Duration: one sitting; each run is under two minutes.

### Pass/Fail Criteria

- **Validated if:** the mount-first path completes challenge-free in 3 of 3 runs, and no fresh login is attempted when a mounted profile verifies.
- **Invalidated if:** a challenge appears on the mount-first path, or the mount fails to verify.
- **Inconclusive if:** the mount verifies but the run still logs in for another reason (a workflow defect, not a score defect).

## Risks & Assumptions

### Key Assumptions

- A verified mount is sufficient evidence of authentication, so no fresh login is needed for the bootstrap's purpose.
- The challenge is score-driven and probabilistic, not a hard account flag.
- The operator accepts that the network-identity remedy (proxy or dedicated IP) may be a separate ticket, since #196 owns proxies and #223 lists proxy support out of scope.

### Risks

- Mount-first reduces coverage: a stale or revoked credential would no longer be detected by a fresh login, so the design needs an explicit staleness predicate (the store's `status` and recency fields) rather than a login.
- `--stealth` may be dominated by IP reputation, making H2 inconclusive on this target.
- Each login attempt risks further flagging the account and the egress pool, so the login arms must stay small.

## Timeline

| Phase | Dates | Duration |
|-------|-------|----------|
| Setup & instrumentation | 2026-09-21 | done (probe script committed) |
| Test running | 2026-09-21 | done (E1: 3/3 GREEN via `--mount-only`) |
| Analysis | 2026-09-21 | H1 confirmed (mount-first removes the score-gated action) |
| Decision | 2026-09-21 | fix landed as D237-15 |

---

# Debug Loop (debug-hypothesis)

## Observations

- The symptom is a visible reCAPTCHA Enterprise challenge (400x580 frame) on a fresh login; it occurred once (run 2) and not in three controlled attempts.
- The exact frame is detectable without solving: an iframe matching `/recaptcha/` and `/(bframe|challenge)/` sized above 300x200.
- The mount-and-verify path reaches `/app` with no challenge.
- Egress IP changes per session; the UA and timezone are stable; `navigator.webdriver` is false.
- Run 2 used a scratch profile, no `--stealth`, four blind submits, three 30 s timeouts, and its session lapsed on the 10-minute cap.
- What works: mount + navigate `/app`; a single cold submit also worked three times.
- What does not: nothing deterministic; the failure is intermittent.

## Hypotheses

### H1: The fresh login is unnecessary when a stored profile verifies (ROOT HYPOTHESIS)
- Supports: the mount-and-verify path reached `/app` with no challenge; run 2 mounted the profile first and then logged in anyway; no login means no score-gated action.
- Conflicts: none; the only question is whether mount-only verification is acceptable coverage, which is a design choice, not evidence against the mechanism.
- Test: a mount-only probe (start with the profile, navigate `/app`, assert the authenticated landing) repeated 3 times, asserting no login is performed.

### H2: Default humanization lowers the score
- Supports: `--stealth` exists and is never used; fast synthetic interactions are a known bot signal.
- Conflicts: the score may be dominated by IP reputation; three controlled non-stealth logins were not challenged.
- Test: `recaptcha_challenge_probe.py --stealth` versus without, 3 runs per arm.

### H3: The rotating datacenter egress is the dominant score factor
- Supports: three sessions egressed from three datacenter ASNs; Steel documents the impossible-travel failure and prescribes dedicated IPs.
- Conflicts: the challenge is not reproducible, so the IP alone does not deterministically trigger it; proxies are out of scope here (#196).
- Test: pair the profile with a fixed egress and repeat the mount and login probes; compare the challenge rate.

### H4: A disposable scratch profile is worse than the account's own warm profile
- Supports: run 2 logged in on an empty scratch profile and discarded it; the warm profile needed no login at all.
- Conflicts: none observed, but the warm path removes the login entirely (H1), which subsumes this.
- Test: warm-profile login versus scratch-profile login, 3 runs per arm.

### H5: Blind resubmits and the missing challenge protocol worsen both the score and the recovery
- Supports: four submits and three 30 s timeouts in run 2; repeated failed submits are themselves a bot signal.
- Conflicts: the first submit may have been challenged before any retry, so the retries may be a consequence, not a cause.
- Test: a run that detects the challenge's own marker with a bounded 15 s wait and escalates; assert the run ends bounded and with no second submit.

### H6: The 10-minute session cap and the 120 s inactivity default are too short for a human-in-the-loop step
- Supports: run 2's session lapsed on the 10-minute clock during the human solve.
- Conflicts: none.
- Test: a human-gated run with a longer session timeout and a raised inactivity timeout; assert no lapse.

## Experiments

E1 ran and confirmed H1 (see the Conclude section); the remaining experiments are specified here for a future session.
Each experiment changes one variable and is run through the committed probe.
The order is deliberate: H1 first, because it needs no login and, if confirmed, removes the score-gated action from the bootstrap entirely.

| # | Hypothesis | Variable | Command | Confirms if |
|---|-----------|----------|---------|-------------|
| E1 | H1 | mount-only vs login | probe `--profile magnific-authn --mount-only` | 3 of 3 reach `/app`, zero logins |
| E2 | H2 | `--stealth` on/off | probe `--stealth` vs plain | challenge rate falls with `--stealth` |
| E3 | H3 | egress pinned/unpinned | probe `--proxy <fixed>` vs plain | challenge rate falls when pinned |
| E4 | H4 | warm vs scratch profile | probe `--profile <warm>` vs default scratch | warm challenges less |
| E5 | H5 | protocol vs storm | probe with bounded challenge detection vs `--retry-storm` | bounded end, no second submit |
| E6 | H6 | session/inactivity timeout | probe with raised timeouts under a human gate | no mid-flow lapse |

## E1 result (run 2026-09-21)

`python3 tests/e2e/harness/recaptcha_challenge_probe.py --mount-only --profile magnific-authn` ran three times: GREEN, GREEN, GREEN, each landing on `/app` in under a minute with **no login performed and no challenge**.
H1's mechanism is therefore confirmed: when a stored profile verifies, the score-gated action (a fresh login) is unnecessary, and removing it removes the failure mode.

## Conclude

Root cause (mechanism confirmed by E1): the bootstrap performs a fresh login even when a mounted profile verifies, and the fresh login is the reCAPTCHA-score-gated action that can be challenged; the system then has no stable network identity, no humanization, and no bounded challenge protocol, so a low score blocks the run and the recovery degrades the score further.
The remaining hypotheses (H2-H6) govern the paths that must still log in - a first bootstrap, or a genuinely stale profile - and their experiments are designed but not run.
H1's fix landed as D237-15 (mount-first, verification-gated login, warm write-back, and the non-reactive cadence and clock rules); no Steel-side solving is adopted, per the operator's proactive-only ruling.
The probe script remains the regression vehicle because no unit seam can carry a live, third-party-scored, intermittent symptom.
