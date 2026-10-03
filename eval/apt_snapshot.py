"""Pin Debian apt sources to snapshot.debian.org inside a WebExploitBench tree.

Debian bullseye reached end of life (2026-08-31): its security pool now returns
404 for the versions its Packages index still lists, so every WebExploitBench
Dockerfile that `apt-get`s from a bullseye base fails to build. This patcher
rewrites each Debian apt source to a fixed `snapshot.debian.org` timestamp, so
the exact package versions exist forever and the build is reproducible.

The rewrite is scoped to END-OF-LIFE suites: the injected layer reads the base
image's `VERSION_CODENAME` and no-ops on a current-stable base (bookworm,
trixie). A current base already tracks the live archive and is rebuilt with
packages newer than any fixed snapshot, so pinning it would force a downgrade
and `apt-get install` would fail with "held broken packages". Only the suites
the archive has retired (bullseye, buster) are pinned.

The patch is applied to a checkout in place, because the image build reads the
Dockerfiles from that checkout. It is idempotent: the injected block carries a
marker and a second run is a no-op.

The build runs on a native amd64 runner (the CI image workflow), so the patched
Dockerfiles never run under qemu emulation. The same patcher is safe to run on
the eval server's checkout for a local fallback build.

Usage:
    python3 eval/apt_snapshot.py <webench-root> [--timestamp TS]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The last snapshot before bullseye LTS ended; it carries bullseye and buster.
DEFAULT_TIMESTAMP = "20260815T000000Z"
MARKER = "# ph-apt-snapshot"
FROM_PREFIX = "FROM "
_SKIP_DIRS = {".git", ".cache", "node_modules"}

# One Dockerfile layer that pins every Debian source, but only on an END-OF-LIFE
# suite. A current-stable base (bookworm, trixie) already tracks the live archive
# and is periodically rebuilt with packages newer than any fixed snapshot; pinning
# it to the snapshot forces a downgrade and `apt-get install` fails with "held
# broken packages". So the block reads the base image's own codename and no-ops
# unless it is a suite the archive has retired (bullseye/buster). The `#` sed
# delimiter keeps the URL slashes readable; the `(deb|security)` alternation would
# clash with a `|` delimiter. Both the classic `deb http://...` form and the
# deb822 `URIs: http://...` form are handled.
_APT_BLOCK = """\
{MARKER}
RUN set -eux; \\
    codename="$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release)"; \\
    case "$codename" in \\
        bullseye|buster) ;; \\
        *) echo "ph-apt-snapshot: $codename is not EOL; skipping"; exit 0 ;; \\
    esac; \\
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*; do \\
        [ -f "$f" ] || continue; \\
        sed -i -E "s#https?://(deb|security)\\.debian\\.org/debian-security#http://snapshot.debian.org/archive/debian-security/{timestamp}#g; s#https?://(deb|security)\\.debian\\.org/debian#http://snapshot.debian.org/archive/debian/{timestamp}#g" "$f"; \\
        sed -i -E "/snapshot\\.debian\\.org/ s#^deb #deb [check-valid-until=no] #" "$f"; \\
        if grep -q "URIs:.*snapshot\\.debian\\.org" "$f" && ! grep -q "^Check-Valid-Until:" "$f"; then \\
            sed -i -E "/^URIs:.*snapshot\\.debian\\.org/a Check-Valid-Until: no" "$f"; \\
        fi; \\
    done
"""


def patch_dockerfile(text: str, timestamp: str) -> str:
    """Insert the apt-snapshot block after every `FROM` line, once."""
    if MARKER in text:
        return text
    if "apt-get" not in text:
        return text
    block = _APT_BLOCK.format(MARKER=MARKER, timestamp=timestamp)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        out.append(line)
        if line.lstrip().startswith(FROM_PREFIX) and not line.rstrip().endswith("\\"):
            out.append(block)
    return "".join(out)


def dockerfiles_with_apt(root: Path) -> list[Path]:
    """Every Dockerfile under `root` that runs `apt-get`, in sorted order."""
    found: list[Path] = []
    for path in sorted(root.rglob("Dockerfile*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "apt-get" in text:
            found.append(path)
    return found


def patch_tree(root: Path, timestamp: str = DEFAULT_TIMESTAMP) -> list[Path]:
    """Patch every apt Dockerfile under `root`; return the ones actually changed."""
    changed: list[Path] = []
    for path in dockerfiles_with_apt(root):
        text = path.read_text(encoding="utf-8")
        patched = patch_dockerfile(text, timestamp)
        if patched != text:
            path.write_text(patched, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="WebExploitBench checkout to patch")
    parser.add_argument(
        "--timestamp",
        default=DEFAULT_TIMESTAMP,
        help=f"snapshot.debian.org timestamp (default {DEFAULT_TIMESTAMP})",
    )
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"apt_snapshot: not a directory: {args.root}", file=sys.stderr)
        return 2
    changed = patch_tree(args.root, args.timestamp)
    if changed:
        for path in changed:
            print(f"apt_snapshot: patched {path}")
    else:
        print("apt_snapshot: no Dockerfiles needed patching")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
