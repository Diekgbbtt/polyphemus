import hashlib
import json
import base64
from types import SimpleNamespace

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.code_search import (
    CodeSearchError,
    CodeSearchService,
)
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)


def _fixture(tmp_path):
    ensure_project("p", root=tmp_path)
    generated = (
        "const first = 'alpha';\r\n"
        "const API = 'upper';\r\n"
        + "x".join(["alpha"] * 20)
        + "\r\n"
    ).encode()
    JsIntakeStore(root=tmp_path).record_exec_result(
        project_id="p",
        run_id="r",
        pod_id="pod",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {"endpoint": "https://app.test/app.js"},
                    "response": {
                        "status_code": 200,
                        "headers": {"Content-Type": "application/javascript"},
                    },
                }
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="account-a",
    )
    reference = issue_js_intake_reference("p", "r", context_ref="account-a")
    lead_id = JsIntakeReader(root=tmp_path).list(reference=reference)["leads"][0][
        "lead_id"
    ]
    digest = hashlib.sha256(generated).hexdigest()
    work_ref = f"/work/js-analysis/r/{digest}.js"
    manifest = AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "account-a"},
        work_file_ref=work_ref,
        sha256=digest,
        size=len(generated),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(generated),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    recovered = b"export const alpha = true;\n"
    recovered_digest = hashlib.sha256(recovered).hexdigest()
    manifest.update(
        lambda value: value.setdefault("recovery", {}).setdefault("sources", {}).update(
            {
                "src_a": {
                    "source_id": "src_a",
                    "lead_id": lead_id,
                    "context_ref": "account-a",
                    "kind": "typescript",
                    "content_state": "text",
                    "content_sha256": recovered_digest,
                    "size": len(recovered),
                    "work_file_ref": (
                        f"/work/js-analysis/r/recovered/{recovered_digest}.js"
                    ),
                    "status": "available",
                    "available": True,
                },
                "src_b": {
                    "source_id": "src_b",
                    "lead_id": lead_id,
                    "context_ref": "account-a",
                    "kind": "vue",
                    "content_state": "text",
                    "content_sha256": recovered_digest,
                    "size": len(recovered),
                    "work_file_ref": (
                        f"/work/js-analysis/r/recovered/{recovered_digest}.js"
                    ),
                    "status": "available",
                    "available": True,
                },
            }
        )
    )
    contents = {
        lead_id: generated,
        "src_a": recovered,
        "src_b": recovered,
    }
    return lead_id, reference, contents


def test_literal_search_is_exact_scoped_and_preserves_duplicate_provenance(tmp_path):
    lead_id, reference, contents = _fixture(tmp_path)
    service = CodeSearchService(root=tmp_path)

    result = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=30,
    )
    upper = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="ALPHA",
        contents=contents,
        limit=30,
    )
    recovered = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="true",
        contents=contents,
        limit=10,
    )

    source_ids = {match["source"]["source_id"] for match in recovered["matches"]}
    assert result["status"] == "complete"
    assert result["total_matches"] == 23
    assert source_ids == {"src_a", "src_b"}
    assert upper["total_matches"] == 0
    assert upper["status"] == "complete"
    assert all(match["source"]["kind"] for match in result["matches"])
    assert all("alpha" in match["redacted_preview"].lower() for match in result["matches"])


def test_search_pagination_cursor_is_bound_and_query_limits_are_enforced(tmp_path):
    lead_id, reference, contents = _fixture(tmp_path)
    service = CodeSearchService(root=tmp_path)
    first = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=2,
    )
    second = service.results(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        cursor=first["next_cursor"],
        limit=2,
    )
    foreign = issue_js_intake_reference("p", "r", context_ref="account-b")

    assert len(first["matches"]) == 2
    assert second["matches"]
    assert {m["match_id"] for m in first["matches"]}.isdisjoint(
        {m["match_id"] for m in second["matches"]}
    )
    with pytest.raises(CodeSearchError) as cursor:
        service.results(
            reference=foreign,
            lead_id=lead_id,
            text="alpha",
            cursor=first["next_cursor"],
            limit=2,
        )
    assert cursor.value.reason in {
        "search_outside_context",
        "invalid_search_cursor",
    }
    with pytest.raises(CodeSearchError) as short:
        service.search_from_contents(
            reference=reference,
            lead_id=lead_id,
            text="a",
            contents=contents,
        )
    assert short.value.reason == "invalid_search_literal"
    with pytest.raises(CodeSearchError) as long:
        service.search_from_contents(
            reference=reference,
            lead_id=lead_id,
            text="a" * 129,
            contents=contents,
        )
    assert long.value.reason == "invalid_search_literal"

    inventory = service.source_inventory(
        reference=reference,
        lead_id=lead_id,
        limit=2,
    )
    inventory_next = service.source_inventory(
        reference=reference,
        lead_id=lead_id,
        cursor=inventory["next_cursor"],
        limit=2,
    )
    assert len(inventory["sources"]) == 2
    assert len(inventory_next["sources"]) == 1
    assert inventory["total_sources"] == 3


def test_partial_byte_limit_and_changed_snapshot_are_explicit(tmp_path):
    lead_id, reference, contents = _fixture(tmp_path)
    service = CodeSearchService(root=tmp_path)
    partial = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        max_examined_bytes=len(contents[lead_id]),
        limit=30,
    )
    assert partial["status"] == "partial"
    assert partial["coverage_gap"] == "examined_byte_limit"
    assert partial["examined_bytes"] == len(contents[lead_id])
    assert partial["scan_resume_cursor"]
    resumed = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents={"src_a": contents["src_a"], "src_b": contents["src_b"]},
        resume_cursor=partial["scan_resume_cursor"],
        limit=10,
    )
    assert resumed["status"] == "complete"
    assert resumed["total_matches"] == 23
    complete = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=2,
    )
    AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    ).update(
        lambda value: value["leads"][lead_id].update({"sha256": "f" * 64})
    )
    with pytest.raises(CodeSearchError) as stale:
        service.results(
            reference=reference,
            lead_id=lead_id,
            text="alpha",
            cursor=complete["next_cursor"],
            limit=2,
        )
    assert stale.value.reason == "stale_search_snapshot"


def test_search_rejects_content_not_in_snapshot_and_keeps_query_private(tmp_path):
    lead_id, reference, contents = _fixture(tmp_path)
    service = CodeSearchService(root=tmp_path)
    wrong = dict(contents)
    wrong[lead_id] = contents[lead_id] + b"tampered"

    with pytest.raises(CodeSearchError) as mismatch:
        service.search_from_contents(
            reference=reference,
            lead_id=lead_id,
            text="alpha",
            contents=wrong,
            limit=5,
        )
    assert mismatch.value.reason == "search_content_mismatch"

    result = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=1,
    )
    assert result["query_sha256"]
    assert "alpha" not in json.dumps(
        {key: value for key, value in result.items() if key != "matches"}
    )


def test_corrupt_persisted_search_record_is_not_treated_as_current(tmp_path):
    lead_id, reference, contents = _fixture(tmp_path)
    service = CodeSearchService(root=tmp_path)
    result = service.search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=2,
    )
    record_path = (
        tmp_path
        / "p"
        / "recon"
        / "js_analysis"
        / "r"
        / "code_searches"
        / f"{result['search_id']}.json"
    )
    document = json.loads(record_path.read_text())
    document["matches"][0]["start_byte"] += 1
    record_path.write_text(json.dumps(document))

    with pytest.raises(CodeSearchError) as corrupt:
        service.results(
            reference=reference,
            lead_id=lead_id,
            text="alpha",
            cursor=result["next_cursor"],
            limit=2,
        )
    assert corrupt.value.reason == "search_record_corrupt"


def test_search_prepares_redaction_once_per_file_not_per_match(
    tmp_path, monkeypatch
):
    from polymerhus.recon.js_acquisition import code_search

    lead_id, reference, contents = _fixture(tmp_path)
    provider = code_search.prepare_redaction
    prepared_ids = []

    def counted(source):
        prepared_ids.append(hashlib.sha256(source).hexdigest())
        return provider(source)

    monkeypatch.setattr(code_search, "prepare_redaction", counted)
    result = code_search.CodeSearchService(root=tmp_path).search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=10,
    )

    assert result["total_matches"] == 23
    assert len(prepared_ids) == 2
    assert len(set(prepared_ids)) == 2


def _single_source_fixture(tmp_path):
    ensure_project("p", root=tmp_path)
    generated = b"alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha\n"
    JsIntakeStore(root=tmp_path).record_exec_result(
        project_id="p",
        run_id="r",
        pod_id="pod",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {"endpoint": "https://app.test/app.js"},
                    "response": {
                        "status_code": 200,
                        "headers": {"Content-Type": "application/javascript"},
                    },
                }
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="account-a",
    )
    reference = issue_js_intake_reference("p", "r", context_ref="account-a")
    lead_id = JsIntakeReader(root=tmp_path).list(reference=reference)["leads"][0][
        "lead_id"
    ]
    digest = hashlib.sha256(generated).hexdigest()
    manifest = AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "account-a"},
        work_file_ref=f"/work/js-analysis/r/{digest}.js",
        sha256=digest,
        size=len(generated),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(generated),
        sha256=digest,
        work_file_ref=f"/work/js-analysis/r/{digest}.js",
    ) == "acquired"
    return lead_id, reference, {lead_id: generated}


def test_deadline_mid_file_resumes_without_lost_or_duplicate_matches(
    tmp_path, monkeypatch
):
    from polymerhus.recon.js_acquisition import code_search

    lead_id, reference, contents = _single_source_fixture(tmp_path)
    provider = code_search.prepare_redaction
    clock = SimpleNamespace(now=0.0)

    class TimedPrepared:
        def __init__(self, prepared):
            self.prepared = prepared

        def window(self, start, end):
            result = self.prepared.window(start, end)
            clock.now += 0.1
            return result

    def timed(source):
        return TimedPrepared(provider(source))

    monkeypatch.setattr(code_search, "prepare_redaction", timed)
    partial = code_search.CodeSearchService(
        root=tmp_path,
        clock=lambda: clock.now,
    ).search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        limit=10,
        deadline_s=0.25,
    )

    assert partial["status"] == "partial"
    assert partial["coverage_gap"] == "search_deadline"
    assert partial["scan_resume_cursor"]
    assert 0 < len(partial["matches"]) < 10

    encoded = base64.urlsafe_b64decode(
        partial["scan_resume_cursor"]
        + "=" * (-len(partial["scan_resume_cursor"]) % 4)
    )
    body = json.loads(encoded[:-8])
    body.pop("match_offset")
    legacy_body = json.dumps(body, separators=(",", ":")).encode()
    legacy_digest = hashlib.sha256(
        f"{body['search_id']}\0account-a".encode() + legacy_body
    ).digest()[:8]
    legacy_cursor = base64.urlsafe_b64encode(
        legacy_body + legacy_digest
    ).decode().rstrip("=")

    monkeypatch.setattr(code_search, "prepare_redaction", provider)
    resumed = code_search.CodeSearchService(
        root=tmp_path,
        clock=lambda: 0.0,
    ).search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text="alpha",
        contents=contents,
        resume_cursor=legacy_cursor,
        limit=10,
    )

    assert resumed["status"] == "complete"
    assert resumed["total_matches"] == 10
    assert resumed["examined_bytes"] == len(contents[lead_id])
    assert len({m["match_id"] for m in resumed["matches"]}) == len(
        resumed["matches"]
    )
    assert {
        match["match_id"] for match in partial["matches"]
    }.issubset(
        {match["match_id"] for match in resumed["matches"]}
    )


def test_preview_aligns_utf8_boundaries_and_preserves_match_offsets():
    from polymerhus.recon.js_acquisition import code_search

    content = ("😀" * 80 + "\r\nalpha\r\n" + "😀" * 80).encode()
    start = content.index(b"alpha")
    end = start + len(b"alpha")
    prepared = code_search.prepare_redaction(content)

    preview = code_search.CodeSearchService._match_preview(
        content,
        start,
        end,
        prepared,
    )

    assert "alpha" in preview
    assert content[start:end] == b"alpha"
