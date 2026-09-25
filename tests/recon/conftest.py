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
