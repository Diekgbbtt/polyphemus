"""The SkillEvolver (#232 D232-7/8/9): one bounded evolution pass per
`(project, skill)`, the cap-or-period controller, and the posted-lesson
injection surface.

The app-owned `skills` module lives in the app layer beside the skill store:
evolution is a behaviour OF the skills-access surface, shared across every
module, and not a bounded context of its own.

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
               `HumanMessage`; the turn's surface is the role's bound tools,
               the armed project-bound `write_skill`, and the READ-ONLY
               target-context tools the workflow grounds on (D-W3-5:
               `search_http_history`, `get_http_artifact`, `auth_store`,
               `graph_view`)
    publish  - the AGENT calls its armed project-bound `write_skill`; the store
               re-validates structurally and bumps `metadata.version`
    outcome  - `EvolutionOutcome` carries the decision, the resolved version
               (the new one when `published`, else the base version the pass
               read - `None` only for `skill_unknown`, D-W3-3), the consumed
               keys, and the thread id

The controller is a per-PROJECT session on the app-owned `skills` module,
started on any project launch and shared across every module: per tick it fires
a pass for every skill whose unconsumed count reaches the cap OR whose period
since the last pass elapsed. The per-skill last-pass timestamps are
controller-local and in-memory; consumption is the only durable state. The
controller's thread is a first-class app thread: the project thread endpoint
lists it and the hold/resume verbs address it.

Import performs no I/O (CODING_STANDARD section 6): the stores default lazily,
the prompt is read on first use, and the session/checkpointer seams resolve
inside the default turn.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only; the runtime import is lazy
    from langchain_core.messages import HumanMessage

    from polymerhus.app.llm.checkpoints import FlushResult

from polymerhus.app.data_root import validate_path_component
from polymerhus.app.llm.session_address import ModuleScopedSession
from polymerhus.app.llm.skills import (
    _SKILLS_ROOT,
    PROCEDURE_BRANCH,
    LessonInvalidError,
    LessonStore,
    SkillStore,
    SkillUnknownError,
    StoreUnavailableError,
    dump_text_atomic,
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


def evolver_session_id(project_id: str) -> str:
    """The project-scoped controller session id: `skills:<project_id>:evolver`."""
    if not project_id:
        raise ValueError("project_id must be a non-empty string")
    return f"skills:{project_id}:{EVOLVER_SESSION_SEGMENT}"


def evolver_thread_id(project_id: str, skill: str) -> str:
    """The pass's checkpointer thread: a module-scoped `skills` session with the
    synthetic `skill-evolution:<project_id>` run segment, discriminated by the
    skill. The same logical pass always derives the same id (no UUID/time)."""
    return ModuleScopedSession(
        module="skills",
        run_id=f"{EVOLUTION_RUN_PREFIX}:{project_id}",
        tool=skill,
        role_id=EVOLVER_ROLE_ID,
    ).thread_id


def flush_skills_checkpointer() -> "FlushResult":
    """The app-owned `skills` module's tear-down flush hook: archive the module
    index's committed threads into the still-open pooled saver through the
    SHARED `flush_module_index("skills")` seam. Fail-open via the shared
    `flush_seam_result` boundary."""
    from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
        flush_module_index,
        flush_seam_result,
    )
    return flush_seam_result(lambda: flush_module_index("skills"), module="skills")


def skills_control_plane_available() -> bool:
    """True when the app-owned `skills` module is registered on an active
    runtime. The evolve REST surface fails closed when it is absent."""
    from polymerhus.app.runtime import get_active_runtime  # noqa: PLC0415

    runtime = get_active_runtime()
    if runtime is None:
        return False
    try:
        runtime.handle("skills")
        return True
    except KeyError:
        return False


async def _gate_wait(runtime) -> None:
    """One controller-tick unit boundary on the shared `skills` gate: the module
    pause and the per-session hold both block here."""
    gate = runtime.gate("skills")
    if gate is None:
        return
    async with gate:
        return


def ensure_project_evolver(
    project_id: str, *, runtime=None, controller_fn=None
) -> str | None:
    """Start the project's SkillEvolver controller on the app `skills` module,
    once per project. Called on every project launch; idempotent while the
    controller session is live. Fail-open: a missing runtime or admission
    refusal returns None and never blocks the launch."""
    from polymerhus.app.runtime import get_active_runtime  # noqa: PLC0415

    runtime = runtime or get_active_runtime()
    if runtime is None:
        return None
    session_id = evolver_session_id(project_id)
    coro = None
    try:
        if runtime.has_run("skills", session_id):
            return session_id
        runtime.ensure_running("skills")
        controller = controller_fn or arun_evolver_controller
        coro = controller(project_id, wait_ready=lambda: _gate_wait(runtime))
        runtime.schedule("skills", coro, name=session_id)
        return session_id
    except Exception as exc:  # noqa: BLE001 - fail-open: never block a launch
        if coro is not None:
            coro.close()
        logger.warning(
            "skill evolver: project controller for %s not started (%s); "
            "fail-open", project_id, exc,
        )
        return None


def _finish_record(records, project_id: str, pass_id: str, outcome) -> None:
    """Stamp the durable pass record; a record failure is warned, never a
    reason to lose the pass outcome the caller already holds (fail-open)."""
    try:
        records.finish(project_id, pass_id, outcome)
    except Exception as exc:  # noqa: BLE001 - fail-open bookkeeping
        logger.warning(
            "skill evolver: could not record the evolution pass %s: %s",
            pass_id, exc,
        )


def _degraded_outcome(skill: str, exc: Exception) -> "EvolutionOutcome":
    """The coded outcome a raising forced pass is recorded with."""
    return EvolutionOutcome(
        "degraded", skill, detail=f"turn failed: {exc}")


def launch_evolution_pass(
    project_id: str,
    skill: str,
    *,
    pass_fn=None,
    name=None,
    records=None,
    runtime=None,
) -> Any:
    """Schedule ONE forced SkillEvolver pass on the app `skills` module.

    The REST trigger and the project controller share the module context and
    the per-skill thread, so they can never fork the checkpointer state. The
    pass waits on the shared `skills` gate before it starts, so a project
    thread hold and a module pause address it like any other app thread."""
    from polymerhus.app.runtime import get_active_runtime  # noqa: PLC0415

    runtime = runtime or get_active_runtime()
    if runtime is None:
        raise RuntimeError("skills control plane is not active")
    resolved_name = name or evolution_pass_id(project_id, skill)

    async def _invoke():
        try:
            outcome = await (pass_fn or arun_evolution_pass)(project_id, skill)
        except Exception as exc:  # noqa: BLE001 - the record still settles, then re-raise
            if records is not None:
                _finish_record(
                    records, project_id, resolved_name,
                    _degraded_outcome(skill, exc))
            raise
        if records is not None:
            _finish_record(records, project_id, resolved_name, outcome)
        return outcome

    async def _run():
        gate = runtime.gate("skills")
        if gate is None:
            return await _invoke()
        async with gate:
            return await _invoke()

    coro = _run()
    try:
        return runtime.schedule("skills", coro, name=resolved_name)
    except Exception:  # noqa: BLE001 - close the unscheduled coroutine, re-raise
        coro.close()
        raise


# --- the durable per-pass record (D-W3-4) -------------------------------------
#
# The REST trigger is a launch + status pair, so one pass must stay addressable
# AFTER the request that started it ended. The identifier is the launcher's
# schedule name (`skills:evolve:<project_id>:<skill>`, D-W3-4's named stable
# candidate), and the record is one YAML file per identifier under the
# project's own skill area in the live catalogue root:
#
#     skills/target-specific-procedure/<project_id>/evolution/<pass_id>.yaml
#
# A relaunch for the same (project, skill) replaces the slot's record: the
# identifier addresses the skill's pass slot, and the newest pass is what the
# status endpoint reports. Writes are atomic under the per-project lock (the
# skill store's discipline); reads are fail-open.

EVOLUTION_PASSES_DIRNAME = "evolution"

_PASS_LOCKS: dict[str, threading.Lock] = {}
_PASS_LOCKS_GUARD = threading.Lock()


def evolution_pass_id(project_id: str, skill: str) -> str:
    """The pass identifier: the launcher's schedule name
    `skills:evolve:<project_id>:<skill>` (D-W3-4). Stable for the pass slot of
    one `(project, skill)` and human-addressable, so the launch can hand it out
    and the status endpoint can read the record back from it."""
    return f"skills:evolve:{project_id}:{skill}"


def _pass_lock(root: Path, project_id: str) -> threading.Lock:
    """The per-(root, project) pass-record lock (the skill store's pattern)."""
    key = f"{root}::{project_id}"
    with _PASS_LOCKS_GUARD:
        lock = _PASS_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PASS_LOCKS[key] = lock
        return lock


def _utc_now() -> str:
    import datetime  # noqa: PLC0415 - stdlib, kept local like the store's stamps

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class EvolutionPassStore:
    """The durable per-pass record store behind the launch + status pair
    (D-W3-4): `start` writes the running record a launch hands out,
    `finish` stamps the outcome the launcher read back, and `get` is the
    status endpoint's read. `discard` drops a running record whose launch was
    refused, and only when it is still that same record (a stale discard never
    removes a newer pass's record).

    Rooted under the live `skills/` root (default `_SKILLS_ROOT`), in the
    project's `target-specific-procedure/<project_id>/evolution/` area, beside
    the bundles and the lesson shards; the explicit-root constructor is kept
    for the tests' temp stores. Import performs no I/O."""

    def __init__(self, root_dir: str | Path | None = None):
        self._root = Path(root_dir) if root_dir is not None else _SKILLS_ROOT

    def _record_file(self, project_id: str, pass_id: str) -> Path:
        """The record file for one pass identifier. Both components are
        validated: an unsafe id (separators, traversal, control characters) is
        refused, never escaped into a path. The `:` separators of the schedule
        name are the one character a file name must not carry verbatim, so the
        stem encodes them."""
        validate_path_component(pass_id, "pass_id")
        base = (
            self._root
            / PROCEDURE_BRANCH
            / validate_path_component(project_id, "project_id")
            / EVOLUTION_PASSES_DIRNAME
        )
        return base / f"{pass_id.replace(':', '_')}.yaml"

    def _read(self, path: Path) -> dict | None:
        """One record file's mapping; a missing, unreadable, or unparseable
        file degrades to None with a warning (fail-open, the read doctrine)."""
        import yaml  # noqa: PLC0415 - already a production dependency

        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("skill evolver: unreadable pass record %s: %s", path, exc)
            return None
        return loaded if isinstance(loaded, dict) else None

    def _dump(self, path: Path, record: dict) -> None:
        """Write one record through the skills domain's ONE atomic whole-file
        write (`skills.dump_text_atomic`); a failed dump is a loud
        `StoreUnavailableError`."""
        import yaml  # noqa: PLC0415 - already a production dependency

        dump_text_atomic(
            path,
            yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=4096),
        )

    def get(self, project_id: str, pass_id: str) -> dict | None:
        """The recorded pass, or None: an unknown identifier, an unreadable
        record, and an unsafe identifier all read as None (fail-open - the
        status endpoint maps None to 404)."""
        try:
            path = self._record_file(project_id, pass_id)
        except ValueError as exc:
            logger.warning("skill evolver: unsafe pass id %r: %s", pass_id, exc)
            return None
        return self._read(path)

    def start(self, project_id: str, skill: str, pass_id: str) -> dict:
        """Persist the RUNNING record a launch hands out, replacing any record
        the slot held (a relaunch supersedes the previous pass's record)."""
        path = self._record_file(project_id, pass_id)
        record = {
            "pass_id": pass_id,
            "project_id": project_id,
            "skill": skill,
            "status": "running",
            "launched_at": _utc_now(),
            "finished_at": None,
            "outcome": None,
        }
        with _pass_lock(self._root, project_id):
            self._dump(path, record)
        logger.info(
            "skill evolver: pass %s launched for %s/%s", pass_id, project_id, skill
        )
        return record

    def finish(self, project_id: str, pass_id: str, outcome) -> dict:
        """Stamp the finished record with the pass outcome, keeping the
        launch stamp the record already carries."""
        path = self._record_file(project_id, pass_id)
        with _pass_lock(self._root, project_id):
            record = self._read(path) or {}
            record.update(
                {
                    "pass_id": pass_id,
                    "project_id": project_id,
                    "skill": record.get("skill") or "",
                    "status": "finished",
                    "launched_at": record.get("launched_at") or _utc_now(),
                    "finished_at": _utc_now(),
                    "outcome": outcome.to_dict() if outcome is not None else None,
                }
            )
            self._dump(path, record)
        logger.info(
            "skill evolver: pass %s finished for %s (%s)",
            pass_id,
            project_id,
            (record.get("outcome") or {}).get("decision", "unknown"),
        )
        return record

    def discard(
        self, project_id: str, pass_id: str, *, launched_at: str | None = None
    ) -> None:
        """Drop the slot's record on a refused launch. With `launched_at`
        given, only a record still carrying that launch stamp is dropped, so a
        refused launch never removes a newer pass's record."""
        try:
            path = self._record_file(project_id, pass_id)
        except ValueError:
            return
        with _pass_lock(self._root, project_id):
            record = self._read(path)
            if record is None:
                return
            if launched_at is not None and record.get("launched_at") != launched_at:
                return
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:  # noqa: BLE001 - fail-open cleanup
                logger.warning(
                    "skill evolver: could not drop the refused pass record %s: %s",
                    path,
                    exc,
                )


@dataclasses.dataclass(frozen=True)
class EvolutionOutcome:
    """One pass's outcome. `decision` is the closed vocabulary
    `published | zero_skip | skill_unknown | no_write | degraded`; `version`
    is the RESOLVED version (D-W3-3): the new version a `published` pass read
    back, the base version a `zero_skip` / `no_write` / `degraded` pass read,
    and `None` only for `skill_unknown` and for a failure before any base
    version resolved; `consumed_keys` are the lesson keys this pass marked
    consumed."""

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


def build_evolver_read_tools(project_id: str) -> list:
    """The pass's READ-ONLY target-context surface (D-W3-5): the hunting
    module's `search_http_history` / `get_http_artifact`, the app auth store's
    `auth_store`, and the shared read-only L0/L1 `graph_view`.

    Each tool is the SAME single implementation its other bindings use, with
    the production seam bound here: the Kali HTTP-history client, the
    project-scoped `ReadOnlyGraphView` (which refuses write-shaped cypher), and
    the auth store. The evolver never writes through any of them (D-W3-5): the
    prompt carries the read-only discipline, `graph_view` refuses writes at the
    tool, and the only write path on the pass's surface stays `write_skill`.

    The hunting import resolves LAZILY inside the call (CODING_STANDARD
    section 6): the evolver lives in the app layer, a store-only test must not
    pay the hunting import, and the direction app -> attack already exists at
    the REST launch seam.
    """
    from polymerhus.app.auth.tool import build_auth_store_tool  # noqa: PLC0415
    from polymerhus.app.clients.kali_http_history import (  # noqa: PLC0415
        default_http_get_fn,
        default_http_search_fn,
    )
    from polymerhus.attack.hunting.graph_view_tool import (  # noqa: PLC0415
        build_graph_view_tool,
    )
    from polymerhus.attack.hunting.read_only_graph import (  # noqa: PLC0415
        ReadOnlyGraphView,
    )
    from polymerhus.attack.hunting.hunter_tools import (  # noqa: PLC0415
        HttpHistoryGetTool,
        HttpHistorySearchTool,
    )

    return [
        HttpHistorySearchTool(
            http_search_fn=default_http_search_fn, project_id=project_id
        ),
        HttpHistoryGetTool(
            http_get_fn=default_http_get_fn, project_id=project_id
        ),
        build_auth_store_tool(project_id=project_id),
        build_graph_view_tool(ReadOnlyGraphView(project_id).read),
    ]


def _build_lessons_prompt(skill: str, version: str, records: list[dict]) -> "HumanMessage":
    """One HumanMessage carrying EVERY selected record in its FULL stored shape
    (D232-9: never the lesson prose alone, never a digest), rendered as YAML -
    the same shape the shard holds - grouped under the dispatched skill with
    its current version, plus the instruction. The prose fields stay the
    substance the model reads; the harness's own outcome vocabulary never
    appears here (the result is read from the store, D-W3-1)."""
    from langchain_core.messages import HumanMessage  # noqa: PLC0415 - lazy, no import side effects
    import yaml  # noqa: PLC0415 - already a production dependency

    header = (
        f"Skill: {skill}\n"
        f"Current version: {version}\n"
        f"Unconsumed lessons selected for this pass ({len(records)}):\n\n"
    )
    body = yaml.safe_dump(records, sort_keys=False, allow_unicode=True)
    instruction = (
        "\nVerify these lessons against the read surfaces before you trust them. "
        "Decide whether the survivors ground a revision of the procedure: "
        "create a new skill, update the existing one, or write nothing - "
        "writing nothing is the default when no objectively grounded change "
        "exists. If you change the procedure, publish it with write_skill into "
        "the project bundle and cite the consumed lesson keys in "
        "source_note_ids."
    )
    return HumanMessage(content=header + body + instruction)


async def _default_turn_fn(
    thread_id, prompt, *, tools, middleware, system_prompt, context, model_factory
):
    """The production turn seam: one stateful `arun_session_turn` on the pass's
    thread, resolving the checkpointer for the CURRENT module context (the
    controller and the REST-forced pass run inside the app-owned `skills`
    module context, so the thread lands in the skills index). Imports resolve
    here, never at module import."""
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
    read_tools=None,
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
        return EvolutionOutcome(
            "zero_skip", skill, version=version, thread_id=thread_id
        )

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

    # produce: the role's bound surface, the armed project write tool, and the
    # read-only target-context tools the workflow grounds on (D-W3-5); the
    # prompt as the single HumanMessage, and the injectable turn seam.
    try:
        binding = skill_agent_binding(
            EVOLVER_ROLE_ID,
            project_id=project_id,
            with_write_skill=True,
            store=skill_store,
            lesson_store=lesson_store,
        )
        reads = (
            read_tools
            if read_tools is not None
            else build_evolver_read_tools(project_id)
        )
        tools = list(binding.tools) + list(reads)
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
            tools=tools,
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
    wait_ready=None,
    cap: int | None = None,
    period: float | None = None,
    tick: float | None = None,
) -> None:
    """The cap-or-period controller (D232-8): a per-PROJECT session on the app
    `skills` module that fires `arun_evolution_pass` for every due skill, per
    tick, until its `stop_event` is set or the app runtime cancels it. It is
    shared across every module and is not part of any hunting run's quiesce.
    Fail-open: a failing tick or pass is warned and the loop continues.

    `wait_ready` is the session's unit boundary: an awaitable the project
    launcher binds to the shared `skills` gate. It is awaited once per tick, so
    a module pause and a per-session hold (the app thread REST verbs, by this
    controller's thread id) stop and release the controller exactly like any
    other session. `None` (the unit tests and the REPL) runs ungated."""
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
            if wait_ready is not None:
                await wait_ready()
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
    "EVOLUTION_PASSES_DIRNAME",
    "EVOLUTION_RUN_PREFIX",
    "EVOLVER_ROLE_ID",
    "EVOLVER_SESSION_SEGMENT",
    "EvolutionOutcome",
    "EvolutionPassStore",
    "StoreUnavailableError",
    "append_posted_lessons",
    "arun_evolution_pass",
    "arun_evolver_controller",
    "ensure_project_evolver",
    "flush_skills_checkpointer",
    "launch_evolution_pass",
    "skills_control_plane_available",
    "build_evolver_read_tools",
    "due_skills",
    "evolution_pass_id",
    "evolver_session_id",
    "evolver_thread_id",
]
