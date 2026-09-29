---
name: rate-aware-recon-configuration
description: >-
  Use when configuring recon pod commands from a measured rate-limit posture:
  supplies the syntax and configurable rate, thread, concurrency, depth, and
  delay controls exposed by katana, arjun, ffuf, and httpx.
metadata:
  version: '1.0'
---

# Rate-aware recon configuration

This skill documents tool controls only. The reconstruction decision and
posture workflow live in the Configurator role prompt.

## katana

- `-c <n>` sets the concurrent crawl workers.
- `-rl <n>` sets the request rate limit.
- `-d <n>` sets crawl depth.
- `-ct <duration>` bounds crawl wall-clock time.
- `-pcs -pcsm simhash -pcsd <n>` enables page-content-similarity pruning.
- `-iqp -fsu -fst <n>` collapses repeated query-parameter values.

Use these together: increasing `-c` without controlling `-rl` can increase the
aggregate request rate even when the crawl itself is bounded by `-d` or `-ct`.

## arjun

- `--rate-limit <n>` caps requests per second.
- `-t <n>` sets worker threads.
- `--delay <seconds>` inserts a per-request delay where supported by the
  installed version.

Prefer a conservative `--rate-limit` with a small thread count. A low rate with
too many workers can still burst through the per-worker queue behavior.

## ffuf

- `-rate <n>` caps requests per second.
- `-t <n>` sets concurrent threads.
- `-p <delay>`-style pacing can be supplied by the installed ffuf version when
  a fixed inter-request delay is preferable to a rate cap.
- `-maxtime <seconds>` bounds total execution.

The aggregate load comes from `-rate` combined with `-t`; keep threads low when
the target exposes a strict per-connection or burst limit.

## httpx

- `-rl <n>` sets the global request rate limit.
- `-threads <n>` sets concurrent workers.
- `-timeout <seconds>` bounds each request.
- `-retries <n>` controls retry attempts.

For probing many inputs, lower `-threads` and an explicit `-rl` are usually more
predictable than relying on the client default. Retries amplify rejected
requests and should stay low under a measured limiter.

## General rules

- Tool flags are executable syntax, not a substitute for the role prompt's
  posture decision.
- Keep rate, thread, concurrency, and delay controls mutually consistent.
- When a tool has no equivalent pacing flag, reduce fan-out, input count, or
  execution time instead of assuming the runtime will pace it.
- Preserve required input and output flags from the original command template.
- Keep placeholders such as `{auth_flags}` and `{session}` unresolved.
