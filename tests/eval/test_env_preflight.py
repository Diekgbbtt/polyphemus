"""Unit tests for the eval env preflight (`eval/env_preflight.py`).

The preflight fills keys missing from the per-instance `.env` with their
`.env.example` values without clobbering operator values, and reports the
keyset drift (added / extra / required-still-missing). These tests cross the
`run()` seam only, on tmp fixtures - the repo-root `.env` is never read.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
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


@pytest.mark.parametrize("value", ['""', "''", '"  "', "' '", "   ", "\t"])
def test_required_blank_values_count_as_missing(
    tmp_path: Path, preflight, value: str
) -> None:
    example = write(tmp_path / ".env.example", "REQ=fillme\n")
    env = write(tmp_path / ".env", f"REQ={value}\n")
    overlay = write(
        tmp_path / "overlay.yml", "services:\n  a:\n    environment:\n      REQ: ${REQ:?REQ is required}\n"
    )

    result = preflight.run(env, example, overlay)

    # Compose's env reader treats quoted-empty and whitespace-only as empty,
    # so `${REQ:?}` rejects them exactly like an unset or empty value.
    assert result.required_missing == ["REQ"]
    assert result.exit_code != 0


@pytest.mark.parametrize("value", ["x", '"x"', "'x'", "  x  "])
def test_required_nonblank_values_pass(
    tmp_path: Path, preflight, value: str
) -> None:
    example = write(tmp_path / ".env.example", "REQ=fillme\n")
    env = write(tmp_path / ".env", f"REQ={value}\n")
    overlay = write(
        tmp_path / "overlay.yml", "services:\n  a:\n    environment:\n      REQ: ${REQ:?REQ is required}\n"
    )

    result = preflight.run(env, example, overlay)

    assert result.required_missing == []
    assert result.exit_code == 0


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
        "      BAZ: ${BAZ:?custom message}\n"
        "      QUX: ${QUX?colon-less required form}\n"
        "      BAT: ${BAT:=assign-default form}\n"
        "      LIT: $${ESCAPED:?renders literally, no requirement}\n",
    )

    assert preflight.required_vars(overlay) == ["BAZ", "FOO", "QUX"]


def test_real_overlay_required_set_matches_the_no_default_contract(
    preflight,
) -> None:
    overlay = REPO_ROOT / "eval" / "docker-compose.eval.yml"

    required = preflight.required_vars(overlay)

    # Derived from the real contract, not a second literal: the five hard
    # `os.environ[...]` reads in app/config.py plus one key per distinct
    # `model_key` across ROLES and HUNTING_ROLES in app/llm/providers.py, plus
    # the A6 capability override the eval deployment requires (its absence is
    # the silent summariser degradation this preflight fails on).
    # Provider API keys are deliberately absent: they are per-provider and app
    # boot (validate_llm_config) already names the missing one.
    config_src = (REPO_ROOT / "src" / "polymerhus" / "app" / "config.py").read_text(
        encoding="utf-8"
    )
    hard_reads = set(re.findall(r'os\.environ\["([A-Za-z_][A-Za-z0-9_]*)"\]', config_src))
    from polymerhus.app.llm.providers import HUNTING_ROLES, ROLES

    role_keys = {role.model_key for role in ROLES + HUNTING_ROLES}
    assert hard_reads == {
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "POSTGRES_DSN",
        "KALI_MCP_URL",
    }
    assert required == sorted(hard_reads | role_keys | {preflight.CAPABILITY_OVERRIDES_KEY})


def _capability_env(preflight, value: str) -> dict[str, str]:
    import json

    return {
        "AAA": "one",
        preflight.CAPABILITY_OVERRIDES_KEY: value,
    }


def _capability_overlay(tmp_path: Path, preflight) -> Path:
    key = preflight.CAPABILITY_OVERRIDES_KEY
    return write(
        tmp_path / "overlay.yml",
        f"services:\n  agent:\n    environment:\n      {key}: ${{{key}:?{key} is required}}\n",
    )


def test_capability_override_correct_passes(tmp_path: Path, preflight) -> None:
    import json

    value = json.dumps(preflight.REQUIRED_CAPABILITY_OVERRIDES)
    example = write(tmp_path / ".env.example", f"AAA=one\n{preflight.CAPABILITY_OVERRIDES_KEY}={value}\n")
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = _capability_overlay(tmp_path, preflight)

    result = preflight.run(env, example, overlay)

    assert result.capability_findings == []
    assert result.exit_code == 0


def test_capability_override_absent_is_reported_and_fails(
    tmp_path: Path, preflight
) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = _capability_overlay(tmp_path, preflight)

    result = preflight.run(env, example, overlay)

    # The generic required check and the A6 correctness check both fire; the
    # finding names the override so the degradation is not silent.
    assert any(
        preflight.CAPABILITY_OVERRIDES_KEY in finding
        for finding in result.capability_findings
    )
    assert result.exit_code != 0


def test_capability_override_wrong_flags_is_reported_and_fails(
    tmp_path: Path, preflight
) -> None:
    import json

    wrong = json.dumps(
        {"opencode-go/deepseek-v4.1-flash": {"supports_structured_output": True,
                                             "supports_forced_tool_choice": True}}
    )
    example = write(
        tmp_path / ".env.example", f"AAA=one\n{preflight.CAPABILITY_OVERRIDES_KEY}={wrong}\n"
    )
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = _capability_overlay(tmp_path, preflight)

    result = preflight.run(env, example, overlay)

    assert any("supports_structured_output" in finding for finding in result.capability_findings)
    assert result.exit_code != 0


def test_capability_override_malformed_json_is_reported(
    tmp_path: Path, preflight
) -> None:
    example = write(
        tmp_path / ".env.example", f"AAA=one\n{preflight.CAPABILITY_OVERRIDES_KEY}=not json\n"
    )
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = _capability_overlay(tmp_path, preflight)

    result = preflight.run(env, example, overlay)

    assert any(
        preflight.CAPABILITY_OVERRIDES_KEY in finding
        for finding in result.capability_findings
    )
    assert result.exit_code != 0


def test_capability_override_extra_providers_are_allowed(
    tmp_path: Path, preflight
) -> None:
    import json

    value = json.dumps(
        {
            **preflight.REQUIRED_CAPABILITY_OVERRIDES,
            "other-provider/other-model": {"supports_structured_output": False},
        }
    )
    example = write(
        tmp_path / ".env.example", f"AAA=one\n{preflight.CAPABILITY_OVERRIDES_KEY}={value}\n"
    )
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = _capability_overlay(tmp_path, preflight)

    result = preflight.run(env, example, overlay)

    assert result.capability_findings == []
    assert result.exit_code == 0


def test_capability_override_not_checked_without_the_overlay_requirement(
    tmp_path: Path, preflight
) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    env = write(tmp_path / ".env", "AAA=one\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    result = preflight.run(env, example, overlay)

    assert result.capability_findings == []
    assert result.exit_code == 0


def test_real_example_carries_the_canonical_capability_override(preflight) -> None:
    example = preflight.parse_assignments(REPO_ROOT / ".env.example")
    overlay = REPO_ROOT / "eval" / "docker-compose.eval.yml"

    findings = preflight.capability_override_findings(example, overlay)

    assert findings == []


def _source_env_override(env_path: Path) -> subprocess.CompletedProcess[str]:
    """Source `env_path` under bash exactly as the production driver does.

    The driver runs `set -a; . "$EVAL_INSTANCES_ROOT/eval-server-1/.env";
    set +a` under `set -u`, so the file is a shell script as well as a compose
    env_file. A JSON value that bash brace-expands is split into words, the
    assignment degrades to a command prefix, and the variable stays UNSET in
    the host shell; a later `set -u` reference then aborts. This helper prints
    the sourced value so the test can assert it survived.
    """
    script = (
        "set -euo pipefail; set -a; . \"$1\"; set +a; "
        "printf '%s' \"$LLM_CAPABILITY_OVERRIDES\""
    )
    return subprocess.run(
        ["bash", "-c", script, "bash", str(env_path)],
        capture_output=True,
        text=True,
    )


def test_real_example_sources_cleanly_under_bash_set_u(
    tmp_path: Path, preflight
) -> None:
    """The whole committed `.env.example` must survive `bash` brace-expansion.

    This is the general falsifier for any unquoted JSON/brace value, not just
    the A6 override: source the real file exactly as the production driver
    does and read the override back as JSON.
    """
    env = tmp_path / ".env"
    env.write_bytes((REPO_ROOT / ".env.example").read_bytes())

    proc = _source_env_override(env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == preflight.REQUIRED_CAPABILITY_OVERRIDES


def test_preflight_fill_of_the_capability_override_is_byte_exact_and_shell_safe(
    tmp_path: Path, preflight
) -> None:
    """A missing override is repaired by the preflight, byte-exact and quotable.

    The preflight appends the `.env.example` value verbatim, so if the example
    carries the single-quoted spelling the appended line does too. Prove the
    appended line is byte-exact against the canonical JSON AND that sourcing
    the repaired `.env` under `set -u` yields that JSON.
    """
    example = REPO_ROOT / ".env.example"
    key = preflight.CAPABILITY_OVERRIDES_KEY
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            line
            for line in example.read_text(encoding="utf-8").splitlines()
            if not line.startswith(f"{key}=")
        )
        + "\n",
        encoding="utf-8",
    )
    overlay = REPO_ROOT / "eval" / "docker-compose.eval.yml"

    result = preflight.run(env, example, overlay)

    assert key in result.added  # missing -> repaired, not failed
    canonical = json.dumps(preflight.REQUIRED_CAPABILITY_OVERRIDES)
    expected_line = f"{key}='{canonical}'"
    body = env.read_text(encoding="utf-8")
    assert f"{expected_line}\n" in body  # byte-exact: canonical JSON, single-quoted

    proc = _source_env_override(env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == preflight.REQUIRED_CAPABILITY_OVERRIDES


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


def test_cli_missing_overlay_is_a_usage_error(
    tmp_path: Path, preflight, capsys: pytest.CaptureFixture[str]
) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\n")
    env = write(tmp_path / ".env", "AAA=one\n")

    rc = preflight.main(
        [str(env), "--example", str(example), "--overlay", str(tmp_path / "nope.yml")]
    )

    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_append_preserves_crlf_newlines(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\nBBB=two\n")
    env = tmp_path / ".env"
    env.write_bytes(b"AAA=mine\r\n")
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")

    result = preflight.run(env, example, overlay)

    assert result.added == ["BBB"]
    raw = env.read_bytes()
    assert b"BBB=two\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")  # no LF/CRLF mixing


def test_marker_block_is_not_repeated(tmp_path: Path, preflight) -> None:
    example = write(tmp_path / ".env.example", "AAA=one\nBBB=two\n")
    env = write(
        tmp_path / ".env",
        f"AAA=mine\n{preflight.MARKER}\nBBB=stale-removed-by-operator\n",
    )
    overlay = write(tmp_path / "overlay.yml", "services: {}\n")
    env.write_text(
        env.read_text(encoding="utf-8").replace("BBB=stale-removed-by-operator\n", ""),
        encoding="utf-8",
    )

    result = preflight.run(env, example, overlay)

    assert result.added == ["BBB"]
    assert env.read_text(encoding="utf-8").count(preflight.MARKER) == 1
