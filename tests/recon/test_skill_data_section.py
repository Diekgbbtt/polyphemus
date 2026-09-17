"""#222 unit tier - the skill data-section convention (spec frontmatter).

Each test names the behaviour it pins. The data section is the contract
`load_skill` indexes, validates, and reports: every `skills/<name>/SKILL.md`
carries Agent Skills spec frontmatter - `name` == the skill directory,
`description` = what + when, `metadata` string map carrying `version`.
"""
import pytest

from polymerhus.app.llm import skills


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
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: Does demo things.\n"
        "metadata:\n  version: '1.0'\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    assert skills.validate_skill("demo-skill") == []


def test_validate_skill_rejects_missing_keys(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "legacy-skill",
        "---\nname: legacy-skill\ndescription: Predates the convention.\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    errors = skills.validate_skill("legacy-skill")
    assert any("metadata" in e for e in errors)


def test_validate_skill_rejects_name_directory_mismatch(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "real-dir",
        "---\nname: other-name\ndescription: D.\n"
        "metadata:\n  version: '1.0'\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    errors = skills.validate_skill("real-dir")
    assert any("must equal the skill directory" in e for e in errors)


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
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: D.\nmetadata:\n  version: '1.0'\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    tool = skills.build_load_skill_tool()
    assert tool.name == "load_skill"
    out = tool.invoke({"name": "demo-skill"})
    assert out == skills.skill_for("demo-skill")
    assert out.startswith("# Body")  # frontmatter stripped, same as skill_for


def test_load_skill_tool_refresh_rereads_after_disk_change(tmp_path, monkeypatch):
    _write_skill(tmp_path, "demo-skill",
                 "---\nname: d\ndescription: D.\nmetadata:\n  version: '1.0'\n---\n\nv1\n")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    tool = skills.build_load_skill_tool()
    assert tool.invoke({"name": "demo-skill"}) == "v1\n"
    (tmp_path / "demo-skill" / "SKILL.md").write_text("v2\n", encoding="utf-8")
    assert tool.invoke({"name": "demo-skill"}) == "v1\n"  # cached
    assert tool.invoke({"name": "demo-skill", "refresh": True}) == "v2\n"


def test_load_skill_tool_degrades_fail_open_on_unknown_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)  # empty dir

    out = skills.build_load_skill_tool().invoke({"name": "does/not/exist"})
    assert out == ""  # same fail-open as skill_for's default fallback


def test_load_skill_description_carries_contract_verbatim():
    assert skills.SKILL_LOAD_CONTRACT in skills.build_load_skill_tool().description


# --- AST-222-05: the steel skill is read directly from the crawl prompts/ dir ---

def test_steel_skill_readers_serve_the_module_prompt():
    from polymerhus.recon.crawl import crawl_agent, crawl_agentic

    body = crawl_agentic._load_steel_crawl_skill()
    assert body  # the steel-crawl role prompt ships with the crawl module
    assert not body.startswith("---")  # plain .md, no frontmatter
    assert crawl_agent._load_skill() == body  # both readers, one prompt file
    assert "Steel Agentic Crawl" in body


# --- AST-222-06: every repo skill conforms (the #222 convention criterion) ---

def test_every_repo_skill_conforms_to_data_section():
    names = skills.list_skills()
    assert names  # the catalogue is non-empty: a vacuous pass proves nothing
    bad = {n: skills.validate_skill(n) for n in names}
    bad = {n: errors for n, errors in bad.items() if errors}
    assert not bad, f"non-conforming skills: {bad}"


# --- AST-222-07: a session agent loads a skill at runtime through the tool ---

def test_session_agent_loads_skill_through_tool_at_phase_entry(tmp_path, monkeypatch):
    """Acceptance 1 (#222): a session agent loads a skill by name at runtime
    through the tool. The scripted phase-entry turn calls `load_skill`; the
    delivered body is byte-identical to the shared loader (single-loader
    discipline holds inside the agent loop)."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.app.llm.session import run_session_turn

    _write_skill(
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: D.\nmetadata:\n  version: '1.0'\n---\n\n# Phase discipline\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

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
            "args": {"name": "demo-skill"},
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
    assert bodies[0] == skills.skill_for("demo-skill")
    assert "Phase discipline" in bodies[0]


def test_session_agent_without_tool_binding_cannot_load_skill(tmp_path, monkeypatch):
    """The gating half: with no `load_skill` binding on the turn, the same
    phase-entry call loads nothing - offering the tool at phase entry is what
    enables runtime loading (convention gate, #222)."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.app.llm.session import run_session_turn

    _write_skill(
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: D.\nmetadata:\n  version: '1.0'\n---\n\n# Phase discipline\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)
    marker = skills.skill_for("demo-skill")
    assert "Phase discipline" in marker

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
            "args": {"name": "demo-skill"},
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
    assert not any("Phase discipline" in b for b in bodies)

# --- AST-222-01: skill_meta reads the data section ---

def test_skill_meta_returns_data_section(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: Does demo things.\n"
        "metadata:\n  version: '1.0'\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    meta = skills.skill_meta("demo-skill")
    assert meta == {
        "name": "demo-skill",
        "description": "Does demo things.",
        "metadata": {"version": "1.0"},
    }

# --- AST-222-08: the L1 skill index (Q3) ---

def test_render_skill_index_lists_bound_skills_sorted(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "b-skill",
        "---\nname: b-skill\ndescription: B does things.\nmetadata:\n  version: '1.0'\n---\n\n# B\n",
    )
    _write_skill(
        tmp_path, "a-skill",
        "---\nname: a-skill\ndescription: A does things.\nmetadata:\n  version: '1.0'\n---\n\n# A\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    index = skills.render_skill_index(["b-skill", "a-skill"])
    assert skills.SKILL_INDEX_HEADER in index
    assert index.index("- a-skill: A does things.") < index.index("- b-skill: B does things.")


def test_render_skill_index_skips_unknown_skills_fail_open(tmp_path, monkeypatch):
    _write_skill(
        tmp_path, "real-skill",
        "---\nname: real-skill\ndescription: Real.\nmetadata:\n  version: '1.0'\n---\n\n# R\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    index = skills.render_skill_index(["real-skill", "ghost-skill"])
    assert "- real-skill: Real." in index
    assert "ghost-skill" not in index  # stale binding never breaks the render


def test_index_middleware_passes_base_through_without_bound_skills():
    from langchain_core.language_models import BaseChatModel

    mw = skills.skill_index_middleware()
    import asyncio

    class _M(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult
            from langchain_core.messages import AIMessage
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def _run():
        called = {}

        async def _handler(request):
            called["system"] = request.system_message.content if request.system_message else None
            from langchain.agents.middleware.types import ModelResponse
            from langchain_core.messages import AIMessage
            return ModelResponse(result=[AIMessage(content="ok")])

        from langchain.agents.middleware.types import ModelRequest
        req = ModelRequest(
            model=_M(), messages=[], system_prompt="base prompt",
            state={"messages": []},
            runtime=type("R", (), {"context": {}})(),
        )
        await mw.wrap_model_call(req, _handler)
        return called["system"]

    assert asyncio.run(_run()) == "base prompt"


def test_index_middleware_appends_bound_skills_to_system_message(tmp_path, monkeypatch):
    from polymerhus.app.llm import skills as sk

    _write_skill(
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: Demo discipline.\nmetadata:\n  version: '1.0'\n---\n\n# Body\n",
    )
    monkeypatch.setattr(sk, "_SKILLS_ROOT", tmp_path)
    mw = sk.skill_index_middleware()
    import asyncio

    from langchain_core.language_models import BaseChatModel

    class _M(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult
            from langchain_core.messages import AIMessage
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def _run():
        seen = {}

        async def _handler(request):
            seen["system"] = request.system_message.content if request.system_message else None
            from langchain.agents.middleware.types import ModelResponse
            from langchain_core.messages import AIMessage
            return ModelResponse(result=[AIMessage(content="ok")])

        from langchain.agents.middleware.types import ModelRequest
        req = ModelRequest(
            model=_M(), messages=[],
            state={"messages": []},
            runtime=type("R", (), {"context": {"skills": ["demo-skill", "ghost"]}})(),
        )
        await mw.wrap_model_call(req, _handler)
        return seen["system"]

    system = asyncio.run(_run())
    assert "- demo-skill: Demo discipline." in system
    assert "ghost" not in system


def test_session_turn_carries_bound_skill_index_to_model(tmp_path, monkeypatch):
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.app.llm.session import run_session_turn

    _write_skill(
        tmp_path, "demo-skill",
        "---\nname: demo-skill\ndescription: Demo discipline.\nmetadata:\n  version: '1.0'\n---\n\n# Body\n",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)
    received = []

    class _RecordingModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            received.extend(messages)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

        def bind_tools(self, tools, **kwargs):
            return self

    run_session_turn(
        "crawler", "run9:index",
        [HumanMessage(content="go")],
        checkpointer=InMemorySaver(),
        middleware=[skills.skill_index_middleware()],
        context={"skills": ["demo-skill"]},
        model_factory=lambda role: _RecordingModel(),
        observe=False,
    )
    systems = [m.content for m in received if isinstance(m, SystemMessage)]
    assert systems  # the middleware composed a system message from the None base
    assert any("- demo-skill: Demo discipline." in s for s in systems)


# --- project-authored skills in the L1 index (the authn bundle gate) ---

def _write_project_bundle(root, project_id, name, description):
    """Write a per-project bundle FILE directly (the external author's output),
    NOT through `write_skill` - a project-authored skill such as `authn` has no
    bootstrapped catalogue metadata, so it lands as a plain file at the designed
    data-dir location."""
    bundle = root / project_id / "skills" / name / "SKILL.md"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  version: '1.0'\n"
        f"---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_render_skill_index_collects_a_project_skill_only_when_its_bundle_exists(
    tmp_path,
):
    store = skills.SkillStore(root_dir=tmp_path / "data")
    _write_project_bundle(
        tmp_path / "data", "proj-1", "authn", "Per-project authentication procedure."
    )

    collected = skills.render_skill_index(
        ["authn"], project_id="proj-1", store=store
    )
    assert "- authn: Per-project authentication procedure." in collected

    # A project with no bundle at the designed location collects nothing.
    assert "authn" not in skills.render_skill_index(
        ["authn"], project_id="proj-2", store=store
    )
    # Catalogue-only resolution never invents a project-only skill either.
    assert "authn" not in skills.render_skill_index(["authn"], store=store)


def test_index_middleware_renders_the_project_authn_frontmatter(tmp_path):
    import asyncio

    from langchain_core.language_models import BaseChatModel

    _write_project_bundle(
        tmp_path / "data", "proj-1", "authn", "Per-project authentication procedure."
    )
    store = skills.SkillStore(root_dir=tmp_path / "data")
    mw = skills.skill_index_middleware(store=store)

    class _M(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult
            from langchain_core.messages import AIMessage
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def _run(context):
        seen = {}

        async def _handler(request):
            seen["system"] = request.system_message.content if request.system_message else None
            from langchain.agents.middleware.types import ModelResponse
            from langchain_core.messages import AIMessage
            return ModelResponse(result=[AIMessage(content="ok")])

        from langchain.agents.middleware.types import ModelRequest
        req = ModelRequest(
            model=_M(), messages=[], system_prompt="base",
            state={"messages": []},
            runtime=type("R", (), {"context": context})(),
        )
        await mw.wrap_model_call(req, _handler)
        return seen["system"]

    rendered = asyncio.run(
        _run({"skills": ["authn"], "project_id": "proj-1"})
    )
    assert "- authn: Per-project authentication procedure." in rendered

    unbound = asyncio.run(_run({"skills": ["authn"], "project_id": "proj-2"}))
    assert "authn" not in unbound  # no bundle at the designed location: not collected
