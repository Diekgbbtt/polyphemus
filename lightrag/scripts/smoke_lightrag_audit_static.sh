#!/bin/sh
set -eu

# Locate the repository root from this script's location.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

PYTHON_CMD=""

# 1. Use PYTHON_BIN if explicitly provided.
if [ -n "${PYTHON_BIN:-}" ]; then
    PYTHON_CMD="$PYTHON_BIN"
fi

# 2. Use <current repository root>/.venv/bin/python if available.
if [ -z "$PYTHON_CMD" ] && [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_CMD="$REPO_ROOT/.venv/bin/python"
fi

# 3. If running from a Git worktree, derive the main repository root
#    from `git rev-parse --git-common-dir` and use its .venv/bin/python.
if [ -z "$PYTHON_CMD" ]; then
    if git rev-parse --git-common-dir >/dev/null 2>&1; then
        GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null) || true
        if [ -n "$GIT_COMMON_DIR" ]; then
            case "$GIT_COMMON_DIR" in
                /*) ;;
                *) GIT_COMMON_DIR="$PWD/$GIT_COMMON_DIR" ;;
            esac
            GIT_COMMON_DIR=${GIT_COMMON_DIR%/}
            case "$GIT_COMMON_DIR" in
                */.git) MAIN_REPO_ROOT=${GIT_COMMON_DIR%/.git} ;;
                .git) MAIN_REPO_ROOT=$PWD ;;
                *) MAIN_REPO_ROOT="$GIT_COMMON_DIR" ;;
            esac
            if [ -x "$MAIN_REPO_ROOT/.venv/bin/python" ]; then
                PYTHON_CMD="$MAIN_REPO_ROOT/.venv/bin/python"
            fi
        fi
    fi
fi

# 4. Fall back to python3 if available.
if [ -z "$PYTHON_CMD" ] && command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
fi

# 5. If none was found, exit with a clear error.
if [ -z "$PYTHON_CMD" ]; then
    echo "Error: could not find a Python interpreter." >&2
    echo "Set PYTHON_BIN to a python executable, or ensure .venv/bin/python exists, or install python3." >&2
    exit 1
fi

# Run only the local audit unit tests.
"$PYTHON_CMD" -m pytest tests/ingestion/test_audit.py "$@"

echo "Static audit smoke test passed"
