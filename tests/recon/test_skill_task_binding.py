"""#236 unit tier - the artifact-declared skill configuration at the binding seam.

`skill_agent_binding(role_id, task_skills=...)` is the ONE seam the artifacts'
declared skill lists ride: it resolves each declared name through the SAME store
seam the loader uses (the per-project bundle first, then the shared catalogue),
unions the survivors with the role baseline (`ROLE_SKILLS`), de-duplicates and
sorts them, and hands the result to the L1 index middleware - so each resolved
skill's frontmatter `description` is rendered into the agent's system prompt by
the existing `dynamic_prompt` + `render_skill_index` mechanism, never a new
rendering path.

These tests pin the policy the acceptance criteria state:

- the baseline is never displaced (an artifact adds, never removes);
- an identifier that resolves to nothing is warned and skipped - the ONE
  documented policy, never a silent drop;
- the meta family stays unadvertised and the count cap is the mechanism's job;
- a skill that exists only as a per-project bundle resolves and renders its own
  description (the store seam, project-first - #236's render-path criterion);
- a malformed declaration degrades to the baseline, never a raise;
- the union is de-duplicated and deterministically ordered, so the rendered
  index is byte-stable, and the context is rebuilt per binding (never a shared
  object mutated in place).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import SystemMessage

from polymerhus.app.llm import skills
from polymerhus.app.llm.skills import (
    ROLE_SKILLS,
    SkillStore,
    list_skills,
    skill_agent_binding,
    skill_meta,
)


class _FakeRequest:
    """The minimum `ModelRequest` surface the index middleware touches."""

    def __init__(self, system_prompt: str = "BASE", context=None):
        self.system_prompt = system_prompt
        self.runtime = SimpleNamespace(context=context)
        self.system_message = None

    def override(self, **kwargs):
        self.system_message = kwargs.get("system_message")
        return self


def _render(middleware, *, system_prompt="BASE", context=None) -> str:
    request = _FakeRequest(system_prompt, context)
    middleware.wrap_model_call(request, lambda req: "unused")
    assert isinstance(request.system_message, SystemMessage)
    return request.system_message.content


def _project_bundle(root, project_id: str, name: str, description: str) -> None:
    """Write one per-project bundle at its designed location under the
    `target-specific-procedure/` branch."""
    bundle = root / "target-specific-procedure" / project_id / name
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n"
        "metadata:\n  version: '1.0'\n---\n\n# Procedure\n",
        encoding="utf-8",
    )


# --- the union: baseline + artifact, de-duplicated and sorted -----------------


def test_task_skills_union_the_baseline_deduplicated_and_sorted(monkeypatch) -> None:
    from polymerhus.app.config import config

    monkeypatch.setattr(config, "PROJECT_ID", "proj-cfg")
    binding = skill_agent_binding(
        "pod_runner", task_skills=["steel-browser", "csrf", "lightrag-query", "ssrf"]
    )

    # The baseline (lightrag-query, steel-browser) is never displaced; the
    # declared names join it; the union is a sorted SET (the dedup drops the
    # repeated steel-browser and lightrag-query).
    assert binding.context["skills"] == [
        "csrf", "lightrag-query", "ssrf", "steel-browser",
    ]
    assert binding.context["project_id"] == "proj-cfg"


def test_an_empty_declaration_leaves_the_baseline_untouched() -> None:
    for declared in (None, [], ()):
        binding = skill_agent_binding("pod_runner", task_skills=declared)
        assert binding.context["skills"] == list(ROLE_SKILLS["pod_runner"])


def test_an_unresolvable_identifier_is_warned_and_skipped(caplog) -> None:
    """The ONE documented policy for an identifier that resolves to no skill:
    a runtime warn plus skip - never a silent drop."""
    with caplog.at_level(logging.WARNING, logger="polymerhus.app.llm.skills"):
        binding = skill_agent_binding(
            "pod_runner", task_skills=["ssrf", "no-such-skill"]
        )

    assert "ssrf" in binding.context["skills"]
    assert "no-such-skill" not in binding.context["skills"]
    assert any("no-such-skill" in record.message for record in caplog.records)


def test_the_meta_family_is_never_advertised_by_an_artifact(caplog) -> None:
    """An artifact is LLM-authored, so the meta exclusion is the mechanism's
    job: a declared meta-family name is refused loudly, never rendered."""
    with caplog.at_level(logging.WARNING, logger="polymerhus.app.llm.skills"):
        binding = skill_agent_binding(
            "pod_runner",
            task_skills=["meta/meta-usage-skill", "meta/meta-write-skill", "ssrf"],
        )

    assert binding.context["skills"] == ["lightrag-query", "ssrf", "steel-browser"]
    for name in ("meta/meta-usage-skill", "meta/meta-write-skill"):
        assert any(name in record.message for record in caplog.records)


def test_the_declared_set_is_capped_by_the_mechanism(caplog) -> None:
    """An artifact cannot grow the index without bound: names past the cap
    (deterministic sorted order) are dropped LOUDLY, never silently."""
    catalogue = [n for n in list_skills() if not skills.is_meta_skill(n)]
    declared = catalogue[: skills.MAX_TASK_SKILLS + 4]
    assert len(declared) > skills.MAX_TASK_SKILLS, "the fixture must exceed the cap"

    with caplog.at_level(logging.WARNING, logger="polymerhus.app.llm.skills"):
        binding = skill_agent_binding("pod_runner", task_skills=declared)

    added = [n for n in binding.context["skills"]
             if n not in ROLE_SKILLS["pod_runner"]]
    assert len(added) == skills.MAX_TASK_SKILLS
    assert added == sorted(declared)[: skills.MAX_TASK_SKILLS]
    dropped = sorted(declared)[skills.MAX_TASK_SKILLS:]
    assert any(all(name in record.message for name in dropped)
               for record in caplog.records), "the dropped tail must be named"


def test_unresolvable_names_never_consume_the_cap(caplog) -> None:
    """The cap applies to the RESOLVED additions: unresolvable junk is warned
    and skipped first, so it can never evict a valid declaration."""
    junk = [f"no-such-skill-{i}" for i in range(skills.MAX_TASK_SKILLS)]
    with caplog.at_level(logging.WARNING, logger="polymerhus.app.llm.skills"):
        binding = skill_agent_binding(
            "pod_runner", task_skills=[*junk, "ssrf"]
        )

    assert "ssrf" in binding.context["skills"]
    assert all(name not in binding.context["skills"] for name in junk)
    assert any("no-such-skill-0" in record.message for record in caplog.records)


def test_a_malformed_declaration_degrades_to_the_baseline() -> None:
    """A malformed artifact degrades its skill set, never crashes the binding:
    a bare string, a scalar, and a mixed list all resolve to what is valid."""
    for declared in ("ssrf", 123, object()):
        binding = skill_agent_binding("pod_runner", task_skills=declared)
        assert binding.context["skills"] == list(ROLE_SKILLS["pod_runner"])

    mixed = skill_agent_binding("pod_runner", task_skills=[None, 7, "ssrf", ""])
    assert mixed.context["skills"] == ["lightrag-query", "ssrf", "steel-browser"]


def test_a_declaration_against_an_exempt_role_is_refused_loudly(caplog) -> None:
    """The roster's exemption is a considered capability-minimalism decision,
    not artifact-overridable: the declaration is warned and ignored."""
    with caplog.at_level(logging.WARNING, logger="polymerhus.app.llm.skills"):
        binding = skill_agent_binding("hunting_orchestrator", task_skills=["ssrf"])

    assert binding.tools == []
    assert binding.middleware == []
    assert binding.context == {}
    assert any("exempt" in record.message for record in caplog.records)


# --- the rendered index: the descriptions the artifacts selected --------------


def test_an_artifact_named_skill_renders_verbatim_with_the_baseline() -> None:
    binding = skill_agent_binding("pod_runner", task_skills=["ssrf"])

    rendered = _render(binding.middleware[0], context=binding.context)

    assert f"- ssrf: {skill_meta('ssrf')['description']}" in rendered
    for name in ROLE_SKILLS["pod_runner"]:
        assert f"- {name}: {skill_meta(name)['description']}" in rendered


def test_an_artifact_named_suite_leaf_renders_verbatim() -> None:
    """The mount replacement: a nested suite leaf (level 2) is an artifact-legal
    name and resolves through the live catalogue like any flat skill."""
    binding = skill_agent_binding(
        "pod_runner", task_skills=["sql-injection-second-order"]
    )

    assert "sql-injection-second-order" in binding.context["skills"]
    rendered = _render(binding.middleware[0], context=binding.context)
    assert (
        f"- sql-injection-second-order: "
        f"{skill_meta('sql-injection-second-order')['description']}" in rendered
    )


def test_a_project_bundle_skill_named_by_an_artifact_renders(tmp_path) -> None:
    """#236's render-path criterion: a skill that exists ONLY as a per-project
    bundle resolves through the SAME store seam the loader uses (project
    first) and renders its own frontmatter description - never a blank or
    silently absent line."""
    store = SkillStore(root_dir=tmp_path)
    _project_bundle(tmp_path, "proj-1", "authn", "Authenticate against this target.")
    skills.clear_cache()

    binding = skill_agent_binding(
        "pod_runner", project_id="proj-1", store=store, task_skills=["authn"]
    )

    assert "authn" in binding.context["skills"]
    rendered = _render(binding.middleware[0], context=binding.context)
    assert "- authn: Authenticate against this target." in rendered


def test_a_project_bundle_that_is_unreadable_is_warned_not_rendered_blank(
    tmp_path, caplog
) -> None:
    """A declared project skill whose bundle is NOT at its designed location
    resolves nothing: the binding warns and skips it, so no blank line can
    reach the index."""
    store = SkillStore(root_dir=tmp_path)
    (tmp_path / "target-specific-procedure" / "proj-1" / "authn").mkdir(parents=True)
    # no SKILL.md: the bundle directory exists but resolves no frontmatter

    with caplog.at_level(logging.WARNING, logger="polymerhus.app.llm.skills"):
        binding = skill_agent_binding(
            "pod_runner", project_id="proj-1", store=store, task_skills=["authn"]
        )

    assert "authn" not in binding.context["skills"]
    rendered = _render(binding.middleware[0], context=binding.context)
    assert "authn" not in rendered
    assert any("authn" in record.message for record in caplog.records)


def test_the_rendered_index_is_byte_stable_across_bindings_and_turns() -> None:
    """The prompt-cache prefix (ADR A5): the same declaration renders
    byte-identical across the turns of one hunt, and the context is rebuilt per
    binding rather than shared and mutated in place."""
    first = skill_agent_binding("pod_runner", task_skills=["ssrf", "csrf"])
    second = skill_agent_binding("pod_runner", task_skills=["csrf", "ssrf"])

    assert first.context is not second.context
    assert first.context["skills"] == second.context["skills"]
    render_a = _render(first.middleware[0], context=first.context)
    render_b = _render(second.middleware[0], context=second.context)
    render_a2 = _render(first.middleware[0], context=first.context)
    assert render_a == render_b == render_a2

    # A caller mutating one binding's context never leaks into another's.
    first.context["skills"].append("mutated")
    assert "mutated" not in second.context["skills"]


def test_the_auth_wrapper_forwards_the_artifact_declaration() -> None:
    """The four hunting agents bind through `auth_capable_binding`: the
    declaration must reach the ONE binding seam, never be re-implemented."""
    from polymerhus.app.auth.seams import auth_capable_binding

    binding = auth_capable_binding("pod_triager", task_skills=["ssrf"])

    assert "ssrf" in binding.context["skills"]
    # The auth wrapper appends its own `authn` skill to the union it received.
    assert binding.context["skills"] == ["lightrag-query", "ssrf", "authn"]
    assert [t.name for t in binding.tools][:2] == [
        "load_skill", "record_skill_lesson",
    ]


# --- import safety (CODING_STANDARD section 6) --------------------------------


def test_importing_the_touched_modules_performs_no_io():
    """The touched modules import with a scrubbed environment: the five keys
    `polymerhus.app.config` already demands at import (a pre-existing import-time
    config demand of the app layer, not of these modules) and NOTHING else - no
    LLM role vars, no gateway URL, no data-root override."""
    import os
    import subprocess
    import sys

    modules = [
        "polymerhus.app.llm.skills",
        "polymerhus.app.auth.seams",
        "polymerhus.attack.hunting.hunt_orchestrator",
        "polymerhus.attack.hunting.hunting_agent",
        "polymerhus.attack.hunting.surfer",
        "polymerhus.attack.hunting.pod.types",
        "polymerhus.attack.hunting.pod.llm",
        "polymerhus.attack.hunting.pod.graph",
        "polymerhus.attack.hunting.pod.agents",
    ]
    scrubbed = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": "src",
        "NEO4J_URI": "bolt://unused",
        "NEO4J_USER": "unused",
        "NEO4J_PASSWORD": "unused",
        "POSTGRES_DSN": "postgresql://unused",
        "KALI_MCP_URL": "http://unused",
    }
    completed = subprocess.run(
        [sys.executable, "-c",
         "; ".join(f"import {m}" for m in modules) + "; print('import-ok')"],
        capture_output=True,
        text=True,
        env=scrubbed,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "import-ok" in completed.stdout


def test_a_malformed_artifact_field_is_refused_by_the_schema() -> None:
    """The two artifact schemas round-trip a declared skill list; a malformed
    value is a schema violation (the dispatch refuses it, never a crash)."""
    import pydantic

    from polymerhus.attack.hunting.hunt_orchestrator import HuntConfig
    from polymerhus.attack.hunting.pod.types import TestImplementationSpec

    config = HuntConfig.model_validate({
        "hunt_id": "h1", "unit_id": "Service:a", "fault_class": "CWE-1",
        "prompt_template": {"rationale": "r"},
        "skills": ["ssrf", "csrf"],
    })
    assert config.skills == ["ssrf", "csrf"]

    spec = TestImplementationSpec(**{"skills": ["ssrf"]})
    assert spec.skills == ["ssrf"]

    with pytest.raises(pydantic.ValidationError):
        HuntConfig.model_validate({
            "hunt_id": "h1", "unit_id": "Service:a", "fault_class": "CWE-1",
            "prompt_template": {"rationale": "r"},
            "skills": "ssrf",  # a bare string is not a list of names
        })
    with pytest.raises(pydantic.ValidationError):
        TestImplementationSpec(**{"skills": 7})
