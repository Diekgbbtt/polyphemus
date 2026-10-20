"""Arm M E1: the mechanism-typist prompt links every System to its Services.

The prompt is the role prefix for the extraction call.
Without the linking section the typist can describe a gate and never attach it, and the M4 `AUTHORIZED_BY` items stay missing.
The section mirrors the evidence section's style, and Example 6 carries the worked linking example.
"""

from polymerhus.analysis.mechanism_typist import _load_skill


def test_prompt_links_each_system_to_its_services() -> None:
    prompt = _load_skill()

    assert "## Link each System to its Services" in prompt
    assert "system_edges:" in prompt
    assert "service_slug: admin" in prompt
    assert "anonymous-allowed routes" in prompt
    assert "account-creation Service" in prompt
    assert "one edge per (service, System) pair" in prompt
    assert "never duplicate" in prompt.lower()


def test_example_six_shows_the_full_route_chain_and_the_edge() -> None:
    prompt = _load_skill()

    assert "full route chain" in prompt
    assert "GET /api/admin/users" in prompt
    assert "403" in prompt
    assert "AUTHORIZED_BY" in prompt
    assert "service_slug: account-registration" in prompt
    assert "mints the accounts" in prompt
    assert "Stop at existence + linkage" in prompt
