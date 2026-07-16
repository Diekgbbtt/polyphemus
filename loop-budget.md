# Loop Budget — polymerhus L1-MVP

## Per-iteration / per-FR-area limits

| Scope | Max iterations/day | Max tokens/day | Max sub-agent spawns/attempt |
|---|---|---|---|
| Phase-0 planning | 1 | 200k | 0 |
| Per FR-area dev→test→debug | 6 attempts total (cap 3/area, ×2 areas/day guidance) | 800k | 2 (1 implementer + 1 verifier) |
| Verifier pass | — | 150k | — (runs as the 1 verifier spawn) |

Guidance, not a hard meter: the point is to notice when an FR area is burning budget without converging (a signal to escalate, per the attempt cap), not to micro-account tokens.

## On budget exceed

1. Switch to report-only (stop writing code; summarise state).
2. Append an event to `loop-run-log.md`.
3. Notify the human via `STATE.md` `High Priority`.

## Kill switch

- Flag: `loop-pause-all` in `STATE.md` `High Priority`.
- When active, the loop exits immediately and resumes only after a human clears the flag.
