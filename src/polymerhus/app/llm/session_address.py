"""Typed session addresses: the domain identity of ONE agent instance's session memory (#94).

A stateful agent's checkpointer thread must uniquely identify the CONCURRENT execution
unit, not merely its role - keying by `(run, role)` alone collides across the several
pods/hunts of a run that share a role, and the checkpointer would then load one
instance's memory into another. The address IS that unique identity.

Why per-module TYPES rather than one `(run, *path, role)` builder: the three modules
discriminate a concurrent instance by structurally DIFFERENT things - an analysis
proposer runs serialized (NO discriminator), a recon pod by (phase, tool, input-asset),
a hunt by (hunt_id [, spec]). A single type spanning all three could only do so with a
union-of-optionals, which reproduces the ambiguity of an untyped positional path in
field form. So each module has its OWN address type with exactly its named fields.

They share no behaviour to inherit - only a CONTRACT (produce a `thread_id`, expose a
`role_id`) - so the shared shape is a structural `Protocol`, not a base class: each
address is an INDEPENDENT frozen dataclass that satisfies `SessionAddress`. Frozen
dataclasses, not pydantic: the value here is naming + immutability + a single escaped
composer, none of which needs a validation framework (the LLM/wire boundary is where
pydantic earns its place, not here).

The one string the LangGraph checkpointer requires (`configurable.thread_id`) is produced
by `.thread_id`; every caller builds an address and reads that, so the escape/hash logic
is single-sourced in `_compose` and never hand-rolled.

The runtime manager's registry lifecycles key on these same ids (ADR #169 Q12/Q14:
session id = coroutine id = registry run name). The runtime's per-session lifecycle
verbs (hold / resume / cancel by id) therefore address the exact session whose memory
the address describes - one identity, two registries.

This module imports nothing heavy and performs no I/O at import (CODING_STANDARD 6).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

# The one separator between address segments. A segment containing it is escaped so an
# occurrence inside a segment can never be read as a boundary.
_SEP = ":"
# Segments longer than this are hashed to keep a thread key bounded (an input-asset url
# is a legitimate but unbounded discriminator); the hash stays collision-free.
_MAX_SEGMENT = 80


def _seg(value: Any) -> str:
    """One address segment, made boundary-safe: the separator is escaped, and an
    over-long segment is replaced by a stable short hash so the key stays bounded
    without losing uniqueness."""
    s = str(value).strip()
    if len(s) > _MAX_SEGMENT:
        return "h" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]
    return s.replace(_SEP, "_")


def _compose(run_id: str, *discriminators: Any, role_id: str) -> str:
    """Compose a thread id: run -> each present instance discriminator -> role. Empty
    (None/"") discriminators are dropped so a missing one never shifts the address."""
    segments = [_seg(run_id)]
    segments += [_seg(d) for d in discriminators if d not in (None, "")]
    segments.append(_seg(role_id))
    return _SEP.join(segments)


def _compose_module_scoped(
    module: str, run_id: str, *discriminators: Any, role_id: str | None = None
) -> str:
    """Compose a module-scoped thread id: module -> run -> each present instance
    discriminator -> role (when given). The module is the LEADING segment so two modules
    can never collide on the same (run, phase, tool, discriminator) in the shared #94
    pooled store; every other rule mirrors `_compose` - empty (None/"") discriminators
    are dropped so a missing one never shifts the address. The result is a PURE function
    of its inputs (no UUID/time/random source), so the same logical instance always
    derives the same id and a post-crash enumeration re-derives the key."""
    segments = [_seg(module), _seg(run_id)]
    segments += [_seg(d) for d in discriminators if d not in (None, "")]
    if role_id not in (None, ""):
        segments.append(_seg(role_id))
    return _SEP.join(segments)


class SessionAddress(Protocol):
    """The structural contract every module's session address satisfies: a stable
    `role_id` and a `thread_id` unique to the concurrent execution unit. A consumer
    (the session seam, the observability config, #85 memory routing) depends on THIS,
    never on a concrete module type."""

    role_id: str

    @property
    def thread_id(self) -> str: ...


@dataclass(frozen=True)
class AnalysisSession:
    """An analysis proposer's session. The proposers run SERIALIZED (the supervisor's
    chunk-major schedule holds `ANALYSER_PASS_SEMAPHORE`, one graph per run), so run +
    role is already unique - there is NO instance discriminator by design."""

    run_id: str
    role_id: str

    @property
    def thread_id(self) -> str:
        return _compose(self.run_id, role_id=self.role_id)


@dataclass(frozen=True)
class PodSession:
    """A recon pod agent's session (the triager today). Up to MAX_PODS pods run one role
    CONCURRENTLY (the job-agent `Send` fan-out), so the address discriminates by the pod
    instance: its phase, tool, and a stable input-asset token (`asset` - the caller
    resolves it, e.g. the input url or a hash of the input asset)."""

    run_id: str
    phase: Any
    tool: str
    asset: str
    role_id: str

    @property
    def thread_id(self) -> str:
        return _compose(self.run_id, self.phase, self.tool, self.asset, role_id=self.role_id)


@dataclass(frozen=True)
class HuntSession:
    """A hunt's stateful agent session. One thread per hunt (the hunter's author + judge
    + back-edge re-entries share it, so the judge resumes the author's reasoning), keyed
    by `hunt_id` so concurrent hunts never collide. The test-executor pod (#84) derives
    its role threads from this same address: `spec` = the semantic spec id
    `<fault>_<strategy>` (the #164 hunter's `SpecItem.spec_id`, ADR #169 Q13 - NOT a
    content hash, and the SAME value the pod-memory keys on), with `role_id` =
    `pod_runner` | `pod_triager` (D84-2)."""

    run_id: str
    hunt_id: str
    role_id: str = "hunting_hunter"
    spec: str | None = None

    @property
    def thread_id(self) -> str:
        return _compose(self.run_id, self.hunt_id, self.spec, role_id=self.role_id)


@dataclass(frozen=True)
class OrchestratorSession:
    """The recon-orchestrator's session: ONE actor per recon run (feat/async-actor-agents).

    The orchestrator is a run-scoped, macro-routing agent driven by `run_pipeline` - not
    a per-pod fan-out like the triager - so run + role already identifies the single
    concurrent instance. There is NO phase discriminator: the actor STAYS ACTIVE across
    the run, taking one routing turn per pipeline phase on the SAME thread, so its
    checkpointed memory carries the steering reasoning across phases."""

    run_id: str
    role_id: str = "job_orchestrator"

    @property
    def thread_id(self) -> str:
        return _compose(self.run_id, role_id=self.role_id)


@dataclass(frozen=True)
class HuntingOrchestratorSession:
    """The hunt-orchestrator's session: ONE actor per hunting run
    (feat/async-actor-agents).

    The hunt-orchestrator is the run-scoped parent of the hunting effort - the gate
    reasoning and the re-match judge both run as turns of ONE actor on this thread, so
    its checkpointed memory carries the pass's reasoning; `run_pipeline`'s recon
    phase controllers are dispatched from this actor's client (`arun_orchestration`).
    No per-direction discriminator: the actor stays active across the whole pass."""

    run_id: str
    role_id: str = "hunting_orchestrator"

    @property
    def thread_id(self) -> str:
        return _compose(self.run_id, role_id=self.role_id)


@dataclass(frozen=True)
class SessionContext:
    """A per-instance session binding an owning node sets for a seam that cannot carry
    the address through its OWN contract (the recon `triage_fn`, the hunting
    `author`/`judge`). Replaces the stringly `(thread_id, checkpointer)` tuple with a
    typed pair the consumer reads as `ctx.address.thread_id` / `ctx.checkpointer`."""

    address: SessionAddress
    checkpointer: Any


@dataclass(frozen=True)
class ModuleScopedSession:
    """A module-scoped session address: the deterministic thread_id the per-module
    checkpointer index, the run-task registry, and the resume enumeration all key on.

    The module types above name exactly what discriminates a module's concurrent
    instances; THIS is the runtime's general address form - the same pure, boundary-safe
    composition with the module namespace as the leading segment - so any module's
    instances resolve through it and two modules can never collide on the same (run,
    phase, tool, discriminator) in the shared #94 pooled store. The composition is a pure
    function of (module, run, phase, tool, discriminator): no UUID, no time source, no
    randomness, so the same logical instance always derives the same id and a post-crash
    enumeration re-derives the key (module-runtime-architecture.md section 6, G7a)."""

    module: str
    run_id: str
    phase: Any = None
    tool: str | None = None
    discriminator: str | None = None
    role_id: str | None = None

    @property
    def thread_id(self) -> str:
        return _compose_module_scoped(
            self.module, self.run_id, self.phase, self.tool, self.discriminator, role_id=self.role_id
        )
