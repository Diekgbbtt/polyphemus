"""The skills-access domain: the loader `skill_for`, the `load_skill` tool, and
the per-project skill store and `write_skill` tool.

The substrate loads Markdown SKILL.md files as LLM context (the system-anatomy
skills, the lightrag query guide, the client-side semantic models). Every
on-demand consumer wants the same three behaviours: read `skills/<name>/SKILL.md`,
strip the YAML frontmatter, cache the result, and DEGRADE to a caller-supplied
fallback if the file is unavailable (a missing mount must never crash the pod).
This module is the one place that does it; the anatomy readers
(`_load_webpage_skill`, `_load_authz_skill`) call here, so hardening the loader
hardens every consumer.

Role prompts are NOT skills: each role's system prompt lives with its owning
module in a `prompts/` dir and is read directly (fail-closed) - see
`skills/README.md`. Only genuine progressive-disclosure skills live under
`skills/` and load through here.

#222 makes the single loader agent-reachable: `build_load_skill_tool()` builds
the ONE shared `load_skill` tool, which calls `skill_for` internally, so
bake-time mounts and runtime loads return byte-identical bodies and can never
diverge. Every skill carries a spec-conformant data section (Agent Skills
frontmatter: `name` == the skill directory, `description` = what + when,
`metadata` string map carrying `version`) that `skill_meta` reads,
`validate_skill` judges, and `list_skills` indexes; runtime loading is bounded
by the phase-gating convention (load at phase entry, once per thread, never
speculatively mid-reasoning - see `skills/README.md` and
`docs/design/skill-runtime-loading-222-decisions.md`).

#221 makes the L1 half live: `ROLE_SKILLS` declares each role's bounded skill
set and `skill_agent_binding(role_id)` is the ONE call every tool-calling agent
makes to bind its whole skill surface (index middleware + skill tools + the
context carrying the bounded set), so the frontmatter description of every
skill a role may load is rendered into that role's system message.

#234 adds the write half of the same domain (ADR B1): the per-project skill
store (`SkillStore`) under the app-owned data root, the `write_skill` tool bound
to one project, and the `meta-usage-skill` reading protocol appended by the read
path to every load except meta-family skills (`skills/meta/`). Loader, store,
writer, and protocol injection are one domain
here so they cannot drift; the prompt/compaction domain stays unaware of skills.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from polymerhus.app.data_root import DATA_ROOT, validate_path_component

logger = logging.getLogger(__name__)

# Repo-root `skills/` dir. This file is src/polymerhus/app/llm/skills.py,
# so parents = [llm, app, polymerhus, src, <repo root>] -> parents[4].
# The skills/ mount lives at the repo root (mounted at /srv/skills in dev, baked
# by the Dockerfile in prod), OUTSIDE the src/ package tree.
_SKILLS_ROOT = Path(__file__).resolve().parents[4] / "skills"

# Cache keyed by `(name, fallback)`: the same missing skill read with two
# different fallbacks is two distinct requests, so an earlier cached miss can
# never override the fallback a later caller asked for.
_CACHE: dict[tuple[str, str], str] = {}


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block, leaving the body as-is when there
    is none. The single stripping rule shared by the reader and the store."""
    if text.startswith("---"):
        return text.split("---", 2)[-1].lstrip()
    return text


def skill_for(name: str, *, fallback: str = "") -> str:
    """Return the skill body at `skills/<name>/SKILL.md`, YAML frontmatter
    stripped and cached. `name` is the flat skill name (e.g. 'webpage-profile',
    'lightrag-query'). On a missing or unreadable file, degrade to `fallback`
    (default '') and cache that, so a missing mount degrades gracefully instead
    of crashing the caller. The cache is keyed by `(name, fallback)`: the same
    missing skill read with two different fallbacks is two distinct requests, so
    an earlier cached miss can never override the fallback a later caller asked
    for."""
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
    """Index the skill catalogue: the sorted flat skill names (the directory
    carrying each `SKILL.md` directly under `skills/`)."""
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
    "Your system prompt lists the skills available to you (name + when-to-use). "
    "Call load_skill once per skill whose discipline bears on your turn, then "
    "reason from the returned body; loading the same skill twice returns the "
    "cached body unchanged.\n\n"
    "A missing protocol appends nothing, an unknown skill still degrades to "
    "`''`, and loading a meta-family skill (any skill under `skills/meta/`, "
    "including the protocol skills themselves) returns its bare body (no "
    "protocol on the protocol skills: no blackloops). The appended protocol "
    "always reads from the shared catalogue - a per-project bundle never "
    "shadows it.\n\n"
    "EVERY skill carries a data section (frontmatter with name, description, "
    "metadata.version) so callers can tell what was loaded.\n\n"
    "PHASE-GATING CONVENTION - load at phase entry, once per thread, never "
    "speculatively mid-reasoning: call load_skill once when your phase starts "
    "for each skill your phase needs, then reason from the returned body. "
    "Repeat loads are cache-cheap but a second load buys nothing new. "
    "`refresh` is the development hot-reload path only - never set it mid-run."
)


# The L1 skill index (Q3): the header teaching the L2 move, followed by one
# `- name: description` line per bound skill, sorted. Rendered into the system
# message by `skill_index_middleware` from each skill's frontmatter - the index
# is never hand-written, so it cannot drift from the catalogue.
SKILL_INDEX_HEADER = (
    "Skills available through the `load_skill` tool (load the listed skill "
    "whose discipline bears on your turn):"
)


def render_skill_index(names, project_id: str | None = None, store=None) -> str:
    """Render the L1 index for the bound skill names: the header plus one
    `- name: description` line per skill that resolves (sorted). Unknown names
    are skipped fail-open - a stale binding never breaks the render.

    Resolution is the SAME store seam the loader uses (B3): the per-project
    bundle first (a project-authored skill such as `authn`, whose bundle is the
    only copy), then the shared catalogue. A skill whose frontmatter does not
    resolve - including a project skill whose bundle is NOT at its designed
    data-dir location `<data_root>/<project_id>/skills/<name>/SKILL.md` - is
    simply not collected into the index, so it never renders and never advertises
    itself as available. Without a `project_id` the render is catalogue-only
    (every pre-existing site unchanged)."""
    seam = store if store is not None else SkillStore()
    lines = [SKILL_INDEX_HEADER]
    for name in sorted(set(names)):
        meta = seam.meta(name, project_id=project_id)
        description = meta.get("description") if isinstance(meta, dict) else None
        if not isinstance(description, str) or not description:
            continue
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)


# The bounded skill set per role (#221): the skill-domain analogue of the
# established tool-bounding pattern. A role's cognitive job declares, in ONE
# place, the catalogue skills whose discipline bears on its turns - never the
# whole catalogue, the same minimal-high-signal rule every tool surface
# follows (`runner_react_tools`, `CRAWL_TOOL_NAMES`). The names travel to the
# agent through the native invocation context (`context={"skills": [...]}`) and
# the shared index middleware renders each one's frontmatter `description`
# verbatim into the turn's system message, so the agent reads WHAT it may load
# and WHEN without a word of hand-written index text.
#
# An empty tuple is a deliberate, honest declaration: the role is EXEMPT - it
# binds no skill surface at all (no `load_skill` tool, no L1 index, no
# context-carried set). The rationale is capability minimalism: the skill
# surface earns its context cost only on an agent whose turn can act on
# procedural knowledge, so an exempt role carries neither a dead tool schema nor
# an index that could never render. `skill_agent_binding` enforces the roster:
# a role id that is NOT declared here (usually a typo) raises, so a new
# tool-calling agent cannot silently arrive without a considered decision,
# while a declared-exempt role binds nothing rather than raising (the shared
# actor site serves a bound role and an exempt one).
#
# The analysis module's proposers are exempt on the operator's ruling
# (2026-09-17): their turns interact with LOCAL context only (the published
# L0/L1 substrate through the session seams), never with an external
# environment, so no skill of the catalogue bears on them.
#
# Verify-by-test, not by comment: `test_skill_seam.py` sweeps the roster (every
# session-mode role is declared), pins the exempt set, and asserts every
# declared name resolves in the catalogue - so a stale or forgotten binding
# fails the suite, never a run.
ROLE_SKILLS: dict[str, tuple[str, ...]] = {
    # -- recon -----------------------------------------------------------------
    # The pod triager reads a delivered job's web artefacts into anchored
    # observations; classifying a page's rendering and architectural shape is
    # exactly what the two anatomy skills state.
    "triager": ("webpage-analysis", "webpage-profile"),
    # The configurator picks a rate profile from steering signals, and the
    # control-plane orchestrator routes jobs over assets and phases - both are
    # coverage bookkeeping over signals, not target knowledge.
    "configurator": (),
    "job_orchestrator": (),
    # -- analysis (exempt: local-context reasoning only) ------------------------
    # The three proposers reason over the published L0/L1 substrate into typed
    # model deltas; the catalogue carries no modelling discipline for that job,
    # and their turns never touch an external environment.
    "assigner": (),
    "mechanism_typist": (),
    "data_modeller": (),
    # -- hunting ---------------------------------------------------------------
    # The agent that touches the live target: the KB guide is its retrieval
    # discipline, the browser skill is how a JS-rendered or bot-gated target is
    # actually driven (through its own exec surface).
    "hunting_hunter": ("lightrag-query", "steel-browser"),
    "pod_runner": ("lightrag-query", "steel-browser"),
    # The critic never touches the target: its KB reads are context reads
    # (D84-27), so only the retrieval discipline bears.
    "pod_triager": ("lightrag-query",),
    # The gate/ratify/match decisions run over candidate material; no knowledge
    # skill bears.
    "hunting_orchestrator": (),
    # `crawler` is deliberately ABSENT, not forgotten: it is a tool-calling role
    # (`agent_mode == "session"`) whose loop is a manual `bind_tools` ReAct loop
    # (`recon/crawl/crawl_agentic.py`), not `create_agent`, so no
    # `dynamic_prompt` middleware runs to render an index. Its delivery - the
    # rendered index prepended by direct read plus the load tool in its bound set
    # (the spec's non-`create_agent` clause) - is the known gap; the day it is
    # closed the crawler declares `("steel-browser",)` here and nothing else
    # changes.
    #
    # FORWARD (operator instruction, 2026-09-17): when #223 lands (the recon
    # job-specific agents refactored into stateful entities), those agents take
    # the session seam and MUST be wired to the skill primitives here - declare
    # their bounded sets in this roster and bind them through
    # `skill_agent_binding`, exactly as the hunting roles are.
}


def skills_for_role(role_id: str) -> tuple[str, ...]:
    """The role's bounded skill set: `ROLE_SKILLS[role_id]`, or `()` for an
    unknown role (which `skill_agent_binding` refuses - an undeclared role is a
    wiring defect, not an exemption). `()` for a DECLARED role means exempt: no
    skill surface is bound."""
    return ROLE_SKILLS.get(role_id, ())


@dataclass(frozen=True)
class SkillAgentBinding:
    """One tool-calling agent's complete skill surface, in the three pieces its
    session seam consumes: the L1 index `middleware` (an empty list for an
    exempt role), the L2 skill `tools` (`load_skill`, plus `write_skill` for a
    write-capable agent), and the invocation `context` carrying the role's
    bounded skill set. Compose with `list(mw) + binding.middleware` and
    `list(tools) + binding.tools` - both are lists, so an exempt binding
    composes to nothing and no site needs a branch."""

    role_id: str
    middleware: list
    tools: list
    context: dict


def skill_agent_binding(
    role_id: str,
    *,
    project_id: str | None = None,
    with_write_skill: bool = False,
    store: "SkillStore | None" = None,
) -> SkillAgentBinding:
    """Build the ONE per-agent skill binding (the `skill_agent_seams` successor,
    Q3 -> #221): every tool-calling agent binds its whole skill surface through
    this single call, so the middleware, the tools, and the bounded set can never
    drift or be half-wired - the exact discipline the tool-bounding pattern
    already imposes on a tool surface.

    `role_id` is the role the turn actually runs as (the site's own address or
    role constant), so the declaration in `ROLE_SKILLS` is the only thing that
    decides what the index lists. `project_id`/`with_write_skill`/`store` reach
    `build_skill_tools`, so a read-only agent (the default) can never acquire the
    write tool by accident.

    An UNDECLARED role id raises: the roster is the considered decision for every
    tool-calling role, so an unlisted one (usually a typo) is a wiring defect
    caught at construction, not a silent no-op. A DECLARED role with an empty
    set is exempt and returns an inert binding (no middleware, no tools, no
    skills in the context): the site stays uniform, and nothing dead is bound.
    Import performs no I/O."""
    if role_id not in ROLE_SKILLS:
        raise ValueError(
            f"skill seam: {role_id!r} is not declared in ROLE_SKILLS - every "
            "tool-calling role is either given a bounded skill set there or "
            "declared exempt with an empty tuple. An undeclared role (usually a "
            "typo) is a wiring defect."
        )
    names = ROLE_SKILLS[role_id]
    if not names:
        return SkillAgentBinding(
            role_id=role_id, middleware=[], tools=[], context={}
        )
    # The project id rides the SAME invocation context the bounded set does, so
    # the index resolves per-project bundles (a project-authored skill such as
    # `authn`) and `load_skill` reads them - one seam, no per-site plumbing.
    context = {"skills": list(names)}
    if project_id is not None:
        context["project_id"] = project_id
    return SkillAgentBinding(
        role_id=role_id,
        middleware=[skill_index_middleware(store=store)],
        tools=build_skill_tools(
            project_id, with_write_skill=with_write_skill, store=store
        ),
        context=context,
    )


def _bound_skills(context) -> list:
    """The agent's bounded skill set from the invocation context (Q3-a): the
    `skills` key of the runtime context dict (`agent.invoke(..., context=
    {"skills": [...]})`). Absent, unshaped, or empty -> no index (explicit
    binding required; the middleware never invents one)."""
    if isinstance(context, dict):
        names = context.get("skills")
    else:
        names = getattr(context, "skills", None)
    if not isinstance(names, (list, tuple)):
        return []
    return [n for n in names if isinstance(n, str) and n]


def _context_project_id(context):
    """The bound project id from the native invocation context - the same
    `context=` mapping that carries `skills` (`context={"skills": [...],
    "project_id": "..."}`). Absent or unshaped -> None, so the index stays
    catalogue-only. This is what makes a project-authored skill (a bundle that
    exists only under `<data_root>/<project_id>/skills/`) render its frontmatter
    description into the system prompt."""
    if isinstance(context, dict):
        project_id = context.get("project_id")
    else:
        project_id = getattr(context, "project_id", None)
    return project_id if isinstance(project_id, str) and project_id else None


def skill_index_middleware(store=None):
    """Build the shared L1 skill-index middleware (Q3): a `dynamic_prompt`
    that appends `render_skill_index` for the invocation context's bounded
    skill set to the turn's system message. No bound skills -> the system
    message passes through byte-identical. When the context also carries a
    `project_id`, the index resolves per-project bundles first, so a
    project-authored skill (e.g. `authn`) is collected only when its bundle is
    at the designed data-dir location and renders its own frontmatter
    description.

    The names arrive through the native `context=` seam - `skill_agent_binding`
    fills that context from `ROLE_SKILLS`, so the middleware itself stays
    policy-free and is identical at every agent. Import performs no I/O."""
    from langchain.agents.middleware import dynamic_prompt  # noqa: PLC0415

    @dynamic_prompt
    def _skill_index(request) -> str:
        context = getattr(getattr(request, "runtime", None), "context", None)
        names = _bound_skills(context)
        base = request.system_prompt or ""
        if not names:
            return base
        index = render_skill_index(
            names, project_id=_context_project_id(context), store=store
        )
        return f"{base}\n\n{index}" if base else index

    return _skill_index


# The reading-protocol skill (#234): the first-class usage-protocol skill in
# the shared catalogue, appended to every `load_skill` result by the skill
# read path itself - except meta-family skills (any skill under `skills/meta/`),
# which load bare (no blackloops), and always read from the shared catalogue
# (no shadowing). `PROTOCOL_SEPARATOR` is the pinned composition rule -
# loader-identical body, separator, protocol body.
#
# The meta family is a taxonomy class, not a per-skill flag: the exemption is
# a path rule (`is_meta_skill`), so any skill placed under `skills/meta/` is
# exempt from the usage-protocol append by construction. The two existing
# meta-skills live there beside meta-authoring skills like
# `meta/authn-skill-writing`.
META_SKILLS_PREFIX = "meta/"
META_USAGE_SKILL = f"{META_SKILLS_PREFIX}meta-usage-skill"
META_WRITE_SKILL = f"{META_SKILLS_PREFIX}meta-write-skill"
PROTOCOL_SEPARATOR = "\n\n---\n\n"


def is_meta_skill(name: str) -> bool:
    """The meta-family taxonomy filter: true when `name` is the `meta` area
    itself or any loader path under `skills/meta/` (so `meta/meta-usage-skill`,
    `meta/meta-write-skill`, and `meta/authn-skill-writing` are all meta
    skills). Meta-family skills never receive the `meta-usage-skill` append -
    the exemption is keyed on the directory path, never on a per-skill list, so
    a new meta skill is exempt the moment it lands under `skills/meta/`."""
    return name == META_SKILLS_PREFIX.rstrip("/") or name.startswith(
        META_SKILLS_PREFIX
    )


def build_load_skill_tool(
    project_id: str | None = None, store: "SkillStore | None" = None
):
    """Build the ONE shared `load_skill` agent-callable tool (#222, #234).

    The tool is the single loader made agent-reachable: it reads through the
    shared store seam (the per-project bundle first, then the repo catalogue -
    bake-time mounts and runtime loads can never diverge), then appends the
    `meta-usage-skill` reading protocol (#234: the skills-domain output
    extension - on every load except meta-family skills (under `skills/meta/`),
    no marker,
    no pause mechanism, and no coupling to the prompt or compaction domain).
    `refresh=True` clears the skill cache first (the development hot-reload
    path). Import performs no I/O (CODING_STANDARD section 6); the default store
    is constructed lazily inside the factory call, never at import.

    Fail-open is preserved end to end: a missing protocol appends nothing, an
    unknown skill still degrades to `''`, and loading a meta-family skill
    returns its bare body (no protocol on the protocol skills: no blackloops).
    The appended protocol always reads from the shared catalogue - a
    per-project bundle never shadows it."""
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
        if not body or is_meta_skill(name):
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


# The data-section contract (A3, Agent Skills spec subset): every
# `skills/<name>/SKILL.md` carries YAML frontmatter with `name` (EQUAL to the
# skill directory - the loader path is the index key, the frontmatter name the
# reported identity, and the two must agree), `description` (non-empty: what the
# skill does + when to use it), and a `metadata` string map carrying `version`
# (non-empty). Structured `inputs` do NOT live in frontmatter - the body
# describes invocation context better than a schema stub. Presence, shape, and
# the name==directory rule are validated.
_REQUIRED_DATA_KEYS = ("name", "description", "metadata")


def _version_violations(meta: dict, *, subject: str) -> list[str]:
    """The `metadata.version` rule: a mapping carrying a non-empty string
    `version`. An absent `metadata` is reported by the required-keys sweep, so
    it is not re-reported here."""
    md = meta.get("metadata")
    if md is None:
        return []
    if not isinstance(md, dict):
        return [f"{subject}: 'metadata' must be a mapping"]
    if not isinstance(md.get("version"), str) or not md.get("version"):
        return [f"{subject}: 'metadata.version' must be a non-empty string"]
    return []


def validate_skill(name: str) -> list[str]:
    """Judge one skill against the data-section contract. Returns the list of
    violations (`[]` when conforming) - never raises, so a validator can sweep
    the whole catalogue and report every offender."""
    meta = skill_meta(name)
    errors = []
    for key in _REQUIRED_DATA_KEYS:
        if key not in meta:
            errors.append(f"{name}: data section missing required key {key!r}")
    if "name" in meta:
        if not isinstance(meta["name"], str):
            errors.append(f"{name}: data section 'name' must be a string")
        elif meta["name"] != name.split("/")[-1]:
            errors.append(
                f"{name}: data section 'name' {meta['name']!r} must equal "
                "the skill directory"
            )
    if "description" in meta and (
        not isinstance(meta["description"], str) or not meta["description"]
    ):
        errors.append(
            f"{name}: data section 'description' must be a non-empty string"
        )
    errors.extend(_version_violations(meta, subject=f"{name}: data section"))
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
    errors.extend(_version_violations(meta, subject=f"{skill}: frontmatter"))
    return errors


def _bump_version(version: str) -> str:
    """The operator's monotonic version rule: `major.minor`, minor +1, one
    decimal place. A missing minor part counts as 0."""
    major, _, minor = str(version).partition(".")
    try:
        return f"{int(major)}.{int(minor or 0) + 1}"
    except ValueError as exc:
        raise SkillInvalidError(
            f"skill_invalid: version {version!r} is not major.minor"
        ) from exc


def _dump_frontmatter(meta: dict) -> str:
    """Render the store-owned frontmatter block prepended to a composed
    `procedure` write."""
    import yaml  # noqa: PLC0415 - already a production dependency (hunt_store, ...)

    body = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=4096)
    return f"---\n{body}---\n\n"


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

    def meta(self, name: str, project_id: str | None = None) -> dict:
        """The skill's data section (parsed frontmatter), resolved the same way
        `read` resolves the body: the per-project bundle first, then the shared
        catalogue. A project bundle that is absent, unreadable, or not at its
        designed location falls through to the catalogue; a name with neither
        returns `{}`. Never raises - the index render depends on this."""
        if project_id is not None:
            try:
                path = self._bundle_dir(project_id, name) / "SKILL.md"
                meta = _parse_frontmatter(path.read_text(encoding="utf-8"))
                if meta is not None:
                    return meta
            except (OSError, ValueError):
                logger.warning(
                    "skill store: unreadable project bundle frontmatter for "
                    "%s/%s; falling back to the shared catalogue",
                    project_id,
                    name,
                )
        return skill_meta(name)

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

    def _existing_frontmatter(self, project_id: str, skill: str) -> dict | None:
        """The project bundle's current frontmatter mapping, or `None` when the
        bundle carries no readable SKILL.md (fail-open, like every read)."""
        try:
            path = self._bundle_dir(project_id, skill) / "SKILL.md"
            return _parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _compose_procedure(self, project_id: str, skill: str, body: str) -> str:
        """Compose the store-owned SKILL.md for one `procedure` write.

        The metadata is never the caller's: it is the operator-bootstrapped
        frontmatter the project already carries, or - on the project's first
        update - the shared catalogue skill's frontmatter copied over. The
        store then bumps `metadata.version` one minor and appends the caller's
        body, so a skill with no bootstrapped metadata refuses rather than
        inventing any. Any frontmatter in `body` is dropped.
        """
        meta = self._existing_frontmatter(project_id, skill) or skill_meta(skill)
        if not meta:
            raise SkillInvalidError(
                f"skill_invalid: {skill!r} has no bootstrapped frontmatter "
                "(bootstrap is operator-authorised)"
            )
        source = {**meta, "name": skill}
        violations = _frontmatter_violations(source, skill=skill)
        if violations:
            raise SkillInvalidError("skill_invalid: " + "; ".join(violations))
        composed = {
            "name": skill,
            "description": source["description"],
            "metadata": {"version": _bump_version(source["metadata"]["version"])},
        }
        return _dump_frontmatter(composed) + _strip_frontmatter(body)

    def write(
        self,
        project_id: str,
        skill: str,
        target: str,
        content: str,
        source_note_ids: tuple[str, ...] | list[str] = (),
    ) -> None:
        """Persist one whole bundle file, creating the bundle on first use.

        `target` is the typed surface (`procedure` for the SKILL.md body,
        `references/<name>` for a reference file). `content` must be `str`;
        a `procedure` write carries the body alone (the store composes the
        frontmatter and bumps `metadata.version`), a `references/<name>` write
        carries the whole file. `source_note_ids` is log-only provenance:
        recorded on the write log line, never consulted. Refusals
        (`SkillTargetError`, `SkillInvalidError`, `StoreUnavailableError`)
        carry the coded signal the tool maps to an envelope. Every file write
        is atomic under the per-project lock; a refused write persists nothing.
        """
        if not isinstance(content, str):
            raise SkillInvalidError(
                f"skill_invalid: {skill!r} content must be text"
            )
        file_path = self._target_file(project_id, skill, target)
        if target == "procedure":
            content = self._compose_procedure(project_id, skill, content)
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
    "scripts/, assets/). The `procedure` target carries the SKILL.md body "
    "alone; `references/<name>` writes one bulky target file (endpoint "
    "snapshots, header dumps, role matrices) so the procedure stays compact "
    "and carries only a context pointer. The bundle is created on first write. "
    "The store owns the frontmatter - `name`, `description`, and the "
    "`metadata.version` it bumps one minor per write, carrying the "
    "operator-bootstrapped metadata (the project's own on later writes, the "
    "shared catalogue's copied over on the first); a skill with no "
    "bootstrapped metadata refuses.\n\n"
    "WRITE RULES - one whole file per call, written atomically. "
    "Malformed content fails with `skill_invalid`, an unknown "
    "target with `skill_target`, a degraded store with `store_unavailable`. "
    "Every outcome arrives as an in-band coded envelope; nothing raises into "
    "the turn."
)


def build_write_skill_tool(project_id: str, store: "SkillStore | None" = None):
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
            "SKILL.md body; `references/<name>` writes one reference file."
        )
        content: str = Field(
            description="The whole new file text. A `procedure` write carries "
            "the body alone - the store owns the frontmatter (name, "
            "description, and the metadata.version it bumps); a "
            "`references/<name>` write carries the whole reference file."
        )
        source_note_ids: list[str] = Field(default_factory=list)

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
    store: "SkillStore | None" = None,
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
    "META_SKILLS_PREFIX",
    "META_USAGE_SKILL",
    "META_WRITE_SKILL",
    "PROTOCOL_SEPARATOR",
    "ROLE_SKILLS",
    "SKILL_INDEX_HEADER",
    "SKILL_LOAD_CONTRACT",
    "WRITE_SKILL_CONTRACT",
    "SkillAgentBinding",
    "SkillInvalidError",
    "SkillStore",
    "SkillTargetError",
    "StoreUnavailableError",
    "build_load_skill_tool",
    "build_skill_tools",
    "build_write_skill_tool",
    "clear_cache",
    "is_meta_skill",
    "list_skills",
    "render_skill_index",
    "skill_agent_binding",
    "skill_for",
    "skill_index_middleware",
    "skill_meta",
    "skills_for_role",
    "validate_skill",
]
