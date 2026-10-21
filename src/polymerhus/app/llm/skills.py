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

W4 mounts the nested suite catalogue: `SkillCatalogue` indexes one root by the
loader name of every `SKILL.md`-bearing directory, whatever its nesting depth.
The live root `skills/` carries four top-level branches (operator topology
ruling, 2026-10-20): `web-vulnerability-testing/` (the suite: the group parents
and their variant leaves report their flat leaf names under the suite's logical
root), `meta/` (the path-shaped meta family), `internal/` (the tool wrappers and
the single-agent specialisations, flat leaf names), and
`target-specific-procedure/` (per-project data, resolved project-first by the
project seam and never in the shared index). A branch is a namespace, never a
skill: no branch directory carries its own `SKILL.md`. The mount refuses a
duplicate name loudly (both colliding paths named) and resolves
`references/`-`scripts/` inside the owning leaf at any depth (taxonomy spec
section 6, rules R1-R4 and R8; the flat live-root layout is superseded).
The DEFAULT resolution of `skill_for`/`list_skills`/`skill_meta`/`validate_skill`
is a lazy `SkillCatalogue` over `_SKILLS_ROOT`, so a nested leaf resolves by
its flat name with no caller plumbing. An explicit `catalogue=` mount still
wins when passed.

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

#236 makes the skill surface artifact-declared and adds the description
listing. `skill_agent_binding(role_id, task_skills=...)` unions an artifact's
declared skill names (a ratified `HuntConfig` for the hunter, a
`TestImplementationSpec` for the pod runner) with the role baseline: the names
resolve through the SAME store seam the loader uses (project bundle first, then
the catalogue), the union is de-duplicated and sorted, the meta family is
refused, and the added set is capped at `MAX_TASK_SKILLS` AFTER resolution - an
unresolvable name is warned and skipped, never silently dropped, and the
baseline is never displaced. The L1 index middleware renders the resolved
descriptions, so the artifact set rides the #221 mechanism with no new
rendering path. The same ONE `load_skill` tool gains the listing mode: no name
lists the catalogue's descriptions (all, or the `pattern` regex), meta excluded,
capped at `MAX_SKILL_LISTING`; the threat modeller's suite pair is a separate
surface, and the shared binding still composes the same listing tool for any
role that lists freely and loads a named body.
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import validate_path_component

logger = logging.getLogger(__name__)

# Repo-root `skills/` dir. This file is src/polymerhus/app/llm/skills.py,
# so parents = [llm, app, polymerhus, src, <repo root>] -> parents[4].
# The skills/ mount lives at the repo root (mounted at /srv/skills in dev, baked
# by the Dockerfile in prod), OUTSIDE the src/ package tree.
_SKILLS_ROOT = Path(__file__).resolve().parents[4] / "skills"

# The suite's logical root (taxonomy spec R1/D-T1): the identity of the whole
# well-formed suite. It never appears as a segment of a reported skill name -
# `SkillCatalogue` mounts the suite branch under it.
#
# The live root's top-level branches (operator topology ruling, 2026-10-20,
# superseding the flat live root): the suite (`web-vulnerability-testing/`), the
# meta family (`meta/`), the internal skills (`internal/`: the tool wrappers and
# the single-agent specialisations), and the per-project procedures
# (`target-specific-procedure/<project_id>/`). A branch is a namespace, never a
# skill: no branch directory carries its own `SKILL.md`, and a project skill may
# not take a branch name.
LOGICAL_SUITE_ROOT = "web-vulnerability-testing"
META_BRANCH = "meta"
INTERNAL_BRANCH = "internal"
PROCEDURE_BRANCH = "target-specific-procedure"
BRANCH_NAMES = frozenset(
    {LOGICAL_SUITE_ROOT, META_BRANCH, INTERNAL_BRANCH, PROCEDURE_BRANCH}
)

# Cache keyed by `(root, name, fallback)`: the same leaf name read from two
# catalogues (the live root and an explicitly mounted one) is two distinct
# requests, so a mounted catalogue can never serve the live root's body or the
# reverse. It is also keyed by `fallback`: the same missing skill read with two
# different fallbacks is two distinct requests, so an earlier cached miss can
# never override the fallback a later caller asked for.
_CACHE: dict[tuple[str, str, str], str] = {}


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block, leaving the body as-is when there
    is none. The single stripping rule shared by the reader and the store."""
    if text.startswith("---"):
        return text.split("---", 2)[-1].lstrip()
    return text


def _parse_frontmatter(text: str) -> dict | None:
    """The parsed frontmatter mapping of a skill body, or `None` when the body
    carries none or it does not parse to a mapping - never a raise. `text` is
    the raw file content (frontmatter included). The ONE frontmatter parser: the
    catalogue reader and the per-project store judge the same shape."""
    import yaml  # noqa: PLC0415 - already a production dependency (hunt_store, ...)

    if not text.startswith("---"):
        return None
    try:
        meta = yaml.safe_load(text.split("---", 2)[1])
    except Exception:  # noqa: BLE001 - unparseable frontmatter is not valid
        return None
    return meta if isinstance(meta, dict) else None


def _read_cached(root: Path, name: str, path: Path | None, fallback: str) -> str:
    """The one read-and-cache path behind `skill_for` and every mounted
    catalogue: read `path`, strip the frontmatter, cache under
    `(root, name, fallback)`. `path` is None when the name resolves no bundle
    (an unknown name, or a missing mount): the fallback is cached and returned,
    so a missing mount degrades gracefully instead of crashing the caller."""
    key = (str(root), name, fallback)
    if key in _CACHE:
        return _CACHE[key]
    if path is None:
        logger.warning(
            "skill loader: no skill %r under %s; using fallback", name, root
        )
        text = fallback
    else:
        try:
            text = _strip_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            logger.warning(
                "skill loader: skill not found at %s; using fallback", path
            )
            text = fallback
    _CACHE[key] = text
    return text


def skill_for(
    name: str,
    *,
    fallback: str = "",
    catalogue: "SkillCatalogue | None" = None,
) -> str:
    """Return the named skill body, YAML frontmatter stripped and cached. `name`
    is the loader name (`webpage-profile`, `lightrag-query`, a suite leaf such
    as `jwt-claims-confusion`; the `meta/` family keeps its path shape:
    `meta/meta-usage-skill`). On a missing or unreadable bundle, degrade to
    `fallback` (default '') and cache that, so a missing mount degrades
    gracefully instead of crashing the caller.

    The default resolves through the lazy live-root catalogue (`skills/`), so
    the suite's nested leaves load by their flat leaf name. `catalogue` selects
    an EXPLICIT mount (W4): the read then resolves through that index, and an
    explicit mount still wins over the live root."""
    if catalogue is not None:
        return catalogue.read(name, fallback=fallback)
    return _live_catalogue().read(name, fallback=fallback)


def clear_cache() -> None:
    """Drop the skill cache (test/hot-reload seam) - every catalogue's, the
    lazy live-root index included, so a newly added skill is re-indexed."""
    _CACHE.clear()
    _reset_live_catalogue()


def list_skills(catalogue: "SkillCatalogue | None" = None) -> list[str]:
    """Index the skill catalogue: the sorted loader names of every
    `SKILL.md`-bearing directory under the live root `skills/` (a level-1 flat
    skill or group parent, a level-2 variant). With `catalogue` given, the
    explicit mount's index is reported instead. A level-2 namespaced skill (the
    `meta/` family) keeps its path-shaped name, so the path-based meta rule
    still holds; the logical root never appears (R1/R3)."""
    if catalogue is not None:
        return catalogue.list_skills()
    return _live_catalogue().list_skills()


def list_suite_classes(catalogue: "SkillCatalogue | None" = None) -> list[str]:
    """The web-vulnerability suite's CLASS parents (the level-1 bundles under
    `web-vulnerability-testing/`). This is the class vocabulary the unit threat
    model's `web_vulnerability_class` stores; the nested variants are procedures,
    not classes."""
    if catalogue is not None:
        return catalogue.suite_classes()
    return _live_catalogue().suite_classes()


def list_suite_leaves(catalogue: "SkillCatalogue | None" = None) -> list[str]:
    """Every web-vulnerability suite skill: the class parents AND their nested
    variant leaves. The threat modeller's and the hunter's `skill_list` render
    this discovery surface, so an assumption probe can load any leaf procedure."""
    if catalogue is not None:
        return catalogue.suite_leaves()
    return _live_catalogue().suite_leaves()


def read_suite_raw(name: str, catalogue: "SkillCatalogue | None" = None) -> str:
    """One suite class's raw `SKILL.md` text (frontmatter intact), for the
    suite seam's listing parser and load. An unknown name degrades to ""."""
    if catalogue is not None:
        return catalogue.read_raw(name)
    return _live_catalogue().read_raw(name)


# --- The nested catalogue (W4, taxonomy spec section 6; the mount replacement) -
#
# The live catalogue root (`_SKILLS_ROOT`) now carries the suite's nested groups
# (a class or family parent at level 1, its variants at level 2) beside the
# flat product skills and the `meta/` family. Production therefore resolves it
# through ONE catalogue: `SkillCatalogue` lazily indexes the live root as the
# DEFAULT, so `skill_for`, `list_skills`, `skill_meta`, `validate_skill`, the
# store seam, the L1 index, and the artifact-declared task skills all follow
# the same index. An explicit `catalogue=` mount is still an index over an
# explicit root and still wins when passed.
#
# The index is built once per snapshot (the live snapshot is rebuilt by
# `clear_cache`, the test/hot-reload seam), and every name it reports is the
# containing directory name of a SKILL.md - except a level-2 bundle under a
# plain namespace directory (`meta/`), whose loader name keeps the path. Three
# defects are loud at mount time, because each one would otherwise hide a skill
# or load the wrong bundle: a duplicate leaf name (R4), a SKILL.md outside the
# two catalogue levels (R2), and a bundle directory carrying the logical root's
# name (R1).


class DuplicateSkillNameError(ValueError):
    """The denoted duplicate-name signal (R4/D-T3): two `SKILL.md`-bearing
    directories carry the same leaf name, so a flat-leaf load could not pick
    one. Carries the colliding `name` and both bundle directories (`first`,
    `second`), so a caller can report the collision without parsing prose."""

    def __init__(self, name: str, first: Path, second: Path):
        self.name = name
        self.first = Path(first)
        self.second = Path(second)
        super().__init__(
            f"duplicate_skill_name: {name!r} resolves to two bundles - "
            f"{self.first} and {self.second}; suite names are globally unique "
            "(taxonomy spec R4), so no load may pick one silently"
        )


class SkillLayoutError(ValueError):
    """The denoted misplaced-bundle signal: a `SKILL.md` at a branch root (a
    branch is a namespace, never a skill), or a bundle directory carrying the
    logical root's name."""


class SkillCatalogue:
    """The catalogue index (W4): one root, indexed by the flat leaf name of
    every `SKILL.md`-bearing directory.

    Mounting is an identity (R1): `logical_root` names the whole catalogue and
    defaults to the suite's (`LOGICAL_SUITE_ROOT`); it never appears in a
    reported name. Construction scans the root and raises
    `DuplicateSkillNameError` / `SkillLayoutError` (both ValueError) on the
    first defect, so a catalogue that would resolve ambiguously never loads.
    A missing root mounts as an empty catalogue: reads degrade to their
    fallback exactly like `skill_for`. Import performs no I/O; the scan is the
    explicit mount call, and the index is the snapshot a caller mounts.

    A bundle's reported name follows the branches: a bundle under `meta/`
    keeps its root-relative path (a namespaced meta skill, so `is_meta_skill`
    and the declared `meta/...` names keep resolving); a bundle under
    `target-specific-procedure/` is per-project data and stays out of the
    shared index; every other bundle reports its flat leaf directory name, so
    the suite variants and the internal tools keep the layout-agnostic identity
    every client loads, lists, and validates by."""

    def __init__(
        self, root: str | Path, *, logical_root: str = LOGICAL_SUITE_ROOT
    ):
        self._root = Path(root)
        # The identity must be ONE safe component (R1: never a path), so the
        # shared component rule refuses a root that could read as a name path.
        self._logical_root = validate_path_component(logical_root, "logical_root")
        self._bundles = self._index()

    # -- the mount identity and the index -------------------------------------

    @property
    def root(self) -> Path:
        """The physical root this catalogue was mounted from."""
        return self._root

    @property
    def logical_root(self) -> str:
        """The catalogue's identity under its mount (R1)."""
        return self._logical_root

    def _index(self) -> dict[str, Path]:
        """The name -> bundle-directory index over the whole mounted tree,
        walked in sorted (deterministic) order so the reported FIRST duplicate
        is stable: the earlier path in walk order is `first`.

        Every `SKILL.md`-bearing directory is a skill, whatever its nesting
        depth below the mount, so every client stays agnostic to the branch
        layout. Three rules decide the reported name: a bundle under the
        `meta/` branch keeps its root-relative path (the path-keyed meta rule);
        a bundle under the `target-specific-procedure/` branch is per-project
        data, resolved by the project seam project-first, never in the shared
        index (each project carries its own `authn`); every other bundle
        reports its flat leaf directory name, whichever branch holds it. The
        branch roots themselves are namespaces, never skills."""
        bundles: dict[str, Path] = {}
        for skill_file in sorted(self._root.rglob("SKILL.md"), key=str):
            if not skill_file.is_file():
                continue
            bundle = skill_file.parent
            parts = bundle.relative_to(self._root).parts
            if parts[0] == PROCEDURE_BRANCH:
                continue
            if len(parts) == 1 and parts[0] in BRANCH_NAMES:
                raise SkillLayoutError(
                    f"skill_layout: {skill_file} sits at a branch root; a "
                    "branch is a namespace, not a skill (topology ruling)"
                )
            if bundle.name == self._logical_root:
                raise SkillLayoutError(
                    f"skill_layout: {bundle} carries the logical root's name "
                    f"{self._logical_root!r}; the root is an identity, never a "
                    "skill name (taxonomy spec R1)"
                )
            name = "/".join(parts) if parts[0] == META_BRANCH else bundle.name
            first = bundles.get(name)
            if first is not None:
                raise DuplicateSkillNameError(name, first, bundle)
            bundles[name] = bundle
        return bundles

    # -- reads: the same fail-open contract as the flat loader -----------------

    def list_skills(self) -> list[str]:
        """The catalogue's sorted loader names: the containing directory of
        every indexed `SKILL.md` (the flat leaf, R3); a namespaced skill (the
        `meta/` family) keeps its path-shaped root-relative name. Never the
        logical root."""
        return sorted(self._bundles)

    def read(self, name: str, *, fallback: str = "") -> str:
        """The named skill's body, frontmatter stripped and cached: the flat
        leaf resolves whichever group holds it (R3), and a namespaced skill
        resolves by its path-shaped name. An unknown name degrades to
        `fallback` (default ''), never a raise - the same fail-open contract
        `skill_for` states."""
        bundle = self._bundles.get(name)
        path = bundle / "SKILL.md" if bundle is not None else None
        return _read_cached(self._root, name, path, fallback)

    def meta(self, name: str) -> dict:
        """The named skill's parsed data section: `{}` for an unknown name, or
        frontmatter that is absent or does not parse to a mapping - never a
        raise. Read from the leaf the index resolved."""
        bundle = self._bundles.get(name)
        if bundle is None:
            return {}
        try:
            text = (bundle / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            return {}
        return _parse_frontmatter(text) or {}

    def bundle_path(self, name: str, relative: str = "") -> Path | None:
        """The path of one skill-local bundle artefact (R8) under the leaf's own
        directory: `references/<slug>.md`, `scripts/<slug>`, or the bundle
        directory itself for an empty `relative`. Returns None for an unknown
        name. A `relative` that is absolute, carries a backslash, or escapes the
        leaf directory raises ValueError - a traversal attempt is refused, never
        followed (the same separator rule `validate_path_component` applies)."""
        target = Path(relative)
        if target.is_absolute() or ".." in target.parts or "\\" in relative:
            raise ValueError(
                f"skill_bundle: {relative!r} is not a safe bundle-relative path"
            )
        bundle = self._bundles.get(name)
        if bundle is None:
            return None
        return bundle / target

    def suite_classes(self) -> list[str]:
        """The suite's CLASS parents: the level-1 bundles under the logical
        root. A class parent is the directory name the unit threat model stores
        in `web_vulnerability_class`; the nested variant leaves are procedures
        of that class, never separate classes."""
        suite_root = (self._root / self._logical_root).resolve()
        return sorted(
            name for name, bundle in self._bundles.items()
            if bundle.parent.resolve() == suite_root
        )

    def suite_leaves(self) -> list[str]:
        """Every suite skill: the class parents AND their nested variant leaves.
        This is the discovery surface the threat modeller and the hunter list;
        the class parent remains the value stored in `web_vulnerability_class`."""
        suite_root = (self._root / self._logical_root).resolve()
        return sorted(
            name for name, bundle in self._bundles.items()
            if suite_root in bundle.resolve().parents
        )

    def read_raw(self, name: str) -> str:
        """The named skill's `SKILL.md` text with the frontmatter INTACT (the
        suite seam's listing parses it; the seam strips the body on load). An
        unknown name returns "" and never raises - the same fail-open contract
        as `read`."""
        bundle = self._bundles.get(name)
        if bundle is None:
            return ""
        try:
            return (bundle / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            return ""


# The live-root catalogue is built LAZILY on the first read: the import stays
# I/O-free (CODING_STANDARD section 6). `_LIVE_CATALOGUE_ROOT` records the root
# the snapshot indexes, so a test or a hot reload that repoints `_SKILLS_ROOT`
# rebuilds instead of serving a stale index; the lock keeps two first readers
# from racing the scan. A malformed live tree degrades to an empty catalogue
# with one loud log rather than raising into an agent turn - the fail-open
# contract every read states (the repo checks and tests still fail the defect).
# The sentinel child path a failed live mount degrades to: it is never created
# and carries no bundles, so the fallback catalogue is empty by construction
# rather than a half-built index.
_LIVE_CATALOGUE_EMPTY = ".unmounted"

_LIVE_CATALOGUE_LOCK = threading.Lock()
_LIVE_CATALOGUE: "SkillCatalogue | None" = None
_LIVE_CATALOGUE_ROOT: Path | None = None


def _empty_live_catalogue(root: Path) -> "SkillCatalogue":
    """The empty catalogue a malformed live tree degrades to: mounted under the
    sentinel child no skill scan creates, so every read resolves nothing."""
    return SkillCatalogue(root / _LIVE_CATALOGUE_EMPTY)


def _live_catalogue() -> "SkillCatalogue":
    """The lazily mounted catalogue over the live root (the mount replacement):
    the DEFAULT resolution behind `skill_for`, `list_skills`, and `skill_meta`.
    Built once per root snapshot (rebuilt after `clear_cache`). A root whose
    tree fails to mount is logged and replaced by an empty catalogue, so every
    read degrades to its fallback instead of crashing an agent turn."""
    global _LIVE_CATALOGUE, _LIVE_CATALOGUE_ROOT
    root = Path(_SKILLS_ROOT)
    with _LIVE_CATALOGUE_LOCK:
        if _LIVE_CATALOGUE is None or _LIVE_CATALOGUE_ROOT != root:
            try:
                catalogue = SkillCatalogue(root)
            except (OSError, ValueError):
                logger.exception(
                    "skill loader: the live catalogue at %s failed to mount; "
                    "every skill read degrades to its fallback",
                    root,
                )
                catalogue = _empty_live_catalogue(root)
            _LIVE_CATALOGUE = catalogue
            _LIVE_CATALOGUE_ROOT = root
        return _LIVE_CATALOGUE


def _reset_live_catalogue() -> None:
    """Drop the live-root snapshot (the `clear_cache` half): the next read
    re-scans, so a newly added skill is indexed and a repointed root is
    followed."""
    global _LIVE_CATALOGUE, _LIVE_CATALOGUE_ROOT
    with _LIVE_CATALOGUE_LOCK:
        _LIVE_CATALOGUE = None
        _LIVE_CATALOGUE_ROOT = None


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
    "LISTING MODE - call load_skill with no name to list the catalogue's skill "
    "descriptions (name + when-to-use), optionally narrowed by `pattern` (a "
    "regex searched against each skill's name and description). The listing is "
    "the discovery surface for a skill outside your bound index, it never "
    "returns a body, it excludes the meta-family skills, and it is capped (the "
    "omitted count is stated).\n\n"
    "PHASE-GATING CONVENTION - load at phase entry, once per thread, never "
    "speculatively mid-reasoning: call load_skill once when your phase starts "
    "for each skill your phase needs, then reason from the returned body. "
    "Repeat loads are cache-cheap but a second load buys nothing new. "
    "`refresh` is the development hot-reload path only - never set it mid-run."
)

# The listing-mode header: the header teaching the discovery move, followed by
# one `- name: description` line per skill the pattern matched, sorted. Rendered
# from each skill's frontmatter, so the listing can never drift from the
# catalogue.
SKILL_LIST_HEADER = (
    "Skill descriptions available through the `load_skill` listing (call "
    "`load_skill` with no name to list them all, or pass `pattern` - a regex - "
    "to narrow; the listing excludes the meta-family skills):"
)

# The hard ceiling on one description listing (#236): the catalogue and a
# project's own bundles are both unbounded in principle, so the listing is
# capped and the omitted count is stated - never an unbounded prompt growth.
MAX_SKILL_LISTING = 32


def list_skill_descriptions(
    *,
    project_id: str | None = None,
    store: "SkillStore | None" = None,
    pattern: str = "",
) -> str:
    """Render the description listing of the skill catalogue (#236): the
    header plus one `- name: description` line per skill, sorted, resolved
    through the SAME store seam the loader uses (the per-project bundle first,
    then the shared catalogue). The project's own bundles are enumerated too, so
    a project-authored skill is discoverable.

    The meta-family skills are excluded (the mechanism's job, never the
    author's), the listing is capped at `MAX_SKILL_LISTING` with the omitted
    count stated, and `pattern` is a regex searched against each skill's NAME
    and its DESCRIPTION (so both a name filter and a text filter work).
    The cap is a read bound as well as an output bound: once it is reached no
    further frontmatter is resolved, and the remaining candidates are counted
    from the names alone.
    Fail-open, always loud: an invalid pattern, an empty result, and a
    truncation each render an explicit line - never a blank or silently absent
    listing."""
    seam = store if store is not None else SkillStore()
    names = set(list_skills())
    names.update(seam.list_skills(project_id))
    matcher = None
    if pattern:
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            return f"load_skill: invalid pattern {pattern!r} ({exc}); nothing listed."
    # The meta exclusion is a name rule, so the candidate list is built without
    # a read; the cap then bounds the frontmatter reads below, not just the
    # rendered lines.
    candidates = [name for name in sorted(names) if not is_meta_skill(name)]
    lines = [SKILL_LIST_HEADER]
    listed = 0
    omitted = 0
    for index, name in enumerate(candidates):
        if listed >= MAX_SKILL_LISTING:
            # The cap is a READ bound: once MAX accepted entries are listed, no
            # further frontmatter is read; the remaining candidates are counted
            # from the names alone and stated as omitted.
            omitted = len(candidates) - index
            break
        meta = seam.meta(name, project_id=project_id)
        description = meta.get("description") if isinstance(meta, dict) else None
        if not isinstance(description, str) or not description:
            continue
        line = f"- {name}: {description}"
        if matcher is not None and not (
            matcher.search(name) or matcher.search(description)
        ):
            continue
        lines.append(line)
        listed += 1
    if omitted:
        lines.append(f"- ({omitted} more skills match; narrow with `pattern`)")
    elif not listed:
        lines.append(
            f"(no skill matches {pattern!r})" if pattern else "(no skill resolves)"
        )
    return "\n".join(lines)


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
    location
    `skills/target-specific-procedure/<project_id>/<name>/SKILL.md` - is
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
    # The configurator role is reserved for the #238 profile-driven
    # rate-limit configuration (its steering-fed throttle turn retired with
    # the mid-run steering machinery, #243), and the control-plane
    # orchestrator routes jobs over assets and phases - both are coverage
    # bookkeeping over signals, not target knowledge.
    "configurator": (),
    "job_orchestrator": (),
    # -- analysis (exempt: local-context reasoning only) ------------------------
    # The proposers reason over the published L0/L1 substrate into typed model
    # deltas; the catalogue carries no modelling discipline for that job, and
    # their turns never touch an external environment.
    "assigner": (),
    "mechanism_typist": (),
    # -- hunting ---------------------------------------------------------------
    # The agent that touches the live target: the KB guide is its retrieval
    # discipline, the browser skill is how a JS-rendered or bot-gated target is
    # actually driven (through its own exec surface).
    "hunting_hunter": ("lightrag-query", "steel-browser"),
    "pod_runner": ("lightrag-query", "steel-browser"),
    # The critic never touches the target: its KB reads are context reads
    # (D84-27), so only the retrieval discipline bears.
    "pod_triager": ("lightrag-query",),
    # The threat modeller (S1 5.5): no catalogue skill bears on the job - its
    # class material is the web-vulnerability SUITE, bound through the
    # modeller's own `skill_list` / `skill_load` pair - so the roster declares it
    # exempt and the actor arms the read-only skill surface + `auth_store`
    # explicitly (the recon-orchestrator coupling, `app/auth/seams.py`).
    "hunting_threat_modeller": (),
    # -- app (the skill-evolution loop) -----------------------------------------
    # The SkillEvolver authors revisions of project bundles; its discipline is
    # the authoring meta-skill (#232 D232-7). It is a BOUND role whose pass arms
    # its own binding with the write capability (`with_write_skill=True`).
    "skill_evolver": ("meta/meta-write-skill",),
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


# The hard ceiling on the artifact-declared additions ONE binding accepts
# (#236): the artifact is LLM-authored, so the exclusion of the meta family and
# this cap are the MECHANISM's job, never the author's goodwill. The cap applies
# to the RESOLVED additions (a name that resolves nothing is skipped first), in
# deterministic sorted order; the dropped tail is named in a warning - never a
# silent drop.
MAX_TASK_SKILLS = 8


def _resolve_task_skills(
    task_skills,
    *,
    role_id: str,
    project_id: str | None,
    seam: "SkillStore",
) -> list[str]:
    """Resolve an artifact-declared skill list into the names that may join the
    role's bounded set (#236): the ONE policy for identifiers that resolve to
    nothing is WARN PLUS SKIP - an LLM-authored artifact is never trusted to
    name only existing skills, and a stale name must degrade the hunt's skill
    set, never crash the dispatch or render a blank line.

    Order of the gates, each loud:

    - a malformed declaration (a bare string, a non-iterable, a non-string
      entry, an empty name) degrades to nothing with a warning;
    - a meta-family name (`is_meta_skill`) is refused with a warning: the meta
      skills stay unadvertised, so no artifact can advertise them;
    - each remaining name is RESOLVED through the SAME store seam the loader
      uses (the per-project bundle first, then the shared catalogue): a name
      whose frontmatter carries no non-empty `description` is warned and
      skipped, so the survivors are exactly the names the L1 index can render;
    - only THEN does the cap apply to the RESOLVED additions (sorted,
      de-duplicated, capped at `MAX_TASK_SKILLS`, the dropped tail named in the
      warning): unresolvable junk can never consume the budget and evict a
      valid declaration.

    Import performs no I/O; the resolution reads frontmatter (the binding call
    is the deliberate read site, never an import)."""
    if task_skills is None:
        return []
    if isinstance(task_skills, str) or not isinstance(task_skills, (list, tuple, set, frozenset)):
        logger.warning(
            "skill binding: %s declared %r as its task skills (not a list of "
            "names); ignored",
            role_id, task_skills,
        )
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in task_skills:
        if not isinstance(raw, str) or not raw.strip():
            logger.warning(
                "skill binding: %s declared a non-name %r in its task skills; "
                "skipped",
                role_id, raw,
            )
            continue
        name = raw.strip()
        if name in seen:
            continue
        seen.add(name)
        if is_meta_skill(name):
            logger.warning(
                "skill binding: %s declared the meta-family skill %r; meta "
                "skills stay unadvertised, skipped",
                role_id, name,
            )
            continue
        candidates.append(name)
    resolved: list[str] = []
    for name in sorted(candidates):
        meta = seam.meta(name, project_id=project_id)
        description = meta.get("description") if isinstance(meta, dict) else None
        if not isinstance(description, str) or not description:
            logger.warning(
                "skill binding: %s declared %r but no skill resolves under "
                "that name (project bundle or shared catalogue); skipped",
                role_id, name,
            )
            continue
        resolved.append(name)
    if len(resolved) > MAX_TASK_SKILLS:
        logger.warning(
            "skill binding: %s resolved %d task skills; the cap keeps the "
            "first %d and drops %s",
            role_id, len(resolved), MAX_TASK_SKILLS,
            resolved[MAX_TASK_SKILLS:],
        )
        resolved = resolved[:MAX_TASK_SKILLS]
    return resolved


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
    lesson_store: "LessonStore | None" = None,
    task_skills=None,
) -> SkillAgentBinding:
    """Build the ONE per-agent skill binding (the `skill_agent_seams` successor,
    Q3 -> #221): every tool-calling agent binds its whole skill surface through
    this single call, so the middleware, the tools, and the bounded set can never
    drift or be half-wired - the exact discipline the tool-bounding pattern
    already imposes on a tool surface.

    `role_id` is the role the turn actually runs as (the site's own address or
    role constant), so the declaration in `ROLE_SKILLS` is the only thing that
    decides what the index lists - and it is also the identity the
    `record_skill_lesson` tool stamps on a lesson (D232-2). `project_id`/
    `with_write_skill`/`store`/`lesson_store` reach `build_skill_tools`, so a
    read-only agent (the default) can never acquire the write tool by accident.

    `task_skills` is the ARTIFACT-DECLARED configuration (#236): the skill names
    a ratified `HuntConfig` (for the hunter) or a `TestImplementationSpec` (for
    the pod runner) declared for this dispatch. The declared names are resolved
    through the same store seam the loader uses (project bundle first, then the
    shared catalogue), unioned with the role's baseline set, de-duplicated and
    sorted - so the rendered index is byte-stable across the turns of one hunt.
    The baseline is NEVER displaced: an artifact adds skills, it cannot remove
    the role's declared discipline. The meta family is refused and the added set
    is capped (`MAX_TASK_SKILLS`); an identifier that resolves to nothing is
    warned and skipped (the ONE documented policy - see `_resolve_task_skills`).
    A declaration against an EXEMPT role is warned and ignored: the roster's
    exemption is a considered capability-minimalism decision, not
    artifact-overridable.

    An UNDECLARED role id raises: the roster is the considered decision for every
    tool-calling role, so an unlisted one (usually a typo) is a wiring defect
    caught at construction, not a silent no-op. A DECLARED role with an empty
    set is exempt and returns an inert binding (no middleware, no tools, no
    skills in the context): the site stays uniform, and nothing dead is bound.

    The retired hunt-orchestrator's #236 read grant composed the SAME
    `build_load_skill_tool`; the unit threat model replaces it with the
    modeller's suite pair and the `arm_exempt_surface` binding. The roster and
    this seam stay unchanged. Import performs no I/O."""
    if role_id not in ROLE_SKILLS:
        raise ValueError(
            f"skill seam: {role_id!r} is not declared in ROLE_SKILLS - every "
            "tool-calling role is either given a bounded skill set there or "
            "declared exempt with an empty tuple. An undeclared role (usually a "
            "typo) is a wiring defect."
        )
    names = ROLE_SKILLS[role_id]
    if task_skills is not None and not names:
        logger.warning(
            "skill binding: %s is declared exempt in ROLE_SKILLS but its "
            "artifact declared %r; the exemption is not artifact-overridable, "
            "ignored",
            role_id, task_skills,
        )
        task_skills = None
    if not names:
        return SkillAgentBinding(
            role_id=role_id, middleware=[], tools=[], context={}
        )
    # The project scope is tool-owned (`config.PROJECT_ID` when unset) and rides
    # the SAME invocation context the bounded set does, so the index resolves
    # per-project bundles (a project-authored skill such as `authn`) and
    # `load_skill` reads them - one seam, no per-site plumbing.
    project_id = _resolve_project_id(project_id)
    # The artifact-declared names resolve through the SAME store seam the loader
    # and the index render use (project bundle first, then catalogue), so the
    # declared set and the rendered index can never disagree. The store is
    # constructed only when something was declared (its construction performs no
    # I/O; the frontmatter reads are this call's deliberate work).
    if task_skills:
        resolved = _resolve_task_skills(
            task_skills,
            role_id=role_id,
            project_id=project_id,
            seam=store if store is not None else SkillStore(),
        )
    else:
        resolved = []
    # De-duplicated and sorted: the union is a SET, and its order must not
    # depend on the declaration order (byte-stable prompt prefix per hunt).
    union = sorted({*names, *resolved})
    return SkillAgentBinding(
        role_id=role_id,
        middleware=[skill_index_middleware(store=store)],
        tools=build_skill_tools(
            project_id,
            with_write_skill=with_write_skill,
            store=store,
            lesson_store=lesson_store,
            role_id=role_id,
        ),
        context={"skills": union, "project_id": project_id},
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


def _resolve_project_id(project_id: str | None) -> str:
    """The tool-owned project scope: the explicit id, else the deployment's
    single project (`config.PROJECT_ID`), resolved LAZILY so import never
    touches config/env (CODING_STANDARD §6). No agent harness threads identity -
    the tool owns its scope (operator ruling: one project runs at a time)."""
    if project_id:
        return project_id
    from polymerhus.app.config import config  # noqa: PLC0415 - lazy, no env at import

    return config.PROJECT_ID


def build_load_skill_tool(
    project_id: str | None = None,
    store: "SkillStore | None" = None,
):
    """Build the ONE shared `load_skill` agent-callable tool (#222, #234, #236).

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

    LISTING MODE (#236): called with no name, the tool lists the catalogue's
    skill descriptions - all of them, or the ones matching the `pattern` regex -
    through `list_skill_descriptions`, which excludes the meta-family skills and
    respects `MAX_SKILL_LISTING`. This is the SAME tool, never a fork of the
    load path.

    Fail-open is preserved end to end: a missing protocol appends nothing, an
    unknown skill still degrades to `''`, and loading a meta-family skill
    returns its bare body (no protocol on the protocol skills: no blackloops).
    The appended protocol always reads from the shared catalogue - a
    per-project bundle never shadows it."""
    from langchain_core.tools import tool  # noqa: PLC0415

    project_id = _resolve_project_id(project_id)
    seam = store if store is not None else SkillStore()

    @tool
    def load_skill(name: str = "", pattern: str = "", refresh: bool = False) -> str:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `SKILL_LOAD_CONTRACT` is set on the returned tool explicitly)."""
        if refresh:
            clear_cache()
        if not name:
            return list_skill_descriptions(
                project_id=project_id, store=seam, pattern=pattern
            )
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


def skill_meta(name: str, *, catalogue: "SkillCatalogue | None" = None) -> dict:
    """Return the skill's data section: the parsed YAML frontmatter mapping of
    the named bundle (`{}` when the bundle is missing, has no frontmatter, or
    the frontmatter does not parse to a mapping - never a raise). The default
    resolves through the live-root catalogue, so a nested suite leaf is read
    through its indexed bundle; with `catalogue` given, the data section is read
    from that explicit mount instead."""
    if catalogue is not None:
        return catalogue.meta(name)
    return _live_catalogue().meta(name)


# The data-section contract (A3, Agent Skills spec subset): every bundled
# `SKILL.md` carries YAML frontmatter with `name` (EQUAL to the skill
# directory - the loader path is the index key, the frontmatter name the
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


def validate_skill(
    name: str, *, catalogue: "SkillCatalogue | None" = None
) -> list[str]:
    """Judge one skill against the data-section contract. Returns the list of
    violations (`[]` when conforming) - never raises, so a validator can sweep
    the whole catalogue and report every offender. With `catalogue` given, the
    skill is judged through that mount (its flat leaf name, R3)."""
    meta = skill_meta(name, catalogue=catalogue)
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
#     ├── assets/
#     └── revisions/          (the revision manifest + per-revision snapshots)
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

# The accepted version shapes (D-W3-2): `major`, `major.minor`, and the
# ratified suite's `major.minor.patch` (a missing minor counts as 0 for the
# bump, exactly as before; the patch is read and ignored).
_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")

# The revision store (D-W3-2): every published write of a bundle appends one
# record to `<bundle>/revisions/manifest.yaml` - the consumed note keys and the
# old and new version, in a STORED structure, never a log line - and snapshots
# the file it wrote at `<bundle>/revisions/<ordinal>.md`, so the previous
# revision body stays retrievable. The lesson prose is NOT duplicated here: the
# note keys address the lesson shard, which holds every record in full.
_REVISIONS_DIRNAME = "revisions"
_REVISION_MANIFEST = "manifest.yaml"
_REVISION_KEYS = (
    "ordinal",
    "target",
    "file",
    "previous_version",
    "version",
    "source_note_ids",
    "written_at",
    "snapshot",
)

# The fixed sub-directories of the project `skills/` bucket the scaffold owns
# (`lessons/` holds the lesson shards; `evolution/` holds the evolution-pass
# records): the directory is not a bundle, so no project skill may take one of
# these names (D232-1's `lessons` precedent, extended by W3's pass records).
RESERVED_SKILL_NAMES = frozenset({"lessons", "evolution"} | BRANCH_NAMES)


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
    """The operator's monotonic version rule (D-W3-2): `major.minor` or
    `major.minor.patch` - the ratified suite's form - plus the historical bare
    `major` (a missing minor counts as 0). Major is read, minor is bumped by
    one, the patch is read and ignored, and the emitted version is always
    `major.(minor+1)`. Any other shape refuses: a version is a dotted numeric
    identity, never a longer tuple or a non-numeric part."""
    match = _VERSION_RE.fullmatch(str(version).strip())
    if match is None:
        raise SkillInvalidError(
            f"skill_invalid: version {version!r} is not major, major.minor, or "
            "major.minor.patch"
        )
    return f"{int(match.group(1))}.{int(match.group(2) or 0) + 1}"


def _dump_frontmatter(meta: dict) -> str:
    """Render the store-owned frontmatter block prepended to a composed
    `procedure` write."""
    import yaml  # noqa: PLC0415 - already a production dependency (hunt_store, ...)

    body = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=4096)
    return f"---\n{body}---\n\n"


def dump_text_atomic(path: Path, text: str) -> None:
    """Write `text` atomically through the app's ONE construction point
    (`polymerhus.app.atomic_write.write_text_atomic`, #340): render in memory,
    then temp + fsync + `os.replace`, so every file on disk is whole and a
    crash mid-dump never leaves a partial target.

    The ONE atomic whole-file write of the skills domain: `SkillStore` and the
    evolution pass-record store both go through it, so the discipline cannot
    drift between stores. A failed dump is a loud `StoreUnavailableError`."""
    try:
        write_text_atomic(path, text)
    except OSError as exc:
        raise StoreUnavailableError(
            f"store_unavailable: cannot persist {path} ({exc})"
        ) from exc


class SkillStore:
    """The per-project skill-bundle store (#234): the one seam the loader and
    the writer share, and - since D-W3-2 - the owner of the bundle's revision
    index (`revisions/manifest.yaml` plus one snapshot per published revision),
    so every revision stays retrievable with its consumed note keys and its
    old and new version. Rooted under the live `skills/` root (default
    `_SKILLS_ROOT`), whose `target-specific-procedure/<project_id>/` branch is
    the project's own skill area: the bootstrapper's procedures and the evolved
    or newly mined project-specific skills live there, laid out like the
    catalogue bundles. The explicit-root constructor is kept for the tests'
    temp stores (the `hunt_store` / #220 auth-store precedent). Import performs
    no I/O."""

    def __init__(self, root_dir: str | Path | None = None):
        """Rooted under `root_dir` (default: the live `skills/` root)."""
        self._root = Path(root_dir) if root_dir is not None else _SKILLS_ROOT

    # -- paths -------------------------------------------------------------

    def _project_skills_root(self, project_id: str) -> Path:
        validate_path_component(project_id, "project_id")
        return self._root / PROCEDURE_BRANCH / project_id

    def _bundle_dir(self, project_id: str, skill: str) -> Path:
        validate_path_component(skill, "skill")
        if skill in RESERVED_SKILL_NAMES:
            raise SkillInvalidError(
                f"skill_invalid: {skill!r} is a reserved skills/ directory "
                "name, not a skill bundle"
            )
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

    def list_skills(self, project_id: str | None = None) -> list[str]:
        """The project's own skill-bundle names, sorted: every directory under
        the project `skills/` bucket that carries a `SKILL.md`, minus the
        scaffold-owned reserved names (`lessons`, `evolution` - directories, not
        bundles). The listing surface's project half (#236): a project-authored
        skill such as `authn` is discoverable. A missing bucket is the valid
        empty; an unreadable one and an unsafe project id degrade to `[]` - a
        listing never raises."""
        if project_id is None:
            return []
        try:
            base = self._project_skills_root(project_id)
            return sorted(
                child.name
                for child in base.iterdir()
                if child.is_dir()
                and child.name not in RESERVED_SKILL_NAMES
                and (child / "SKILL.md").is_file()
            )
        except (OSError, ValueError):
            return []

    def read(self, name: str, project_id: str | None = None, fallback: str = "") -> str:
        """The skill body for `name`, frontmatter stripped: the project bundle
        first, then the shared repo catalogue.

        The branch decision is a minimal filesystem PROBE, never an exception:
        a project bundle that exists is authoritative (from its minting on it
        shadows the baseline for this project), and only an absent bundle
        fails over to the shared catalogue. A present but unreadable bundle
        degrades to `fallback`, so a broken project version never silently
        serves the baseline."""
        if project_id is not None:
            try:
                path = self._bundle_dir(project_id, name) / "SKILL.md"
            except (OSError, ValueError):
                path = None
            if path is not None and path.is_file():
                try:
                    return _strip_frontmatter(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    logger.warning(
                        "skill store: unreadable project bundle for %s/%s; "
                        "degrading to the fallback (the project bundle shadows "
                        "the catalogue)",
                        project_id,
                        name,
                    )
                    return fallback
        return skill_for(name, fallback=fallback)

    def meta(self, name: str, project_id: str | None = None) -> dict:
        """The skill's data section (parsed frontmatter), resolved with the
        same probe `read` uses: a project bundle that exists is authoritative
        (it shadows the baseline), and only an absent bundle fails over to the
        shared catalogue. A present but unreadable or frontmatter-less bundle
        returns `{}` rather than the baseline's data. Never raises - the index
        render depends on this."""
        if project_id is not None:
            try:
                path = self._bundle_dir(project_id, name) / "SKILL.md"
            except (OSError, ValueError):
                path = None
            if path is not None and path.is_file():
                try:
                    meta = _parse_frontmatter(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    logger.warning(
                        "skill store: unreadable project bundle frontmatter for "
                        "%s/%s; returning no data section (the project bundle "
                        "shadows the catalogue)",
                        project_id,
                        name,
                    )
                    return {}
                return meta if meta is not None else {}
        return skill_meta(name)

    # -- writes: validate, then one atomic whole-file rewrite ------------------

    @staticmethod
    def _dump_text_atomic(path: Path, text: str) -> None:
        """The store's atomic whole-file write; delegates to the ONE shared
        implementation (`dump_text_atomic`), which the pass-record store reuses
        so the temp-file-plus-replace discipline cannot drift between stores."""
        dump_text_atomic(path, text)

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
        bundle carries no readable SKILL.md. The same structure probe the reads
        use: presence selects the project bundle, absence selects the
        catalogue metadata at the compose step."""
        try:
            path = self._bundle_dir(project_id, skill) / "SKILL.md"
        except (OSError, ValueError):
            return None
        if not path.is_file():
            return None
        try:
            return _parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _compose_procedure(
        self, project_id: str, skill: str, body: str
    ) -> tuple[str, str, str]:
        """Compose the store-owned SKILL.md for one `procedure` write.

        The metadata is never the caller's: it is the operator-bootstrapped
        frontmatter the project already carries, or - on the project's first
        update - the shared catalogue skill's frontmatter copied over. The
        store then bumps `metadata.version` one minor and appends the caller's
        body, so a skill with no bootstrapped metadata refuses rather than
        inventing any. Any frontmatter in `body` is dropped.

        Returns `(composed_text, previous_version, new_version)` so the caller
        can record the revision's provenance (D-W3-2).
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
        previous_version = source["metadata"]["version"]
        version = _bump_version(previous_version)
        composed = {
            "name": skill,
            "description": source["description"],
            "metadata": {"version": version},
        }
        return (
            _dump_frontmatter(composed) + _strip_frontmatter(body),
            previous_version,
            version,
        )

    def _bundle_version(self, project_id: str, skill: str) -> str:
        """The bundle's current version through the same seam the loader uses
        (project bundle first, catalogue second); `""` when none resolves. Used
        by a reference write, whose revision record carries the unchanged
        version; never a refusal - a reference write is not versioned."""
        meta = self._existing_frontmatter(project_id, skill) or skill_meta(skill)
        metadata = meta.get("metadata") if isinstance(meta, dict) else None
        version = metadata.get("version") if isinstance(metadata, dict) else None
        return version if isinstance(version, str) else ""

    # -- the revision store (D-W3-2) -----------------------------------------

    def _revisions_dir(self, project_id: str, skill: str) -> Path:
        return self._bundle_dir(project_id, skill) / _REVISIONS_DIRNAME

    def _manifest_file(self, project_id: str, skill: str) -> Path:
        return self._revisions_dir(project_id, skill) / _REVISION_MANIFEST

    def _read_manifest(self, project_id: str, skill: str) -> list[dict]:
        """The recorded revisions in append order. A missing manifest is the
        valid empty; a CORRUPT one raises `StoreUnavailableError` (the write
        path must never silently drop the bundle's revision history) - the
        public `revisions` degrades that to `[]` with a warning."""
        path = self._manifest_file(project_id, skill)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise StoreUnavailableError(
                f"store_unavailable: cannot read revision manifest {path} ({exc})"
            ) from exc
        import yaml  # noqa: PLC0415 - already a production dependency

        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise StoreUnavailableError(
                f"store_unavailable: unreadable revision manifest {path} ({exc})"
            ) from exc
        if loaded is None:
            return []
        if not isinstance(loaded, list) or not all(
            isinstance(record, dict) for record in loaded
        ):
            raise StoreUnavailableError(
                f"store_unavailable: revision manifest {path} is not a record list"
            )
        return list(loaded)

    def revisions(self, project_id: str, skill: str) -> list[dict]:
        """Every recorded revision of the skill bundle, in ordinal order: the
        consumed note keys (`source_note_ids`), the old and new version, the
        written file, the timestamp, and the snapshot name. Fail-open: a
        missing, unreadable, or corrupt manifest reads as `[]` with a warning -
        a revision read never raises. The full lesson text is NOT here; the
        keys address the lesson shard, which holds every record in full."""
        try:
            return self._read_manifest(project_id, skill)
        except (StoreUnavailableError, ValueError, OSError) as exc:
            logger.warning(
                "skill store: unreadable revision manifest for %s/%s: %s",
                project_id, skill, exc,
            )
            return []

    def revision_content(
        self, project_id: str, skill: str, ordinal: int
    ) -> str | None:
        """The stored body of one revision by its ordinal (`revisions/<ordinal>
        .md`), or `None` when no such revision or snapshot is readable. This is
        how the previous revision body stays retrievable after the live
        `SKILL.md` was overwritten."""
        record = next(
            (
                item
                for item in self.revisions(project_id, skill)
                if item.get("ordinal") == ordinal
            ),
            None,
        )
        if record is None:
            return None
        snapshot = record.get("snapshot")
        if not isinstance(snapshot, str) or not snapshot:
            return None
        try:
            validate_path_component(snapshot, "snapshot")
            path = self._revisions_dir(project_id, skill) / snapshot
            return path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None

    def _record_revision(
        self,
        project_id: str,
        skill: str,
        *,
        target: str,
        file_relative: str,
        content: str,
        previous_version: str,
        version: str,
        source_note_ids,
        records: list[dict],
    ) -> None:
        """Append one revision to the bundle's manifest and snapshot the file
        it wrote, under the caller's per-project lock. `records` is the
        manifest already read by the caller (the read is the loud half: a
        corrupt manifest refuses BEFORE anything is persisted). A snapshot or
        manifest write failure raises `StoreUnavailableError` naming the
        landed-but-unrecorded file - never a silent provenance loss."""
        import datetime  # noqa: PLC0415 - stdlib, kept local like the yaml import

        import yaml  # noqa: PLC0415 - already a production dependency

        ordinal = len(records) + 1
        snapshot = f"{ordinal:04d}.md"
        record = {
            "ordinal": ordinal,
            "target": target,
            "file": file_relative,
            "previous_version": previous_version,
            "version": version,
            "source_note_ids": [str(item) for item in source_note_ids],
            "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "snapshot": snapshot,
        }
        revisions_dir = self._revisions_dir(project_id, skill)
        try:
            self._dump_text_atomic(revisions_dir / snapshot, content)
            self._dump_text_atomic(
                revisions_dir / _REVISION_MANIFEST,
                yaml.safe_dump(
                    [*records, record], sort_keys=False, allow_unicode=True, width=4096
                ),
            )
        except StoreUnavailableError as exc:
            raise StoreUnavailableError(
                f"{exc} (the revision landed in {file_relative} but its "
                "provenance record did not)"
            ) from exc

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
        carries the whole file. `source_note_ids` is the revision's provenance
        (D-W3-2): it is recorded in the bundle's revision manifest together
        with the old and new version, and the written file is snapshotted, so
        every published revision stays retrievable and indexable from the
        skill's own bundle. Refusals (`SkillTargetError`, `SkillInvalidError`,
        `StoreUnavailableError`) carry the coded signal the tool maps to an
        envelope. Every file write is atomic under the per-project lock; a
        refused write persists nothing (a corrupt revision manifest refuses
        before the bundle file is touched).
        """
        if not isinstance(content, str):
            raise SkillInvalidError(
                f"skill_invalid: {skill!r} content must be text"
            )
        file_path = self._target_file(project_id, skill, target)
        with _lock_for(f"{self._root}::{project_id}"):
            # Compose and the manifest read happen INSIDE the lock: both read
            # the bundle's current frontmatter, so composing outside it would
            # let two concurrent rewrites record the same old version (the
            # revision's provenance must be as truthful as the entry sequence).
            # The manifest read is the loud, fail-loud half and happens BEFORE
            # the bundle write: a corrupt revision index refuses the write
            # instead of publishing a revision whose provenance cannot land.
            records = self._read_manifest(project_id, skill)
            if target == "procedure":
                content, previous_version, version = self._compose_procedure(
                    project_id, skill, content
                )
            else:
                previous_version = version = self._bundle_version(project_id, skill)
            self._ensure_bundle(project_id, skill)
            self._dump_text_atomic(file_path, content)
            self._record_revision(
                project_id,
                skill,
                target=target,
                file_relative=str(
                    file_path.relative_to(self._bundle_dir(project_id, skill))
                ),
                content=content,
                previous_version=previous_version,
                version=version,
                source_note_ids=source_note_ids,
                records=records,
            )
            logger.info(
                "skill store: wrote %s target=%s project=%s version=%s "
                "previous_version=%s source_notes=%s revision=%d",
                skill,
                target,
                project_id,
                version,
                previous_version,
                list(source_note_ids),
                len(records) + 1,
            )


    # A canonical bundle relative path: the SKILL.md itself or one safe file
    # stem under a canonical subdirectory. No nesting, no traversal (the
    # `validate_path_component` rule at bundle-file granularity).
    _BUNDLE_FILE_RE = re.compile(
        r"(?:SKILL\.md|(?:references|scripts|assets)/[A-Za-z0-9][A-Za-z0-9._-]*)\Z"
    )

    def replace_bundle(
        self, project_id: str, skill: str, files: Mapping[str, str]
    ) -> None:
        """Wholesale, non-idempotent placement of a skill bundle's files, verbatim.

        The eval data-dependency face places a PRE-BUILT bundle (the authn skill
        authored by the bootstrapper), so the store writes the caller's bytes as-is
        - unlike `write`, it does NOT compose or bump frontmatter. `files` maps a
        canonical bundle-relative path (`SKILL.md`, `references/<name>`,
        `scripts/<name>`, `assets/<name>`) to its UTF-8 text; `SKILL.md` is
        required and its frontmatter is re-validated (name == the bundle directory),
        so a malformed bundle refuses instead of landing. Existing files not named
        in `files` are left untouched; every named file is overwritten or created.
        Every write is atomic under the per-project lock."""
        if not isinstance(files, Mapping) or not files:
            raise SkillInvalidError("skill_invalid: files must be a non-empty mapping")
        if "SKILL.md" not in files:
            raise SkillInvalidError("skill_invalid: the bundle must include SKILL.md")
        for rel, text in files.items():
            if not isinstance(rel, str) or not self._BUNDLE_FILE_RE.match(rel):
                raise SkillTargetError(
                    f"skill_target: {rel!r} is not a canonical bundle file path"
                )
            if not isinstance(text, str):
                raise SkillInvalidError(f"skill_invalid: {rel!r} content must be text")
        meta = _parse_frontmatter(files["SKILL.md"])
        if meta is None:
            raise SkillInvalidError(
                f"skill_invalid: {skill!r} SKILL.md carries no parseable frontmatter"
            )
        violations = _frontmatter_violations(meta, skill=skill)
        if violations:
            raise SkillInvalidError("skill_invalid: " + "; ".join(violations))
        with _lock_for(f"{self._root}::{project_id}"):
            bundle = self._ensure_bundle(project_id, skill)
            for rel, text in files.items():
                self._dump_text_atomic(bundle / rel, text)
            logger.info(
                "skill store: placed bundle %s project=%s files=%s",
                skill,
                project_id,
                sorted(files),
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


# The single lesson-recording contract, rendered verbatim into the tool
# description at every binding (the `SKILL_LOAD_CONTRACT` /
# `WRITE_SKILL_CONTRACT` precedent). Mirrors `skills/README.md` - update both
# together. The type semantics are cited here compactly AND in
# `meta-usage-skill` (D232-3: the three prose sites - this contract, the usage
# protocol, the evolver prompt - state the same semantics).
RECORD_LESSON_CONTRACT = (
    "Record ONE skill-usage lesson: a reusable observation about a skill you "
    "used, grounded in this run's evidence, persisted in the project's lesson "
    "shard for that skill.\n\n"
    "FIELDS - `skill`: the skill the lesson is about (one flat name). `type`: "
    "`specification` (knowledge specific to the target's attack surface), "
    "`extension` (an extension of the procedure: new steps, an optimised "
    "grouping, an anti-pattern - steps that must not be done - or an extension "
    "of the technique's scope), or `defect` (a genuine error in the illustrated "
    "procedure). `lesson`: the reusable lesson in prose. `expected`: what the "
    "skill states or implies, extracted as close to its wording as possible. "
    "`evidence`: concrete identifiers from this run (http-history artifact "
    "ids, request/response entries, run ids).\n\n"
    "THE STORE STAMPS the key, the skill's base version, the writing agent's "
    "identity, and the timestamp - never supply them. A skill whose version "
    "does not resolve is refused.\n\n"
    "OUTCOMES - one in-band envelope: `{ok: true, key, base_version}` or "
    "`{ok: false, error, detail}` with error one of `lesson_invalid`, "
    "`skill_unknown`, `store_unavailable`. Nothing raises into the turn.\n\n"
    "Record once per material observation; the SkillEvolver consumes the "
    "accumulated lessons, so not every step needs one."
)


def build_record_lesson_tool(
    project_id: str | None = None,
    store: "LessonStore | None" = None,
    role_id: str | None = None,
):
    """Build the shared `record_skill_lesson` agent-callable tool (#232
    D232-4/5), bound to `project_id` and carrying the caller's `role_id`.

    The agent supplies the observation; the symbolic layer supplies identity:
    the store generates the key and stamps `base_version`/`written_at`, and
    this factory stamps `agent.role_id` (the binding's role) plus the ambient
    session id read from the conversation scope (`run_session_turn` binds the
    thread id for the turn's duration - `bound_conversation_id`). Every
    refusal is a coded in-band envelope; nothing raises into the turn. Import
    performs no I/O: `store` defaults to a lazily-constructed `LessonStore`
    inside the factory call."""
    from langchain_core.tools import tool  # noqa: PLC0415
    from pydantic import BaseModel, Field  # noqa: PLC0415

    project_id = _resolve_project_id(project_id)
    seam = store if store is not None else LessonStore()

    class RecordLessonArgs(BaseModel):
        """The `record_skill_lesson` args (the bound project needs no identity
        parameter)."""

        skill: str = Field(
            description="The skill the lesson is about (one flat name)."
        )
        type: str = Field(
            description="The lesson type: `specification`, `extension`, or "
            "`defect` - the contract states each one's semantics."
        )
        lesson: str = Field(description="The reusable lesson, in prose.")
        expected: str = Field(
            default="",
            description="What the skill states or implies, extracted as close "
            "to its wording as possible.",
        )
        evidence: list[str] = Field(
            default_factory=list,
            description="Concrete identifiers from this run (http-history "
            "artifact ids, request/response entries, run ids).",
        )

    @tool(args_schema=RecordLessonArgs)
    def record_skill_lesson(
        skill: str,
        type: str,
        lesson: str,
        expected: str = "",
        evidence: list | None = None,
    ) -> dict:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `RECORD_LESSON_CONTRACT` is set on the returned tool explicitly)."""
        from polymerhus.app.llm.conversation import bound_conversation_id  # noqa: PLC0415

        try:
            base_version = seam.base_version(project_id, skill)
            key = seam.append(
                project_id,
                skill=skill,
                type=type,
                lesson=lesson,
                expected=expected,
                evidence=evidence or [],
                agent={
                    "role_id": role_id or "",
                    "session_id": bound_conversation_id() or "",
                },
            )
        except SkillUnknownError as exc:
            return {"ok": False, "error": "skill_unknown", "detail": str(exc)}
        except LessonInvalidError as exc:
            return {"ok": False, "error": "lesson_invalid", "detail": str(exc)}
        except StoreUnavailableError as exc:
            return {"ok": False, "error": "store_unavailable", "detail": str(exc)}
        except ValueError as exc:  # noqa: BLE001 - unsafe component, fail-open
            return {"ok": False, "error": "lesson_invalid",
                    "detail": f"lesson_invalid: {exc}"}
        except Exception as exc:  # noqa: BLE001 - fail-open, never a raise
            return {"ok": False, "error": "store_unavailable",
                    "detail": f"store_unavailable: {exc}"}
        return {"ok": True, "key": key, "base_version": base_version}

    # The `@tool` decorator snapshots the docstring at decoration; assign the
    # interpolated contract as the description so every binding carries it.
    tool_obj = record_skill_lesson
    if hasattr(tool_obj, "description"):
        tool_obj.description = RECORD_LESSON_CONTRACT
    return tool_obj


def build_skill_tools(
    project_id: str | None = None,
    with_write_skill: bool = False,
    store: "SkillStore | None" = None,
    lesson_store: "LessonStore | None" = None,
    role_id: str | None = None,
) -> list:
    """The shared agent skill seam (#234, #232): the one place agent owners
    collect the skill tools. Every agent gets the read-only pair
    `load_skill` + `record_skill_lesson` (#232 D232-4: the universally safe,
    append-only lesson observation); an agent whose procedure evolves a skill
    additionally gets `write_skill` bound to its project, so agents that
    execute no evolving procedure keep the read-only surface and the write
    blast radius stays explicit. (The L1 skill-index middleware rides
    alongside at the agent owner's binding site - the #222 seam - composed
    with this helper, never reimplemented per agent.)

    `role_id` reaches the lesson tool so the record's agent identity is
    stamped by the symbolic layer (the binding), never supplied by the model;
    `lesson_store` is the injectable lesson seam (tests)."""
    project_id = _resolve_project_id(project_id)
    tools = [
        build_load_skill_tool(project_id, store=store),
        build_record_lesson_tool(project_id, store=lesson_store, role_id=role_id),
    ]
    if with_write_skill:
        if not project_id:
            raise ValueError(
                "skill seam: write_skill needs its project_id - a write tool "
                "without a bound project is a wiring defect"
            )
        tools.append(build_write_skill_tool(project_id, store=store))
    return tools


# --- The skill-usage lesson store (#232 D232-1/2) -----------------------------
#
# A lesson is an executing agent's reusable observation about a skill it used.
# The store is skill-scoped (never hunt-scoped) and lives in the same
# skills-access domain as `SkillStore`, one append-friendly YAML shard per
# skill under the project's own skill area:
#
#     skills/target-specific-procedure/<project_id>/lessons/<skill>.yaml
#
# The project area is the `target-specific-procedure/` branch of the live
# `skills/` root (operator topology ruling, 2026-10-20): the same branch that
# holds the project's bundles (the bootstrapper's procedures and the evolved or
# newly mined project-specific skills), so the project's whole skill surface
# stays together. The per-SKILL shard is the only runtime-keyed leaf this store
# creates lazily (B10's safety-net allowance).
#
# The record is deliberately small (operator ruling, D232-2): a three-value
# `type`, free-text `lesson`/`expected`, a list of concrete evidence ids, and
# STORE/tool-stamped facts the agent never supplies - the generated key
# (`skill:<skill>:<ordinal>`), the skill's `base_version`, the writing agent's
# identity, and `written_at`. Consumption is key-encoded: `mark_consumed`
# rewrites the key with the reserved `:consumed` suffix, so the shard needs no
# cursor and no consumed flag field.
#
# Reads are fail-open (a corrupt shard reads as empty, loudly); writes are
# fail-loud and atomic under the SAME per-project lock `SkillStore` uses.

LESSON_TYPES: tuple[str, ...] = ("specification", "extension", "defect")

# The reserved key suffix marking a lesson consumed (D232-2).
CONSUMED_CODE = ":consumed"

# The shard directory name reserved by PROJECT_SCAFFOLD: a skill literally
# named `lessons` would collide with it and is refused.
_LESSONS_DIRNAME = "lessons"


class LessonInvalidError(ValueError):
    """The denoted malformed-lesson signal: bad type, empty lesson, non-list
    evidence, or an unsafe skill shard name."""


class SkillUnknownError(ValueError):
    """The denoted unresolvable-skill signal: the named skill has no bootstrapped
    version (neither the project bundle nor the shared catalogue carries one),
    so a lesson about it cannot be stamped."""


class LessonStore:
    """The per-skill lesson shard store (#232): explicit-root like every store
    on the live `skills/` root (tests inject a temp root); production defaults
    to `_SKILLS_ROOT`, and the shards live in the project's
    `target-specific-procedure/<project_id>/lessons/` area. Import performs no
    I/O."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        skill_store: "SkillStore | None" = None,
    ):
        self._root = Path(root_dir) if root_dir is not None else _SKILLS_ROOT
        # The version seam is the SAME store the loader reads (bundle-first,
        # catalogue second) so a lesson's base_version can never drift from the
        # procedure text the agent saw.
        self._skills = (
            skill_store if skill_store is not None else SkillStore(root_dir=self._root)
        )

    # -- paths -------------------------------------------------------------

    def _shard_file(self, project_id: str, skill: str) -> Path:
        """The shard for one skill, under the project's own skill area in the
        `target-specific-procedure/` branch. `skill` must be ONE safe path
        component (no separators, no traversal) and may not be a reserved
        branch or control directory name (`lessons`, `evolution`, the four
        topology branches): those directories are not bundles, so no lesson can
        concern them."""
        try:
            validate_path_component(skill, "skill")
        except ValueError as exc:
            raise LessonInvalidError(f"lesson_invalid: {exc}") from exc
        if skill in RESERVED_SKILL_NAMES:
            raise LessonInvalidError(
                f"lesson_invalid: {skill!r} is a reserved skills/ directory name"
            )
        base = (
            self._root
            / PROCEDURE_BRANCH
            / validate_path_component(project_id, "project_id")
        )
        return base / _LESSONS_DIRNAME / f"{skill}.yaml"

    # -- reads: fail-open ----------------------------------------------------

    def _read_records(self, project_id: str, skill: str) -> list[dict]:
        """The shard's records in file (append) order. A missing shard is the
        valid empty; a CORRUPT shard raises `StoreUnavailableError` (the write
        path must never silently overwrite history with an empty list) - the
        public `read` degrades that to `[]` with a warning."""
        path = self._shard_file(project_id, skill)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise StoreUnavailableError(
                f"store_unavailable: cannot read lesson shard {path} ({exc})"
            ) from exc
        import yaml  # noqa: PLC0415 - already a production dependency

        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise StoreUnavailableError(
                f"store_unavailable: unreadable lesson shard {path} ({exc})"
            ) from exc
        if loaded is None:
            return []
        if not isinstance(loaded, list) or not all(
            isinstance(r, dict) for r in loaded
        ):
            raise StoreUnavailableError(
                f"store_unavailable: lesson shard {path} is not a record list"
            )
        return list(loaded)

    def skills_with_lessons(self, project_id: str) -> list[str]:
        """The skills that have a lesson shard on disk (sorted). A missing
        lessons directory is the valid empty, never an error."""
        shards = (
            self._root
            / PROCEDURE_BRANCH
            / validate_path_component(project_id, "project_id")
            / _LESSONS_DIRNAME
        )
        try:
            return sorted(
                child.stem for child in shards.iterdir() if child.suffix == ".yaml"
            )
        except FileNotFoundError:
            return []
        except OSError:
            return []

    def read(
        self,
        project_id: str,
        *,
        skill: str | None = None,
        type: str | None = None,
        unconsumed_only: bool = False,
        key_keyword: str | None = None,
        body_keyword: str | None = None,
    ) -> list[dict]:
        """The matching lesson records in FILE (append) order. `skill` selects
        one shard; absent, every shard is walked. `unconsumed_only` drops keys
        already carrying the `:consumed` code. Keyword filters are
        case-insensitive substrings of the key / of the lesson body (the
        lesson + expected + evidence prose). A corrupt or unreadable shard is
        skipped fail-open with a warning - a lesson read never raises."""
        chosen = [skill] if skill is not None else self.skills_with_lessons(project_id)
        out: list[dict] = []
        for name in chosen:
            try:
                records = self._read_records(project_id, name)
            except (StoreUnavailableError, LessonInvalidError, ValueError) as exc:
                logger.warning(
                    "lesson store: skipping unreadable shard %s: %s", name, exc
                )
                continue
            for rec in records:
                key = str(rec.get("key") or "")
                if unconsumed_only and _is_consumed_key(key):
                    continue
                if type is not None and rec.get("type") != type:
                    continue
                if key_keyword is not None and key_keyword.lower() not in key.lower():
                    continue
                if body_keyword is not None and body_keyword.lower() not in _lesson_text(
                    rec
                ).lower():
                    continue
                out.append(rec)
        return out

    # -- writes: strict, atomic, under the per-project lock ------------------

    def base_version(self, project_id: str, skill: str) -> str:
        """The version the lesson is made against: resolved through the same
        store seam the loader uses (project bundle first, catalogue second).
        Raises `SkillUnknownError` when the skill resolves no bootstrapped
        version - the agent may not invent one, and a lesson without a base is
        not actionable for the evolver."""
        meta = self._skills.meta(skill, project_id=project_id)
        metadata = meta.get("metadata") if isinstance(meta, dict) else None
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if not isinstance(version, str) or not version:
            raise SkillUnknownError(
                f"skill_unknown: {skill!r} has no bootstrapped version "
                "(neither the project bundle nor the catalogue carries one)"
            )
        return version

    def append(
        self,
        project_id: str,
        *,
        skill: str,
        type: str,
        lesson: str,
        expected: str = "",
        evidence: tuple[str, ...] | list[str] = (),
        agent: dict | None = None,
    ) -> str:
        """Append ONE lesson to the skill's shard; return its generated key
        `skill:<skill>:<ordinal>` (monotonic per shard; a repeated lesson
        appends as a new record). The store stamps `base_version` and
        `written_at`; the CALLER stamps the agent identity (the tool reads it
        from its binding - the symbolic layer owns it). Refusals raise the
        coded `LessonInvalidError` / `SkillUnknownError` / `StoreUnavailableError`
        the tool maps to an in-band envelope; a refused append persists
        nothing."""
        if type not in LESSON_TYPES:
            raise LessonInvalidError(
                f"lesson_invalid: type {type!r} must be one of {LESSON_TYPES}"
            )
        if not isinstance(lesson, str) or not lesson.strip():
            raise LessonInvalidError(
                "lesson_invalid: lesson must be a non-empty string"
            )
        if not isinstance(expected, str):
            raise LessonInvalidError("lesson_invalid: expected must be text")
        if isinstance(evidence, str) or not isinstance(evidence, (list, tuple)):
            raise LessonInvalidError(
                "lesson_invalid: evidence must be a list of string identifiers"
            )
        evidence = list(evidence)
        if not all(isinstance(item, str) for item in evidence):
            raise LessonInvalidError(
                "lesson_invalid: evidence must be a list of string identifiers"
            )
        if agent is not None and not isinstance(agent, dict):
            raise LessonInvalidError("lesson_invalid: agent must be a mapping")
        # The version refusal happens BEFORE the lock: it is a pure read of the
        # same seam the loader uses, and a refused append must persist nothing.
        base_version = self.base_version(project_id, skill)
        path = self._shard_file(project_id, skill)
        import datetime  # noqa: PLC0415 - stdlib, kept local like the yaml import

        import yaml  # noqa: PLC0415
        with _lock_for(f"{self._root}::{project_id}"):
            records = self._read_records(project_id, skill)
            record = {
                "key": _next_lesson_key(records, skill),
                "type": type,
                "lesson": lesson,
                "expected": expected,
                "evidence": evidence,
                "base_version": base_version,
                "agent": {
                    "role_id": str((agent or {}).get("role_id") or ""),
                    "session_id": str((agent or {}).get("session_id") or ""),
                },
                "written_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
            records.append(record)
            SkillStore._dump_text_atomic(
                path, yaml.safe_dump(records, sort_keys=False, allow_unicode=True)
            )
        return record["key"]

    def mark_consumed(
        self,
        project_id: str,
        keys: tuple[str, ...] | list[str],
        *,
        consumed: bool = True,
    ) -> int:
        """Rewrite the given lesson keys with (or without) the reserved
        `:consumed` code; return how many keys changed. Idempotent: an
        already-marked key counts zero. Keys the store does not hold are
        ignored. Each affected shard is rewritten atomically under the same
        per-project lock; a write failure raises `StoreUnavailableError`."""
        wanted = {str(key) for key in keys}
        by_skill: dict[str, set[str]] = {}
        for key in wanted:
            skill = _skill_of_lesson_key(key)
            if skill:
                by_skill.setdefault(skill, set()).add(key)
        changed = 0
        import yaml  # noqa: PLC0415

        for skill, skill_keys in by_skill.items():
            path = self._shard_file(project_id, skill)
            with _lock_for(f"{self._root}::{project_id}"):
                records = self._read_records(project_id, skill)
                touched = 0
                for rec in records:
                    key = str(rec.get("key") or "")
                    if key not in skill_keys:
                        continue
                    new_key = (
                        key + CONSUMED_CODE
                        if consumed and not _is_consumed_key(key)
                        else (
                            key[: -len(CONSUMED_CODE)]
                            if not consumed and _is_consumed_key(key)
                            else key
                        )
                    )
                    if new_key != key:
                        rec["key"] = new_key
                        touched += 1
                if touched:
                    SkillStore._dump_text_atomic(
                        path,
                        yaml.safe_dump(records, sort_keys=False, allow_unicode=True),
                    )
                    changed += touched
        return changed


def _is_consumed_key(key: str) -> bool:
    """Whether a lesson key carries the reserved consumed code (D232-2)."""
    return key.endswith(CONSUMED_CODE)


def _lesson_text(record: dict) -> str:
    """The searchable prose of a lesson record: the lesson, its expected
    statement, and the evidence identifiers joined."""
    parts = [
        str(record.get("lesson") or ""),
        str(record.get("expected") or ""),
        " ".join(str(e) for e in record.get("evidence") or []),
    ]
    return " ".join(parts)


def _next_lesson_key(records: list[dict], skill: str) -> str:
    """The next monotonic key for a shard: `skill:<skill>:<max ordinal + 1>`,
    tolerating a consumed suffix on existing keys."""
    highest = 0
    prefix = f"skill:{skill}:"
    for rec in records:
        key = str(rec.get("key") or "")
        if _is_consumed_key(key):
            key = key[: -len(CONSUMED_CODE)]
        if not key.startswith(prefix):
            continue
        try:
            highest = max(highest, int(key[len(prefix):]))
        except ValueError:
            continue
    return f"skill:{skill}:{highest + 1}"


def _skill_of_lesson_key(key: str) -> str:
    """The skill segment of a lesson key (`skill:<skill>:<ordinal>[:consumed]`),
    or `''` when the key is not a lesson key."""
    parts = key.split(":")
    if len(parts) >= 3 and parts[0] == "skill":
        return parts[1]
    return ""


__all__ = [
    "CONSUMED_CODE",
    "LESSON_TYPES",
    "LOGICAL_SUITE_ROOT",
    "MAX_SKILL_LISTING",
    "MAX_TASK_SKILLS",
    "META_SKILLS_PREFIX",
    "META_USAGE_SKILL",
    "META_WRITE_SKILL",
    "PROTOCOL_SEPARATOR",
    "RECORD_LESSON_CONTRACT",
    "ROLE_SKILLS",
    "SKILL_INDEX_HEADER",
    "SKILL_LIST_HEADER",
    "SKILL_LOAD_CONTRACT",
    "WRITE_SKILL_CONTRACT",
    "DuplicateSkillNameError",
    "LessonInvalidError",
    "LessonStore",
    "SkillAgentBinding",
    "SkillCatalogue",
    "SkillInvalidError",
    "SkillLayoutError",
    "SkillStore",
    "SkillTargetError",
    "SkillUnknownError",
    "StoreUnavailableError",
    "build_load_skill_tool",
    "build_record_lesson_tool",
    "build_skill_tools",
    "build_write_skill_tool",
    "clear_cache",
    "is_meta_skill",
    "list_skill_descriptions",
    "list_skills",
    "list_suite_classes",
    "list_suite_leaves",
    "read_suite_raw",
    "render_skill_index",
    "skill_agent_binding",
    "skill_for",
    "skill_index_middleware",
    "skill_meta",
    "skills_for_role",
    "validate_skill",
]
