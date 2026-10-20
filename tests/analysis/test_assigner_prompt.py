"""Arm M E7: the assigner prompt tags the surface class of every placement.

The tag makes the assigner's response reading auditable.
A `live route` is placed when the evidence supports an owner; a `mirror shell`
that repeats the same SPA shell across paths stays unowned unless the evidence
shows a distinct business surface.
"""

from polymerhus.analysis.assigner import _load_assigner_skill


def test_placement_discipline_tags_each_endpoint() -> None:
    prompt = _load_assigner_skill()

    assert "## Placement discipline: live routes and mirror shells" in prompt
    assert "`live route`" in prompt
    assert "`mirror shell`" in prompt


def test_mirror_shell_default_stays_unowned() -> None:
    prompt = _load_assigner_skill()

    assert (
        "stays unowned unless the evidence shows a distinct business surface"
    ) in prompt
