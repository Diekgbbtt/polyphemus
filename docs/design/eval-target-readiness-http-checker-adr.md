# ADR: the readiness contract defaults to a composite front + compose plan

*Status: RATIFIED (2026-10-05). New record. It refines the D47/Round-9 bounded-readiness decision; it supersedes the earlier draft that made the HTTP checker a per-target opt-in.*

## Context

A comfyui trial recorded a target-front `502 Bad Gateway` early in recon, then normal `200`s once ComfyUI bound port 8288 (#325).
The target front is correct: a `502` is the front's answer while its upstream is not listening (`docs/design/hunting-target-front-availability-adr.md`).
The defect is a readiness gap: the chain declared the target ready before its application was serving.

The root cause is the interaction of two intended behaviours:

- `eval/targets/webexploitbench/comfyui.yaml` declares `runner: targetctl` and no `checker`.
  The comfyui compose declares no healthcheck for `comfyui-manager`.
  So `orchestrator/datasets/base.py::readiness_plan` resolved the default compose-health poll.
- `orchestrator/readiness.py::ServiceHealth.ready` treats `running` with no healthcheck as ready.
  Compose has no signal to offer, so a `running` container read as ready even while the app inside it was still booting.

The compose poll is deliberately exhaustive about what the platform declares (Round-9).
Its blindness is precise: when a service declares no healthcheck, the platform cannot learn the application's readiness from compose, and the application binds tens of seconds after the container starts.

The class is much wider than comfyui.
At least eight `targetctl` targets - openremote, dataease, white-jotter, geoserver, prestashop, siyucms, openmetadata, and youlai-mall - also declare no `checker` and have an application-serving service with no healthcheck while a support service does.
The same 502 window therefore remained for them, and an opt-in fix left the footgun in place for every target that did not opt in.

## Decision

### 1. The readiness contract defaults, target by target

`DatasetHelper.readiness_plan` selects the default plan from the target's own composition; no per-target opt-in is required:

- A `targetctl`/`compose` target whose application-serving service declares a healthcheck uses the compose poll alone.
- A `targetctl`/`compose` target whose application-serving service declares no healthcheck uses the **composite** plan: the front HTTP answer AND the compose poll.
- A target with no compose (the `image` runner) probes its published port.

The application-serving services are the challenge's own `application_service_keys` (`challenge.json` in the target's bank entry); when that metadata is absent, the compose's own built services (`build:` + `image:`) stand in.
This is the safe path by construction, not by declaration (CODING_STANDARD section 5: no path is left to chance).

### 2. The composite plan closes the boot window without dropping the stack assertion

A plan holds one or more probes, and every probe must answer ready.
The composite pairs the front HTTP probe with the compose poll, so:

- the front answers `502` while the published port is still binding, so the boot window can never read ready; and
- the compose poll still asserts the stack's own declared health, including the support services (for example comfyui's `ssrf-listener`) that a front-only probe would drop.

Ordering is the front probe first, so a booting application short-circuits before the support-service poll.

### 3. The front probe is an HTTP probe, not a plan kind

There are two probe kinds: `compose` and `http`.
The named `http` checker builds one or two `http` probes; the **front** probe is `plan_front_http`, an HTTP `curl` on the host loopback carrying the synthetic Host, the exact bare-domain path recon uses.
`plan_http_port` is the other `http` builder, for a published port on the host loopback.
It is the explicit fallback for a caller with no synthetic host; every wired strategy passes a host, so it is exercised by test rather than by a live caller, and `readiness_plan` raises rather than silently skipping the HTTP assertion when neither a host nor a port is known.

### 4. A 5xx or no answer is never ready

A `5xx` (including the front's `502`) or no answer is not ready; the first non-5xx answer is.
This reuses the `http_ready` rule, so the `5xx` verdict cannot drift between the two HTTP builders.

### 5. An unknown named checker fails loud

An earlier gap let a misspelled `checker` silently fall back to compose health.
`readiness_plan` raises `ValueError` naming the target and the unknown checker, so a target can never believe it selected a contract while it is still running another.
The named `http` checker is also composite when a compose is resolvable, so an explicit declaration keeps the support-service assertion too.

## Consequences

- Every no-healthcheck application service is asserted at the front before readiness, so a recon trial never records the boot-window `502`.
  The eight reported targets, plus comfyui, jetlinks, mogu-blog-v2, ofbiz, and the mock target, all select the composite by default.
- The compose poll remains the only plan for a healthchecked application service (dify, phpbb, wordpress) and the sole readiness signal where the application declares its own health.
- `comfyui.yaml` and `jetlinks.yaml` carry no `checker`; their readiness contract is the default, which supersedes the earlier per-target opt-in.
- A target that needs the HTTP answer without the stack poll, or a custom rule, can still declare a named checker; a dataset helper's own `checker_<name>` continues to resolve.

## Alignment

The change is harness-only (`eval/**`), so it takes effect with the eval branch advance; no agent image or front configuration changes.
The front probe assumes the shared front is applied before `await_ready`, which every strategy already guarantees by applying the front conf inside `up`.
