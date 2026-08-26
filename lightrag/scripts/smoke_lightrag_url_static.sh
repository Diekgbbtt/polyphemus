#!/bin/sh
set -eu

# Deterministic, non-credit Milestone 4 URL ingestion smoke.
#
# Runs only unit tests that use fake resolvers/transports and mocked
# downstreams (docprep, LightRAG, audit, PostgreSQL). No localhost socket,
# public DNS, external HTTP, Docker startup, LightRAG call, or LLM call is
# made. Each labeled group is a fixed pytest selection; the script stops at
# the first failing group.

# Locate the repository root from this script's location.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

PYTHON_CMD=""

# 1. Use POLYPHEMUS_PY if explicitly provided (repository convention);
#    PYTHON_BIN remains supported as an alias.
if [ -n "${POLYPHEMUS_PY:-}" ]; then
    if [ ! -x "$POLYPHEMUS_PY" ]; then
        echo "Error: POLYPHEMUS_PY is not an executable file: $POLYPHEMUS_PY" >&2
        exit 1
    fi
    PYTHON_CMD="$POLYPHEMUS_PY"
elif [ -n "${PYTHON_BIN:-}" ]; then
    PYTHON_CMD="$PYTHON_BIN"
fi

# 2. Use <repository root>/.venv/bin/python if available.
if [ -z "$PYTHON_CMD" ] && [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_CMD="$REPO_ROOT/.venv/bin/python"
fi

# 3. If this checkout is a Git repository or linked worktree, resolve the main
#    repository root with `git -C "$REPO_ROOT"` (never the caller's cwd) and
#    use its .venv/bin/python.
if [ -z "$PYTHON_CMD" ]; then
    GIT_COMMON_DIR=$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null) || true
    if [ -n "$GIT_COMMON_DIR" ]; then
        case "$GIT_COMMON_DIR" in
            /*) ;;
            *) GIT_COMMON_DIR="$REPO_ROOT/$GIT_COMMON_DIR" ;;
        esac
        GIT_COMMON_DIR=${GIT_COMMON_DIR%/}
        case "$GIT_COMMON_DIR" in
            */.git) MAIN_REPO_ROOT=${GIT_COMMON_DIR%/.git} ;;
            *) MAIN_REPO_ROOT="$GIT_COMMON_DIR" ;;
        esac
        if [ -x "$MAIN_REPO_ROOT/.venv/bin/python" ]; then
            PYTHON_CMD="$MAIN_REPO_ROOT/.venv/bin/python"
        fi
    fi
fi

# 4. No bare system-python fallback: this smoke must run with a repository
#    interpreter that has the tested code and pytest available.
if [ -z "$PYTHON_CMD" ]; then
    echo "Error: could not find a repository Python interpreter." >&2
    echo "Set POLYPHEMUS_PY to a python executable with pytest installed," >&2
    echo "or ensure .venv/bin/python exists in this repository or its" >&2
    echo "main repository root." >&2
    exit 1
fi

cd "$REPO_ROOT"

run_group() {
    label="$1"
    shift
    echo "== $label =="
    "$PYTHON_CMD" -m pytest -q "$@"
}

run_group "HTML download via fake resolver/transport" \
    "tests/ingestion/test_url_downloader.py::test_successful_metadata_sha256_and_artifact"

run_group "Markdown download + exact MIME policy via fakes" \
    "tests/ingestion/test_url_downloader.py::test_valid_markdown_download" \
    "tests/ingestion/test_url_downloader.py::test_exact_mime_policy_matrix"

run_group "Strict RFC 5987 filename* evidence via fakes" \
    "tests/ingestion/test_url_downloader.py::test_extended_filename_is_strict_utf8_evidence_only" \
    "tests/ingestion/test_url_downloader.py::test_declared_unsupported_mime_rejected_even_with_valid_extended_filename"

run_group "Deterministic MIME evidence: conflicts and controls" \
    "tests/ingestion/test_url_downloader.py::test_text_plain_conflicting_url_and_disposition_filenames_are_ambiguous" \
    "tests/ingestion/test_url_downloader.py::test_text_plain_control_containing_decoded_url_filename_is_not_markdown_evidence" \
    "tests/ingestion/test_url_downloader.py::test_text_plain_control_containing_url_filename_does_not_conflict_with_disposition" \
    "tests/ingestion/test_url_downloader.py::test_content_type_standard_charset_parameter_is_parsed_as_media_type"

run_group "Idempotent canonical identity incl. encoded dot segments" \
    "tests/ingestion/test_contracts.py::test_canonicalize_url_decodes_encoded_dot_segments_before_removal" \
    "tests/ingestion/test_contracts.py::test_canonicalize_url_is_idempotent_for_encoded_dot_segments" \
    "tests/ingestion/test_contracts.py::test_canonicalize_url_does_not_decode_encoded_reserved_separators" \
    "tests/ingestion/test_service.py::test_url_submit_encoded_dot_segments_agree_between_source_uri_and_source_key"

run_group "New HTML URL job -> audit -> PROCESSED (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_job_success_reaches_audit_and_processed"

run_group "Unchanged URL recrawl -> SKIPPED_DUPLICATE (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_same_url_unchanged_content_skips_and_refreshes_metadata"

run_group "Cross-URL duplicate -> null hash/activation (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_different_url_same_hash_skips_without_implying_activation"

run_group "Changed URL recrawl -> staged audit-before-delete -> PROCESSED (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_same_url_changed_content_clean_audit_activates_candidate"

run_group "Download failure -> FAILED with sanitized error (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_download_failure_reaches_failed_with_sanitized_error"

run_group "Critical audit -> FAILED_AUDIT (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_job_critical_audit_reaches_failed_audit" \
    "tests/ingestion/test_service.py::test_url_job_new_source_reaches_auditing_without_activation_fields" \
    "tests/ingestion/test_service.py::test_url_job_critical_audit_deletes_rejected_candidate_and_clears_activation_fields" \
    "tests/ingestion/test_service.py::test_url_job_critical_audit_candidate_delete_failure_is_terminalized_sanitized" \
    "tests/ingestion/test_service.py::test_url_same_url_changed_content_failed_audit_keeps_old_active_and_cleans_candidate"

run_group "Unexpected background failure boundary -> FAILED (mocked downstreams)" \
    "tests/ingestion/test_service.py::test_url_unexpected_lightrag_ingestion_failure_is_terminal_and_sanitized" \
    "tests/ingestion/test_service.py::test_url_same_url_changed_content_final_source_persistence_failure_compensates"

run_group "n8n URL workflow: native Header Auth + orchestration only" \
    "tests/ingestion/test_n8n_url_workflow.py"

run_group "URL schema migration gate at application startup" \
    "tests/ingestion/test_api_routes.py::test_app_startup_invokes_url_migration_before_first_request" \
    "tests/ingestion/test_api_routes.py::test_app_startup_migration_failure_prevents_readiness" \
    "tests/ingestion/test_api_routes.py::test_app_repeated_startup_keeps_migration_idempotent"

echo
echo "Static URL smoke test passed: HTML, Markdown, strict filename*, MIME conflicts/controls, idempotent canonical identity, duplicate, staged update, atomic new-URL audit, unexpected-failure boundary, FAILED, FAILED_AUDIT, migration gate, n8n auth"
