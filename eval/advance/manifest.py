"""manifest.py - the alignment-relevant stack manifest.

One SHA per alignment-relevant path group at a given commit, plus an injected
map of the running images' digests. `PATH_RULES` is the single reviewed
constant table for the documented alignment map (ADR section 4); extending it
is a one-line data edit, because a missed alignment artifact is this module's
own risk (R16).

Each concrete tracked path is assigned to the first matching rule, so a
specific classification wins over its parent directory: `kali/Dockerfile` is
an image definition, not merely `kali/**` exec plane, and
`src/polymerhus/app/data_root.py` is schema/data layout, not generic agent
code. A group's SHA is the git object SHA when it covers exactly one object,
otherwise a sha256 over its sorted `<path>\\0<object sha>` lines.

Git access is injected: `build_manifest` takes a `repo` path and a runner, and
does no I/O at import, so a test can point at a tiny temp repo (or a fake
runner entirely).
"""
from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from advance.effects import CommandResult, run_process


@dataclass(frozen=True)
class PathRule:
    """One reviewed path group and its artifact class."""

    name: str
    artifact_class: str
    patterns: tuple[str, ...]


# Order matters: the first matching rule claims the path. Specific overrides
# (`data_root_layout`, `image_definitions`) precede the directory wildcards
# they sit inside. `Dockerfile*` is root-level only, so it never claims
# `kali/Dockerfile`, which the explicit pattern lists here.
PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        "data_root_layout",
        "schema_data_layout",
        ("src/polymerhus/app/data_root.py",),
    ),
    PathRule(
        "image_definitions",
        "image_definition",
        ("kali/Dockerfile", "Dockerfile*"),
    ),
    PathRule("src", "agent_code", ("src/**",)),
    PathRule("skills", "agent_code", ("skills/**",)),
    PathRule("lightrag", "agent_code", ("lightrag/**",)),
    PathRule("kali", "exec_plane", ("kali/**",)),
    PathRule("gateway", "gateway", ("gateway/**",)),
    PathRule("compose", "topology_env", ("docker-compose*.yml",)),
    PathRule("env_schema", "config_schema", (".env.example",)),
    PathRule("db", "schema_data_layout", ("db/**",)),
    PathRule("requirements", "platform", ("requirements*.txt",)),
    PathRule("pyproject", "platform", ("pyproject.toml",)),
    PathRule("dependency_locks", "platform", ("skills-lock.json",)),
)

# S7: the tracked top-level paths deliberately excluded from the manifest. Every
# other tracked path must be claimed by PATH_RULES; `test_advance_manifest.py`
# asserts this against the real tree, so a new top-level tree forces an explicit
# decision here instead of being dropped silently. A trailing "-" is a filename
# prefix (the authoring prompts).
IGNORED_PREFIXES: tuple[str, ...] = (
    ".agents",
    ".gitattributes",
    ".github",
    ".gitignore",
    # Agent tooling (the eval orchestrator agent + its plugin): it configures the
    # agent runtime, not the stack, so a version advance never aligns it.
    ".opencode",
    "CLAUDE.md",
    "CODING_STANDARD.md",
    "CONTEXT-MAP.md",
    "PROMPT-",
    "README.md",
    "STATE.md",
    "data",
    "docs",
    "eval",
    "frontend",
    "loop-budget.md",
    "loop-constraints.md",
    "tests",
    "tools",
)


class ManifestError(RuntimeError):
    """The git tree for a commit could not be read."""


@dataclass(frozen=True)
class ManifestEntry:
    """One path group: its class, composite SHA, and the tracked paths it covers."""

    name: str
    artifact_class: str
    sha: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class StackManifest:
    """The alignment-relevant artifacts at a commit plus running image digests."""

    commit: str
    entries: tuple[ManifestEntry, ...]
    image_digests: Mapping[str, str]


GitRunner = Callable[[Path, Sequence[str]], CommandResult]


def default_git_runner(repo: Path, args: Sequence[str]) -> CommandResult:
    """Run `git -C <repo> <args>` and capture its output."""
    return run_process(["git", "-C", str(repo), *args])


def build_manifest(
    repo: Path,
    commit: str,
    image_digests: Mapping[str, str],
    *,
    git_runner: GitRunner = default_git_runner,
) -> StackManifest:
    """Compute the stack manifest for `commit` in `repo`.

    `image_digests` is the injected `{component: digest}` map from the running
    stack (`eval/advance/images.py`). Raises `ManifestError` when the commit's
    tree cannot be read.
    """
    objects = _list_tree(repo, commit, git_runner)
    assigned: dict[str, list[tuple[str, str]]] = {rule.name: [] for rule in PATH_RULES}
    for path, object_sha in objects:
        rule = _first_match(path)
        if rule is not None:
            assigned[rule.name].append((path, object_sha))

    entries = []
    for rule in PATH_RULES:
        pairs = sorted(assigned[rule.name])
        entries.append(
            ManifestEntry(
                name=rule.name,
                artifact_class=rule.artifact_class,
                sha=_group_sha(pairs),
                paths=tuple(path for path, _ in pairs),
            )
        )
    return StackManifest(
        commit=commit, entries=tuple(entries), image_digests=dict(image_digests)
    )


def _list_tree(
    repo: Path, commit: str, git_runner: GitRunner
) -> list[tuple[str, str]]:
    """Every tracked `(path, object sha)` under `commit`, recursively."""
    result = git_runner(repo, ["ls-tree", "-r", "-z", commit])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ManifestError(f"git ls-tree failed for {commit!r}: {detail}")
    objects: list[tuple[str, str]] = []
    for record in result.stdout.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        _mode, _type, object_sha = meta.split(" ", 2)
        objects.append((path, object_sha))
    return objects


def classify(path: str) -> PathRule | None:
    """The artifact class for a tracked path, or `None` when it is unmatched."""
    return _first_match(path)


def is_ignored(path: str) -> bool:
    """True when a tracked path is deliberately outside the manifest (S7)."""
    for prefix in IGNORED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
        if prefix.endswith("-") and path.startswith(prefix):
            return True
    return False


def _first_match(path: str) -> PathRule | None:
    for rule in PATH_RULES:
        if any(_matches(pattern, path) for pattern in rule.patterns):
            return rule
    return None


def _matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    if "/" not in pattern:
        # Root-level patterns: `*`/`?` never cross a separator, so
        # `requirements*.txt` cannot claim a nested requirements file.
        if "/" in path:
            return False
        return fnmatch.fnmatchcase(path, pattern)
    return pattern == path


def _group_sha(pairs: list[tuple[str, str]]) -> str:
    if len(pairs) == 1:
        return pairs[0][1]
    digest = hashlib.sha256()
    for path, object_sha in pairs:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(object_sha.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
