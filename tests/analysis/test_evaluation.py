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


# --- the Assigner arm (AMV-9) -------------------------------------------------
#
# The Assigner's risk is OVER-production, the mirror of the Bootstrapper's, so these
# pin the properties that stop assignment volume being read as a score.

def _census(**kw):
    base = dict(endpoints=100, aggregates=40, assigned_endpoints=38,
                multi_owner_endpoints=2, admitted=100, proposed=60,
                unresolvable=2, out_of_inventory=3, withheld=15, mean_confidence=0.86)
    base.update(kw)
    return base


def test_assignment_metrics_report_the_stale_pool_as_a_first_class_number():
    """`stale_pool == 0` was recorded live as a WARNING sign, not a win: a run that
    leaves nothing unassigned has almost certainly assigned surface no Service owns.
    So it has to be a column, not an absence."""
    from polymerhus.analysis.evaluation import assignment_metrics

    m = assignment_metrics(_census())
    assert m["stale_pool"] == 62
    assert m["stale_rate"] == 0.62
    assert m["coverage"] == 0.38
    assert m["n_aggregates"] == 40          # the primary axis


def test_assignment_metrics_expose_where_each_judgment_died():
    from polymerhus.analysis.evaluation import assignment_metrics

    m = assignment_metrics(_census())
    assert m["withheld_rate"] == 0.25            # 15/60 - the discipline firing
    assert m["out_of_inventory_rate"] == 0.05    # 3/60  - invented owners
    assert m["unresolvable_rate"] == round(2 / 60, 3)


def test_assignment_metrics_rates_are_zero_not_none_on_an_empty_run():
    """A missing column reads as an absent measurement; these columns are how an
    arm's noise is seen, so they must always be present."""
    from polymerhus.analysis.evaluation import assignment_metrics

    m = assignment_metrics({})
    assert m["withheld_rate"] == 0.0 and m["coverage"] == 0.0 and m["stale_pool"] == 0


def test_bar_sweep_makes_the_confidence_bar_an_output():
    """ASSIGN_CONFIDENCE_BAR is documented as 'an OUTPUT of the assertion suite' but
    nothing swept it. The sweep needs no extra LLM calls - withholding is a pure
    function of confidences already collected - so one run yields the whole curve."""
    from polymerhus.analysis.evaluation import bar_sweep

    out = bar_sweep([0.95, 0.9, 0.8, 0.76, 0.74, 0.6, 0.55], bars=(0.5, 0.75, 0.9))
    assert out["n"] == 7
    assert out["kept"]["0.5"] == 7
    assert out["kept"]["0.75"] == 4       # the cliff sits between 0.74 and 0.76
    assert out["kept"]["0.9"] == 2
    assert out["kept_rate"]["0.9"] == round(2 / 7, 3)


def test_compare_uses_the_assigner_primary_axis_and_integrity_columns():
    from polymerhus.analysis.evaluation import (
        ASSIGNMENT_INTEGRITY_KEYS, assignment_metrics, compare,
    )

    cells = [
        EvalOutcome("skill", 1, "p1", 1.0, assignment_metrics(_census(aggregates=40))),
        EvalOutcome("skill", 2, "p2", 1.0, assignment_metrics(_census(aggregates=44))),
        # the failure this guards: an arm that assigns EVERYTHING looks like a
        # coverage win while its stale pool collapses to zero
        EvalOutcome("baseline", 1, "p3", 1.0,
                    assignment_metrics(_census(aggregates=130, assigned_endpoints=100,
                                               withheld=0, proposed=130))),
    ]
    summary = compare(cells, primary_key="n_aggregates",
                      integrity_keys=ASSIGNMENT_INTEGRITY_KEYS)

    assert summary["skill"]["primary_key"] == "n_aggregates"
    assert summary["skill"]["breadth"]["values"] == [40, 44]
    # baseline "wins" the primary axis while its integrity columns give it away
    assert summary["baseline"]["breadth"]["mean"] == 130
    assert summary["baseline"]["integrity"]["stale_pool"] == [0]
    assert summary["baseline"]["integrity"]["withheld_rate"] == [0.0]
    # granularity_note is Bootstrapper-only: an agent without it gets no such column
    assert "granularity_note" not in summary["skill"]


def test_compare_defaults_are_unchanged_for_the_bootstrapper():
    """The generalisation must not move the first adopter. Same call, same shape."""
    summary = compare(_outcomes("a", [16, 19, 21]))
    assert summary["a"]["primary_key"] == "n_services"
    assert summary["a"]["breadth"]["values"] == [16, 19, 21]
    assert "granularity_note" in summary["a"]
    assert set(summary["a"]["integrity"]) == set(INTEGRITY_KEYS)


def test_evaluate_assigner_labels_each_project_with_the_arm_it_ran_under(monkeypatch):
    """The operator's requirement: the evaluation must ACCOUNT for the config
    parameter, not just measure the graph. A project read without its arm label is an
    unattributable number."""
    from polymerhus.analysis import evaluation

    graphs = {
        "p-skill": _census(aggregates=40),
        "p-base": _census(aggregates=120, assigned_endpoints=99, withheld=0),
    }

    def fake_read(project_id, *, read_fn=None):
        c = dict(graphs[project_id])
        c["confidences"] = [0.9, 0.8, 0.7]
        return c

    monkeypatch.setattr(evaluation, "read_assignment", fake_read)
    summary = evaluation.evaluate_assigner({"skill": ["p-skill"], "baseline": ["p-base"]})

    assert summary["skill"]["projects"] == ["p-skill"]
    assert summary["baseline"]["projects"] == ["p-base"]
    assert summary["skill"]["bar_sweep"]["n"] == 3     # the sweep rides each arm
    assert summary["baseline"]["integrity"]["withheld_rate"] == [0.0]
