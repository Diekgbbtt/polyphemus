"""The per-dataset helper: the one authority that turns a target's compose into
its images and its bounded readiness plan (spec #301).

The generic helper derives the target's own images from the services that declare
both `build:` and `image:` in the compose - the same rule `targetctl` uses - so the
image set can never drift from what the target actually builds. Each derived image
is bound to a canonical tag `ph/<dataset>/<target>:<service>`, which is the
symbolic key the store check and reclaim use.

It also owns the default readiness contract and the built-in named checkers
(`http`): the plan is the compose health poll when the application-serving service
declares a healthcheck, and the composite front + every published application
port + compose plan otherwise, so a slow-boot application - and a backend behind a
front root another service serves (#323) - can never be declared ready before it
answers. A dataset may supply its own helper module
(`orchestrator/datasets/<id>.py`) to add or override named checkers; otherwise the
generic helper applies.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from orchestrator.dataset import BenchmarkDataset
from orchestrator.readiness import (
    ReadinessPlan,
    ReadinessProbe,
    compose_probe,
    http_probe,
    plan_front_http,
    plan_http_port,
    plan_service_port,
)
from orchestrator.target_config import TargetConfiguration

DEFAULT_READY_RETRIES = 60
DEFAULT_READY_INTERVAL_S = 5.0


@dataclass(frozen=True)
class BuiltImage:
    """One image a target's compose builds: its service and its compose tag."""

    service: str
    reference: str


def parse_built_images(compose_text: str) -> tuple[BuiltImage, ...]:
    """The services declaring both `build:` and `image:`, mirroring `targetctl`.

    The parse is deliberately shallow (a compose-service block is a two-space key
    under `services:`), so it reads the same shape `targetctl`'s `build_images`
    reads and needs no YAML dependency. A service gated behind a `profiles:` key
    is not part of the target's default stack - `docker compose config` and
    `docker compose build` both leave it out - so it is not a built image either.
    """
    images: list[BuiltImage] = []
    service: str | None = None
    has_build = False
    image: str | None = None
    profiled = False

    def flush() -> None:
        if service and has_build and image and not profiled:
            images.append(BuiltImage(service=service, reference=image))

    for raw in compose_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2 and stripped.endswith(":") and " " not in stripped[:-1]:
            flush()
            service = stripped[:-1]
            has_build = False
            image = None
            profiled = False
            continue
        if service is None:
            continue
        if indent == 4 and stripped.startswith("build:"):
            has_build = True
        elif indent == 4 and stripped.startswith("image:"):
            image = stripped[len("image:"):].strip().strip("\"'")
        elif indent == 4 and stripped.startswith("profiles:"):
            profiled = True
    flush()
    seen: list[BuiltImage] = []
    for item in images:
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def parse_service_health(compose_text: str) -> dict[str, bool]:
    """The services that declare a `healthcheck:`, mirroring `targetctl`.

    The parse is as shallow as `parse_built_images`: a service block is a
    two-space key under `services:`, and a `healthcheck:` at that block's own
    indent marks the service as healthchecked. A service gated behind a
    `profiles:` key is not part of the target's default stack, so it does not
    count. A service whose healthcheck comes only through a YAML anchor reads as
    unhealthchecked, which fails safe: the caller then adds the front probe.
    """
    health: dict[str, bool] = {}
    service: str | None = None
    has_health = False
    profiled = False

    def flush() -> None:
        if service is not None:
            health[service] = has_health and not profiled

    for raw in compose_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2 and stripped.endswith(":") and " " not in stripped[:-1]:
            flush()
            service = stripped[:-1]
            has_health = False
            profiled = False
            continue
        if service is None:
            continue
        if indent == 4 and stripped.startswith("healthcheck:"):
            has_health = True
        elif indent == 4 and stripped.startswith("profiles:"):
            profiled = True
    flush()
    return health


def parse_application_service_keys(challenge_text: str) -> tuple[str, ...]:
    """The `application_service_keys` a challenge declares, when present.

    This is the target's own statement of which services serve the application
    (WebExploitBench and the mock dataset both carry a `challenge.json`). A
    malformed or absent field yields an empty tuple, so the caller falls back to
    the compose-derived services.
    """
    try:
        data = json.loads(challenge_text)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(data, Mapping):
        return ()
    keys = data.get("application_service_keys")
    if not isinstance(keys, list):
        return ()
    return tuple(key for key in keys if isinstance(key, str) and key)


def parse_target_ports(challenge_text: str) -> dict[str, int]:
    """The challenge's `target_ports` (service -> published application port).

    This is the target's own statement of which services reach the agent over
    HTTP and on which container port. A malformed, absent, or non-positive entry
    is dropped rather than guessed, so the caller keeps the front + compose plan
    when no port is resolvable.
    """
    try:
        data = json.loads(challenge_text)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, Mapping):
        return {}
    ports = data.get("target_ports")
    if not isinstance(ports, Mapping):
        return {}
    result: dict[str, int] = {}
    for service, port in ports.items():
        if not isinstance(service, str) or not service or isinstance(port, bool):
            continue
        if isinstance(port, int) and port > 0:
            result[service] = port
        elif isinstance(port, str) and port.isdigit() and int(port) > 0:
            result[service] = int(port)
    return result


def canonical_tag(dataset_id: str, target: str, service: str) -> str:
    """`ph/<dataset>/<target>:<service>`, the symbolic image key for a target."""
    return f"ph/{dataset_id}/{target}:{service}"


class DatasetHelper:
    """The generic, compose-derived helper for a benchmark dataset."""

    def __init__(self, dataset: BenchmarkDataset) -> None:
        self.dataset = dataset

    # --- paths ----------------------------------------------------------------

    def bank_entry(self, target: str) -> Path:
        return self.dataset.bank_entry(target)

    def compose_path(self, target: str, config: TargetConfiguration) -> Path:
        """The compose file, resolved against the target's bank entry."""
        if not config.compose:
            raise ValueError(f"target {target!r} declares no compose file")
        return self.bank_entry(target) / config.compose

    # --- images ---------------------------------------------------------------

    def built_images(self, target: str, config: TargetConfiguration) -> tuple[BuiltImage, ...]:
        path = self.compose_path(target, config)
        built = parse_built_images(path.read_text(encoding="utf-8"))
        # D49: a service kept out of the stack is not a built image of the target,
        # so it is never tagged, pulled, or reclaimed. The dataset's exclusions
        # (the `evaluator`) merge with any the target itself declares.
        excluded = set(self.dataset.exclude_services) | set(config.exclude_services)
        if not excluded:
            return built
        return tuple(item for item in built if item.service not in excluded)

    def canonical_tags(self, target: str, config: TargetConfiguration) -> tuple[str, ...]:
        """The target's own canonical tags; config.images overrides the derivation."""
        if config.images:
            return tuple(config.images)
        built = self.built_images(target, config)
        return tuple(
            canonical_tag(self.dataset.id, target, item.service) for item in built
        )

    # --- readiness ------------------------------------------------------------

    def app_service_keys(self, target: str, config: TargetConfiguration) -> tuple[str, ...]:
        """The services that serve the application.

        The authority is the challenge's own `application_service_keys`
        (`challenge.json` in the bank entry); a malformed or absent file falls
        back to the target's own built services, so a dataset without challenge
        metadata still gets a best-effort app set.
        """
        challenge = self.bank_entry(target) / "challenge.json"
        try:
            keys = parse_application_service_keys(challenge.read_text(encoding="utf-8"))
        except OSError:
            keys = ()
        if keys:
            return keys
        try:
            built = self.built_images(target, config)
        except (OSError, ValueError):
            return ()
        return tuple(item.service for item in built)

    def app_published_ports(
        self, target: str, config: TargetConfiguration
    ) -> tuple[tuple[str, int], ...]:
        """`(service, port)` for every application service the challenge publishes.

        `target_ports` (`challenge.json`) is the target's own statement of which
        services reach the agent over HTTP. A missing, malformed, or intersecting-
        empty mapping yields `()`, so the caller keeps the front + compose plan.
        """
        challenge = self.bank_entry(target) / "challenge.json"
        try:
            ports = parse_target_ports(challenge.read_text(encoding="utf-8"))
        except OSError:
            return ()
        if not ports:
            return ()
        return tuple(
            (key, ports[key])
            for key in self.app_service_keys(target, config)
            if key in ports
        )

    def app_health_declared(self, target: str, config: TargetConfiguration) -> bool:
        """Whether every application-serving service declares a compose healthcheck.

        A compose whose application services are healthchecked can trust the
        compose poll. An application service with no healthcheck cannot: the poll
        reads it `running` while the application inside is still booting, which is
        the #325 boot window. An application we cannot identify is never assumed
        healthy.
        """
        keys = self.app_service_keys(target, config)
        if not keys:
            return False
        try:
            text = self.compose_path(target, config).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return False
        health = parse_service_health(text)
        return all(health.get(key, False) for key in keys)

    def readiness_plan(
        self,
        target: str,
        config: TargetConfiguration,
        *,
        project: str,
        port: int | str | None = None,
        host: str | None = None,
        retries: int = DEFAULT_READY_RETRIES,
        interval_s: float = DEFAULT_READY_INTERVAL_S,
        compose_file: str | None = None,
    ) -> ReadinessPlan:
        """The bounded readiness plan; safe by construction.

        A named `checker` is resolved to a checker this helper defines; a name
        that resolves to no checker fails loud rather than silently falling back
        to compose health.

        Otherwise the target's own composition selects the default:
        * a `targetctl`/`compose` target whose application-serving service
          declares a healthcheck uses the compose poll alone;
        * a `targetctl`/`compose` target whose application declares no
          healthcheck uses the composite plan - the front HTTP answer, one HTTP
          probe per published application service, AND the compose poll - so the
          boot window cannot read ready and the support services stay asserted;
          the front root may be served by a different service than the backend
          (#323), so each published application service is probed on its own
          port;
        * a target with no compose (the `image` runner) probes its published
          port.

        `compose_file` overrides the compose the poll reads: the targetctl
        strategy passes its generated compose when services are excluded (D49),
        so the poll asserts the same stack `up` started.
        """
        if config.checker:
            named = self._named_checker(config.checker)
            if named is None:
                raise ValueError(
                    f"target {target!r}: unknown readiness checker "
                    f"{config.checker!r}"
                )
            return named(
                target, config, project=project, port=port, host=host,
                retries=retries, interval_s=interval_s, compose_file=compose_file,
            )

        compose = self._compose_probe(
            target, config, project=project, compose_file=compose_file
        )
        if config.runner in ("targetctl", "compose") and compose is not None:
            if self.app_health_declared(target, config):
                return ReadinessPlan(
                    probes=(compose,), retries=retries, interval_s=interval_s
                )
            http = self._http_probe(target, config, host=host, port=port)
            app_ports = self._app_port_probes(
                target, config, project=project, compose_file=compose_file
            )
            return ReadinessPlan(
                probes=(http, *app_ports, compose),
                retries=retries,
                interval_s=interval_s,
            )
        # The image runner (and any target with no compose) probes its port.
        return ReadinessPlan(
            probes=(http_probe(plan_http_port(port, config.ready_path)),),
            retries=retries,
            interval_s=interval_s,
        )

    def checker_http(
        self,
        target: str,
        config: TargetConfiguration,
        *,
        project: str,
        port: int | str | None = None,
        host: str | None = None,
        retries: int = DEFAULT_READY_RETRIES,
        interval_s: float = DEFAULT_READY_INTERVAL_S,
        compose_file: str | None = None,
    ) -> ReadinessPlan:
        """The named `http` checker: the HTTP answers plus, when declarable, stack health.

        A target declares it to make the HTTP answer part of readiness explicit.
        When a compose is resolvable the plan is composite, so the application's
        boot window is closed without dropping the support-service assertion
        (#325 finding 5), and every published application service is probed on
        its own port (#323); a compose-less target gets the front probe alone.
        """
        http = self._http_probe(target, config, host=host, port=port)
        app_ports = self._app_port_probes(
            target, config, project=project, compose_file=compose_file
        )
        compose = self._compose_probe(
            target, config, project=project, compose_file=compose_file
        )
        probes: tuple[ReadinessProbe, ...] = (http, *app_ports)
        if compose:
            probes = (*probes, compose)
        return ReadinessPlan(probes=probes, retries=retries, interval_s=interval_s)

    def _app_port_probes(
        self,
        target: str,
        config: TargetConfiguration,
        *,
        project: str,
        compose_file: str | None,
    ) -> tuple[ReadinessProbe, ...]:
        """One HTTP probe per published application service (#323).

        The front's `/` may be served by a different service than the backend
        (jetlinks' `ui` is up while the `jetlinks` JVM boots), so a front probe
        alone reads ready too early. Each published application service is
        probed on its OWN port, resolved from the running container at probe
        time. An empty application or port set yields no probe.
        """
        resolved = self._resolved_compose_path(target, config, compose_file)
        return tuple(
            http_probe(
                plan_service_port(
                    project, service, internal_port, compose_file=resolved
                )
            )
            for service, internal_port in self.app_published_ports(target, config)
        )

    def _http_probe(
        self,
        target: str,
        config: TargetConfiguration,
        *,
        host: str | None,
        port: int | str | None,
    ) -> ReadinessProbe:
        """The HTTP probe: the front when a synthetic host is available, else the port.

        Every wired strategy passes a host, so the port branch is the explicit
        fallback for a caller that has none; it raises when neither is known, so
        an HTTP assertion is never silently skipped.
        """
        if host:
            return http_probe(plan_front_http(host, config.ready_path))
        if port is not None:
            return http_probe(plan_http_port(port, config.ready_path))
        raise ValueError(
            f"target {target!r}: an HTTP readiness probe needs a host or a port"
        )

    def _compose_probe(
        self,
        target: str,
        config: TargetConfiguration,
        *,
        project: str,
        compose_file: str | None,
    ) -> ReadinessProbe | None:
        """The compose-health probe when a compose is resolvable, else None."""
        resolved = self._resolved_compose_path(target, config, compose_file)
        if resolved is None:
            return None
        return compose_probe(resolved, project)

    def _resolved_compose_path(
        self,
        target: str,
        config: TargetConfiguration,
        compose_file: str | None,
    ) -> str | None:
        """The compose the poll and the port probes read, or None when absent.

        `compose_file` is the strategy's effective compose (the targetctl
        generated copy when services are excluded, D49); absent, the target's
        own declared compose resolves against its bank entry.
        """
        if compose_file:
            return compose_file
        if config.compose:
            return str(self.compose_path(target, config))
        return None

    def _named_checker(self, name: str):
        checker = getattr(self, f"checker_{name}", None)
        return checker if callable(checker) else None


def helper_for(dataset: BenchmarkDataset) -> DatasetHelper:
    """The helper for a dataset: its own module when present, else the generic one."""
    try:
        module = importlib.import_module(f"orchestrator.datasets.{dataset.id}")
    except ModuleNotFoundError:
        return DatasetHelper(dataset)
    factory = getattr(module, "helper", None)
    return factory(dataset) if callable(factory) else DatasetHelper(dataset)
