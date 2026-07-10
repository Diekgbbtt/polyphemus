def test_waf_vocabulary_and_job_kind():
    from agent.recon.steering import (
        is_waf_signal, WAF_MACRO_KINDS, REQUEST_CRAWLER_JOBS,
        AGENTIC_CRAWLER_JOBS, describe_job_kind,
    )
    assert WAF_MACRO_KINDS == frozenset({"waf_protected", "waf_detection"})
    assert is_waf_signal("waf_protected") and not is_waf_signal("auth_surface")
    assert {"katana", "ffuf", "kiterunner", "graphql-cop"} <= REQUEST_CRAWLER_JOBS
    assert "steel_crawl" in AGENTIC_CRAWLER_JOBS
    assert "request-based" in describe_job_kind("katana")
    assert "browser" in describe_job_kind("steel_crawl")


class _FakeSession:
    def __init__(self, rows): self._rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, query, **params): return iter(self._rows)


class _FakeDriver:
    def __init__(self, rows): self._rows = rows
    def session(self): return _FakeSession(self._rows)


def test_read_steering_signals_returns_signal_dicts():
    from agent.recon.pipeline import read_steering_signals
    driver = _FakeDriver([
        {"url": "https://ib.example.com", "macro_kind": "waf_protected", "evidence": "Incapsula"},
        {"url": None, "macro_kind": "waf_detection", "evidence": "x"},
    ])
    assert read_steering_signals("p1", driver=driver) == [
        {"url": "https://ib.example.com", "macro_kind": "waf_protected", "evidence": "Incapsula"},
    ]


def test_read_steering_signals_fail_open_on_error():
    from agent.recon.pipeline import read_steering_signals

    class Boom:
        def session(self): raise RuntimeError("neo4j down")

    assert read_steering_signals("p1", driver=Boom()) == []
