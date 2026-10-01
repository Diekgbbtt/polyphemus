"""Unit tests for the eval decision input (`eval/advance/decision.py`).

The decision input is the structured difference the orchestrator consumes:
dev SHA, eval SHA, the all-idle flag, and the manifest delta (changed and
unchanged groups with before/after SHAs and their class). It carries no
action string, no fail-closed set and no per-class branch - the orchestrator
owns all alignment policy (D42).
"""
from __future__ import annotations

import dataclasses

from advance import decision, manifest

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def make(
    *,
    commit: str = "c",
    src: str = "src0",
    platform: str = "plat0",
    digest: str = DIGEST_A,
) -> manifest.StackManifest:
    return manifest.StackManifest(
        commit=commit,
        entries=(
            manifest.ManifestEntry("src", "agent_code", src),
            manifest.ManifestEntry("platform", "platform", platform),
        ),
        image_digests={"agent": digest},
    )


def test_before_is_eval_after_is_dev() -> None:
    before = make(src="eval0")
    after = make(commit="dev", src="dev0")

    result = decision.build_decision_input(
        "dev-sha", "eval-sha", True, manifest_dev=after, manifest_eval=before
    )

    change = next(c for c in result.delta.changed if c.name == "src")
    assert change.before_sha == "eval0"
    assert change.after_sha == "dev0"


def test_no_change_case_reports_nothing_changed() -> None:
    result = decision.build_decision_input(
        "dev-sha",
        "eval-sha",
        True,
        manifest_dev=make(commit="dev"),
        manifest_eval=make(commit="eval"),
    )

    assert result.dev_sha == "dev-sha"
    assert result.eval_sha == "eval-sha"
    assert result.all_idle is True
    assert result.delta.changed == ()
    assert result.delta.unchanged == ("platform", "src")
    assert result.delta.images_changed == ()
    assert result.delta.images_unchanged == ("agent",)


def test_each_changed_group_surfaces_before_after_and_class() -> None:
    before = make(src="src0", platform="plat0")
    after = make(src="src1", platform="plat0")

    result = decision.build_decision_input(
        "dev", "eval", True, manifest_dev=after, manifest_eval=before
    )

    changes = {c.name: c for c in result.delta.changed}
    assert set(changes) == {"src"}
    assert changes["src"].artifact_class == "agent_code"
    assert changes["src"].before_sha == "src0"
    assert changes["src"].after_sha == "src1"
    assert result.delta.unchanged == ("platform",)


def test_a_fail_closed_class_is_reported_like_any_other() -> None:
    # D37 calls the platform group fail-closed, but that policy is the
    # orchestrator's; the decision input only names the class.
    before = make(platform="plat0")
    after = make(platform="plat1")

    result = decision.build_decision_input(
        "dev", "eval", True, manifest_dev=after, manifest_eval=before
    )

    change = next(c for c in result.delta.changed if c.name == "platform")
    assert change.artifact_class == "platform"
    assert change.before_sha == "plat0"
    assert change.after_sha == "plat1"


def test_changed_image_digest_is_surfaced() -> None:
    result = decision.build_decision_input(
        "dev",
        "eval",
        False,
        manifest_dev=make(digest=DIGEST_B),
        manifest_eval=make(digest=DIGEST_A),
    )

    assert result.all_idle is False
    assert result.delta.images_changed == (
        decision.ImageChange("agent", DIGEST_A, DIGEST_B),
    )
    assert result.delta.images_unchanged == ()


def test_group_added_or_removed_reports_none_for_the_missing_side() -> None:
    before = manifest.StackManifest(
        commit="c",
        entries=(manifest.ManifestEntry("src", "agent_code", "src0"),),
        image_digests={},
    )
    after = manifest.StackManifest(
        commit="c",
        entries=(
            manifest.ManifestEntry("src", "agent_code", "src0"),
            manifest.ManifestEntry("db", "schema_data_layout", "db0"),
        ),
        image_digests={},
    )

    result = decision.build_decision_input(
        "dev", "eval", True, manifest_dev=after, manifest_eval=before
    )

    added = next(c for c in result.delta.changed if c.name == "db")
    assert added.before_sha is None
    assert added.after_sha == "db0"
    assert added.artifact_class == "schema_data_layout"


def test_output_carries_no_action_or_policy_fields() -> None:
    result = decision.build_decision_input(
        "dev",
        "eval",
        True,
        manifest_dev=make(src="src1", digest=DIGEST_B),
        manifest_eval=make(src="src0", digest=DIGEST_A),
    )

    assert {f.name for f in dataclasses.fields(decision.DecisionInput)} == {
        "dev_sha",
        "eval_sha",
        "all_idle",
        "delta",
    }
    assert {f.name for f in dataclasses.fields(decision.ManifestDelta)} == {
        "changed",
        "unchanged",
        "images_changed",
        "images_unchanged",
    }
    assert {f.name for f in dataclasses.fields(decision.ArtifactChange)} == {
        "name",
        "artifact_class",
        "before_sha",
        "after_sha",
    }
    assert {f.name for f in dataclasses.fields(decision.ImageChange)} == {
        "component",
        "before_digest",
        "after_digest",
    }

    rendered = repr(result).lower()
    for forbidden in ("action", "policy", "restart", "recreate", "fail", "align"):
        assert forbidden not in rendered
