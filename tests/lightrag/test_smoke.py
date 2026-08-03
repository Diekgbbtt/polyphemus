from agent.lightrag.smoke import (
    QueryCase,
    SmokeRunResult,
    evaluate_graph_gate,
    evaluate_query_response,
    extract_track_id,
    load_wstg_manifest_scenarios,
    processing_status,
    wait_for_processing,
    run_query_cases,
    run_staged_wstg_ingestion,
    status_counts_from_payload,
    wstg_manifest_query_cases,
    wstg_query_cases_for_files,
    wstg_required_maps_for_files,
    wstg_staged_batches,
    WSTG_BYPASS_QUERY_CASES,
)

import json
from agent.lightrag.experiment_tracker import ExperimentTracker


def test_status_counts_handles_lightrag_nested_payload():
    payload = {
        "status_counts": {
            "pending": 0,
            "processing": 0,
            "processed": 9,
            "failed": 0,
            "all": 9,
        }
    }

    assert status_counts_from_payload(payload) == {
        "pending": 0,
        "processing": 0,
        "processed": 9,
        "failed": 0,
        "all": 9,
    }


def test_processing_status_marks_complete_only_when_idle():
    status = processing_status(
        health={
            "pipeline_busy": False,
            "pipeline_active": False,
            "pipeline_pending_enqueues": 0,
        },
        status_counts={"status_counts": {"processed": 9, "failed": 0, "all": 9}},
        expected_documents=9,
    )

    assert status.complete is True
    assert status.processed == 9
    assert status.failed == 0


def test_wait_for_processing_returns_when_failures_are_terminal():
    class FakeClient:
        def __init__(self):
            self.polls = 0

        def health(self):
            self.polls += 1
            return {
                "pipeline_busy": False,
                "pipeline_active": False,
                "pipeline_pending_enqueues": 0,
            }

        def status_counts(self):
            return {
                "status_counts": {
                    "processed": 29,
                    "failed": 10,
                    "all": 39,
                }
            }

    client = FakeClient()

    status = wait_for_processing(
        client,
        expected_documents=39,
        timeout_seconds=60,
        poll_seconds=60,
    )

    assert client.polls == 1
    assert status.complete is False
    assert status.failed == 10


def test_extract_track_id_searches_nested_upload_payloads():
    payload = {"uploaded": [{"response": {"track_id": "upload-1"}}]}

    assert extract_track_id(payload) == "upload-1"


def test_evaluate_query_response_passes_strict_wstg_inventory_case():
    case = QueryCase(
        case_id="inventory",
        required_terms=("SQL Injection", "NoSQL Injection"),
        required_source_files=(
            "wstg-inpv-05-methodology.md",
            "wstg-inpv-05-6-methodology.md",
        ),
        forbidden_terms=("Stored XSS", "Content Security Policy"),
    )
    response = """
    SQL Injection appears in wstg-inpv-05-methodology.md.
    NoSQL Injection appears in wstg-inpv-05-6-methodology.md.
    """

    evaluation = evaluate_query_response(case, {"response": response})

    assert evaluation.passed is True
    assert evaluation.missing_terms == []
    assert evaluation.forbidden_terms_found == []


def test_evaluate_query_response_flags_missing_terms_and_generalization():
    case = QueryCase(
        case_id="inventory",
        required_terms=("SQL Injection", "NoSQL Injection"),
        forbidden_terms=("Stored XSS", "Content Security Policy"),
    )

    evaluation = evaluate_query_response(
        case,
        {"response": "SQL Injection and Stored XSS are both relevant."},
    )

    assert evaluation.passed is False
    assert evaluation.missing_terms == ["NoSQL Injection"]
    assert evaluation.forbidden_terms_found == ["Stored XSS"]


def test_smoke_result_ignores_non_blocking_query_failures():
    result = SmokeRunResult(
        uploaded=[],
        processing=None,
        normalization=None,
        graph_gate=None,
        query_evaluations=[
            evaluate_query_response(
                QueryCase(
                    case_id="diagnostic",
                    required_terms=("NoSQL Injection",),
                    blocking=False,
                ),
                "SQL Injection only.",
            )
        ],
    )

    assert result.query_evaluations[0].passed is False
    assert result.query_evaluations[0].blocking is False
    assert result.passed is True


def test_bypass_relation_query_is_non_blocking_diagnostic():
    assert WSTG_BYPASS_QUERY_CASES[0].case_id == "wstg_bypass_relations"
    assert WSTG_BYPASS_QUERY_CASES[0].blocking is False


def test_evaluate_query_response_supports_any_of_term_groups():
    case = QueryCase(
        case_id="bypass",
        required_any_terms=(
            ("Web Application Firewall", "WAF"),
            ("Allow List", "allowlist"),
        ),
    )

    evaluation = evaluate_query_response(
        case,
        "WAF bypass can depend on URL allowlist parser behavior.",
    )

    assert evaluation.passed is True


def test_wstg_query_cases_for_files_selects_loaded_targeted_cases():
    cases = wstg_query_cases_for_files(
        ["wstg-inpv-05-methodology.md", "wstg-inpv-05-6-methodology.md"],
        include_diagnostics=True,
        include_bypass=False,
    )

    assert [case.case_id for case in cases] == [
        "wstg_targeted_sql_injection",
        "wstg_targeted_nosql_injection",
    ]
    assert all(case.blocking for case in cases)


def test_wstg_required_maps_for_files_filters_unloaded_expected_entities():
    entity_types, source_files = wstg_required_maps_for_files(
        ["wstg-inpv-05-methodology.md"]
    )

    assert entity_types == {"SQL Injection": "VulnerabilityClass"}
    assert source_files == {"SQL Injection": "wstg-inpv-05-methodology.md"}


def test_wstg_staged_batches_keeps_mini_batch_first(tmp_path):
    for name in (
        "wstg-inpv-05-methodology.md",
        "wstg-athz-01-methodology.md",
        "wstg-info-01-methodology.md",
        "wstg-info-02-methodology.md",
        "wstg-info-03-methodology.md",
    ):
        (tmp_path / name).write_text(name, encoding="utf-8")

    batches = wstg_staged_batches(tmp_path, batch_size=2)

    assert [path.name for path in batches[0]] == [
        "wstg-athz-01-methodology.md",
        "wstg-inpv-05-methodology.md",
    ]
    assert [[path.name for path in batch] for batch in batches[1:]] == [
        ["wstg-info-01-methodology.md", "wstg-info-02-methodology.md"],
        ["wstg-info-03-methodology.md"],
    ]


def test_wstg_manifest_query_cases_use_manifest_titles_and_files(tmp_path):
    (tmp_path / ".manifest.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "wstg_id": "WSTG-INFO-02",
                        "title": "Fingerprint Web Server",
                        "primary_document": "wstg-info-02-methodology.md",
                    },
                    {
                        "wstg_id": "WSTG-INPV-05",
                        "title": "Testing for SQL Injection",
                        "primary_document": "wstg-inpv-05-methodology.md",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    scenarios = load_wstg_manifest_scenarios(tmp_path)
    cases = wstg_manifest_query_cases(
        tmp_path,
        file_names=["wstg-info-02-methodology.md"],
    )

    assert [scenario["primary_document"] for scenario in scenarios] == [
        "wstg-info-02-methodology.md",
        "wstg-inpv-05-methodology.md",
    ]
    assert len(cases) == 1
    assert cases[0].case_id == "wstg_scenario_wstg_info_02_methodology_md"
    assert cases[0].required_terms == ("wstg-info-02-methodology.md",)
    assert cases[0].required_any_terms == (
        ("Fingerprint Web Server", "Fingerprint", "Server"),
    )
    assert cases[0].hl_keywords == (
        "Fingerprint Web Server",
        "WSTG methodology",
        "wstg-info-02-methodology.md",
    )
    assert cases[0].ll_keywords == (
        "wstg-info-02-methodology.md",
        "Fingerprint Web Server",
        "Fingerprint",
        "Server",
    )


def test_run_query_cases_uses_context_gate_and_seeded_keywords():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def query(self, prompt, *, mode, extra):
            self.calls.append({"prompt": prompt, "mode": mode, "extra": extra})
            return {"response": "SQL Injection appears in wstg-inpv-05-methodology.md"}

    client = FakeClient()
    case = QueryCase(
        case_id="sql",
        prompt="sql prompt",
        required_terms=("SQL Injection",),
        required_source_files=("wstg-inpv-05-methodology.md",),
        hl_keywords=("SQL Injection", "WSTG methodology"),
        ll_keywords=("wstg-inpv-05-methodology.md", "UNION"),
    )

    evaluations = run_query_cases(client, (case,))

    assert evaluations[0].passed is True
    assert client.calls == [
        {
            "prompt": "sql prompt",
            "mode": "hybrid",
            "extra": {
                "top_k": 80,
                "chunk_top_k": 10,
                "max_total_tokens": 30000,
                "max_entity_tokens": 12000,
                "max_relation_tokens": 12000,
                "stream": False,
                "only_need_context": True,
                "hl_keywords": ["SQL Injection", "WSTG methodology"],
                "ll_keywords": ["wstg-inpv-05-methodology.md", "UNION"],
            },
        }
    ]


def test_run_staged_wstg_ingestion_uploads_batches_and_waits(tmp_path):
    first = tmp_path / "wstg-inpv-05-methodology.md"
    second = tmp_path / "wstg-inpv-05-6-methodology.md"
    first.write_text("sql", encoding="utf-8")
    second.write_text("nosql", encoding="utf-8")

    class FakeClient:
        base_url = "http://lightrag.test"
        api_key = ""

        def __init__(self):
            self.uploaded = []
            self.reset = []

        def delete_all_documents(self):
            self.reset.append("delete")
            return {"status": "success"}

        def clear_cache(self):
            self.reset.append("clear_cache")
            return {"status": "success"}

        def upload_file(self, path):
            self.uploaded.append(path.name)
            return {"track_id": f"upload-{len(self.uploaded)}"}

        def health(self):
            return {
                "pipeline_busy": False,
                "pipeline_active": False,
                "pipeline_pending_enqueues": 0,
            }

        def status_counts(self):
            return {
                "status_counts": {
                    "processed": len(self.uploaded),
                    "failed": 0,
                    "all": len(self.uploaded),
                }
            }

    client = FakeClient()
    result = run_staged_wstg_ingestion(
        client=client,
        batches=[[first], [second]],
        reset_store=True,
        normalize_types=False,
        run_graph=False,
        run_final_queries=False,
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert client.reset == ["delete", "clear_cache"]
    assert client.uploaded == ["wstg-inpv-05-methodology.md", "wstg-inpv-05-6-methodology.md"]
    assert [batch.processing.processed for batch in result.batches] == [1, 2]
    assert result.batches[0].upload_responses[0]["track_id"] == "upload-1"
    assert result.passed is True


def test_run_staged_wstg_ingestion_logs_batch_history(tmp_path):
    first = tmp_path / "wstg-inpv-05-methodology.md"
    first.write_text("sql", encoding="utf-8")

    class FakeClient:
        base_url = "http://lightrag.test"
        api_key = ""

        def __init__(self):
            self.uploaded = []

        def upload_file(self, path):
            self.uploaded.append(path.name)
            return {"track_id": "upload-sql"}

        def health(self):
            return {
                "pipeline_busy": False,
                "pipeline_active": False,
                "pipeline_pending_enqueues": 0,
            }

        def status_counts(self):
            return {
                "status_counts": {
                    "processed": len(self.uploaded),
                    "failed": 0,
                    "all": len(self.uploaded),
                }
            }

    with ExperimentTracker(tmp_path / "history.sqlite3") as tracker:
        result = run_staged_wstg_ingestion(
            client=FakeClient(),
            batches=[[first]],
            normalize_types=False,
            run_graph=False,
            run_final_queries=False,
            timeout_seconds=1,
            poll_seconds=0,
            tracker=tracker,
            run_label="qa-rebuild",
        )
        records = list(tracker.iter_ingestion_batches(run_label="qa-rebuild"))

    assert result.passed is True
    assert records[0].uploaded_files == ["wstg-inpv-05-methodology.md"]
    assert records[0].metrics["track_ids"] == ["upload-sql"]
    assert records[0].passed is True


def test_graph_gate_validates_required_entities_types_and_sources(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <key id="d2" for="node" attr.name="source_id" attr.type="string"/>
  <key id="d3" for="node" attr.name="file_path" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="SQL Injection">
      <data key="d0">SQL Injection</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">chunk-1</data>
      <data key="d3">wstg-inpv-05-methodology.md</data>
    </node>
    <node id="NoSQL Injection">
      <data key="d0">NoSQL Injection</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">chunk-2</data>
      <data key="d3">wstg-inpv-05-6-methodology.md</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    result = evaluate_graph_gate(
        graphml,
        required_entity_types={
            "SQL Injection": "VulnerabilityClass",
            "NoSQL Injection": "VulnerabilityClass",
        },
        required_source_files={
            "SQL Injection": "wstg-inpv-05-methodology.md",
            "NoSQL Injection": "wstg-inpv-05-6-methodology.md",
        },
    )

    assert result.passed is True
    assert result.unknown_type_count == 0
    assert result.missing_required_entities == []


def test_graph_gate_accepts_expected_wstg_entity_aliases(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <key id="d2" for="node" attr.name="file_path" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Ldap Injection">
      <data key="d0">Ldap Injection</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">wstg-inpv-06-methodology.md</data>
    </node>
    <node id="Reflected Cross-Site Scripting (XSS)">
      <data key="d0">Reflected Cross-Site Scripting (XSS)</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">wstg-inpv-01-methodology.md</data>
    </node>
    <node id="XML Injection">
      <data key="d0">XML Injection</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">wstg-inpv-07-methodology.md</data>
    </node>
    <node id="ServerSide Request Forgery">
      <data key="d0">ServerSide Request Forgery</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">wstg-inpv-19-methodology.md</data>
    </node>
    <node id="Server-Side Request Forgery">
      <data key="d0">Server-Side Request Forgery</data>
      <data key="d1">VulnerabilityClass</data>
      <data key="d2">wstg-athz-05-1-methodology.md</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    result = evaluate_graph_gate(
        graphml,
        required_entity_types={
            "LDAP Injection": "VulnerabilityClass",
            "Reflected Cross-Site Scripting": "VulnerabilityClass",
            "XML Injection": "VulnerabilityClass",
            "Server-Side Request Forgery": "VulnerabilityClass",
        },
        required_source_files={
            "LDAP Injection": "wstg-inpv-06-methodology.md",
            "Reflected Cross-Site Scripting": "wstg-inpv-01-methodology.md",
            "XML Injection": "wstg-inpv-07-methodology.md",
            "Server-Side Request Forgery": "wstg-inpv-19-methodology.md",
        },
    )

    assert result.passed is True
    assert result.missing_required_entities == []
    assert result.missing_required_source_files == []


def test_graph_gate_reports_wrong_source_and_missing_entity(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <key id="d2" for="node" attr.name="file_path" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="SQL Injection">
      <data key="d0">SQL Injection</data>
      <data key="d1">AttackTechnique</data>
      <data key="d2">wrong.md</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    result = evaluate_graph_gate(
        graphml,
        required_entity_types={
            "SQL Injection": "VulnerabilityClass",
            "NoSQL Injection": "VulnerabilityClass",
        },
        required_source_files={"SQL Injection": "wstg-inpv-05-methodology.md"},
    )

    assert result.passed is False
    assert result.missing_required_entities == ["NoSQL Injection"]
    assert result.wrong_required_entity_types == [
        {
            "name": "SQL Injection",
            "actual_type": "AttackTechnique",
            "canonical_actual_type": "AttackTechnique",
            "expected_type": "VulnerabilityClass",
        }
    ]
    assert result.missing_required_source_files == [
        {
            "name": "SQL Injection",
            "expected_source_file": "wstg-inpv-05-methodology.md",
            "actual_source_files": ["wrong.md"],
        }
    ]
