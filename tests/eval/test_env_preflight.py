"""Unit tests for the eval env preflight (`eval/env_preflight.py`).

The preflight fills keys missing from the per-instance `.env` with their
`.env.example` values without clobbering operator values, and reports the
keyset drift (added / extra / required-still-missing). These tests cross the
`run()` seam only, on tmp fixtures - the repo-root `.env` is never read.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_preflight():
    spec = importlib.util.spec_from_file_location(
        "env_preflight", REPO_ROOT / "eval" / "env_preflight.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["env_preflight"] = module  # dataclasses resolve via sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def preflight():
    return load_preflight()


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_keys_appended_and_operator_values_untouched(
    tmp_path: Path, preflight
) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\nBBB=two\nCCC=\n")
    env = write(tmp_path / ".env", "# operator file\nBBB=mine\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    result = preflight.run(env, example, overlay)

    assert result.added == ["AAA", "CCC"]
    assert result.exit_code == 0
    body = env.read_text(encoding="utf-8")
    assert "BBB=mine\n" in body  # never overwritten
    assert "AAA=one\n" in body  # example value appended
    assert "CCC=\n" in body  # empty stays empty
    assert body.startswith("# operator file\nBBB=mine\n")  # append-only


def test_extra_keys_reported_and_preserved(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    env = write(tmp_path / ".env", "AAA=one\nRENAMED_LEFTOVER=x\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    result = preflight.run(env, example, overlay)

    assert result.extra == ["RENAMED_LEFTOVER"]
    assert result.added == []
    assert result.exit_code == 0
    assert "RENAMED_LEFTOVER=x\n" in env.read_text(encoding="utf-8")


def test_required_missing_is_reported_and_fails(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = write(
        tmp_path / "overlay.yml", "services:\n  a:\n    environment:\n      REQ: ${REQ:?REQ is required}\n"
    )

    result = preflight.run(env, example, overlay)

    assert result.required_missing == ["REQ"]
    assert result.exit_code != 0


def test_satisfied_required_key_exits_zero(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\nREQ=fillme\n")
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = write(
        tmp_path / "overlay.yml", "services:\n  a:\n    environment:\n      REQ: ${REQ:?REQ is required}\n"
    )

    result = preflight.run(env, example, overlay)

    assert result.added == ["REQ"]
    assert result.required_missing == []
    assert result.exit_code == 0


def test_fully_populated_env_is_a_noop(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\nBBB=\n")
    env = write(tmp_path / ".env", "AAA=one\nBBB=\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")
    before = env.read_bytes()

    result = preflight.run(env, example, overlay)

    assert result.added == []
    assert result.extra == []
    assert result.required_missing == []
    assert result.exit_code == 0
    assert env.read_bytes() == before


def test_empty_but_present_values_do_not_crash(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=filled\n")
    env = write(tmp_path / ".env", "AAA=\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    result = preflight.run(env, example, overlay)

    assert result.exit_code == 0
    assert "AAA=\n" in env.read_text(encoding="utf-8")  # kept, not refilled


def test_empty_required_value_counts_as_missing(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "REQ=fillme\n")
    env = write(tmp_path / ".env", "REQ=\n")
    overlay = write(
        tmp_path / "overlay.yml", "services:\n  a:\n    environment:\n      REQ: ${REQ:?REQ is required}\n"
    )

    result = preflight.run(env, example, overlay)

    assert result.required_missing == ["REQ"]  # compose `:?` also rejects empty
    assert result.exit_code != 0


def test_second_run_is_idempotent(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\nBBB=two\n")
    env = write(tmp_path / ".env", "AAA=mine\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    first = preflight.run(env, example, overlay)
    after_first = env.read_bytes()
    second = preflight.run(env, example, overlay)

    assert first.added == ["BBB"]
    assert second.added == []
    assert second.exit_code == 0
    assert env.read_bytes() == after_first


def test_required_set_comes_from_the_overlay_not_a_second_list(
    tmp_path: Path, preflight
) -> None:
    overlay = write(
        tmp_path / "overlay.yml",
        "services:\n  a:\n    environment:\n"
        "      FOO: ${FOO:?FOO is required}\n"
        "      BAR: ${BAR:-default}\n"
        "      BAZ: ${BAZ:?custom message}\n",
    )

    assert preflight.required_vars(overlay) == ["BAZ", "FOO"]


def test_real_overlay_required_set_matches_the_no_default_contract(
    preflight,
) -> None:
    overlay = REPO_ROOT / "eval" / "docker-compose.eval.yml"

    required = preflight.required_vars(overlay)

    # app/llm/providers.py::resolve_role reads each role's LLM_<KEY> with no
    # fallback; app/config.py hard-reads the five connection vars. Provider
    # API keys are deliberately absent: they are per-provider and app boot
    # (validate_llm_config) already names the missing one.
    assert required == [
        "KALI_MCP_URL",
        "LLM_ANALYSER",
        "LLM_CONFIGURATOR",
        "LLM_CRAWLER",
        "LLM_HUNTING_HUNTER",
        "LLM_HUNTING_ORCHESTRATOR",
        "LLM_JOB_ORCHESTRATOR",
        "LLM_POD_RUNNER",
        "LLM_POD_TRIAGER",
        "LLM_TRIAGER",
        "NEO4J_PASSWORD",
        "NEO4J_URI",
        "NEO4J_USER",
        "POSTGRES_DSN",
    ]


def test_real_example_as_key_source(tmp_path: Path, preflight) -> None:
    example = REPO_ROOT / ".env.example"
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")
    env = write(
        tmp_path / ".env",
        "NEO4J_URI=bolt://neo4j:7687\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=polymerhus\n"
        "POSTGRES_DSN=postgresql://polymerhus:polymerhus@postgres:5432/polymerhus\n"
        "KALI_MCP_URL=http://kali:8000/mcp\n"
        "LLM_CONFIGURATOR=opencode:manual/test\n"
        "LLM_TRIAGER=opencode:manual/test\n"
        "LLM_JOB_ORCHESTRATOR=opencode:manual/test\n"
        "LLM_CRAWLER=opencode:manual/test\n"
        "LLM_ANALYSER=opencode:manual/test\n"
        "LLM_HUNTING_ORCHESTRATOR=opencode:manual/test\n"
        "LLM_HUNTING_HUNTER=opencode:manual/test\n"
        "LLM_POD_RUNNER=opencode:manual/test\n"
        "LLM_POD_TRIAGER=opencode:manual/test\n",
    )

    result = preflight.run(env, example, overlay)

    assert result.exit_code == 0
    assert "NEO4J_URI=bolt://neo4j:7687\n" in env.read_text(encoding="utf-8")
    assert result.added  # the example carries far more than the 14 required
    assert "MAX_PODS" in result.added


def test_cli_prints_drift_report_and_exits_nonzero_on_required_missing(
    tmp_path: Path, preflight, capsys: pytest.CaptureFixture[str]
) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    env = write(tmp_path / ".env", "AAA=one\nSTALE=x\n")
    overlay = write(
        tmp_path / "overlay.yml", "services:\n  a:\n    environment:\n      REQ: ${REQ:?REQ is required}\n"
    )

    rc = preflight.main(
        [str(env), "--example", str(example), "--overlay", str(overlay)]
    )

    assert rc != 0
    out = capsys.readouterr().out
    assert "added (0)" in out
    assert "STALE" in out  # extra section names the leftover
    assert "REQ" in out  # required-missing section names the unset key


def test_cli_missing_env_file_is_a_usage_error(
    tmp_path: Path, preflight, capsys: pytest.CaptureFixture[str]
) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    rc = preflight.main(
        [str(tmp_path / ".env"), "--example", str(example), "--overlay", str(overlay)]
    )

    assert rc == 2
    assert "not found" in capsys.readouterr().err
