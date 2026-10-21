#!/usr/bin/env bash
set -euo pipefail
#
# sync_instance.sh - freeze the batch worktree's app source into the eval
# instance and prove the two trees are byte-identical.
#
# Usage (from the batch worktree root):
#   eval/deploy/sync_instance.sh <ssh-host> <instance-worktree>
#
# Optional env:
#   SYNC_DIR  where the manifests are written (default /tmp/armm-sync)
#
# The script syncs `src/` and the eval compose overlay, writes a SHA-256
# manifest on each side, diffs them, and prints the manifest hash the trial
# records as its stack fingerprint. It never prints file contents.
#
# The instance `src/` is the codebase the app loads; the overlay is the
# compose file that disables `--reload` for the trial. Both are frozen before
# the agent is force-recreated.

HOST=${1:?usage: sync_instance.sh <ssh-host> <instance-worktree>}
INSTANCE=${2:?usage: sync_instance.sh <ssh-host> <instance-worktree>}
SYNC_DIR=${SYNC_DIR:-/tmp/armm-sync}
ROOT=$(pwd)

if [ ! -d "$ROOT/src" ] || [ ! -f "$ROOT/eval/docker-compose.eval.yml" ]; then
    echo "sync_instance.sh: run from the batch worktree root" >&2
    exit 2
fi

mkdir -p "$SYNC_DIR"
LOCAL_MANIFEST="$SYNC_DIR/local.manifest"
REMOTE_MANIFEST="$SYNC_DIR/remote.manifest"

manifest() {
    local root=$1
    python3 - "$root" <<'PY'
import hashlib
import os
import sys

root = os.path.abspath(sys.argv[1])
for dirpath, dirnames, filenames in os.walk(os.path.join(root, "src")):
    dirnames[:] = sorted(
        name for name in dirnames if name not in {"__pycache__", ".pytest_cache"}
    )
    for name in sorted(filenames):
        if name.endswith(".pyc"):
            continue
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, root)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        print(f"{digest}  {rel}")
PY
}

manifest "$ROOT" > "$LOCAL_MANIFEST"

echo "syncing $ROOT/src -> $HOST:$INSTANCE/src"
rsync -az --delete --delete-excluded \
    --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/' \
    "$ROOT/src/" "$HOST:$INSTANCE/src/"
rsync -az "$ROOT/eval/docker-compose.eval.yml" \
    "$HOST:$INSTANCE/eval/docker-compose.eval.yml"

ssh "$HOST" "python3 - '$INSTANCE'" <<'PY' > "$REMOTE_MANIFEST"
import hashlib
import os
import sys

root = os.path.abspath(sys.argv[1])
for dirpath, dirnames, filenames in os.walk(os.path.join(root, "src")):
    dirnames[:] = sorted(
        name for name in dirnames if name not in {"__pycache__", ".pytest_cache"}
    )
    for name in sorted(filenames):
        if name.endswith(".pyc"):
            continue
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, root)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        print(f"{digest}  {rel}")
PY

if ! diff -u "$LOCAL_MANIFEST" "$REMOTE_MANIFEST"; then
    echo "sync_instance.sh: source manifests differ - HARD STOP" >&2
    exit 1
fi

TREE_HASH=$(shasum -a 256 "$LOCAL_MANIFEST" | awk '{print $1}')
LOCAL_OVERLAY=$(shasum -a 256 "$ROOT/eval/docker-compose.eval.yml" | awk '{print $1}')
REMOTE_OVERLAY=$(ssh "$HOST" "sha256sum '$INSTANCE/eval/docker-compose.eval.yml'" | awk '{print $1}')

if [ "$LOCAL_OVERLAY" != "$REMOTE_OVERLAY" ]; then
    echo "sync_instance.sh: eval overlay hashes differ - HARD STOP" >&2
    exit 1
fi

echo "source-files: $(wc -l < "$LOCAL_MANIFEST" | tr -d ' ')"
echo "source-tree-sha256: $TREE_HASH"
echo "eval-overlay-sha256: $LOCAL_OVERLAY"
echo "manifests match"
