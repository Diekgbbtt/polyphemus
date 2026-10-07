# ADR: the readiness contract defaults to a composite front + application-port + compose plan

*Status: RATIFIED (2026-10-05). AMENDED (2026-10-07, #323): the composite probes every published application service, not only the front. New record. It refines the D47/Round-9 bounded-readiness decision; it supersedes the earlier draft that made the HTTP checker a per-target opt-in.*

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

A later jetlinks recon (#323) exposed a second gap in the same composite.
The challenge declares a **multi-service** application (`application_service_keys: ["jetlinks", "ui"]`) and publishes both services on host ports (`target_ports`).
The target front's conf proxies every path to ONE published port, the `ui` service.
The `ui` nginx answers `/` as soon as it starts, and it proxies `/api` internally to the `jetlinks` JVM backend.
The `jetlinks` JVM answers `/api/*` with `502` for its whole boot window, while the compose declares no healthcheck for either service.
The compose poll read both services `running`, and the front probe on `/` answered `200`, so readiness passed before the application backend served.
The front root is not a backend signal when a different service serves it.

## Decision

### 1. The readiness contract defaults, target by target

`DatasetHelper.readiness_plan` selects the default plan from the target's own composition; no per-target opt-in is required:

- A `targetctl`/`compose` target whose application-serving services declare a healthcheck uses the compose poll alone.
- A `targetctl`/`compose` target whose application-serving services declare no healthcheck uses the **composite** plan: the front HTTP answer, one HTTP probe per published application service, and the compose poll.
- A target with no compose (the `image` runner) probes its published port.

The application-serving services are the challenge's own `application_service_keys` (`challenge.json` in the target's bank entry); when that metadata is absent, the compose's own built services (`build:` + `image:`) stand in.
This is the safe path by construction, not by declaration (CODING_STANDARD section 5: no path is left to chance).

### 2. The composite plan closes the boot window without dropping the stack assertion

A plan holds one or more probes, and every probe must answer ready.
The composite keeps the front HTTP probe, adds one HTTP probe per published application service, and keeps the compose poll, so:

- the front asserts the exact bare-domain routing recon uses, and answers `502` while the front's own upstream is not listening;
- every application service answers on its OWN published port, so a booting backend behind an already-serving fronted service is never read ready; and
- the compose poll still asserts the stack's own declared health, including the support services (for example comfyui's `ssrf-listener`) that an HTTP-only probe would drop.

Ordering is the front probe first, then the application-service port probes, then the compose poll, so a booting application short-circuits before the support-service poll.

### 3. The HTTP probes are HTTP probes, not plan kinds

There are two probe kinds: `compose` and `http`.
The named `http` checker builds the front probe and one probe per published application service, then adds the compose poll when a compose is resolvable.
Three builders produce a `http` probe:

- `plan_front_http`: an HTTP `curl` on the host loopback carrying the synthetic Host, the exact bare-domain path recon uses.
- `plan_http_port`: an HTTP `curl` on a published port on the host loopback.
  It is the explicit fallback for a caller with no synthetic host; every wired strategy passes a host, so it is exercised by test rather than by a live caller, and `readiness_plan` raises rather than silently skipping the HTTP assertion when neither a host nor a port is known.
- `plan_service_port`: resolve a compose service's own published host port with `docker compose -p <project> port <service> <internal_port>`, then `curl` it.
  The challenge publishes its application services on ephemeral host ports, so the port is unknown at plan time; `docker compose port` reads the running container's own mapping, so the probe needs no per-strategy ports file.

### 4. A 5xx or no answer is never ready

A `5xx` (including the front's `502`) or no answer is not ready; the first non-5xx answer is.
This reuses the `http_ready` rule, so the `5xx` verdict cannot drift between the HTTP builders.
An unresolvable service port answers `000`, so a service with no published mapping is never ready.

### 5. An unknown named checker fails loud

An earlier gap let a misspelled `checker` silently fall back to compose health.
`readiness_plan` raises `ValueError` naming the target and the unknown checker, so a target can never believe it selected a contract while it is still running another.
The named `http` checker is also composite when a compose is resolvable, so an explicit declaration keeps the support-service assertion too.

### 6. The application ports come from the challenge's `target_ports`

`DatasetHelper.app_published_ports` reads the challenge's `target_ports` (service -> container port) and intersects it with the application-serving services.
The plan gets one `plan_service_port` probe per entry.
A challenge with no `target_ports`, or one that publishes no application service, keeps the front + compose composite: the port is then unknown, and dropping the backend assertion silently would be worse than keeping the known gap visible.
This is the durable rule, not a per-target `ready_path` or named-checker band-aid: it generalizes to every multi-service no-healthcheck application the benchmark declares.

## Consequences

- Every published application service is asserted on its own port before readiness, so a recon trial never records the boot-window `502`.
  The eight reported targets, plus comfyui, jetlinks, mogu-blog-v2, ofbiz, and the mock target, all select the composite by default.
- The jetlinks backend (`jetlinks:8848` published on an ephemeral host port) is now probed directly, so its JVM boot window cannot read ready while only its `ui` sibling answers.
- The compose poll remains the only plan for a healthchecked application service (dify, phpbb, wordpress) and the sole readiness signal where the application declares its own health.
- `comfyui.yaml` and `jetlinks.yaml` carry no `checker`; their readiness contract is the default, which supersedes the earlier per-target opt-in.
- A target that needs the HTTP answer without the stack poll, or a custom rule, can still declare a named checker; a dataset helper's own `checker_<name>` continues to resolve.

## Alignment

The change is harness-only (`eval/**`), so it takes effect with the eval branch advance; no agent image or front configuration changes.
The front probe assumes the shared front is applied before `await_ready`, which every strategy already guarantees by applying the front conf inside `up`.
The `plan_service_port` probe assumes the target's containers are running before `await_ready`; `up` starts them first, and a missing container resolves to `000`, never ready, so the probe fails safe.
