"""FR-SKILLIF: the single skill loader `skill_for` (L1D-31, ratified door D4).

The recon substrate loads Markdown SKILL.md files as LLM system prompts (the
triager's writing-observations skill, the analyser's service-system-reasoning
skill, and - as the catalogue grows, NM-9 - the system-anatomy skills). Every
loader wants the same three behaviours: read `skills/<name>/SKILL.md`, strip the
YAML frontmatter, cache the result, and DEGRADE to a caller-supplied fallback if
the file is unavailable (a missing mount must never crash the pod). This module
is the one place that does it; `_load_triager_skill` and every per-role skill
loader (the Assigner, the mechanism-typist, the data-modeller, ...) retro-point
here, so hardening the loader hardens every consumer.

#222 makes the single loader agent-reachable: `build_load_skill_tool()` builds
the ONE shared `load_skill` tool, which calls `skill_for` internally, so
bake-time mounts and runtime loads return byte-identical bodies and can never
diverge. Every skill carries a machine-readable data section (`name`,
`description`, `version`, `inputs` frontmatter) that `skill_meta` reads,
`validate_skill` judges, and `list_skills` indexes; runtime loading is bounded
by the phase-gating convention (load at phase entry, once per thread, never
speculatively mid-reasoning - see `skills/README.md` and
`docs/design/skill-runtime-loading-222-decisions.md`).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from pathlib import Path

from polymerhus.app.data_root import DATA_ROOT, validate_path_component

logger = logging.getLogger(__name__)

# Repo-root `skills/` dir. This file is src/polymerhus/recon/domain/skills.py,
# so parents = [domain, recon, polymerhus, src, <repo root>] -> parents[4].
# The skills/ mount lives at the repo root (mounted at /srv/skills in dev, baked
# by the Dockerfile in prod), OUTSIDE the src/ package tree.
_SKILLS_ROOT = Path(__file__).resolve().parents[4] / "skills"

_CACHE: dict[tuple[str, str], str] = {}


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block, leaving the body as-is when there
    is none. The single stripping rule shared by the reader and the store."""
    if text.startswith("---"):
        return text.split("---", 2)[-1].lstrip()
    return text


def skill_for(name: str, *, fallback: str = "") -> str:
    """Return the skill body at `skills/<name>/SKILL.md`, YAML frontmatter
    stripped and cached. `name` is a path under `skills/` using '/' separators
    (e.g. 'recon/triager/writing-observations', 'analysis/analyser'). On a missing
    or unreadable file, degrade to `fallback` (default '') and cache that, so a
    missing mount degrades gracefully instead of crashing the caller. The cache
    is keyed by `(name, fallback)`: the same missing skill read with two
    different fallbacks is two distinct requests, so an earlier cached miss can
    never override the fallback a later caller asked for."""
    key = (name, fallback)
    if key in _CACHE:
        return _CACHE[key]
    path = _SKILLS_ROOT / name / "SKILL.md"
    try:
        text = _strip_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("skill_for: skill not found at %s; using fallback", path)
        text = fallback
    _CACHE[key] = text
    return text


def clear_cache() -> None:
    """Drop the skill cache (test/hot-reload seam)."""
    _CACHE.clear()


def list_skills() -> list[str]:
    """Index the skill catalogue: the sorted loader paths (`'<dir>/...'` under
    `skills/`) of every directory carrying a `SKILL.md`."""
    return sorted(
        str(p.parent.relative_to(_SKILLS_ROOT))
        for p in _SKILLS_ROOT.rglob("SKILL.md")
        if p.is_file()
    )


# The single usage contract, rendered verbatim into the tool description at
# every binding so no agent receives a divergent contract (#222, the #197
# graph_view precedent). Mirrors `skills/README.md` - update both together.
SKILL_LOAD_CONTRACT = (
    "Load a skill by name at runtime: returns the skill body with its YAML "
    "frontmatter stripped - identical semantics to the shared skill_for loader "
    "(cached, fail-open to '' on an unknown skill) - plus the meta-usage-skill "
    "reading protocol appended after a `---` separator (body, separator, "
    "protocol).\n\n"
    "A missing protocol appends nothing, an unknown skill still degrades to "
    "`''`, and loading either meta-skill itself returns its bare body (no "
    "protocol on the protocol skills: no blackloops).\n\n"
    "The appended protocol always reads from the shared catalogue - a "
    "per-project bundle never shadows it.\n\n"
    "EVERY skill carries a data section (frontmatter with name, description, "
    "version, inputs) so callers can tell what was loaded.\n\n"
    "PHASE-GATING CONVENTION - load at phase entry, once per thread, never "
    "speculatively mid-reasoning: call load_skill once when your phase starts "
    "for each skill your phase needs, then reason from the returned body. "
    "Repeat loads are cache-cheap but a second load buys nothing new. "
    "`refresh` is the development hot-reload path only - never set it mid-run."
)


# The reading-protocol skill (#234): the first-class usage-protocol skill in
# the shared catalogue, appended to every `load_skill` result by the skill
# read path itself - except the two meta-skills, which load bare (no
# blackloops), and always read from the shared catalogue (no shadowing). `PROTOCOL_SEPARATOR` is the pinned composition rule -
# loader-identical body, separator, protocol body.
META_USAGE_SKILL = "meta-usage-skill"
META_WRITE_SKILL = "meta-write-skill"
PROTOCOL_SEPARATOR = "\n\n---\n\n"


def build_load_skill_tool(
    project_id: str | None = None, store: SkillStore | None = None
):
    """Build the ONE shared `load_skill` agent-callable tool (#222, #234).

    The tool is the single loader made agent-reachable: it reads through the
    shared store seam (the per-project bundle first, then the repo catalogue -
    bake-time mounts and runtime loads can never diverge), then appends the
    `meta-usage-skill` reading protocol (#234: the skills-domain output
    extension - on every load except the two meta-skills themselves, no
    marker, no pause mechanism,
    and no coupling to the prompt or compaction domain). `refresh=True`
    clears the skill cache first (the development hot-reload path). Import
    performs no I/O (CODING_STANDARD section 6); the default store is
    constructed lazily inside the factory call, never at import.

    Fail-open is preserved end to end: a missing protocol appends nothing, an
    unknown skill still degrades to `''`, and loading either meta-skill
    itself returns its bare body (no protocol on the protocol skills: no
    blackloops). The appended protocol always reads from the shared
    catalogue - a per-project bundle never shadows it."""
    from langchain_core.tools import tool  # noqa: PLC0415

    seam = store if store is not None else SkillStore()

    @tool
    def load_skill(name: str, refresh: bool = False) -> str:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `SKILL_LOAD_CONTRACT` is set on the returned tool explicitly)."""
        if refresh:
            clear_cache()
        body = seam.read(name, project_id=project_id)
        if not body or name in (META_USAGE_SKILL, META_WRITE_SKILL):
            return body
        protocol = seam.read(META_USAGE_SKILL)
        if not protocol:
            return body
        return body + PROTOCOL_SEPARATOR + protocol

    tool_obj = load_skill
    if hasattr(tool_obj, "description"):
        tool_obj.description = SKILL_LOAD_CONTRACT
    return tool_obj


def skill_meta(name: str) -> dict:
    """Return the skill's data section: the parsed YAML frontmatter mapping at
    `skills/<name>/SKILL.md` (`{}` when the file is missing, has no frontmatter,
    or the frontmatter does not parse to a mapping - never a raise)."""
    import yaml  # noqa: PLC0415 - already a production dependency (hunt_store, ...)

    path = _SKILLS_ROOT / name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    raw = text.split("---", 2)[1]
    try:
        meta = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 - unparseable frontmatter degrades to {}
        return {}
    return meta if isinstance(meta, dict) else {}


# The data-section contract (#222): every `skills/**/SKILL.md` carries these
# YAML frontmatter keys. `name`/`description`/`version` are non-empty strings;
# `inputs` is a list (possibly empty) of `{name, description?}` maps declaring
# the invocation context the skill expects. Presence and shape are validated;
# the `name` is deliberately NOT required to equal the loader path - the path
# argument is the index key, the frontmatter name the reported identity.
_REQUIRED_DATA_KEYS = ("name", "description", "version", "inputs")


def validate_skill(name: str) -> list[str]:
    """Judge one skill against the data-section contract. Returns the list of
    violations (`[]` when conforming) - never raises, so a validator can sweep
    the whole catalogue and report every offender."""
    meta = skill_meta(name)
    errors = []
    for key in _REQUIRED_DATA_KEYS:
        if key not in meta:
            errors.append(f"{name}: data section missing required key {key!r}")
    if "name" in meta and not isinstance(meta["name"], str):
        errors.append(f"{name}: data section 'name' must be a string")
    if "description" in meta and not isinstance(meta["description"], str):
        errors.append(f"{name}: data section 'description' must be a string")
    if "version" in meta and (not isinstance(meta["version"], str) or not meta["version"]):
        errors.append(f"{name}: data section 'version' must be a non-empty string")
    if "inputs" in meta:
        inputs = meta["inputs"]
        if not isinstance(inputs, list):
            errors.append(f"{name}: data section 'inputs' must be a list")
        else:
            for item in inputs:
                if isinstance(item, str):
                    continue
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    errors.append(
                        f"{name}: data section 'inputs' items must be "
                        "strings or {name, ...} maps")
                    break
    return errors


# --- The per-project skill store (#234) ---------------------------------------
#
# The per-project skill bundle lives under the app-owned data root beside the
# loader's shared catalogue, in the canonical skill layout:
#
#     <data_root>/<project_id>/skills/<skill_name>/
#     ├── SKILL.md
#     ├── references/
#     ├── scripts/
#     └── assets/
#
# The store is the one authority that reads and writes bundle artifacts: the
# `load_skill` reader resolves the per-project bundle first and the shared
# repo catalogue second, and the `write_skill` writer persists through this
# seam, so bake-time mounts, runtime loads, and executor writes can never
# diverge. Reader reads are fail-open (a missing or unreadable file degrades
# to the fallback); writer writes are strict, atomic (temp file in the same
# dir + `os.replace`) and serialised per project (the `hunt_store` / #220
# auth-store precedent: one `threading.Lock` per `project_id` covers every
# check-then-write critical section).
#
# Writes create the bundle on first use and re-validate the skill
# frontmatter; every refusal is a denoted `ValueError` the `write_skill` tool
# maps to a coded in-band envelope, never a raise into the turn.

# A reference name is one safe file stem - no separators, no traversal.
_REFERENCE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class SkillTargetError(ValueError):
    """The denoted unsupported-target signal: `target` is neither `procedure`
    nor `references/<name>` for a safe single-component `<name>`."""


class SkillInvalidError(ValueError):
    """The denoted malformed-content signal: a `procedure` write whose body
    carries no valid skill frontmatter, or whose frontmatter `name` is not the
    bundle directory it would land in."""


class StoreUnavailableError(ValueError):
    """The denoted degraded-store signal: a write that cannot persist its
    bundle file fails loudly - never a silent corruption."""


# Per-project write serialisation (the `hunt_store` I2 pattern it repeats): a
# per-project lock covers the bundle-creation-plus-atomic-dump critical
# section, so concurrent writers converge instead of forking bundle files
# (content validation is pure and runs before the lock).
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def _lock_for(project_id: str) -> threading.Lock:
    """The per-project lock, created once (the registry itself is guarded
    against concurrent creation)."""
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


def _parse_frontmatter(text: str) -> dict | None:
    """The parsed frontmatter mapping of a skill body, or `None` when the body
    carries none or it does not parse to a mapping - never a raise. `text` is
    the raw file content (frontmatter included)."""
    import yaml  # noqa: PLC0415 - already a production dependency (hunt_store, ...)

    if not text.startswith("---"):
        return None
    try:
        meta = yaml.safe_load(text.split("---", 2)[1])
    except Exception:  # noqa: BLE001 - unparseable frontmatter is not valid
        return None
    return meta if isinstance(meta, dict) else None


def _frontmatter_violations(meta: dict, *, skill: str) -> list[str]:
    """The data-section violations of one bundle frontmatter mapping, plus the
    bundle-identity rule (`name` == the bundle directory). `[]` when valid.
    Same shapes as the catalogue `validate_skill` contract, so a bundle the
    writer accepts would also pass the catalogue sweep."""
    errors = []
    for key in _REQUIRED_DATA_KEYS:
        if key not in meta:
            errors.append(f"{skill}: frontmatter missing required key {key!r}")
    if "name" in meta and meta["name"] != skill:
        errors.append(
            f"{skill}: frontmatter 'name' {meta['name']!r} is not the bundle directory"
        )
    if "description" in meta and (
        not isinstance(meta["description"], str) or not meta["description"]
    ):
        errors.append(
            f"{skill}: frontmatter 'description' must be a non-empty string"
        )
    if "version" in meta and (
        not isinstance(meta["version"], str) or not meta["version"]
    ):
        errors.append(
            f"{skill}: frontmatter 'version' must be a non-empty string"
        )
    if "inputs" in meta:
        inputs = meta["inputs"]
        if not isinstance(inputs, list):
            errors.append(f"{skill}: frontmatter 'inputs' must be a list")
        else:
            for item in inputs:
                if isinstance(item, str):
                    continue
                if not isinstance(item, dict) or not isinstance(
                    item.get("name"), str
                ):
                    errors.append(
                        f"{skill}: frontmatter 'inputs' items must be "
                        "strings or {name, ...} maps")
                    break
    return errors


class SkillStore:
    """The per-project skill-bundle store (#234): the one seam the loader and
    the writer share. Rooted under the app-owned data root (default `DATA_ROOT`);
    the explicit-root constructor is kept for the tests' temp stores (the
    `hunt_store` / #220 auth-store precedent). Import performs no I/O."""

    def __init__(self, root_dir: str | Path | None = None):
        """Rooted under `root_dir` (default: the app-owned `DATA_ROOT`)."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT

    # -- paths -------------------------------------------------------------

    def _project_skills_root(self, project_id: str) -> Path:
        validate_path_component(project_id, "project_id")
        return self._root / project_id / "skills"

    def _bundle_dir(self, project_id: str, skill: str) -> Path:
        validate_path_component(skill, "skill")
        return self._project_skills_root(project_id) / skill

    def _target_file(
        self, project_id: str, skill: str, target: str
    ) -> Path:
        """The bundle file for one write `target`: `procedure` maps to the
        bundle `SKILL.md`; `references/<name>` maps to
        `references/<name>.md`. Anything else raises `SkillTargetError`."""
        if target == "procedure":
            return self._bundle_dir(project_id, skill) / "SKILL.md"
        if target.startswith("references/"):
            name = target[len("references/"):]
            if not name or not _REFERENCE_NAME_RE.fullmatch(name):
                raise SkillTargetError(
                    f"skill_target: {target!r} is not a safe reference name"
                )
            return self._bundle_dir(project_id, skill) / "references" / f"{name}.md"
        raise SkillTargetError(
            f"skill_target: {target!r} must be 'procedure' or 'references/<name>'"
        )

    # -- reads: project-first resolution, always fail-open --------------------

    def read(self, name: str, project_id: str | None = None, fallback: str = "") -> str:
        """The skill body for `name`, frontmatter stripped: the per-project
        bundle first, then the shared repo catalogue. A missing or unreadable
        file degrades to `fallback` (default ''), never a raise."""
        if project_id is not None:
            try:
                path = self._bundle_dir(project_id, name) / "SKILL.md"
                return _strip_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning(
                    "skill store: unreadable project bundle for %s/%s; "
                    "falling back to the shared catalogue",
                    project_id,
                    name,
                )
        return skill_for(name, fallback=fallback)

    # -- writes: validate, then one atomic whole-file rewrite ------------------

    @staticmethod
    def _dump_text_atomic(path: Path, text: str) -> None:
        """Write `text` atomically: dump to a temp file in the SAME directory,
        then `os.replace` onto the target, so every file on disk is whole and
        a crash mid-dump never leaves a partial target (the #220 auth-store
        `_dump_yaml_atomic` discipline for prose)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            raise StoreUnavailableError(
                f"store_unavailable: cannot persist {path} ({exc})"
            ) from exc
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _ensure_bundle(self, project_id: str, skill: str) -> Path:
        """Create the bundle on first use: the skill directory plus its
        canonical `references/`, `scripts/`, `assets/` subdirectories (the
        app-owned scaffold already owns the parent `skills/` dir). A bundle
        that cannot be created refuses `StoreUnavailableError` - never a raw
        `OSError` past this seam."""
        bundle = self._bundle_dir(project_id, skill)
        try:
            for sub in ("references", "scripts", "assets"):
                (bundle / sub).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreUnavailableError(
                f"store_unavailable: cannot create bundle {bundle} ({exc})"
            ) from exc
        return bundle

    def write(
        self,
        project_id: str,
        skill: str,
        target: str,
        content: str,
        source_note_ids: tuple[str, ...] | list[str] = (),
    ) -> None:
        """Persist one whole bundle file, creating the bundle on first use.

        `target` is the typed surface (`procedure` for `SKILL.md`,
        `references/<name>` for a reference file). `content` must be `str`;
        `source_note_ids` is log-only provenance: recorded on the write log
        line, never consulted. Refusals (`SkillTargetError`,
        `SkillInvalidError`, `StoreUnavailableError`) carry the coded signal
        the tool maps to an envelope. Every file write is atomic under the
        per-project lock; a refused write persists nothing.
        """
        if not isinstance(content, str):
            raise SkillInvalidError(
                f"skill_invalid: {skill!r} content must be text"
            )
        file_path = self._target_file(project_id, skill, target)
        if target == "procedure":
            meta = _parse_frontmatter(content)
            if meta is None:
                raise SkillInvalidError(
                    f"skill_invalid: {skill!r} carries no valid skill frontmatter"
                )
            violations = _frontmatter_violations(meta, skill=skill)
            if violations:
                raise SkillInvalidError("skill_invalid: " + "; ".join(violations))
        with _lock_for(f"{self._root}::{project_id}"):
            self._ensure_bundle(project_id, skill)
            self._dump_text_atomic(file_path, content)
            logger.info(
                "skill store: wrote %s target=%s project=%s source_notes=%s",
                skill,
                target,
                project_id,
                list(source_note_ids),
            )


# The single usage contract, rendered verbatim into the tool description at
# every binding so no agent receives a divergent write contract (the
# `GRAPH_VIEW_CONTRACT` / `AUTH_STORE_CONTRACT` precedent). Mirrors
# `skills/README.md` - update both together.
WRITE_SKILL_CONTRACT = (
    "Write the run's per-project skill bundle: the one project-owned skill "
    "directory holding the procedure your project accumulates, so sibling and "
    "later agents start from known ground instead of rediscovering it.\n\n"
    "DOMAIN MODEL - a skill bundle is the project's "
    "`data/<project_id>/skills/<skill>/` directory (SKILL.md, references/, "
    "scripts/, assets/). The `procedure` target rewrites the whole SKILL.md; "
    "`references/<name>` writes one bulky target file (endpoint snapshots, "
    "header dumps, role matrices) so the procedure stays compact and carries "
    "only a context pointer. The bundle is created on first write. Every "
    "procedure write re-validates the frontmatter (name == the bundle "
    "directory, non-empty description and version); a malformed skill is never "
    "persisted.\n\n"
    "WRITE RULES - one whole file per call, written atomically. "
    "Malformed content fails with `skill_invalid`, an unknown "
    "target with `skill_target`, a degraded store with `store_unavailable`. "
    "Every outcome arrives as an in-band coded envelope; nothing raises into "
    "the turn."
)


def build_write_skill_tool(project_id: str, store: SkillStore | None = None):
    """Build the ONE shared `write_skill` agent-callable tool, bound to
    `project_id` (#234).

    `store` is the skill seam (default: the production `SkillStore` -
    constructing it performs no I/O; tests inject an explicit-root store).
    The project id is bound once here; agents never pass identity. Any skill
    in the project's bundle is writable through this tool - the future
    SkillEvolver writes any skill, so there is no per-skill writable set.
    Whether an agent may write at all is decided at the seam: agents that
    execute no evolving procedure are simply not given this tool
    (`build_skill_tools`). The contract rides the tool's description
    verbatim. Import performs no I/O (CODING_STANDARD section 6): the
    default production store is constructed lazily inside the factory call,
    never at import.
    """
    from langchain_core.tools import tool  # noqa: PLC0415
    from pydantic import BaseModel, Field  # noqa: PLC0415

    seam = store if store is not None else SkillStore()

    class WriteSkillArgs(BaseModel):
        """The `write_skill` args (the bound project needs no identity
        parameter)."""

        skill: str = Field(
            description="The project skill bundle to write. The bundle is "
            "created on first write."
        )
        target: str = Field(
            description="The typed write surface: `procedure` rewrites the "
            "whole SKILL.md; `references/<name>` writes one reference file."
        )
        content: str = Field(
            description="The whole new file text. A procedure body must carry "
            "valid skill frontmatter (name == the skill, non-empty "
            "description and version); bulky target material belongs in a "
            "reference."
        )
        source_note_ids: list[str] = Field(
            default_factory=list,
            description="Reserved log-only provenance, recorded and never "
            "consulted at write time.",
        )

    @tool(args_schema=WriteSkillArgs)
    def write_skill(
        skill: str,
        target: str,
        content: str,
        source_note_ids: list | None = None,
    ) -> dict:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `WRITE_SKILL_CONTRACT` is set on the returned tool explicitly)."""
        try:
            seam.write(project_id, skill, target, content,
                       source_note_ids or [])
        except SkillTargetError as exc:
            return {"ok": False, "error": "skill_target", "detail": str(exc)}
        except SkillInvalidError as exc:
            return {"ok": False, "error": "skill_invalid", "detail": str(exc)}
        except StoreUnavailableError as exc:
            return {"ok": False, "error": "store_unavailable",
                    "detail": str(exc)}
        except ValueError as exc:  # noqa: BLE001 - unsafe component, fail-open
            return {"ok": False, "error": "skill_invalid",
                    "detail": f"skill_invalid: {exc}"}
        except Exception as exc:  # noqa: BLE001 - fail-open, never a raise
            return {"ok": False, "error": "store_unavailable",
                    "detail": f"store_unavailable: {exc}"}
        return {"ok": True, "skill": skill, "target": target}

    # The `@tool` decorator snapshots the docstring at decoration; assign the
    # interpolated contract as the description so every binding carries it.
    tool_obj = write_skill
    if hasattr(tool_obj, "description"):
        tool_obj.description = WRITE_SKILL_CONTRACT
    return tool_obj


def build_skill_tools(
    project_id: str | None = None,
    with_write_skill: bool = False,
    store: SkillStore | None = None,
) -> list:
    """The shared agent skill seam (#234): the one place agent owners collect
    the skill tools. Every agent gets the read-only `load_skill`; an agent
    whose procedure evolves a skill additionally gets `write_skill` bound to
    its project, so agents that execute no evolving procedure keep the
    read-only surface and the write blast radius stays explicit. (The L1
    skill-index middleware rides alongside at the agent owner's binding site -
    the #222 seam - composed with this helper, never reimplemented per
    agent.)"""
    tools = [build_load_skill_tool(project_id, store=store)]
    if with_write_skill:
        if not project_id:
            raise ValueError(
                "skill seam: write_skill needs its project_id - a write tool "
                "without a bound project is a wiring defect"
            )
        tools.append(build_write_skill_tool(project_id, store=store))
    return tools


__all__ = [
    "META_USAGE_SKILL",
    "META_WRITE_SKILL",
    "PROTOCOL_SEPARATOR",
    "SKILL_LOAD_CONTRACT",
    "WRITE_SKILL_CONTRACT",
    "SkillInvalidError",
    "SkillStore",
    "SkillTargetError",
    "StoreUnavailableError",
    "build_load_skill_tool",
    "build_skill_tools",
    "build_write_skill_tool",
    "clear_cache",
    "list_skills",
    "skill_for",
    "skill_meta",
    "validate_skill",
]
