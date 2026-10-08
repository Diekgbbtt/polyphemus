# Open operator decisions

*Status: decision request (2026-10-08). Four decisions are surfaced here with their context, options, and a recommendation.
Each blocks or gates a ticket that is otherwise implemented or blocked only on this ruling.
Mark the chosen option inline, or rule in the owning issue.*

This brief does not authorise a code change by itself.
The owning tickets carry the acceptance criteria.

## D-1. #299 - bound the actor one-shot fallback so it does not over-fire on a contract 400

### Context

The provider `opencode-go/deepseek-v4.1-flash` intermittently returns a bare `400` that degrades an actor turn.
`#299` added a one-shot fallback at the actor seam: on the first ambiguous failure, retry once through the fallback path before degrading.
Chained spec-review returned **PASS**, with one **MEDIUM** finding:

- The one-shot fallback fires on a **contract** `400` (a client error the model provoked), not only on a transient/ambiguous `400`.
- The ADR and the actor-seam contract distinguish a contract error (do not retry) from a transient error (retry).
- As written, the seam contradicts its own contract, so a genuine client error burns one wasted fallback call before it degrades.

The ticket is implemented and committed (`fix/299-transient-provider-400`, `cbd1f35`), held from merge.

### Options

- **(i) Narrow the trigger.** Classify the `400` body at the seam: a contract-shaped error does not arm the one-shot fallback; an ambiguous/transient-shaped `400` does.
  This honours the ADR and adds one classifier.
- **(ii) Leave as-is.** Accept one extra fallback call on a contract `400` as harmless; document the deviation in the ADR.
- **(iii) Do not merge.** Withdraw `#299` and fold the transient-`400` handling into the larger provider-failure work (`#331`).

### Recommendation

Option **(i)**. The cost is one small classifier; the contract stays honest.
The ticket's own note (tricky, low-yielding, not deterministically verifiable) argues against a large design, not against a correct trigger.

## D-2. #315 - the trial token budget should bound a phase, not terminate the trial

### Context

`#315` records that the trial token cap terminates the WHOLE trial when one phase overruns, rather than bounding the offending phase and letting the trial continue.
The over-eager cap was removed (`eval-token-budget-and-no-config-cap-adr.md`), so the trial no longer dies on the cap, but the intended phase-scoped budget was never re-introduced.
This is a design re-introduction, not a bug fix.

### Options

- **(i) Phase-scoped budget.** Give each phase its own budget; an overrun pauses or stops that phase, and the trial continues to assessment with partial results.
- **(ii) Keep the cap removed.** Rely on the per-trial wall-clock timeout plus the orphan fix (`#338`); leave no token cap.
- **(iii) A soft cap.** Warn at a phase threshold and stop only at the trial ceiling.

### Recommendation

Option **(i)**, aligned with the design intent recorded in `#315`.
It needs a design pass (where the budget lives, how a phase pause surfaces in the ledger).

## D-3. #331 - the provider-failure stop/flush/resume policy

### Context

`#331` (provider-failure handling) is partly landed: the typed `ProviderUnavailableError`, the pod/triager/surfer propagation, and the provider-caused pass abort landing `interrupted` are on `dev` (`#329`, `#312`).
Two acceptance criteria are operator-gated:

- **AC2 - the resume re-scheduling trigger and its idempotency.** What re-schedules a paused/interrupted run: a timer, an operator verb, or the eval driver; and how a re-schedule stays idempotent (no double dispatch).
- **AC4 - the 429-versus-403 policy.** Which provider statuses pause-and-resume (transient throttle) versus fail the run (hard denial, e.g. a `403`).

### Options

- **AC2:** (a) an operator verb only; (b) an operator verb plus an eval-driver auto-resume with backoff; (c) a timer inside the runtime.
- **AC4:** (a) `429`/`5xx`/timeout pause, everything else fails; (b) also pause on `403` with a distinct reason; (c) pause on all provider errors and let the operator decide.

### Recommendation

- **AC2: (b)** - the operator verb is the floor, the eval driver auto-resumes with backoff so long unattended runs recover; idempotency rides the existing one-live-run-per-project guard.
- **AC4: (a)** - pause on `429`/`5xx`/timeout; fail on a `403` (a hard denial is not a transient throttle). Record the class on the run row `stats` (already built by `#331`).

## D-4. #330 Part 2 - the gateway fail-over / throttle policy

### Context

`#330` is the gateway cost guard (LiteLLM virtual-key budget from `models.dev` costs, provisioned at bootstrap).
**Part 2** is the fail-over/throttle policy for a provider `429`/quota exhaustion (deep-dive in `eval-bugs-map.md` section 8).
There is currently **no fallback model group**, so a `429` fails the run (EV-21).

### Options

- **(i) A router-level fallback model group** (`#246` fail-over chain): reroute to another provider/model on a downstream `429`.
- **(ii) A conservative per-period USD budget plus a per-minute TPM on the gateway key**, sized below the provider roof (prevention; no native token-per-5h cap).
- **(iii) The eval orchestrator recognises the quota failure** and pauses/stops the run.
- **(iv) A combination** of the above.

### Recommendation

Option **(iv)**, specifically **(ii) + (i)**: a conservative per-period USD budget + per-minute TPM as the cheap prevention, plus a router-level fallback group as the robust handling.
Option (iii) is already partly delivered by `#331` (the run pauses `interrupted` with a typed cause).
A native token-per-5h cap is not worth its complexity (section 8).
