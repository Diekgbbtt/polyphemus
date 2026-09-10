"""#222 unit tier - the skill data-section convention (machine-readable frontmatter).

Each test names the behaviour it pins. The data section is the contract
`load_skill` indexes, validates, and reports: every `skills/**/SKILL.md`
carries `name`, `description`, `version`, and `inputs` in its YAML frontmatter.
"""
import pytest

from polymerhus.recon.domain import skills


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


def _write_skill(root, name, text):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")


# --- AST-222-02: validate_skill judges conformance ---

def test_validate_skill_accepts_conforming_skill(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "demo/skill",
        "---\nname: demo-skill\ndescription: Does demo things.\n"
        "version: '1.0'\ninputs:\n  - name: tool_output\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    assert skills.validate_skill("demo/skill") == []


def test_validate_skill_rejects_missing_keys(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "legacy/skill",
        "---\nname: legacy-skill\ndescription: Predates the convention.\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    errors = skills.validate_skill("legacy/skill")
    assert any("version" in e for e in errors)
    assert any("inputs" in e for e in errors)


def test_validate_skill_rejects_absent_data_section(tmp_path, monkeypatch):
    _write_skill(tmp_path, "bare/skill", "# Body without any frontmatter\n")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    errors = skills.validate_skill("bare/skill")
    assert errors  # a skill with no data section is non-conforming


def test_validate_skill_never_raises_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)  # empty dir

    assert skills.validate_skill("does/not/exist")  # errors, never a raise


# --- AST-222-03: list_skills indexes the catalogue ---

def test_list_skills_returns_sorted_loader_paths(tmp_path, monkeypatch):
    _write_skill(tmp_path, "b/skill", "# B\n")
    _write_skill(tmp_path, "a/deep/skill", "# A\n")
    (tmp_path / "not-a-skill").mkdir()
    (tmp_path / "not-a-skill" / "notes.md").write_text("no SKILL.md here\n")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    assert skills.list_skills() == ["a/deep/skill", "b/skill"]


# --- AST-222-04: build_load_skill_tool is the agent-callable loader ---

def test_load_skill_tool_returns_skill_for_identical_body(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "demo/skill",
        "---\nname: demo-skill\ndescription: D.\nversion: '1.0'\ninputs: []\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    tool = skills.build_load_skill_tool()
    assert tool.name == "load_skill"
    out = tool.invoke({"name": "demo/skill"})
    assert out == skills.skill_for("demo/skill")
    assert out.startswith("# Body")  # frontmatter stripped, same as skill_for


def test_load_skill_tool_refresh_rereads_after_disk_change(tmp_path, monkeypatch):
    _write_skill(tmp_path, "demo/skill",
                 "---\nname: d\ndescription: D.\nversion: '1.0'\ninputs: []\n---\n\nv1\n")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    tool = skills.build_load_skill_tool()
    assert tool.invoke({"name": "demo/skill"}) == "v1\n"
    (tmp_path / "demo" / "skill" / "SKILL.md").write_text("v2\n", encoding="utf-8")
    assert tool.invoke({"name": "demo/skill"}) == "v1\n"  # cached
    assert tool.invoke({"name": "demo/skill", "refresh": True}) == "v2\n"


def test_load_skill_tool_degrades_fail_open_on_unknown_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)  # empty dir

    out = skills.build_load_skill_tool().invoke({"name": "does/not/exist"})
    assert out == ""  # same fail-open as skill_for's default fallback


def test_load_skill_description_carries_contract_verbatim():
    assert skills.SKILL_LOAD_CONTRACT in skills.build_load_skill_tool().description


# --- AST-222-05: the steel skill is single-sourced through the loader ---

def test_steel_skill_readers_delegate_to_skill_for():
    from polymerhus.recon.crawl import crawl_agent, crawl_agentic

    skills.clear_cache()
    expected = skills.skill_for("recon/crawler/steel-crawl")
    assert expected  # the migrated skill exists under skills/
    assert not expected.startswith("---")
    assert crawl_agentic._load_steel_crawl_skill() == expected
    assert crawl_agent._load_skill() == expected
    assert "Steel Agentic Crawl" in expected
    assert skills.validate_skill("recon/crawler/steel-crawl") == []


# --- AST-222-06: every repo skill conforms (the #222 convention criterion) ---

# --- AST-222-06: every repo skill conforms (the #222 convention criterion) ---

def test_every_repo_skill_conforms_to_data_section():
    names = skills.list_skills()
    assert names  # the catalogue is non-empty: a vacuous pass proves nothing
    bad = {n: skills.validate_skill(n) for n in names}
    bad = {n: errors for n, errors in bad.items() if errors}
    assert not bad, f"non-conforming skills: {bad}"


# --- AST-222-07: a session agent loads a skill at runtime through the tool ---

def test_session_agent_loads_skill_through_tool_at_phase_entry():
    """Acceptance 1 (#222): a session agent loads a skill by name at runtime
    through the tool. The scripted phase-entry turn calls `load_skill`; the
    delivered body is byte-identical to the shared loader (single-loader
    discipline holds inside the agent loop)."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.app.llm.session import run_session_turn

    class _ScriptedToolModel(BaseChatModel):
        replies: list = []

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            msg = self.replies.pop(0)
            return ChatResult(generations=[ChatGeneration(message=msg)])

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    replies = [
        AIMessage(content="", tool_calls=[{
            "name": "load_skill",
            "args": {"name": "recon/crawler/steel-crawl"},
            "id": "c1",
        }]),
        AIMessage(content="phase ready"),
    ]
    turn = run_session_turn(
        "crawler", "run9:crawler",
        [HumanMessage(content="phase entry: load the crawl discipline")],
        checkpointer=InMemorySaver(),
        tools=[skills.build_load_skill_tool()],
        model_factory=lambda role: _ScriptedToolModel(replies=replies),
        observe=False,
    )
    assert turn.content == "phase ready"
    bodies = [m.content for m in turn.messages if isinstance(m, ToolMessage)]
    assert bodies  # the tool actually executed in the loop
    assert bodies[0] == skills.skill_for("recon/crawler/steel-crawl")
    assert "Steel Agentic Crawl" in bodies[0]


def test_session_agent_without_tool_binding_cannot_load_skill():
    """The gating half: with no `load_skill` binding on the turn, the same
    phase-entry call loads nothing - offering the tool at phase entry is what
    enables runtime loading (convention gate, #222)."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.app.llm.session import run_session_turn

    class _ScriptedToolModel(BaseChatModel):
        replies: list = []

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            msg = self.replies.pop(0)
            return ChatResult(generations=[ChatGeneration(message=msg)])

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    replies = [
        AIMessage(content="", tool_calls=[{
            "name": "load_skill",
            "args": {"name": "recon/crawler/steel-crawl"},
            "id": "c1",
        }]),
        AIMessage(content="phase ready"),
    ]
    turn = run_session_turn(
        "crawler", "run9:crawler",
        [HumanMessage(content="phase entry: load the crawl discipline")],
        checkpointer=InMemorySaver(),
        tools=(),
        model_factory=lambda role: _ScriptedToolModel(replies=replies),
        observe=False,
    )
    bodies = [m.content for m in turn.messages if isinstance(m, ToolMessage)]
    assert not any("Steel Agentic Crawl" in b for b in bodies)

# --- AST-222-01: skill_meta reads the data section ---

def test_skill_meta_returns_data_section(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "demo/skill",
        "---\nname: demo-skill\ndescription: Does demo things.\n"
        "version: '1.0'\ninputs:\n  - name: tool_output\n"
        "    description: The completed tool run.\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    meta = skills.skill_meta("demo/skill")
    assert meta == {
        "name": "demo-skill",
        "description": "Does demo things.",
        "version": "1.0",
        "inputs": [{"name": "tool_output", "description": "The completed tool run."}],
    }
