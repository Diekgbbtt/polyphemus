"""#238 A7/A8/B2 - the E2E stack wiring, checked offline.

The overlay and the Dockerfiles are the harness contract: a wrong tag or a
missing model role means the live gate cannot run, and the failure must be a
failing test here rather than a stack that quietly boots the wrong code.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "docker-compose.e2e.yml"
BASE_COMPOSE = ROOT / "docker-compose.yml"

#: Every role the agent refuses to boot without (providers.py Role table).
BOOT_REQUIRED_ROLES = (
    "LLM_CONFIGURATOR",
    "LLM_CRAWLER",
    "LLM_JOB_ORCHESTRATOR",
    "LLM_TRIAGER",
    "LLM_ANALYSER",
)

FIXTURE_MODEL = "openai:rate-admission-fixture"

#: The E2E-only services that must run the issue-private Kali image.
E2E_KALI_SERVICES = ("kali", "kali-failing-governor", "kali-capture-off")


def _overlay() -> dict:
    """Parse the overlay, tolerating Compose's `!override`/`!reset` tags."""

    class _ComposeLoader(yaml.SafeLoader):
        pass

    def _compose_tag(loader, _tag_suffix, node):
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return loader.construct_scalar(node)

    _ComposeLoader.add_multi_constructor("!", _compose_tag)
    return yaml.load(OVERLAY.read_text(encoding="utf-8"), Loader=_ComposeLoader)


def test_e2e_overlay_configures_every_boot_required_llm_role():
    """#238 A7: the overlay only routed JOB_ORCHESTRATOR + TRIAGER, so the agent
    exited at boot with `LLM_CONFIGURATOR/CRAWLER/ANALYSER must be set`. Every
    boot-required role must be bound to the deterministic fixture."""
    env = _overlay()["services"]["agent"]["environment"]
    for role in BOOT_REQUIRED_ROLES:
        assert env.get(role) == FIXTURE_MODEL, (
            f"the E2E overlay must route {role} at the deterministic fixture"
        )
    assert env["LLM_GATEWAY_URL"].startswith("http://rate-limit-llm")
    assert env["API_KEY_OPENAI"] == "e2e-inert-key"


def test_e2e_overlay_pins_a_configurable_profile_ttl():
    """The freshness knob must be present and OVERRIDABLE: the posture matrix
    needs a long TTL (the later intensives must stay fresh) while the stale gate
    brings the stack up short - both from the committed overlay, never an
    ad-hoc edit to this file."""
    env = _overlay()["services"]["agent"]["environment"]
    ttl = env.get("RATE_LIMIT_PROFILE_TTL_S")
    assert ttl is not None, "the overlay must set the profile TTL"
    assert "RATE_LIMIT_PROFILE_TTL_S:-" in str(ttl), (
        "the TTL must be overridable from the environment for the stale gate"
    )


def test_issue238_overlay_never_uses_shared_latest_tags():
    """#238 B2: the E2E tier must not build on top of the operator's shared
    `:latest` tags - it uses project-private tags so a rebuild/recreate cannot
    clobber (or be clobbered by) the operator's stack."""
    services = _overlay()["services"]
    assert services["agent"]["image"] == "polymerhus-agent:issue-238-e2e"
    for name in E2E_KALI_SERVICES:
        assert services[name]["image"] == "polymerhus-kali:issue-238-e2e", name


def test_e2e_overlay_sets_the_admission_gates():
    """Both admission gates are fixture-scale operator knobs and must be
    committed (never ad-hoc) so the live matrix is reproducible."""
    env = _overlay()["services"]["agent"]["environment"]
    assert float(str(env["RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S"]).split(":-")[-1]
                 .rstrip("}")) == 2.0
    ceiling = str(env["RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S"])
    assert "RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S:-" in ceiling
    assert float(ceiling.split(":-")[-1].rstrip("}")) > 4750 / 16.0
