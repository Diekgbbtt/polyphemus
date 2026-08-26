from lightrag.experiment_tracker import ExperimentTracker


def test_experiment_tracker_persists_and_reads_runs(tmp_path):
    db_path = tmp_path / "history.sqlite3"
    with ExperimentTracker(db_path) as tracker:
        experiment_id = tracker.log_run(
            test_case_id="case-1",
            run_label="baseline-before-reingest",
            abstracted_profile={"frontend": ["React"], "auth": "JWT"},
            query_template_type="feature_to_threat",
            query_payload={"query": "map profile", "mode": "hybrid", "top_k": 40},
            lightrag_config={
                "mode": "hybrid",
                "top_k": 40,
                "max_tokens": 12000,
                "temperature": 0,
            },
            retrieved_subgraph={"entities": [{"id": "WSTG-CLNT-12"}]},
            raw_response="Use WSTG-CLNT-12 for browser storage checks.",
            metrics={"wstg_code_recall": 1.0, "latency_ms": 12.5},
            timestamp="2026-07-30T10:00:00+00:00",
        )

    with ExperimentTracker(db_path) as tracker:
        record = tracker.get_run(experiment_id)
        assert record is not None
        assert record.run_label == "baseline-before-reingest"
        assert record.test_case_id == "case-1"
        assert record.abstracted_profile["frontend"] == ["React"]
        assert record.query_payload["mode"] == "hybrid"
        assert record.retrieved_subgraph["entities"][0]["id"] == "WSTG-CLNT-12"
        assert record.metrics["wstg_code_recall"] == 1.0


def test_experiment_tracker_filters_runs(tmp_path):
    with ExperimentTracker(tmp_path / "history.sqlite3") as tracker:
        tracker.log_run(
            test_case_id="case-a",
            run_label="baseline",
            abstracted_profile={},
            query_template_type="feature_to_threat",
            query_payload={},
            lightrag_config={},
            retrieved_subgraph={},
            raw_response="response",
            metrics={},
            timestamp="2026-07-30T10:00:00+00:00",
        )
        tracker.log_run(
            test_case_id="case-b",
            run_label="after-reingest",
            abstracted_profile={},
            query_template_type="step_by_step_methodology",
            query_payload={},
            lightrag_config={},
            retrieved_subgraph={},
            raw_response="response",
            metrics={},
            timestamp="2026-07-30T10:01:00+00:00",
        )

        assert [record.test_case_id for record in tracker.iter_runs()] == [
            "case-a",
            "case-b",
        ]
        assert [
            record.test_case_id
            for record in tracker.iter_runs(query_template_type="feature_to_threat")
        ] == ["case-a"]
        assert [
            record.test_case_id for record in tracker.iter_runs(run_label="after-reingest")
        ] == ["case-b"]


def test_experiment_tracker_persists_ingestion_batches(tmp_path):
    db_path = tmp_path / "history.sqlite3"
    with ExperimentTracker(db_path) as tracker:
        event_id = tracker.log_ingestion_batch(
            batch_number=2,
            run_label="clean-rebuild",
            input_dir="data/lightrag/inputs/wstg_preprocessed",
            uploaded_files=["wstg-apit-99-methodology.md"],
            upload_responses=[
                {
                    "file_name": "wstg-apit-99-methodology.md",
                    "track_id": "upload-1",
                    "response": {"track_id": "upload-1"},
                }
            ],
            processing={"processed": 1, "failed": 0, "complete": True},
            normalization={"updated": 3},
            graph_gate={"passed": True},
            query_evaluations=[{"case_id": "graphql", "passed": True}],
            metrics={"uploaded_file_count": 1, "track_ids": ["upload-1"]},
            passed=True,
            timestamp="2026-07-30T11:00:00+00:00",
        )

    with ExperimentTracker(db_path) as tracker:
        records = list(tracker.iter_ingestion_batches(run_label="clean-rebuild"))

    assert records[0].ingestion_event_id == event_id
    assert records[0].batch_number == 2
    assert records[0].uploaded_files == ["wstg-apit-99-methodology.md"]
    assert records[0].upload_responses[0]["track_id"] == "upload-1"
    assert records[0].processing["complete"] is True
    assert records[0].passed is True
