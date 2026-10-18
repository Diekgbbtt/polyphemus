"""#232 unit tier - the skill-usage lesson store (D232-1/2).

The lesson layer is a NEW skill-scoped store owned by the skills-access domain:
per-skill shards `<data_root>/<project_id>/skills/lessons/<skill>.yaml`, resolved
through the ONE `app.data_root.project_dir` resolver. These tests assert external
behaviour only: the records read back, the files on disk, the coded refusals.

Operator rulings pinned here:
- the record is a minimal typed envelope with free-text values, three types
  (`specification | extension | defect`), store-stamped `base_version`/`written_at`,
  tool-stamped agent identity, and a store-generated monotonic key
  `skill:<skill>:<ordinal>`;
- consumption is key-encoded: `mark_consumed` rewrites the key with the reserved
  `:consumed` code (no `consumed_by` field, no cursor);
- a repeated lesson appends (ordinals are monotonic).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from polymerhus.app.llm import skills
from polymerhus.app.llm.skills import (
    LESSON_TYPES,
    LessonInvalidError,
    LessonStore,
    SkillUnknownError,
    StoreUnavailableError,
)


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


def _catalogue(tmp_path: Path, skill: str = "ssrf", version: str = "1.0") -> Path:
    """A temp shared catalogue holding one A3-conforming skill (the bootstrapped
    metadata source the lesson store resolves `base_version` through)."""
    catalogue = tmp_path / "catalogue"
    bundle = catalogue / skill
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text(
        "---\n"
        f"name: {skill}\n"
        f"description: The {skill} procedure.\n"
        "metadata:\n"
        f"  version: '{version}'\n"
        "---\n\n# Seed\n",
        encoding="utf-8",
    )
    return catalogue


def _store(tmp_path: Path) -> LessonStore:
    return LessonStore(root_dir=tmp_path / "data")


def test_append_writes_a_per_skill_shard_under_the_skills_bucket(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    key = store.append(
        "proj-1",
        skill="ssrf",
        type="specification",
        lesson="metadata endpoint is reachable on this target",
        expected="the procedure expects cloud metadata to be blocked",
        evidence=["http-artifact/abc123", "run-41"],
        agent={"role_id": "pod_runner", "session_id": "hunting:r1:hunt:c1:pod:s1"},
    )

    assert key == "skill:ssrf:1"
    shard = tmp_path / "data" / "proj-1" / "skills" / "lessons" / "ssrf.yaml"
    assert shard.is_file()
    records = yaml.safe_load(shard.read_text(encoding="utf-8"))
    assert records == [
        {
            "key": "skill:ssrf:1",
            "type": "specification",
            "lesson": "metadata endpoint is reachable on this target",
            "expected": "the procedure expects cloud metadata to be blocked",
            "evidence": ["http-artifact/abc123", "run-41"],
            "base_version": "1.0",
            "agent": {
                "role_id": "pod_runner",
                "session_id": "hunting:r1:hunt:c1:pod:s1",
            },
            "written_at": records[0]["written_at"],
        }
    ]
    assert isinstance(records[0]["written_at"], str) and records[0]["written_at"]


def test_appends_use_monotonic_ordinals_and_read_returns_file_order(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    first = store.append(
        "proj-1", skill="ssrf", type="defect", lesson="step 2 never settles"
    )
    second = store.append(
        "proj-1", skill="ssrf", type="extension", lesson="wait on the selector instead"
    )

    assert first == "skill:ssrf:1"
    assert second == "skill:ssrf:2"
    records = store.read("proj-1", skill="ssrf")
    assert [r["key"] for r in records] == ["skill:ssrf:1", "skill:ssrf:2"]
    assert [r["lesson"] for r in records] == [
        "step 2 never settles",
        "wait on the selector instead",
    ]


def test_type_and_lesson_shape_are_refused_before_any_write(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    with pytest.raises(LessonInvalidError):
        store.append("proj-1", skill="ssrf", type="optimization", lesson="x")
    with pytest.raises(LessonInvalidError):
        store.append("proj-1", skill="ssrf", type="defect", lesson="   ")
    with pytest.raises(LessonInvalidError):
        store.append(
            "proj-1", skill="ssrf", type="defect", lesson="x", evidence="not-a-list"
        )
    assert not (tmp_path / "data" / "proj-1" / "skills" / "lessons").exists()
    assert LESSON_TYPES == ("specification", "extension", "defect")


def test_an_unknown_skill_is_refused_with_the_coded_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    with pytest.raises(SkillUnknownError):
        store.append("proj-1", skill="no-such-skill", type="defect", lesson="x")
    assert not (tmp_path / "data" / "proj-1" / "skills" / "lessons").exists()


def test_a_skill_that_is_not_one_safe_component_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    for bad in ("../escape", "meta/authn", "lessons", "evolution", ""):
        with pytest.raises((LessonInvalidError, ValueError)):
            store.append("proj-1", skill=bad, type="defect", lesson="x")


def test_mark_consumed_rewrites_keys_with_the_reserved_code_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.append("proj-1", skill="ssrf", type="defect", lesson="one")
    store.append("proj-1", skill="ssrf", type="extension", lesson="two")

    marked = store.mark_consumed("proj-1", ["skill:ssrf:1"])
    assert marked == 1
    marked_again = store.mark_consumed("proj-1", ["skill:ssrf:1"])
    assert marked_again == 0  # idempotent: the code is already there

    records = store.read("proj-1", skill="ssrf")
    assert [r["key"] for r in records] == ["skill:ssrf:1:consumed", "skill:ssrf:2"]
    unconsumed = store.read("proj-1", skill="ssrf", unconsumed_only=True)
    assert [r["key"] for r in unconsumed] == ["skill:ssrf:2"]


def test_mark_consumed_ignores_keys_it_does_not_hold(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.append("proj-1", skill="ssrf", type="defect", lesson="one")

    assert store.mark_consumed("proj-1", ["skill:ssrf:99", "skill:other:1"]) == 0
    assert [r["key"] for r in store.read("proj-1", skill="ssrf")] == ["skill:ssrf:1"]


def test_read_filters_by_type_and_keywords(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.append("proj-1", skill="ssrf", type="defect", lesson="metadata is open")
    store.append("proj-1", skill="ssrf", type="extension", lesson="use the alias query")

    assert [r["type"] for r in store.read("proj-1", skill="ssrf", type="extension")] == [
        "extension"
    ]
    assert [
        r["key"]
        for r in store.read("proj-1", skill="ssrf", body_keyword="METADATA")
    ] == ["skill:ssrf:1"]
    assert (
        store.read("proj-1", skill="ssrf", key_keyword=":2")[0]["key"] == "skill:ssrf:2"
    )


def test_read_across_skills_walks_the_shard_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path, "ssrf"))
    (tmp_path / "catalogue" / "idor").mkdir(parents=True, exist_ok=True)
    (tmp_path / "catalogue" / "idor" / "SKILL.md").write_text(
        "---\nname: idor\ndescription: D.\nmetadata:\n  version: '2.0'\n---\n\n# I\n",
        encoding="utf-8",
    )
    store = _store(tmp_path)
    store.append("proj-1", skill="ssrf", type="defect", lesson="s")
    store.append("proj-1", skill="idor", type="defect", lesson="i")

    all_records = store.read("proj-1")
    assert {r["key"] for r in all_records} == {"skill:ssrf:1", "skill:idor:1"}
    assert store.skills_with_lessons("proj-1") == ["idor", "ssrf"]
    assert store.read("proj-1", skill="no-such-skill") == []


def test_a_corrupt_shard_fails_open_on_read_and_loud_on_append(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    shard = tmp_path / "data" / "proj-1" / "skills" / "lessons" / "ssrf.yaml"
    shard.parent.mkdir(parents=True)
    shard.write_text(": [not, valid", encoding="utf-8")

    assert store.read("proj-1", skill="ssrf") == []  # fail-open read, loudly
    with pytest.raises(StoreUnavailableError):
        store.append("proj-1", skill="ssrf", type="defect", lesson="x")
    # the write refusal persisted nothing
    assert shard.read_text(encoding="utf-8") == ": [not, valid"


def test_the_shard_resolves_through_the_one_project_dir_resolver(
    tmp_path: Path, monkeypatch
) -> None:
    from polymerhus.app.data_root import project_dir

    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.append("proj-1", skill="ssrf", type="defect", lesson="x")

    expected = project_dir(
        "proj-1", "skills", root=tmp_path / "data"
    ) / "lessons" / "ssrf.yaml"
    assert expected.is_file()


def test_two_projects_keep_separate_shards(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.append("proj-a", skill="ssrf", type="defect", lesson="a")
    store.append("proj-b", skill="ssrf", type="defect", lesson="b")

    assert [r["lesson"] for r in store.read("proj-a", skill="ssrf")] == ["a"]
    assert [r["lesson"] for r in store.read("proj-b", skill="ssrf")] == ["b"]


# --- the record_skill_lesson tool (#232 D232-4/5) -----------------------------


def test_record_lesson_tool_returns_the_key_and_base_version(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path, version="3.2"))
    store = _store(tmp_path)
    tool = skills.build_record_lesson_tool("proj-1", store=store, role_id="pod_runner")

    out = tool.invoke(
        {
            "skill": "ssrf",
            "type": "extension",
            "lesson": "alias queries retrieve the KB docs",
            "expected": "the canonical term is the only query",
            "evidence": ["http-artifact/1"],
        }
    )

    assert out == {"ok": True, "key": "skill:ssrf:1", "base_version": "3.2"}
    record = store.read("proj-1", skill="ssrf")[0]
    assert record["agent"] == {"role_id": "pod_runner", "session_id": ""}


def test_record_lesson_tool_is_in_band_for_unknown_skill_and_bad_type(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    tool = skills.build_record_lesson_tool("proj-1", store=store)

    unknown = tool.invoke({"skill": "nope", "type": "defect", "lesson": "x"})
    assert unknown["ok"] is False and unknown["error"] == "skill_unknown"
    invalid = tool.invoke({"skill": "ssrf", "type": "optimization", "lesson": "x"})
    assert invalid["ok"] is False and invalid["error"] == "lesson_invalid"
    empty = tool.invoke({"skill": "ssrf", "type": "defect", "lesson": " "})
    assert empty["ok"] is False and empty["error"] == "lesson_invalid"
    # Nothing landed on disk for any refusal.
    assert store.read("proj-1", skill="ssrf") == []


def test_record_lesson_tool_stamps_the_ambient_session_id(
    tmp_path: Path, monkeypatch
) -> None:
    from polymerhus.app.llm.conversation import conversation_scope

    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    tool = skills.build_record_lesson_tool("proj-1", store=store, role_id="pod_runner")

    with conversation_scope("hunting:run-1:hunt:c1:pod:spec-1"):
        out = tool.invoke({"skill": "ssrf", "type": "defect", "lesson": "x"})

    assert out["ok"] is True
    record = store.read("proj-1", skill="ssrf")[0]
    assert record["agent"] == {
        "role_id": "pod_runner",
        "session_id": "hunting:run-1:hunt:c1:pod:spec-1",
    }


def test_record_lesson_tool_carries_the_verbatim_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    tool = skills.build_record_lesson_tool("proj-1", store=_store(tmp_path))

    assert tool.name == "record_skill_lesson"
    assert tool.description == skills.RECORD_LESSON_CONTRACT
    for token in ("specification", "extension", "defect", ":consumed"):
        if token == ":consumed":
            continue  # a store fact, not part of the agent contract
        assert token in tool.description
    schema = tool.args_schema.model_json_schema()
    assert set(schema["properties"]) == {
        "skill",
        "type",
        "lesson",
        "expected",
        "evidence",
    }
    assert schema["required"] == ["skill", "type", "lesson"]

