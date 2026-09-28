#!/usr/bin/env python3
"""env_preflight.py - align the per-instance `.env` with `.env.example`.

Appends keys missing from the instance `.env` with their example values
(empty stays empty), never overwrites an existing key, never deletes, then
prints the keyset drift: added keys, keys absent from `.env.example`
(candidate renames/leftovers, informational only), and required-by-overlay
keys still unset/empty. Exits non-zero only for that last class.

The required set is parsed from the overlay's required-variable patterns
(`${VAR:?msg}` and `${VAR?msg}`) rather than hardcoded here, so the overlay
stays the single source of truth: adding a required variable to
`docker-compose.eval.yml` automatically extends the preflight check, and the
two can never disagree. (Parsing keeps this stdlib only; compose is the only
other reader of these files.)

Exit codes: 0 clean (additions and extras do not fail); 1 a required key is
still unset/empty after the fill; 2 the `.env`, `.env.example`, or overlay
file is missing or unreadable.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
# Both required-interpolation forms compose accepts (`${VAR:?msg}` and
# `${VAR?msg}`); never the default/alt forms (`:-`, `-`, `:+`, `+`, `:=`).
# The lookbehind skips `$$`-escaped literals (`$${VAR:?x}` renders verbatim
# and imposes no requirement).
_REQUIRED_RE = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*):?\?")

_HERE = Path(__file__).resolve().parent
DEFAULT_OVERLAY = _HERE / "docker-compose.eval.yml"
DEFAULT_EXAMPLE = _HERE.parent / ".env.example"

MARKER = "# Appended by eval/env_preflight.py from .env.example."


def parse_assignments(path: Path) -> dict[str, str]:
    """Key/value assignments in a dotenv file, last wins.

    Full-line comments and blank lines are skipped, so commented-out keys
    (documentation in `.env.example`) never count as present. Values ride
    verbatim: compose strips inline comments from env files itself, and
    re-parsing values here would risk corrupting secrets containing `#`.
    """
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _KEY_RE.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def required_vars(overlay_path: Path) -> list[str]:
    """The overlay's required set: every required interpolation, sorted.

    Full-line comments are ignored, so prose mentioning the pattern shape
    never leaks into the set. Limitation, documented not fixed: an inline
    (trailing) comment carrying the pattern would still match, so keep the
    literal pattern out of overlay comments entirely.
    """
    names: set[str] = set()
    for line in overlay_path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        names.update(_REQUIRED_RE.findall(line))
    return sorted(names)


def _has_value(raw: str | None) -> bool:
    """Whether a dotenv value satisfies compose's required check.

    Compose rejects a required variable that is unset OR empty, and its env
    reader treats a quoted-empty (`""`, `''`) or whitespace-only value as
    empty too, so all of those count as missing here.
    """
    if raw is None:
        return False
    text = raw.strip()
    if not text:
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return bool(text[1:-1].strip())
    return True


@dataclass
class PreflightResult:
    added: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    exit_code: int = 0


def run(env_path: Path, example_path: Path, overlay_path: Path) -> PreflightResult:
    """Fill `env_path` from `example_path`, report drift against `overlay_path`.

    Raises OSError when the `.env`, `.env.example`, or overlay is missing or
    unreadable: a missing instance `.env` is an operator error the overlay
    (`required: true`) would fail on anyway, never something to silently
    create here.
    """
    if not example_path.is_file():
        raise FileNotFoundError(f".env.example not found: {example_path}")
    if not env_path.is_file():
        raise FileNotFoundError(f"instance .env not found: {env_path}")
    if not overlay_path.is_file():
        raise FileNotFoundError(f"overlay not found: {overlay_path}")
    example = parse_assignments(example_path)
    present = parse_assignments(env_path)

    missing = [key for key in example if key not in present]
    if missing:
        raw = env_path.read_bytes()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        block = "" if MARKER in raw.decode("utf-8") else f"{MARKER}{newline}"
        block += "".join(f"{key}={example[key]}{newline}" for key in missing)
        with env_path.open("a", encoding="utf-8", newline="") as fh:
            if raw and not raw.endswith(b"\n"):
                fh.write(newline)
            fh.write(block)
        for key in missing:
            present[key] = example[key]

    extra = [key for key in present if key not in example]
    required_missing = [
        key for key in required_vars(overlay_path) if not _has_value(present.get(key))
    ]
    return PreflightResult(
        added=missing,
        extra=extra,
        required_missing=required_missing,
        exit_code=1 if required_missing else 0,
    )


def format_report(result: PreflightResult, env_path: Path) -> str:
    def section(name: str, keys: list[str]) -> str:
        return f"{name} ({len(keys)}): {' '.join(keys) if keys else '-'}"

    return "\n".join(
        [
            f"env_preflight: {env_path}",
            section("added", result.added),
            section("extra", result.extra),
            section("required-missing", result.required_missing),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env", nargs="?", default=".env", help="instance .env path")
    parser.add_argument("--example", default=str(DEFAULT_EXAMPLE))
    parser.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.env), Path(args.example), Path(args.overlay))
    except OSError as exc:
        print(f"env_preflight: error: {exc}", file=sys.stderr)
        return 2
    print(format_report(result, Path(args.env)))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
