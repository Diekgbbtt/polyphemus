#!/usr/bin/env python3
"""Shape-class secret scanner: read-only, standard library only.

Mirrors the ordered shape catalogue in `references/secret-pattern-catalog.md`.
The rows run most specific first, so a typed shape is never pre-empted by a
generic entropy catch.

Usage:
  python3 secret-scan.py [options] [PATH ...]
  cat fetched-body.txt | python3 secret-scan.py

Options:
  --min-severity {critical,high,medium,low}  drop rows below this severity
  --max-bytes N     skip files larger than N bytes (default 10485760)
  --no-skip         scan conventional noise directories too
  -h, --help        this header

Output: one JSON object per line, one record per match:
  {"shape", "severity", "family", "match", "source", "line", "column"}

`match` is masked to its first four and last two characters, so a scan log
never carries a live secret in full.

Exit codes:
  0  completed, whether or not matches were found
  2  invalid arguments

Unreadable and skipped files warn on stderr, so a clean run is never
silently clean.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SEVERITIES = ("critical", "high", "medium", "low")

# The issuer prefix table, the exact body lengths, and the issuer endpoints are
# runtime knowledge-base facts; the rows below hold the shape classes only, so
# a runtime prefix table slots in above them as extra most-specific rows.
SHAPES: list[tuple[str, str, str, str]] = [
    # (shape, severity, family, pattern)
    ("key-armour-block", "critical", "key_material",
     r"-----BEGIN [A-Z0-9 ]{0,20}PRIVATE KEY-----"),
    ("service-account-document", "critical", "cloud_identity",
     r'"type"\s*:\s*"[a-z_]*service[_ ]?account[a-z_]*"'),
    ("key-pair-credential", "critical", "cloud_infrastructure",
     r"\b[A-Z]{4}[0-9A-Z]{16}\b"),
    ("issuer-prefixed-token", "high", "prefixed_token",
     r"\b[a-z][a-z0-9]{1,5}[_-][A-Za-z0-9]{20,}\b"),
    ("numeric-separated-bot-token", "high", "messaging_bot",
     r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"),
    ("signed-token-triplet", "medium", "session_artefact",
     r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    ("bearer-assignment", "medium", "auth_header",
     r"(?i)\bauthorization\b[\"']?\s*[:=]\s*[\"']?\s*bearer\s+[A-Za-z0-9._\-]{20,}"),
    ("basic-auth-header", "medium", "auth_header",
     r"(?i)\bauthorization\b[\"']?\s*[:=]\s*[\"']?\s*basic\s+[A-Za-z0-9+/=]{16,}"),
    ("credentialed-url", "medium", "connection_string",
     r"[a-z][a-z0-9+.\-]{1,10}://[^/\s:@\"']+:[^/\s:@\"']+@[^\s/\"']+"),
    ("signed-request-url", "medium", "notification_service",
     r"(?i)\b(?:webhook|hook|notify|callback)[_\-]?url[\"']?\s*[:=]\s*[\"']?(https?://[^\s\"']+)"),
    ("context-anchored-secret", "medium", "context_anchor",
     r"(?i)(?:api[_\-]?key|apikey|api[_\-]?secret|client[_\-]?secret|"
     r"[a-z_\-]{0,20}token|password|passwd|passphrase|private[_\-]?key)"
     r"[\"']?\s*[:=]\s*[\"']([A-Za-z0-9+/=_\-]{24,})[\"']"),
    ("context-anchored-hex", "medium", "context_anchor",
     r"(?i)(?:secret|token|key|hmac|signature)[\"']?\s*[:=]\s*[\"']([a-f0-9]{32,})[\"']"),
    ("encoded-holder", "low", "encoded",
     r"\b[A-Za-z0-9+/]{60,}={0,2}\b"),
    ("high-entropy-literal", "low", "generic",
     r"\b(?=[A-Za-z0-9]{32,}\b)"
     r"(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])"
     r"(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{32,}\b"),
]

COMPILED = [(name, sev, fam, re.compile(pattern)) for name, sev, fam, pattern in SHAPES]

# Conventional noise directory names: a default, not a verdict.
SKIP_PARTS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".cache", "dist", "build", "vendor", "target",
})


def mask(value: str) -> str:
    """Keep the shape readable without carrying the secret in full."""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * min(len(value) - 6, 24) + value[-2:]


def active_shapes(min_severity: str):
    """The ordered rows at or above the severity floor."""
    floor = SEVERITIES.index(min_severity)
    return [row for row in COMPILED if SEVERITIES.index(row[1]) <= floor]


def scan_text(text: str, source: str = "<stdin>", shapes=None):
    """Scan one text blob; yield one record per match, shapes in order."""
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, severity, family, rx in (shapes if shapes is not None else COMPILED):
            for match in rx.finditer(line):
                yield {
                    "shape": name,
                    "severity": severity,
                    "family": family,
                    "match": mask(match.group(0)),
                    "source": source,
                    "line": line_no,
                    "column": match.start() + 1,
                }


def scan_path(path: str, max_bytes: int, skip: bool, shapes):
    """Walk a file or directory; yield records. Never writes, never fetches."""
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            if skip:
                dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for name in sorted(files):
                yield from scan_path(os.path.join(root, name), max_bytes, skip, shapes)
        return
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            print(
                f"[warning] skipped (> {max_bytes} bytes, NOT scanned): {path}",
                file=sys.stderr,
            )
            return
        with open(path, "r", errors="replace") as handle:
            yield from scan_text(handle.read(), source=path, shapes=shapes)
    except OSError as exc:
        # A missing or unreadable path must not read as "no secrets found".
        print(f"[warning] could not read (skipped): {path} ({exc})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="help")
    parser.add_argument("--min-severity", choices=SEVERITIES, default="low")
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--no-skip", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    shapes = active_shapes(args.min_severity)

    if args.paths:
        for path in args.paths:
            for record in scan_path(path, args.max_bytes, not args.no_skip, shapes):
                print(json.dumps(record))
    else:
        try:
            text = sys.stdin.read()
        except KeyboardInterrupt:
            return 0
        for record in scan_text(text, shapes=shapes):
            print(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
