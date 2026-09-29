#!/usr/bin/env bash
set -euo pipefail
#
# ff_dev.sh - the delivery plane's fast-forward (ADR section 1, D34).
#
# Owns exactly one reference: bring the canonical server checkout's local `dev`
# branch up to `origin/dev` with a fast-forward. It clones the checkout from
# the public HTTPS origin when absent, then fetches and ff-merges `dev`. It is
# the remote half of `.github/workflows/deploy-eval.yml`, which pipes this file
# over SSH (`bash -s`); keeping it a plain local script is what makes it
# testable against local git repositories.
#
# It is structurally incapable of touching the `eval` branch, eval worktrees,
# containers, or instance directories: the branch name is a hardcoded literal
# (`dev`), the clone is single-branch, the runner refuses to operate from any
# other branch, and it never resets or rebases. The `dev` -> `eval` advancement
# belongs to the server sync daemon (D34), never to the delivery plane.
#
# Required env:
#   EVAL_DEV_DIR     path of the canonical `dev` checkout
# Optional env:
#   EVAL_DEV_ORIGIN  git remote to clone/fetch from
#                    (default https://github.com/Diekgbbtt/polyphemus.git)
#
# Exit 0 on success (already-current is success); non-zero on a missing
# variable, a checkout on the wrong branch, or a non-fast-forward - in which
# case the working tree is left exactly as it was.

BRANCH=dev
DEFAULT_ORIGIN="https://github.com/Diekgbbtt/polyphemus.git"

die() {
    echo "ff_dev.sh: $*" >&2
    exit 1
}

: "${EVAL_DEV_DIR:?ff_dev.sh: EVAL_DEV_DIR is required (the canonical dev checkout path)}"
ORIGIN="${EVAL_DEV_ORIGIN:-$DEFAULT_ORIGIN}"

if [ ! -e "${EVAL_DEV_DIR}/.git" ]; then
    echo "ff_dev.sh: no checkout at ${EVAL_DEV_DIR}; cloning ${BRANCH} from ${ORIGIN}"
    mkdir -p "$(dirname "${EVAL_DEV_DIR}")"
    # --single-branch: the checkout only ever knows the `dev` branch, so no
    # eval ref can even exist in it (structural, not a runtime check).
    git clone --quiet --single-branch --branch "${BRANCH}" "${ORIGIN}" "${EVAL_DEV_DIR}"
fi

CURRENT="$(git -C "${EVAL_DEV_DIR}" symbolic-ref --short -q HEAD || true)"
[ "${CURRENT}" = "${BRANCH}" ] || die "checkout ${EVAL_DEV_DIR} is on '${CURRENT:-detached HEAD}', expected '${BRANCH}'; refusing to switch branches"

# Fetch only the `dev` refspec: no --prune, so no other remote-tracking ref is
# ever added or removed.
git -C "${EVAL_DEV_DIR}" fetch --quiet origin "${BRANCH}"

BEFORE="$(git -C "${EVAL_DEV_DIR}" rev-parse HEAD)"
# --ff-only: a diverged or otherwise non-fast-forwardable `dev` aborts here and
# leaves the working tree untouched. We never reset and never rebase.
if ! git -C "${EVAL_DEV_DIR}" merge --ff-only --quiet "origin/${BRANCH}"; then
    die "cannot fast-forward ${EVAL_DEV_DIR} to origin/${BRANCH} (local ${BRANCH} has diverged); working tree left untouched"
fi
AFTER="$(git -C "${EVAL_DEV_DIR}" rev-parse HEAD)"

echo "ff_dev.sh: ${EVAL_DEV_DIR} on ${BRANCH} fast-forwarded ${BEFORE} -> ${AFTER}"
