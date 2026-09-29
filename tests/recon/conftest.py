import pytest

from polymerhus.recon.control import pipeline


@pytest.fixture(autouse=True)
def _no_real_posture_writes(monkeypatch):
    """The default posture seam is a no-op in the unit tier; the write path is
    exercised explicitly by tests/recon/test_rate_limit_posture_write.py."""
    monkeypatch.setattr(
        pipeline, "_default_write_posture",
        lambda project_id, profile, run_id: None,
    )


@pytest.fixture(autouse=True)
def _deterministic_phase_configurator(monkeypatch):
    """Unit pipeline tests select every offered pod unless they inject a plan.

    This keeps the phase boundary deterministic without invoking the real
    Configurator LLM. Tests that exercise selection/refusal pass an explicit
    `configure_phase` seam.
    """
    from polymerhus.recon.control import configurator as configurator_module
    from polymerhus.recon.control import pipeline

    def configure_phase(project_id, run_id, phase, target_key, offers):
        pods = [
            configurator_module.ReconPodProposal(
                job_name=offer.job_name,
                input_id=offer.input_id,
                command=(
                    None
                    if offer.configurator_mode == "agent"
                    else (offer.command_template or "true")
                ),
                rationale="unit-test default",
            )
            for offer in offers.offers
        ]
        return configurator_module.ConfiguratorDecision(
            phase=phase,
            target_key=target_key,
            posture_status="known_target",
            pods=pods,
            rationale="unit-test default",
        )

    monkeypatch.setattr(
        pipeline, "_default_configure_phase", configure_phase, raising=False
    )
