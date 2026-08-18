"""Recon-orchestrator agent: macro cross-job routing decision (decide_routing).

A fake LLM is injected so no provider/network is touched.
"""


class _FakeStructured:
    def __init__(self, result): self._result = result
    def invoke(self, messages): return self._result


class _FakeLLM:
    def __init__(self, result): self._result = result
    def with_structured_output(self, schema, **kw): return _FakeStructured(self._result)


def test_decide_routing_maps_exclusions():
    from polymerhus.recon.control.orchestrator_agent import decide_routing, RoutingDecision, _JobExclusion
    result = RoutingDecision(exclusions=[_JobExclusion(job="katana", exclude_urls=["https://ib.x"])])
    out = decide_routing(
        [{"url": "https://ib.x", "macro_kind": "waf_protected", "evidence": "Incapsula"}],
        ["katana", "steel_crawl"], llm=_FakeLLM(result),
    )
    assert out == {"katana": ["https://ib.x"]}


def test_decide_routing_ignores_hallucinated_job():
    from polymerhus.recon.control.orchestrator_agent import decide_routing, RoutingDecision, _JobExclusion
    result = RoutingDecision(exclusions=[_JobExclusion(job="not_in_phase", exclude_urls=["https://x"])])
    out = decide_routing(
        [{"url": "https://x", "macro_kind": "waf_protected", "evidence": "e"}],
        ["katana"], llm=_FakeLLM(result),
    )
    assert out == {}  # job not in phase_jobs -> dropped


def test_decide_routing_empty_signals_is_noop():
    from polymerhus.recon.control.orchestrator_agent import decide_routing
    assert decide_routing([], ["katana"], llm=None) == {}


def test_decide_routing_fail_open():
    from polymerhus.recon.control.orchestrator_agent import decide_routing

    class Boom:
        def with_structured_output(self, *a, **k): raise RuntimeError("llm down")

    out = decide_routing([{"url": "u", "macro_kind": "waf_protected", "evidence": "e"}],
                         ["katana"], llm=Boom())
    assert out == {}
