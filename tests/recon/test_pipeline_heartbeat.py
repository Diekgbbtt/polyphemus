import asyncio

from agent.recon import pipeline


def test_heartbeat_tick_fires_and_is_cancelled(monkeypatch):
    ticks = []

    class Reg:
        def create_run(self, *a, **k): pass
        def upsert_job(self, *a, **k): pass
        def set_run_status(self, *a, **k): pass

    monkeypatch.setattr(pipeline.config, "HEARTBEAT_TICK_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda rid: ticks.append(rid))

    async def fake_run_job(job, assets, **k):
        await asyncio.sleep(0.05)  # a slow single job with no registry writes
        return []

    async def _run():
        await pipeline.run_pipeline(
            "proj", run_id="r1", job_subset=["subfinder"],
            run_job=fake_run_job, load_settings=lambda p: {}, registry=Reg(),
            read_assets=lambda t, p: [],
        )
        assert ticks, "heartbeat tick never fired during a slow job"
        await asyncio.sleep(0.03)
        n = len(ticks)
        await asyncio.sleep(0.05)
        assert len(ticks) == n, "heartbeat tick was not cancelled after the run finished"

    asyncio.run(_run())
