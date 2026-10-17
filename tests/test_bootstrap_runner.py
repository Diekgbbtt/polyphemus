"""Unit tier: the external-bootstrap runner (`tools/bootstrap/runner`), part 1.

The runner is the mechanised form of the mined external-bootstrap run: it drives
one opencode worker session per target through the authn then L1 phases, gates
each phase with the real shape validator, repairs a red gate a bounded number of
times, verifies teardown from the docker engine, and persists a resumable state.

This file covers the two fast, pure seams: the wrapper builders (`wrappers`) and
the phase gate (`gates`). The environment drivers and the harness adapter live in
`test_bootstrap_runner_env.py`; the orchestration loop in
`test_bootstrap_runner_loop.py`; the CLI, the run config, and the state in
`test_bootstrap_runner_cli.py` and `test_bootstrap_runner_state.py`. No test in
this module touches the network, a model, ssh, or docker.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_path(rel: str) -> None:
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


# The entry point's own sys.path contract (run_external_bootstrap.py).
_on_path("tools/bootstrap")
_on_path("eval")
_on_path("src")

from runner import gates, wrappers  # noqa: E402

PROMPT_TEXT = "PHASE PROMPT BODY: deploy then author, following the meta-skill.\n"
CONTRACT_TEXT = "CONTRACT BODY: three sections, laid out exactly so.\n"
META_TEXT = "META-SKILL BODY: P0 to P6.\n"


def _sources(**overrides) -> wrappers.WrapperSources:
    base = dict(
        prompt_path="tools/bootstrap/prompts/data-dep-authn.md",
        prompt_text=PROMPT_TEXT,
        contract_path="tools/bootstrap/DATA-DEPENDENCIES.md",
        contract_text=CONTRACT_TEXT,
        meta_skill_path="skills/meta/authn-skill-writing/SKILL.md",
        meta_skill_text=META_TEXT,
        validator_path="tools/bootstrap/validate_data_dependencies.py",
        validator_invocation=(
            "cd /wt && PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py "
            "--auth-only --staging /wt/eval/data-dependencies shop"
        ),
    )
    base.update(overrides)
    return wrappers.WrapperSources(**base)


def _facts(**overrides) -> wrappers.WrapperFacts:
    base = dict(
        target="shop",
        base_url="http://198.51.100.7:48287/",
        web_root="/root/WebExploitBench",
        worktree="/wt",
        staging="/wt/eval/data-dependencies",
        target_dir="/root/WebExploitBench/shop",
        lifecycle_hint=("/root/wb ps shop",),
        kbs_dir="/wt/eval/data/webexploitbench/shop",
    )
    base.update(overrides)
    return wrappers.WrapperFacts(**base)


# --- wrappers: substitution completeness ------------------------------------


def test_authn_wrapper_cites_prompt_contract_and_meta_skill():
    text = wrappers.authn_wrapper(_facts(), _sources())
    assert "tools/bootstrap/prompts/data-dep-authn.md" in text
    assert "tools/bootstrap/DATA-DEPENDENCIES.md" in text
    assert "skills/meta/authn-skill-writing/SKILL.md" in text
    # The carrier text itself rides along, so a worker that cannot resolve the
    # cited path still reads the same procedure.
    assert PROMPT_TEXT.strip() in text
    assert CONTRACT_TEXT.strip() in text
    assert META_TEXT.strip() in text


def test_authn_wrapper_carries_every_substitution():
    text = wrappers.authn_wrapper(_facts(), _sources())
    for token, value in (
        ("<target>", "shop"),
        ("<web_root>", "/root/WebExploitBench"),
        ("<worktree>", "/wt"),
        ("<staging>", "/wt/eval/data-dependencies"),
        ("<base_url>", "http://198.51.100.7:48287/"),
        ("<target_dir>", "/root/WebExploitBench/shop"),
    ):
        assert f"`{token}` -> {value}" in text


def test_authn_wrapper_orders_the_lifecycle_override():
    text = wrappers.authn_wrapper(_facts(), _sources())
    assert "ALREADY deployed and ready at http://198.51.100.7:48287/" in text
    assert "do NOT deploy" in text
    assert "`/root/wb ps shop`" in text
    assert "do NOT tear the target down" in text


def test_wrappers_forbid_the_sealed_paths():
    for build in (wrappers.authn_wrapper, wrappers.l1_wrapper):
        text = build(_facts(), _sources())
        assert "/root/WebExploitBench/shop/vulnerability/" in text
        assert "/root/WebExploitBench/shop/challenge.json" in text
        assert "never read" in text
        assert "No ground-truth path is handed to you" in text


def test_wrappers_carry_the_exact_validator_command():
    for build in (wrappers.authn_wrapper, wrappers.l1_wrapper):
        text = build(_facts(), _sources())
        assert (
            "PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py "
            "--auth-only --staging /wt/eval/data-dependencies shop"
        ) in text


def test_wrappers_carry_the_no_secrets_report_clause():
    for build in (wrappers.authn_wrapper, wrappers.l1_wrapper):
        text = build(_facts(), _sources())
        assert "No secrets." in text
        assert "<= 30 lines" in text


def test_wrappers_pin_the_overview_contract_reminders():
    for build in (wrappers.authn_wrapper, wrappers.l1_wrapper):
        text = build(_facts(), _sources())
        assert "SINGLE TOKEN" in text
        assert "NEVER a host, IP, or port" in text
        assert "At least 2 journeys" in text
        assert "250-word" in text
        assert "path-free" in text


def test_authn_wrapper_keeps_the_phase_boundary():
    text = wrappers.authn_wrapper(_facts(), _sources())
    assert "Do NOT author the L1 surface" in text
    assert "/wt/eval/data-dependencies/shop/" in text
    assert "persisted session snapshot" in text


def test_l1_wrapper_keeps_the_session_and_phase_boundary():
    text = wrappers.l1_wrapper(_facts(), _sources())
    assert "phase-1 session" in text
    assert "Do NOT mutate `auth/`" in text
    assert "Never crawl the authenticated surface anonymously" in text
    assert "Write the L1 artifacts into `<target_dir>`." in text


def test_l1_wrapper_names_the_kb_output_root_when_given_one():
    text = wrappers.l1_wrapper(
        _facts(), _sources(), output_dir="/wt/eval/data/webexploitbench/shop"
    )
    assert "to `/wt/eval/data/webexploitbench/shop`." in text
    assert "Do NOT mutate `auth/`" in text


def test_wrappers_are_pure_functions_of_their_arguments():
    facts = _facts()
    sources = _sources()
    assert wrappers.authn_wrapper(facts, sources) == wrappers.authn_wrapper(facts, sources)
    assert "shop" in wrappers.authn_wrapper(_facts(target="shop"), sources)
    assert "`blog`" in wrappers.authn_wrapper(_facts(target="blog"), sources)


# --- gates: mode selection and report parsing -------------------------------


def test_auth_only_gate_command_pins_the_documented_invocation():
    argv = gates.validator_argv(
        python="python3",
        validator=Path("/wt/tools/bootstrap/validate_data_dependencies.py"),
        target="shop",
        mode=gates.AUTH_ONLY,
        staging=Path("/wt/eval/data-dependencies"),
    )
    assert argv == (
        "python3",
        "/wt/tools/bootstrap/validate_data_dependencies.py",
        "--auth-only",
        "--staging",
        "/wt/eval/data-dependencies",
        "shop",
    )


def test_full_gate_command_targets_the_kb_dir_with_staging():
    argv = gates.validator_argv(
        python="python3",
        validator=Path("/wt/tools/bootstrap/validate_data_dependencies.py"),
        target="white-jotter",
        mode=gates.FULL,
        staging=Path("/wt/eval/data-dependencies"),
        target_dir=Path("/wt/eval/data/webexploitbench/white-jotter"),
    )
    assert argv[-3:] == (
        "--staging",
        "/wt/eval/data-dependencies",
        "/wt/eval/data/webexploitbench/white-jotter",
    )
    assert "--auth-only" not in argv
    assert "--l1-only" not in argv


def test_gate_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        gates.validator_argv(
            python="python3", validator=Path("v.py"), target="t", mode="wat"
        )


def test_parse_report_reads_ok_and_fail_lines():
    ok_out = "OK   eval/data/webexploitbench/shop\n\n1/1 target(s) valid\n"
    assert gates.parse_report(ok_out, "shop") is True
    fail_out = (
        "FAIL eval/data/webexploitbench/shop\n"
        "  [overview] Overview: 'domain' missing\n"
        "\n0/1 target(s) valid\n"
    )
    assert gates.parse_report(fail_out, "shop") is False


def test_parse_report_matches_the_auth_only_bare_target_name():
    assert gates.parse_report("OK   shop\n\n1/1 target(s) valid\n", "shop") is True


def test_parse_report_treats_a_missing_mention_as_not_ok():
    assert gates.parse_report("Traceback (most recent call last):\n", "shop") is None


def test_validator_gate_does_not_pass_on_a_nonzero_exit_with_an_ok_line(tmp_path):
    """Defence in depth: an exit code that disagrees with the report is a FAIL."""
    script = tmp_path / "fake_validator.py"
    script.write_text("print('OK   shop')\nraise SystemExit(1)\n", encoding="utf-8")
    gate = gates.ValidatorGate(
        validator=script,
        staging=tmp_path / "staging",
        kbs=tmp_path / "kbs",
        worktree=tmp_path,
        python=sys.executable,
    )
    result = gate.run("shop", gates.AUTH_ONLY)
    assert result.ok is False
    assert result.command[0] == sys.executable


def test_validator_gate_parses_the_real_validator_over_a_fixture(tmp_path):
    """The real validator, in auth-only mode, over a crafted good/bad target."""
    project = tmp_path / "staging" / "shop" / "auth"
    project.mkdir(parents=True)
    (project / "overview.yaml").write_text("mechanism: none\n", encoding="utf-8")
    (project / "credentials.yaml").write_text("accounts: {}\n", encoding="utf-8")
    gate = gates.ValidatorGate(
        validator=REPO_ROOT / "tools" / "bootstrap" / "validate_data_dependencies.py",
        staging=tmp_path / "staging",
        kbs=tmp_path / "kbs",
        worktree=REPO_ROOT,
        python=sys.executable,
    )
    clean = gate.run("shop", gates.AUTH_ONLY)
    assert clean.ok, clean.output
    assert "OK" in clean.output

    (project / "credentials.yaml").write_text("accounts: 5\n", encoding="utf-8")
    broken = gate.run("shop", gates.AUTH_ONLY)
    assert not broken.ok
    assert "credentials.yaml" in broken.failure_text

    # full mode reads the KB dir: absent, so the gate is red for a real reason.
    full = gate.run("shop", gates.FULL)
    assert not full.ok
    assert "operator_kb.md" in full.output


def test_validator_env_puts_src_first_on_pythonpath():
    env = gates.validator_env(Path("/wt"), {"PYTHONPATH": "/elsewhere"})
    assert env["PYTHONPATH"].split(":") == ["/wt/src", "/elsewhere"]
