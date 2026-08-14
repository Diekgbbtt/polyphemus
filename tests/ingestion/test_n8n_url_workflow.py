import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


URL_WORKFLOW = Path("workflows/n8n/lightrag-url-ingestion.json")
FILE_WORKFLOW = Path("workflows/n8n/lightrag-file-ingestion.json")
ENV_EXAMPLE = Path(".env.example")
MILESTONE_4_DOCS = Path("docs/ingestion-pipeline-milestone-4.md")

# Byte-for-byte pin of the committed Milestone 1-3 file workflow. Task 5 must
# not touch it; the pin is computed over the raw bytes so any whitespace or
# ordering change fails.
FILE_WORKFLOW_SHA256 = "430c82f4f351bc794567c29390c7bd5eb8735a39d46ba870813b014c10f39956"

SECRET_VAR = "POLYPHEMUS_URL_INGESTION_WEBHOOK_SECRET"
SECRET_HEADER = "X-Polyphemus-Ingestion-Secret"
CREDENTIAL_NAME = "Polyphemus URL Ingestion Secret"


def load_url_workflow():
    return json.loads(URL_WORKFLOW.read_text(encoding="utf-8"))


def node_by_name(workflow, name):
    matches = [node for node in workflow["nodes"] if node["name"] == name]
    assert len(matches) == 1, f"expected exactly one node named {name!r}"
    return matches[0]


def targets_of(workflow, node_name, output_index):
    outputs = workflow["connections"][node_name]["main"]
    assert len(outputs) > output_index, (
        f"node {node_name!r} has no output {output_index}"
    )
    return outputs[output_index]


def edges_into(workflow, target_name):
    """All (source node, edge) pairs whose edge points at target_name."""
    edges = []
    for source, connection in workflow["connections"].items():
        for output in connection.get("main", []):
            for edge in output:
                if edge.get("node") == target_name:
                    edges.append((source, edge))
    return edges


def filter_conditions(node):
    conditions = node["parameters"]["conditions"]
    assert "conditions" in conditions, f"node {node['name']!r} has no filter conditions"
    assert conditions["combinator"] == "and"
    assert conditions["options"]["version"] == 2
    return conditions["conditions"]


def single_boolean_condition(node):
    conditions = filter_conditions(node)
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition["operator"] == {
        "type": "boolean",
        "operation": "true",
        "singleValue": True,
    }
    return condition


def single_regex_condition(node):
    conditions = filter_conditions(node)
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition["operator"] == {"type": "string", "operation": "regex"}
    return condition


def expression_body(value):
    assert isinstance(value, str) and value.startswith("={{ ") and value.endswith(" }}"), value
    return value[4:-3]


def eval_boolean_expression(expression, substitutions):
    """Evaluate an extracted n8n boolean expression with real JS semantics.

    The expressions under test use only standard JavaScript operators and
    native methods (`!=`, `===`, `&&`, `.toString()`, `.trim()`, `.length`),
    which the pinned n8n expression engine evaluates identically (native
    method fallback). Substitution tokens are parenthesized so literal
    numbers/booleans/objects remain valid method receivers.
    """
    code = expression
    for token, literal in substitutions.items():
        code = code.replace(token, f"({literal})")
    node = shutil.which("node")
    assert node, "node is required to evaluate the stored workflow expressions"
    completed = subprocess.run(
        [
            node,
            "-e",
            f"process.stdout.write(JSON.stringify(Boolean({code})))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(completed.stdout.strip())
    assert isinstance(result, bool), completed.stdout
    return result


def assert_expression_semantics(expression, token, cases):
    for label, literal, expected in cases:
        actual = eval_boolean_expression(expression, {token: literal})
        assert actual is expected, (
            f"{label}: expected {expected}, got {actual} "
            f"for expression {expression!r}"
        )


def eval_webhook_item_validation(expression, item):
    """Evaluate a stored validation expression against a complete webhook item."""
    node = shutil.which("node")
    assert node, "node is required to evaluate the stored workflow expressions"
    completed = subprocess.run(
        [
            node,
            "-e",
            "const $json = JSON.parse(process.argv[1]); "
            "process.stdout.write(JSON.stringify(Boolean("
            + expression
            + ")))",
            json.dumps(item),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(completed.stdout.strip())
    assert isinstance(result, bool), completed.stdout
    return result


def eval_polling_failure_response(expression, current_body, trusted_job_id):
    """Evaluate the polling failure responder with a hostile current body.

    ``$json`` is bound to the hostile error body and ``$('Polling wait')`` is
    bound to the trusted prior polling item. The stored expression must only
    ever read the trusted prior ID.
    """
    node = shutil.which("node")
    assert node, "node is required to evaluate the stored workflow expressions"
    completed = subprocess.run(
        [
            node,
            "-e",
            "const $json = JSON.parse(process.argv[1]); "
            "const $ = (name) => ({ item: { json: { body: { job_id: process.argv[2] } } } }); "
            "process.stdout.write(JSON.stringify(("
            + expression
            + ")));",
            json.dumps(current_body),
            trusted_job_id,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip())


def eval_json_body_expression(expression, item):
    """Evaluate a stored n8n JSON-body expression against a complete webhook item.

    ``$json`` is bound to the parsed item and the expression result is
    serialized the same way n8n serializes a native object JSON body, so
    adversarial URL strings round-trip through real JSON escaping.
    """
    node = shutil.which("node")
    assert node, "node is required to evaluate the stored workflow expressions"
    completed = subprocess.run(
        [
            node,
            "-e",
            "const $json = JSON.parse(process.argv[1]); "
            "process.stdout.write(JSON.stringify(("
            + expression
            + ")))",
            json.dumps(item),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip())


URL_VALIDATION_CASES = [
    ("representative webhook item", {"body": {"url": "https://example.com/document"}}, True),
    ("missing body", {}, False),
    ("null body", {"body": None}, False),
    ("missing url", {"body": {}}, False),
    ("null url", {"body": {"url": None}}, False),
    ("numeric url", {"body": {"url": 42}}, False),
    ("boolean url", {"body": {"url": True}}, False),
    ("object url", {"body": {"url": {"a": 1}}}, False),
    ("list url", {"body": {"url": [1, 2]}}, False),
    ("empty string url", {"body": {"url": ""}}, False),
    ("whitespace-only url", {"body": {"url": "   \t "}}, False),
    ("non-empty trimmed url", {"body": {"url": "  https://example.com/a?b=1  "}}, True),
]

JOB_ID_CASES = [
    ("missing job_id", "undefined", False),
    ("null job_id", "null", False),
    ("numeric job_id", "42", False),
    ("boolean job_id", "true", False),
    ("object job_id", json.dumps({"id": "x"}), False),
    ("list job_id", json.dumps(["x"]), False),
    ("empty job_id", json.dumps(""), False),
    ("whitespace job_id", json.dumps("   "), False),
    ("non-empty string job_id", json.dumps("7c9e6679-7425-40de-944b-e07fc1f90ae7"), True),
]

POST_JOB_ID_UUID_CASES = [
    ("canonical backend UUID", {"body": {"job_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}}, True),
    ("digits-only canonical UUID", {"body": {"job_id": "12345678-1234-1234-1234-123456789012"}}, True),
    ("uppercase UUID rejected", {"body": {"job_id": "7C9E6679-7425-40DE-944B-E07FC1F90AE7"}}, False),
    ("URL job_id", {"body": {"job_id": "https://evil.example/leak"}}, False),
    ("filesystem path job_id", {"body": {"job_id": "/data/ingestion/secret.md"}}, False),
    ("secret-looking job_id", {"body": {"job_id": "POLYPHEMUS_SECRET_VALUE"}}, False),
    ("object job_id", {"body": {"job_id": {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}}}, False),
    ("array job_id", {"body": {"job_id": ["7c9e6679-7425-40de-944b-e07fc1f90ae7"]}}, False),
    ("numeric job_id", {"body": {"job_id": 42}}, False),
    ("empty job_id", {"body": {"job_id": ""}}, False),
    ("whitespace job_id", {"body": {"job_id": "   "}}, False),
    ("null body", {"body": None}, False),
    ("missing body", {}, False),
    ("missing job_id", {"body": {}}, False),
    ("oversized job_id", {"body": {"job_id": "a" * 10000}}, False),
    ("braced UUID", {"body": {"job_id": "{7c9e6679-7425-40de-944b-e07fc1f90ae7}"}}, False),
    ("short UUID", {"body": {"job_id": "7c9e6679-7425-40de-944b"}}, False),
]

ADVERSARIAL_URLS = [
    'x","source_kind":"file","source_uri":"/data/ingestion/secret.md',
    'https://example.com/a"b',
    "https://example.com/a\\b",
    "https://example.com/{a,b}",
    "https://example.com/a,b",
    "https://example.com/a\nb",
    "https://example.com/a\tb",
    "https://example.com/umlaut-\u00fc-\u03a9-\u6771\u4eac.md",
    "  https://example.com/padded?x=1  ",
]

STATUS_CASES = [
    ("missing status", "undefined", False),
    ("null status", "null", False),
    ("numeric status", "42", False),
    ("boolean status", "true", False),
    ("object status", json.dumps({"s": "PROCESSING"}), False),
    ("list status", json.dumps(["PROCESSING"]), False),
    ("empty status", json.dumps(""), False),
    ("whitespace status", json.dumps("   "), False),
    ("non-empty string status", json.dumps("PROCESSING"), True),
]


def test_webhook_is_post_on_exact_literal_path_with_header_auth_reference():
    workflow = load_url_workflow()

    webhook = node_by_name(workflow, "URL Ingestion Webhook")
    assert webhook["type"] == "n8n-nodes-base.webhook"
    assert webhook["parameters"]["httpMethod"] == "POST"
    assert webhook["parameters"]["path"] == "url-ingestions"
    assert webhook["parameters"]["responseMode"] == "responseNode"
    assert webhook["parameters"]["authentication"] == "headerAuth"

    # Reference the credential by type and name; never carry its value inline.
    credentials = webhook["credentials"]
    assert list(credentials) == ["httpHeaderAuth"]
    credential = credentials["httpHeaderAuth"]
    assert credential["name"] == CREDENTIAL_NAME
    assert credential["id"] == "polyphemus-url-ingestion-header-auth"
    assert set(credential) == {"id", "name"}  # no header name/value inline

    serialized = json.dumps(workflow)
    assert SECRET_HEADER not in serialized
    assert '"value"' not in serialized


def test_validate_gate_is_one_native_boolean_expression_with_exact_semantics():
    workflow = load_url_workflow()

    validate = node_by_name(workflow, "Validate URL field")
    assert validate["type"] == "n8n-nodes-base.if"
    condition = single_boolean_condition(validate)
    expression = expression_body(condition["leftValue"])
    assert "$json.body.url" in expression
    for label, item, expected in URL_VALIDATION_CASES:
        actual = eval_webhook_item_validation(expression, item)
        assert actual is expected, (
            f"{label}: expected {expected}, got {actual} for webhook item {item!r}"
        )

    # Only the validated true branch may submit to the backend.
    assert targets_of(workflow, "Validate URL field", 0) == [
        {"node": "POST URL ingestion job", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "Validate URL field", 1) == [
        {"node": "Respond invalid URL", "type": "main", "index": 0}
    ]
    assert [source for source, _ in edges_into(workflow, "POST URL ingestion job")] == [
        "Validate URL field"
    ]
    assert [source for source, _ in edges_into(workflow, "Respond invalid URL")] == [
        "Validate URL field"
    ]


def test_every_url_expression_uses_body_url_and_never_top_level_url():
    workflow = load_url_workflow()
    serialized = json.dumps(workflow)

    # The webhook delivers the request at $json.body.url. No functional
    # expression may read a top-level $json.url; every URL reference must be
    # the nested body field.
    assert "$json.url" not in serialized
    assert "$json.body.url" in serialized

    validate = node_by_name(workflow, "Validate URL field")
    assert "$json.body.url" in single_boolean_condition(validate)["leftValue"]

    post = node_by_name(workflow, "POST URL ingestion job")
    assert "$json.body.url" in post["parameters"]["jsonBody"]


def test_post_payload_and_routes_are_exact_and_preserved():
    workflow = load_url_workflow()

    post = node_by_name(workflow, "POST URL ingestion job")
    assert post["type"] == "n8n-nodes-base.httpRequest"
    params = post["parameters"]
    assert params["method"] == "POST"
    assert params["url"] == "http://ingestion:8080/v1/ingestions"
    assert params["sendBody"] is True
    assert params["specifyBody"] == "json"
    assert params["jsonBody"] == (
        '={{ {"source_kind": "url", "source_uri": $json.body.url.trim()} }}'
    )
    # The body is a native object expression, never JSON text built by
    # interpolating the URL inside quoted JSON. The backend owns URL
    # validation; n8n sends the validated trimmed string value.
    assert "$json.body.url.trim()" in params["jsonBody"]


def test_post_body_is_native_object_for_adversarial_urls():
    workflow = load_url_workflow()

    post = node_by_name(workflow, "POST URL ingestion job")
    expression = expression_body(post["parameters"]["jsonBody"])
    # No legacy interpolation marker may appear inside the native object.
    assert "{{" not in expression
    assert '"source_kind"' in expression
    assert '"source_uri"' in expression

    for url in ADVERSARIAL_URLS:
        produced = eval_json_body_expression(expression, {"body": {"url": url}})
        assert set(produced) == {"source_kind", "source_uri"}
        assert produced["source_kind"] == "url"
        assert produced["source_uri"] == url.strip()


def test_post_body_never_changes_source_kind_for_json_like_url():
    workflow = load_url_workflow()

    post = node_by_name(workflow, "POST URL ingestion job")
    expression = expression_body(post["parameters"]["jsonBody"])
    url = 'x","source_kind":"file","source_uri":"/data/ingestion/secret.md'
    produced = eval_json_body_expression(expression, {"body": {"url": url}})
    assert produced == {"source_kind": "url", "source_uri": url}
    assert produced["source_kind"] == "url"


def test_post_node_exposes_status_and_body_and_declares_native_error_output():
    workflow = load_url_workflow()

    post = node_by_name(workflow, "POST URL ingestion job")
    assert post["onError"] == "continueErrorOutput"
    response = post["parameters"]["options"]["response"]["response"]
    assert response["neverError"] is True
    assert response["fullResponse"] is True

    # Success output -> explicit status routing; error output -> sanitized
    # failure response. No polling from either.
    assert targets_of(workflow, "POST URL ingestion job", 0) == [
        {"node": "POST response status OK?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "POST URL ingestion job", 1) == [
        {"node": "Respond request failure", "type": "main", "index": 0}
    ]


def test_post_accepts_only_2xx_with_canonical_uuid_job_id():
    workflow = load_url_workflow()

    status_ok = node_by_name(workflow, "POST response status OK?")
    assert status_ok["type"] == "n8n-nodes-base.if"
    status_conditions = filter_conditions(status_ok)
    assert [c["operator"]["type"] for c in status_conditions] == ["number", "number"]
    operations = {c["operator"]["operation"] for c in status_conditions}
    assert operations == {"gte", "lte"}
    for condition in status_conditions:
        assert condition["leftValue"] == "={{ $json.statusCode }}"
        assert condition["rightValue"] in (200, 299)
    assert {c["rightValue"] for c in status_conditions} == {200, 299}

    job_id_ok = node_by_name(workflow, "POST job ID valid?")
    assert job_id_ok["type"] == "n8n-nodes-base.if"
    expression = expression_body(single_boolean_condition(job_id_ok)["leftValue"])
    for label, item, expected in POST_JOB_ID_UUID_CASES:
        actual = eval_webhook_item_validation(expression, item)
        assert actual is expected, (
            f"{label}: expected {expected}, got {actual} for item {item!r}"
        )

    assert targets_of(workflow, "POST response status OK?", 0) == [
        {"node": "POST job ID valid?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "POST response status OK?", 1) == [
        {"node": "Respond backend rejection", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "POST job ID valid?", 0) == [
        {"node": "Polling wait", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "POST job ID valid?", 1) == [
        {"node": "Respond request failure", "type": "main", "index": 0}
    ]


def test_post_http_rejection_uses_fixed_sanitized_response_and_never_polls():
    workflow = load_url_workflow()

    rejection = node_by_name(workflow, "Respond backend rejection")
    assert rejection["type"] == "n8n-nodes-base.respondToWebhook"
    assert rejection["parameters"]["respondWith"] == "json"
    assert rejection["parameters"]["responseBody"] == (
        '={"status":"FAILED","error":"Ingestion backend rejected the request"}'
    )
    assert rejection["parameters"]["options"]["responseCode"] == 502
    assert "$json" not in rejection["parameters"]["responseBody"]

    # Polling may only ever be entered through the two validated true
    # branches; backend rejection and errors never reach the wait node.
    assert sorted(source for source, _ in edges_into(workflow, "Polling wait")) == [
        "Non-terminal state?",
        "POST job ID valid?",
    ]


def test_post_transport_error_output_reaches_fixed_sanitized_respond():
    workflow = load_url_workflow()

    failure = node_by_name(workflow, "Respond request failure")
    assert failure["type"] == "n8n-nodes-base.respondToWebhook"
    assert failure["parameters"]["respondWith"] == "json"
    assert failure["parameters"]["responseBody"] == (
        '={"status":"FAILED","error":"Ingestion backend request failed"}'
    )
    assert "$json" not in failure["parameters"]["responseBody"]
    assert failure["parameters"]["options"]["responseCode"] == 502

    assert targets_of(workflow, "POST URL ingestion job", 1) == [
        {"node": "Respond request failure", "type": "main", "index": 0}
    ]


def test_post_and_get_error_branches_route_to_sanitized_responders():
    workflow = load_url_workflow()

    # Every POST rejection/error and every GET/poll error terminates at a
    # sanitized responder; none relays the backend body. Pre-polling branches
    # are fully fixed (no job_id); post-polling branches may use only the
    # trusted prior polling ID.
    assert targets_of(workflow, "POST response status OK?", 1) == [
        {"node": "Respond backend rejection", "type": "main", "index": 0}
    ]
    for source in ("POST job ID valid?",):
        assert targets_of(workflow, source, 1) == [
            {"node": "Respond request failure", "type": "main", "index": 0}
        ]
    for source in (
        "GET URL job status",
        "GET response status OK?",
        "GET body valid?",
        "Non-terminal state?",
    ):
        assert targets_of(workflow, source, 1) == [
            {"node": "Respond polling failure", "type": "main", "index": 0}
        ]

    for name in ("Respond backend rejection", "Respond request failure"):
        body = node_by_name(workflow, name)["parameters"]["responseBody"]
        assert "$json" not in body
        assert "={{ $json.body }}" not in body


def test_pre_polling_error_responder_is_fixed_without_job_id():
    workflow = load_url_workflow()

    failure = node_by_name(workflow, "Respond request failure")
    body = failure["parameters"]["responseBody"]
    assert "$json" not in body
    assert body.startswith("=")
    payload = json.loads(body[1:])
    assert payload == {"status": "FAILED", "error": "Ingestion backend request failed"}
    assert "job_id" not in payload


def test_polling_error_responder_reflects_only_trusted_prior_job_id():
    workflow = load_url_workflow()

    polling = node_by_name(workflow, "Respond polling failure")
    expression = expression_body(polling["parameters"]["responseBody"])
    # The current error body is never read: no $json reference may exist.
    assert "$json" not in expression
    assert "$('Polling wait').item.json.body.job_id" in expression

    trusted = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    hostile_bodies = [
        {"body": {"job_id": {"id": "x"}}},  # object job_id
        {"body": {"job_id": ["x"]}},  # array job_id
        {"body": {"job_id": "/data/ingestion/secret.md"}},  # filesystem path
        {"body": {"job_id": "https://evil.example/leak"}},  # URL
        {"body": {"job_id": "POLYPHEMUS_SECRET_VALUE"}},  # secret-looking string
        {"body": {"job_id": ""}},  # empty job_id
        {"body": {}},  # missing job_id
    ]
    for current_body in hostile_bodies:
        response = eval_polling_failure_response(expression, current_body, trusted)
        assert response == {
            "job_id": trusted,
            "status": "FAILED",
            "error": "Ingestion backend request failed",
        }


def test_job_id_is_carried_through_wait_into_every_get_poll():
    workflow = load_url_workflow()

    wait = node_by_name(workflow, "Polling wait")
    assert wait["type"] == "n8n-nodes-base.wait"
    assert wait["parameters"]["amount"] == 10
    assert wait["parameters"]["unit"] == "seconds"
    assert targets_of(workflow, "Polling wait", 0) == [
        {"node": "GET URL job status", "type": "main", "index": 0}
    ]

    # The GET URL reads the job_id carried on the item passed through the
    # wait node (the HTTP response body), never a top-level or empty value.
    get_node = node_by_name(workflow, "GET URL job status")
    assert get_node["parameters"]["method"] == "GET"
    assert (
        get_node["parameters"]["url"]
        == "=http://ingestion:8080/v1/ingestions/{{ $json.body.job_id }}"
    )

    # The only consumers of the wait node are the two validated branches, so
    # the id entering every poll is a validated non-empty string.
    assert sorted(source for source, _ in edges_into(workflow, "Polling wait")) == [
        "Non-terminal state?",
        "POST job ID valid?",
    ]


def test_get_node_exposes_status_and_body_and_declares_native_error_output():
    workflow = load_url_workflow()

    get_node = node_by_name(workflow, "GET URL job status")
    assert get_node["onError"] == "continueErrorOutput"
    response = get_node["parameters"]["options"]["response"]["response"]
    assert response["neverError"] is True
    assert response["fullResponse"] is True

    assert targets_of(workflow, "GET URL job status", 0) == [
        {"node": "GET response status OK?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "GET URL job status", 1) == [
        {"node": "Respond polling failure", "type": "main", "index": 0}
    ]


def test_get_non_2xx_and_malformed_bodies_terminate_and_never_loop():
    workflow = load_url_workflow()

    status_ok = node_by_name(workflow, "GET response status OK?")
    status_conditions = filter_conditions(status_ok)
    assert [c["operator"]["type"] for c in status_conditions] == ["number", "number"]
    assert {c["operator"]["operation"] for c in status_conditions} == {"gte", "lte"}
    for condition in status_conditions:
        assert condition["leftValue"] == "={{ $json.statusCode }}"
    assert {c["rightValue"] for c in status_conditions} == {200, 299}

    assert targets_of(workflow, "GET response status OK?", 0) == [
        {"node": "GET body valid?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "GET response status OK?", 1) == [
        {"node": "Respond polling failure", "type": "main", "index": 0}
    ]

    # Neither gate may feed the wait loop: every non-2xx or malformed 2xx
    # response must terminate deterministically.
    for gate in ("GET response status OK?", "GET body valid?"):
        for output in workflow["connections"][gate]["main"]:
            assert all(edge["node"] != "Polling wait" for edge in output)
    assert [source for source, _ in edges_into(workflow, "GET URL job status")] == [
        "Polling wait"
    ]


def test_get_success_requires_valid_status_and_expected_job_identity():
    workflow = load_url_workflow()

    body_valid = node_by_name(workflow, "GET body valid?")
    conditions = filter_conditions(body_valid)
    assert len(conditions) == 3
    assert all(c["operator"]["type"] == "boolean" for c in conditions)
    assert all(c["operator"]["operation"] == "true" for c in conditions)

    status_condition = next(
        c for c in conditions if "$json.body.status" in c["leftValue"]
    )
    job_id_condition = next(
        c for c in conditions if "$json.body.job_id" in c["leftValue"]
    )
    identity_condition = next(
        c for c in conditions if "$('Polling wait')" in c["leftValue"]
    )

    status_expression = expression_body(status_condition["leftValue"])
    assert_expression_semantics(status_expression, "$json.body.status", STATUS_CASES)
    job_id_expression = expression_body(job_id_condition["leftValue"])
    assert_expression_semantics(job_id_expression, "$json.body.job_id", JOB_ID_CASES)
    assert identity_condition["leftValue"] == (
        "={{ $json.body.job_id === $('Polling wait').item.json.body.job_id }}"
    )

    assert targets_of(workflow, "GET body valid?", 0) == [
        {"node": "Terminal state?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "GET body valid?", 1) == [
        {"node": "Respond polling failure", "type": "main", "index": 0}
    ]


def test_all_four_terminal_states_route_to_the_correct_responders():
    workflow = load_url_workflow()

    terminal = node_by_name(workflow, "Terminal state?")
    terminal_condition = single_regex_condition(terminal)
    assert terminal_condition["leftValue"] == "={{ $json.body.status }}"
    assert terminal_condition["rightValue"] == (
        "^(PROCESSED|SKIPPED_DUPLICATE|FAILED|FAILED_AUDIT)$"
    )

    success = node_by_name(workflow, "Success or duplicate?")
    success_condition = single_regex_condition(success)
    assert success_condition["leftValue"] == "={{ $json.body.status }}"
    assert success_condition["rightValue"] == "^(PROCESSED|SKIPPED_DUPLICATE)$"

    assert targets_of(workflow, "Terminal state?", 0) == [
        {"node": "Success or duplicate?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "Success or duplicate?", 0) == [
        {"node": "Respond success", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "Success or duplicate?", 1) == [
        {"node": "Respond failed", "type": "main", "index": 0}
    ]

    respond_success = node_by_name(workflow, "Respond success")
    assert respond_success["parameters"]["respondWith"] == "json"
    assert respond_success["parameters"]["responseBody"] == (
        '={{ {"job_id": $json.body.job_id, "status": $json.body.status} }}'
    )
    assert "responseCode" not in respond_success["parameters"]["options"]

    respond_failed = node_by_name(workflow, "Respond failed")
    assert respond_failed["parameters"]["respondWith"] == "json"
    assert respond_failed["parameters"]["responseBody"] == (
        '={{ {"job_id": $json.body.job_id, "status": $json.body.status} }}'
    )
    assert respond_failed["parameters"]["options"]["responseCode"] == 502


def test_only_recognized_non_terminal_states_loop_through_the_ten_second_wait():
    workflow = load_url_workflow()

    non_terminal = node_by_name(workflow, "Non-terminal state?")
    non_terminal_condition = single_regex_condition(non_terminal)
    assert non_terminal_condition["leftValue"] == "={{ $json.body.status }}"
    assert non_terminal_condition["rightValue"] == (
        "^(DISCOVERED|STABILIZING|PROCESSING|NORMALIZED|INGESTING|AUDITING)$"
    )

    assert targets_of(workflow, "Terminal state?", 1) == [
        {"node": "Non-terminal state?", "type": "main", "index": 0}
    ]
    assert targets_of(workflow, "Non-terminal state?", 0) == [
        {"node": "Polling wait", "type": "main", "index": 0}
    ]
    # An unrecognized/malformed status terminates instead of looping.
    assert targets_of(workflow, "Non-terminal state?", 1) == [
        {"node": "Respond polling failure", "type": "main", "index": 0}
    ]

    assert sorted(source for source, _ in edges_into(workflow, "Polling wait")) == [
        "Non-terminal state?",
        "POST job ID valid?",
    ]


def test_responders_never_return_wrappers_headers_or_n8n_error_internals():
    workflow = load_url_workflow()

    responders = [
        node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.respondToWebhook"
    ]
    assert responders
    for responder in responders:
        body = responder["parameters"]["responseBody"]
        if body.startswith("={{ "):
            # Expression-backed responses may only interpolate the validated
            # scalar job_id/status fields; never relay the full backend body,
            # headers, response wrapper, or any error object.
            assert "={{ $json.body }}" not in body, responder["name"]
            assert "$json.headers" not in body
            assert "$json.statusCode" not in body
            assert "$json.statusMessage" not in body
            assert "$json.error" not in body
            assert "$response" not in body
            referenced_paths = re.findall(r"\$json\.body\.([A-Za-z0-9_]+)", body)
            assert set(referenced_paths) <= {"job_id", "status"}, responder["name"]
            polling_references = re.findall(
                r"\$\('Polling wait'\)\.item\.json\.body\.([A-Za-z0-9_]+)",
                body,
            )
            assert set(polling_references) <= {"job_id"}, responder["name"]
        else:
            # Literal responses are fixed sanitized payloads.
            assert body in {
                '={"error":"url must be a non-empty string"}',
                '={"status":"FAILED","error":"Ingestion backend rejected the request"}',
                '={"status":"FAILED","error":"Ingestion backend request failed"}',
            }, responder["name"]
        assert "$json.headers" not in body
        assert "$json.statusCode" not in body
        assert "$json.statusMessage" not in body
        assert "$json.error" not in body
        assert "$response" not in body


def test_backend_error_body_cannot_leak_into_public_webhook_response():
    workflow = load_url_workflow()
    serialized = json.dumps(workflow)

    hostile_fields = (
        "/data/ingestion/",
        "stack_trace",
        "secret_value",
        "query_secret",
        "10.0.0.1",
    )

    # No responder may relay the whole backend body; a hostile backend error
    # body therefore can never reach the webhook caller.
    responders = [
        node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.respondToWebhook"
    ]
    assert responders
    for responder in responders:
        body = responder["parameters"]["responseBody"]
        assert "={{ $json.body }}" not in body, responder["name"]
        assert "$json.body.error" not in body
        assert "$json.body.audit" not in body
        assert "$json.body.source_uri" not in body
        assert "$json.body.source_key" not in body

    # The URL-carrying field is only ever read from the incoming webhook item,
    # never echoed back with its query string in a response.
    for field in hostile_fields:
        assert field not in serialized


def test_url_workflow_is_inactive_and_uses_native_orchestration_nodes_only():
    workflow = load_url_workflow()

    assert workflow["active"] is False

    allowed_types = {
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.if",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.respondToWebhook",
    }
    node_types = {node["type"] for node in workflow["nodes"]}
    assert node_types <= allowed_types

    for forbidden in (
        "n8n-nodes-base.code",
        "n8n-nodes-base.function",
        "n8n-nodes-base.functionItem",
        "n8n-nodes-base.executeCommand",
        "n8n-nodes-base.localFileTrigger",
        "n8n-nodes-base.readWriteFile",
        "n8n-nodes-base.htmlExtract",
        "n8n-nodes-base.readPdf",
        "n8n-nodes-base.extractFromFile",
    ):
        assert forbidden not in node_types


def test_url_workflow_has_no_download_parser_ssrf_or_audit_logic():
    workflow = load_url_workflow()
    serialized = json.dumps(workflow)

    http_urls = {
        node["parameters"]["url"]
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.httpRequest"
    }
    assert http_urls == {
        "http://ingestion:8080/v1/ingestions",
        "=http://ingestion:8080/v1/ingestions/{{ $json.body.job_id }}",
    }

    assert "/data/ingestion" not in serialized
    assert "executeCommand" not in serialized
    assert "move" not in serialized
    assert "critical" not in serialized
    assert "audit" not in serialized  # FAILED_AUDIT is uppercase and allowed
    assert "merge_candidates" not in serialized
    assert "lightrag_docprep" not in serialized


def test_env_example_documents_manual_secret_procedure_without_active_assignment():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    lines = text.splitlines()

    # No active assignment: the variable must never be `VAR=...` anywhere.
    assert f"{SECRET_VAR}=" not in text
    assert not any(line.strip().startswith(f"{SECRET_VAR}=") for line in lines)

    # The variable name may appear only inside comments.
    mentions = [line for line in lines if SECRET_VAR in line]
    assert mentions
    assert all(line.lstrip().startswith("#") for line in mentions)

    assert SECRET_HEADER in text
    assert CREDENTIAL_NAME in text
    assert "Header Auth" in text
    assert "encrypted credential store" in text
    assert "Do not store" in text
    assert "password manager" in text
    assert "manually" in text


def test_milestone4_live_webhook_example_body_matches_workflow_shape():
    docs = MILESTONE_4_DOCS.read_text(encoding="utf-8")

    # The documented HTTP body must be the raw webhook payload. n8n exposes
    # the request body as $json.body, so the JSON body is {"url": ...} and
    # must not be wrapped in a nested "body" object.
    assert '-d \'{"url":"https://example.com/document"}\'' in docs
    assert '{"body":{"url":"https://example.com/document"}}' not in docs


def test_existing_file_workflow_is_byte_for_byte_unchanged():
    digest = hashlib.sha256(FILE_WORKFLOW.read_bytes()).hexdigest()
    assert digest == FILE_WORKFLOW_SHA256
