"""The SkillEvolver (#232 D232-7/8/9): one bounded evolution pass per
`(project, skill)`, the cap-or-period controller, and the posted-lesson
injection surface.

There is no skills module: this lives in the app layer beside the skill store,
because evolution is a behaviour OF the skills-access surface, not a bounded
context of its own.

The pass is the workflow the role prompt implements:

    inspect  - resolve the skill and its current version (unresolvable ->
               `skill_unknown`, no write)
    select   - ALL unconsumed lessons of that skill (empty -> `zero_skip`, no
               model call, no write)
    mark     - rewrite exactly the selected keys consumed as they are loaded
               for pasting (D232-2's key-encoded idiom; a failed pass has
               consumed its input - the accepted trade)
    produce  - one stateful turn on the per-`(project, skill)` thread, every
               selected record pasted in FULL (key, type, lesson, expected,
               evidence, base_version, agent, written_at) into one
               `HumanMessage`
    publish  - the AGENT calls its armed project-bound `write_skill`; the store
               re-validates structurally and bumps `metadata.version`
    outcome  - `EvolutionOutcome` carries the decision, the version read back,
               the consumed keys, and the thread id

The controller is a per-hunting-run session (scheduled by the hunting bootstrap
alongside the orchestrator pass and the surfer, cancelled with the run): per
tick it fires a pass for every skill whose unconsumed count reaches the cap OR
whose period since the last pass elapsed. The per-skill last-pass timestamps
are controller-local and in-memory; consumption is the only durable state.

Import performs no I/O (CODING_STANDARD section 6): the stores default lazily,
the prompt is read on first use, and the session/checkpointer seams resolve
inside the default turn.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging
import time
from pathlib import Path

from langchain_core.messages import HumanMessage

from polymerhus.app.llm.session_address import ModuleScopedSession
from polymerhus.app.llm.skills import (
    LessonInvalidError,
    LessonStore,
    SkillStore,
    SkillUnknownError,
    skill_agent_binding,
)

logger = logging.getLogger(__name__)

# The role identity the pass runs as (D232-7). It is a declared bound role
# (`ROLE_SKILLS`), a registered session-mode `Role` validated at app boot, and
# the identity the lesson tool stamps on any lesson the pass itself records.
EVOLVER_ROLE_ID = "skill_evolver"

# The run-scoped session segment (the ADR Q13 shape extended by the first free
# segment, exactly like the surfer's).
EVOLVER_SESSION_SEGMENT = "evolver"

# The synthetic run segment of the pass's THREAD (not of a hunting run): it
# makes the thread per-(project, skill) and continuous across hunting runs.
EVOLUTION_RUN_PREFIX = "skill-evolution"


def evolver_session_id(run_id: str) -> str:
    """The run-scoped controller session id: `hunting:<run_id>:evolver`."""
    if not run_id:
        raise ValueError("run_id must be a non-empty string")
    return f"hunting:{run_id}:{EVOLVER_SESSION_SEGMENT}"


def evolver_thread_id(project_id: str, skill: str) -> str:
    """The pass's checkpointer thread: a module-scoped hunting session with the
    synthetic `skill-evolution:<project_id>` run segment, discriminated by the
    skill. The same logical pass always derives the same id (no UUID/time)."""
    return ModuleScopedSession(
        module="hunting",
        run_id=f"{EVOLUTION_RUN_PREFIX}:{project_id}",
        tool=skill,
        role_id=EVOLVER_ROLE_ID,
    ).thread_id


@dataclasses.dataclass(frozen=True)
class EvolutionOutcome:
    """One pass's outcome. `decision` is the closed vocabulary
    `published | zero_skip | skill_unknown | no_write | degraded`; `version` is
    the version read back after the turn (None when no skill resolved);
    `consumed_keys` are the lesson keys this pass marked consumed."""

    decision: str
    skill: str
    version: str | None = None
    consumed_keys: tuple[str, ...] = ()
    thread_id: str | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "skill": self.skill,
            "version": self.version,
            "consumed_keys": list(self.consumed_keys),
            "thread_id": self.thread_id,
            "detail": self.detail,
        }


def due_skills(
    counts: dict[str, int] | "dict[str, int]",
    *,
    last_pass: "dict[str, float]",
    now: float,
    cap: int,
    period: float,
) -> list[str]:
    """The pure due selection (D232-8): a skill with at least one lesson is due
    when its unconsumed count reaches `cap` OR its period since the last pass
    elapsed. A skill with NO `last_pass` entry is NOT due - the controller
    initialises first-sight skills, so the period batches rather than firing
    immediately (only the cap fast-path can fire on first sight). Deterministic:
    sorted output."""
    due: list[str] = []
    for skill in sorted(counts):
        count = counts[skill]
        if count <= 0:
            continue
        if count >= cap:
            due.append(skill)
            continue
        last = last_pass.get(skill)
        if last is not None and now - last >= period:
            due.append(skill)
    return due


@functools.lru_cache(maxsize=1)
def _load_evolver_prompt() -> str:
    """The role prompt, read from the owning module's `prompts/` directory on
    first use (never at import). Fail-closed: an unreadable prompt is a wiring
    defect, not a degraded pass - the caller maps the raise to `degraded`."""
    path = Path(__file__).with_name("prompts") / "skill_evolver.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"skill evolver prompt unreadable at {path}: {exc}") from exc
    if not text.strip():
        raise RuntimeError(f"skill evolver prompt is empty at {path}")
    return text


def _build_lessons_prompt(skill: str, version: str, records: list[dict]) -> HumanMessage:
    """One HumanMessage carrying EVERY selected record in its FULL stored shape
    (D232-9: never the lesson prose alone, never a digest), rendered as YAML -
    the same shape the shard holds - plus a header naming the skill, its
    current version, and the instruction."""
    import yaml  # noqa: PLC0415 - already a production dependency

    header = (
        f"Skill: {skill}\n"
        f"Current version: {version}\n"
        f"Unconsumed lessons selected for this pass ({len(records)}):\n\n"
    )
    body = yaml.safe_dump(records, sort_keys=False, allow_unicode=True)
    instruction = (
        "\nDecide whether these lessons ground a revision of the procedure: "
        "create a new skill, update the existing one, or write nothing "
        "(zero-skip is the default when no objectively grounded change exists). "
        "If you change the procedure, publish it with write_skill into the "
        "project bundle and cite the consumed lesson keys in source_note_ids."
    )
    return HumanMessage(content=header + body + instruction)


async def _default_turn_fn(
    thread_id, prompt, *, tools, middleware, system_prompt, context, model_factory
):
    """The production turn seam: one stateful `arun_session_turn` on the pass's
    thread, resolving the checkpointer for the CURRENT module context (the
    controller runs inside the hunting module context, so the thread lands in
    the hunting index; the REST-forced pass is wrapped by the hunting
    launcher). Imports resolve here, never at module import."""
    from polymerhus.app.llm.checkpoints import get_session_checkpointer  # noqa: PLC0415
    from polymerhus.app.llm.session import arun_session_turn  # noqa: PLC0415

    return await arun_session_turn(
        EVOLVER_ROLE_ID,
        thread_id,
        [prompt],
        checkpointer=get_session_checkpointer(),
        tools=tools,
        middleware=middleware,
        system_prompt=system_prompt,
        context=context,
        model_factory=model_factory,
        extra_tags=("skill-evolution",),
    )


def _resolve_lesson_store(
    lesson_store: LessonStore | None, skill_store: SkillStore | None
) -> LessonStore:
    if lesson_store is not None:
        return lesson_store
    if skill_store is not None:
        return LessonStore(skill_store=skill_store)
    return LessonStore()


async def arun_evolution_pass(
    project_id: str,
    skill: str,
    *,
    skill_store: SkillStore | None = None,
    lesson_store: LessonStore | None = None,
    model=None,
    turn_fn=None,
) -> EvolutionOutcome:
    """One bounded pass for one `(project, skill)` (D232-9). Never raises: every
    failure is a coded `EvolutionOutcome` decision."""
    lesson_store = _resolve_lesson_store(lesson_store, skill_store)
    thread_id = evolver_thread_id(project_id, skill)

    # inspect: resolve the skill's version through the SAME store seam the
    # loader uses; an unresolvable skill cannot be revised (no base to revise).
    try:
        version = lesson_store.base_version(project_id, skill)
    except SkillUnknownError as exc:
        return EvolutionOutcome(
            "skill_unknown", skill, thread_id=thread_id, detail=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 - fail-open: a coded outcome, never a raise
        return EvolutionOutcome(
            "degraded", skill, thread_id=thread_id,
            detail=f"store_unavailable: {exc}",
        )

    # select: ALL unconsumed lessons; none grounds a change, so the pass
    # short-circuits before any model call.
    try:
        records = lesson_store.read(project_id, skill=skill, unconsumed_only=True)
    except Exception as exc:  # noqa: BLE001 - fail-open
        return EvolutionOutcome(
            "degraded", skill, version=version, thread_id=thread_id,
            detail=f"store_unavailable: {exc}",
        )
    if not records:
        return EvolutionOutcome("zero_skip", skill, thread_id=thread_id)

    # mark: the selected keys are consumed as they are loaded for pasting, so a
    # crash cannot re-paste them into a later pass (D232-2's accepted trade: a
    # failed pass has consumed its input; the endpoint can re-post lessons).
    consumed_keys = tuple(str(record.get("key") or "") for record in records)
    try:
        lesson_store.mark_consumed(project_id, consumed_keys)
    except Exception as exc:  # noqa: BLE001 - fail-open: nothing was pasted
        return EvolutionOutcome(
            "degraded", skill, version=version, thread_id=thread_id,
            detail=f"store_unavailable: {exc}",
        )

    # produce: the role's bound surface plus the armed project write tool, the
    # prompt as the single HumanMessage, and the injectable turn seam.
    try:
        binding = skill_agent_binding(
            EVOLVER_ROLE_ID,
            project_id=project_id,
            with_write_skill=True,
            store=skill_store,
            lesson_store=lesson_store,
        )
        system_prompt = _load_evolver_prompt()
        prompt = _build_lessons_prompt(skill, version, records)
    except Exception as exc:  # noqa: BLE001 - fail-open
        return EvolutionOutcome(
            "degraded", skill, version=version, consumed_keys=consumed_keys,
            thread_id=thread_id, detail=f"wiring: {exc}",
        )

    model_factory = (lambda _role_id: model) if model is not None else None
    turn = turn_fn if turn_fn is not None else _default_turn_fn
    try:
        await turn(
            thread_id,
            prompt,
            tools=binding.tools,
            middleware=binding.middleware,
            system_prompt=system_prompt,
            context=binding.context,
            model_factory=model_factory,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open: the pass degrades
        logger.warning(
            "skill evolver: pass for %s/%s degraded: %s", project_id, skill, exc
        )
        return EvolutionOutcome(
            "degraded", skill, version=version, consumed_keys=consumed_keys,
            thread_id=thread_id, detail=f"turn failed: {exc}",
        )

    # outcome: read the version back through the same seam; an unchanged version
    # means the turn decided no write (or its write did not land).
    try:
        new_version = lesson_store.base_version(project_id, skill)
    except Exception:  # noqa: BLE001 - fail-open: fall back to the base
        new_version = version
    decision = "published" if new_version != version else "no_write"
    return EvolutionOutcome(
        decision, skill, version=new_version, consumed_keys=consumed_keys,
        thread_id=thread_id,
    )


async def arun_evolver_controller(
    project_id: str,
    *,
    skill_store: SkillStore | None = None,
    lesson_store: LessonStore | None = None,
    model=None,
    turn_fn=None,
    pass_fn=None,
    stop_event: asyncio.Event | None = None,
    cap: int | None = None,
    period: float | None = None,
    tick: float | None = None,
) -> None:
    """The cap-or-period controller (D232-8): a per-hunting-run session that
    fires `arun_evolution_pass` for every due skill, per tick, until its
    `stop_event` is set or the run's terminal path cancels it. Fail-open: a
    failing tick or pass is warned and the loop continues; the run's status is
    never affected (the controller is not part of quiesce)."""
    lesson_store = _resolve_lesson_store(lesson_store, skill_store)
    if stop_event is None:
        stop_event = asyncio.Event()
    if pass_fn is None:
        pass_fn = arun_evolution_pass
    if cap is None or period is None or tick is None:
        from polymerhus.app.config import config  # noqa: PLC0415 - lazy, no env at import

        cap = config.SKILL_EVOLVER_LESSON_CAP if cap is None else cap
        period = config.SKILL_EVOLVER_PERIOD_S if period is None else period
        tick = config.SKILL_EVOLVER_TICK_S if tick is None else tick

    last_pass: dict[str, float] = {}
    while not stop_event.is_set():
        try:
            now = time.monotonic()
            counts = {
                name: len(lesson_store.read(project_id, skill=name, unconsumed_only=True))
                for name in lesson_store.skills_with_lessons(project_id)
            }
            for name in counts:
                last_pass.setdefault(name, now)
            for name in due_skills(
                counts, last_pass=last_pass, now=now, cap=cap, period=period
            ):
                try:
                    await pass_fn(
                        project_id,
                        name,
                        skill_store=skill_store,
                        lesson_store=lesson_store,
                        model=model,
                        turn_fn=turn_fn,
                    )
                except Exception as exc:  # noqa: BLE001 - fail-open per skill
                    logger.warning(
                        "skill evolver: pass for %s/%s failed (fail-open): %s",
                        project_id, name, exc,
                    )
                last_pass[name] = time.monotonic()
        except Exception as exc:  # noqa: BLE001 - fail-open: a bad tick never kills the loop
            logger.warning(
                "skill evolver: tick for %s failed (fail-open): %s", project_id, exc
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=tick)
        except (asyncio.TimeoutError, TimeoutError):
            continue


def append_posted_lessons(
    project_id: str,
    skill: str,
    lessons,
    *,
    lesson_store: LessonStore | None = None,
) -> list[str]:
    """Append the evolve endpoint's posted lessons (D232-10) to the skill's
    shard, store-stamped and agent-stamped as the operator, BEFORE the forced
    pass runs. Returns the generated keys; a malformed posted lesson raises the
    store's coded `LessonInvalidError` (the endpoint maps it to 400)."""
    store = lesson_store if lesson_store is not None else LessonStore()
    keys: list[str] = []
    for item in lessons or ():
        if not isinstance(item, dict):
            raise LessonInvalidError(
                "lesson_invalid: a posted lesson must be a mapping"
            )
        keys.append(
            store.append(
                project_id,
                skill=skill,
                type=item.get("type") or "",
                lesson=item.get("lesson") or "",
                expected=item.get("expected") or "",
                evidence=item.get("evidence") or [],
                agent={"role_id": "operator"},
            )
        )
    return keys


__all__ = [
    "EVOLUTION_RUN_PREFIX",
    "EVOLVER_ROLE_ID",
    "EVOLVER_SESSION_SEGMENT",
    "EvolutionOutcome",
    "append_posted_lessons",
    "arun_evolution_pass",
    "arun_evolver_controller",
    "due_skills",
    "evolver_session_id",
    "evolver_thread_id",
]
