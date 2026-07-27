"""Unit tier for the analysis-agent configuration eval harness (`evaluation.py`).

The harness is the instrument the operator reads prompt decisions off, so its own
correctness matters as much as an agent's: a miscounted arm or a silently-dropped
cell would produce a confident, wrong conclusion. No LLM, no DB - the invoke/read
collaborators are injected, which is the same seam a future analysis agent uses to
adopt the harness.
"""


from polymerhus.analysis.evaluation import (
    INTEGRITY_KEYS,
    EvalOutcome,
    compare,
    format_comparison,
    run_matrix,
    skeleton_metrics,
)


def _skeleton(n_services=3, *, contracts=True, roles=("admin", "user"), edges=0, systems=3):
    return {
        "services": [
            {"slug": f"svc-{i}", "exposure": "public" if i % 2 else "authenticated",
             "service_contract": f"Does thing {i}." if contracts else ""}
            for i in range(n_services)
        ],
        "systems": ([{"kind": "AuthorizationSystem", "roles": list(roles), "realms": ["web"]}]
                    + [{"kind": f"K{i}"} for i in range(systems - 1)]),
        "service_system_edges": edges,
    }


# --- metrics ------------------------------------------------------------------

def test_breadth_and_integrity_are_measured_together():
    """Breadth must never be readable alone: an arm can buy Service count by losing
    role vocabulary, which is exactly what one live arm did."""
    m = skeleton_metrics(_skeleton(5))
    assert m["n_services"] == 5
    for key in INTEGRITY_KEYS:
        assert key in m, f"{key} must ride alongside breadth"
    assert m["contract_coverage"] == 1.0
    assert m["n_roles"] == 2


def test_missing_contracts_show_up_as_reduced_coverage():
    m = skeleton_metrics(_skeleton(4, contracts=False))
    assert m["n_services"] == 4          # breadth unaffected ...
    assert m["contract_coverage"] == 0.0  # ... but the cost is visible in the same row


def test_lost_role_vocabulary_is_visible():
    """The live failure this guards: a breadth-maximising arm dropped an
    AuthorizationSystem's whole role list while scoring joint-best on count."""
    assert skeleton_metrics(_skeleton(9, roles=()))["n_roles"] == 0


def test_granularity_is_reported_but_not_scored():
    """Operator ruling: granularity has no principled measure, so it is an
    observation. It must not appear as a number anything ranks on."""
    m = skeleton_metrics({
        "services": [{"slug": s, "service_contract": "c"} for s in
                     ("shopping-basket", "checkout-payment", "reviews")],
        "systems": [], "service_system_edges": 0,
    })
    note = m["granularity_note"]
    assert note["journey_split"] == 2  # basket + checkout, not reviews
    assert sorted(note["journey_covering_services"]) == ["checkout-payment", "shopping-basket"]
    assert "granularity" not in {k for k in m if k != "granularity_note"}


def test_metrics_tolerate_an_empty_skeleton():
    m = skeleton_metrics({"services": [], "systems": [], "service_system_edges": 0})
    assert m["n_services"] == 0
    assert m["contract_coverage"] == 0.0  # no ZeroDivisionError on an empty arm


# --- the matrix ---------------------------------------------------------------

def test_matrix_runs_every_config_the_requested_number_of_times():
    calls = []

    def invoke(config, run_name):
        calls.append((config, run_name))
        return f"pid-{config}-{len(calls)}"

    out = run_matrix(["a", "b"], invoke_fn=invoke, read_fn=lambda p: _skeleton(2), repeats=3)
    assert len(out) == 6
    assert [c for c, _ in calls] == ["a", "a", "a", "b", "b", "b"]
    assert all(o.error is None for o in out)


def test_a_failed_cell_is_recorded_and_the_matrix_continues():
    """Losing an hour of completed arms to one provider blip would be its own defect,
    so a cell fails open - but it must be MARKED, never silently counted as a run."""
    def invoke(config, run_name):
        if config == "bad":
            raise RuntimeError("provider exploded")
        return "pid"

    out = run_matrix(["bad", "good"], invoke_fn=invoke,
                     read_fn=lambda p: _skeleton(2), repeats=2)
    assert len(out) == 4
    bad = [o for o in out if o.config == "bad"]
    assert all(o.error and "provider exploded" in o.error for o in bad)
    assert all(o.metrics == {} for o in bad)


def test_the_project_id_is_carried_so_a_result_stays_inspectable():
    """A number with no graph behind it cannot be checked; every cell records the
    project it wrote, and nothing in the harness deletes it."""
    out = run_matrix(["a"], invoke_fn=lambda c, n: "proj-42",
                     read_fn=lambda p: _skeleton(1), repeats=1)
    assert out[0].project_id == "proj-42"


# --- comparison ---------------------------------------------------------------

def json_keys(obj, acc=None):
    acc = acc if acc is not None else set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            json_keys(v, acc)
    return acc


def _outcomes(config, values):
    return [EvalOutcome(config, i + 1, f"p{i}", 1.0, skeleton_metrics(_skeleton(v)))
            for i, v in enumerate(values)]


def test_compare_reports_distributions_not_a_verdict():
    """Comparative BY CONSTRUCTION: no threshold, no pass/fail, no 'winner' - the
    ranking is the reader's, with integrity in view."""
    summary = compare(_outcomes("a", [16, 19, 21]) + _outcomes("b", [20, 20, 28]))
    assert summary["a"]["breadth"]["mean"] == 18.7
    assert summary["b"]["breadth"]["mean"] == 22.7
    assert "winner" not in summary and "passed" not in summary
    for s in summary.values():
        assert "threshold" not in json_keys(s)


def test_compare_exposes_the_floor_not_just_the_mean():
    """A high mean over a low floor is not a win; min/stdev make that visible."""
    summary = compare(_outcomes("wide", [10, 30]) + _outcomes("tight", [19, 21]))
    assert summary["wide"]["breadth"]["mean"] == summary["tight"]["breadth"]["mean"] == 20.0
    assert summary["wide"]["breadth"]["min"] < summary["tight"]["breadth"]["min"]
    assert summary["wide"]["breadth"]["stdev"] > summary["tight"]["breadth"]["stdev"]


def test_integrity_is_reported_as_the_observed_SET_not_an_average():
    """One degraded run among three must stay visible. Averaging roles [11,11,0] to
    7.3 would hide the failure; the set {0, 11} cannot be misread."""
    good = EvalOutcome("x", 1, "p1", 1.0, skeleton_metrics(_skeleton(9)))
    lost = EvalOutcome("x", 2, "p2", 1.0, skeleton_metrics(_skeleton(9, roles=())))
    summary = compare([good, lost])
    assert summary["x"]["integrity"]["n_roles"] == [0, 2]


def test_an_all_failed_arm_is_reported_as_such_not_omitted():
    summary = compare([EvalOutcome("dead", 1, "", 1.0, {}, error="boom")])
    assert summary["dead"]["n"] == 0 and summary["dead"]["failed"] == 1


def test_format_comparison_renders_every_arm():
    summary = compare(_outcomes("a", [16, 19]) + _outcomes("b", [20, 28]))
    rendered = format_comparison(summary)
    assert "a" in rendered and "b" in rendered
    assert "n_roles" in rendered  # integrity travels with the breadth row
