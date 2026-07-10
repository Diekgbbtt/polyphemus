class _FakeStructured:
    def __init__(self, result): self._result = result
    def invoke(self, messages): return self._result


class _FakeLLM:
    def __init__(self, result): self._result = result
    def with_structured_output(self, schema, **kw): return _FakeStructured(self._result)


def test_decide_routing_maps_exclusions():
    from agent.recon.steering_agent import decide_routing, RoutingDecision, _JobExclusion
    result = RoutingDecision(exclusions=[_JobExclusion(job="katana", exclude_urls=["https://ib.x"])])
    out = decide_routing(
        [{"url": "https://ib.x", "macro_kind": "waf_protected", "evidence": "Incapsula"}],
        ["katana", "steel_crawl"], llm=_FakeLLM(result),
    )
    assert out == {"katana": ["https://ib.x"]}


def test_decide_routing_empty_signals_is_noop():
    from agent.recon.steering_agent import decide_routing
    assert decide_routing([], ["katana"], llm=None) == {}


def test_decide_routing_fail_open(monkeypatch):
    from agent.recon.steering_agent import decide_routing

    class Boom:
        def with_structured_output(self, *a, **k): raise RuntimeError("llm down")

    out = decide_routing([{"url": "u", "macro_kind": "waf_protected", "evidence": "e"}],
                         ["katana"], llm=Boom())
    assert out == {}


def test_decide_pod_selection_applies_plan():
    from agent.recon.steering_agent import decide_pod_selection, PodSelection, _AssetPlan
    result = PodSelection(plan=[
        _AssetPlan(url="https://a", run=True, throttle=True),
        _AssetPlan(url="https://b", run=False),
    ])
    selected, throttle = decide_pod_selection(
        [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}],
        "katana", [{"url": "https://a"}, {"url": "https://b"}], llm=_FakeLLM(result),
    )
    assert selected == [{"url": "https://a"}]
    assert throttle == {"https://a"}


def test_decide_pod_selection_fail_open_runs_all():
    from agent.recon.steering_agent import decide_pod_selection

    class Boom:
        def with_structured_output(self, *a, **k): raise RuntimeError("llm down")

    assets = [{"url": "https://a"}]
    selected, throttle = decide_pod_selection(
        [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}],
        "katana", assets, llm=Boom())
    assert selected == assets and throttle == set()
