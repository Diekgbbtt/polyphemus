from lightrag.graph_audit import (
    audit_lightrag_graph,
    canonicalize_entity_type,
    normalize_lightrag_entity_types,
    plan_entity_type_updates,
)


def test_canonicalize_entity_type_accepts_lightrag_case_variants():
    assert canonicalize_entity_type("attacktechnique") == "AttackTechnique"
    assert canonicalize_entity_type("VulnerabilityClass") == "VulnerabilityClass"
    assert canonicalize_entity_type("configurationartifact") == "Artifact"
    assert canonicalize_entity_type("environmentalcondition") == "PreconditionEnvironment"
    assert canonicalize_entity_type("defensivetechnology") == "DefensiveControl"
    assert canonicalize_entity_type("asymmetricencryption") == "TechnologyStack"
    assert canonicalize_entity_type("dangerous_api") == "TechnologyStack"
    assert canonicalize_entity_type("framework") == "TechnologyStack"
    assert canonicalize_entity_type("integrationmethod") == "TechnologyStack"
    assert canonicalize_entity_type("messagehash") == "TechnologyStack"
    assert canonicalize_entity_type("operatingsystemcommands") == "PayloadPattern"
    assert canonicalize_entity_type("passwordhashing") == "TechnologyStack"
    assert canonicalize_entity_type("privilegedfunctionality") == "AttackGoal"
    assert canonicalize_entity_type("role") == "AttackerCapability"
    assert canonicalize_entity_type("securityheader") == "DefensiveControl"
    assert canonicalize_entity_type("sink") == "TechnologyStack"
    assert canonicalize_entity_type("standard") == "DefensiveControl"
    assert canonicalize_entity_type("specialcharacters") == "PayloadPattern"
    assert canonicalize_entity_type("symmetric-keyalgorithm") == "TechnologyStack"
    assert canonicalize_entity_type("targetenvironment") == "PreconditionEnvironment"
    assert canonicalize_entity_type("targetsystem") == "TechnologyStack"
    assert canonicalize_entity_type("directive") == "Artifact"
    assert canonicalize_entity_type("pathpattern") == "PayloadPattern"
    assert canonicalize_entity_type("attackmethod") == "AttackTechnique"
    assert canonicalize_entity_type("defensivecontrolbypass") == "AttackTechnique"
    assert canonicalize_entity_type("detectionmethod") == "AttackTechnique"
    assert canonicalize_entity_type("testmethodology") == "AttackTechnique"
    assert canonicalize_entity_type("testingmethodology") == "AttackTechnique"
    assert canonicalize_entity_type("testprocedure") == "AttackTechnique"
    assert canonicalize_entity_type("technicalcomponent") == "TechnologyStack"
    assert canonicalize_entity_type("dangerousinputcharacter") == "PayloadPattern"
    assert canonicalize_entity_type("logicaloperator") == "PayloadPattern"
    assert canonicalize_entity_type("cookienameprefix") == "DefensiveControl"
    assert canonicalize_entity_type("samesiteattribute") == "DefensiveControl"
    assert canonicalize_entity_type("passwordcrackingtechnique") == "AttackTechnique"
    assert canonicalize_entity_type("sqlserveradministrativeprivilege") == "AttackerCapability"
    assert canonicalize_entity_type("sqlserverautomationobjectcreationfunction") == "TechnologyStack"
    assert canonicalize_entity_type("sqlserverautomationobjectdestructionfunction") == "TechnologyStack"
    assert canonicalize_entity_type("sqlserverautomationobjectmethodinvocationfunction") == "TechnologyStack"
    assert canonicalize_entity_type("sqlserverbuilt-infunction") == "TechnologyStack"
    assert canonicalize_entity_type("sqlserverextendedprocedurelibrary") == "Artifact"
    assert canonicalize_entity_type("sqlserverextendedstoredprocedure") == "TechnologyStack"
    assert canonicalize_entity_type("sqlserverstoredprocedure") == "TechnologyStack"
    assert canonicalize_entity_type("sqlserverversionvariable") == "ObservableSignal"
    assert canonicalize_entity_type("tool") == "TechnologyStack"
    assert canonicalize_entity_type("header") == "DefensiveControl"
    assert canonicalize_entity_type("title") == "Artifact"
    assert canonicalize_entity_type("serviceendpoint") == "TechnologyStack"
    assert canonicalize_entity_type("technicalattribute") == "Artifact"
    assert canonicalize_entity_type("process") == "TechnologyStack"
    assert canonicalize_entity_type("action") == "TechnologyStack"
    assert canonicalize_entity_type("actor") == "AttackerCapability"
    assert canonicalize_entity_type("attackscenario") == "AttackTechnique"
    assert canonicalize_entity_type("attacktechniqueset") == "AttackTechnique"
    assert canonicalize_entity_type("observable") == "ObservableSignal"
    assert canonicalize_entity_type("observablesource") == "TechnologyStack"
    assert canonicalize_entity_type("weaknessclass") == "VulnerabilityClass"
    assert canonicalize_entity_type("wstgcategory") == "Artifact"
    assert canonicalize_entity_type("other") is None


def test_audit_reports_noise_unknown_types_and_expected_mismatches(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <key id="d2" for="node" attr.name="description" attr.type="string"/>
  <key id="d3" for="edge" attr.name="keywords" attr.type="string"/>
  <key id="d4" for="edge" attr.name="description" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="SQL Injection">
      <data key="d0">SQL Injection</data>
      <data key="d1">attacktechnique</data>
      <data key="d2">A weakness described as a technique by the extractor.</data>
    </node>
    <node id="Input Validation">
      <data key="d0">Input Validation</data>
      <data key="d1">defensivecontrol</data>
      <data key="d2">A control that validates input.</data>
    </node>
    <node id="SQLMap">
      <data key="d0">SQLMap</data>
      <data key="d1">technologystack</data>
      <data key="d2">Tester tooling noise.</data>
    </node>
    <node id="ASCII Code">
      <data key="d0">ASCII Code</data>
      <data key="d1">other</data>
      <data key="d2">Fallback type noise.</data>
    </node>
    <node id="Runtime_exec">
      <data key="d0">Runtime_exec</data>
      <data key="d1">dangerous_api</data>
      <data key="d2">Command execution sink.</data>
    </node>
    <node id="Pipe Symbol">
      <data key="d0">Pipe Symbol</data>
      <data key="d1">specialcharacters</data>
      <data key="d2">Shell metacharacter pattern.</data>
    </node>
    <node id="Os Command Filters">
      <data key="d0">Os Command Filters</data>
      <data key="d1">UNKNOWN</data>
      <data key="d2">Command filtering control.</data>
    </node>
    <node id="PayloadPattern">
      <data key="d0">PayloadPattern</data>
      <data key="d1">UNKNOWN</data>
      <data key="d2">Ontology label extracted as entity.</data>
    </node>
    <node id="Traditional SQL Database">
      <data key="d0">Traditional SQL Database</data>
      <data key="d1">UNKNOWN</data>
      <data key="d2">Database technology extracted with fallback type.</data>
    </node>
    <node id="Html Code">
      <data key="d0">Html Code</data>
      <data key="d1">UNKNOWN</data>
      <data key="d2">HTML code artifact extracted with fallback type.</data>
    </node>
    <node id="Attacker">
      <data key="d0">Attacker</data>
      <data key="d1">UNKNOWN</data>
      <data key="d2">Generic actor noise.</data>
    </node>
    <edge source="SQL Injection" target="Input Validation">
      <data key="d3">prevented by</data>
      <data key="d4">Input validation can prevent SQL injection.</data>
    </edge>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(
        graphml,
        expected_entity_types={
            "SQL Injection": "VulnerabilityClass",
            "Input Validation": "DefensiveControl",
            "Web Application Firewall": "DefensiveControl",
            "Os Command Filters": "DefensiveControl",
            "Traditional SQL Database": "TechnologyStack",
            "Html Code": "Artifact",
        },
    )

    assert report.entity_count == 11
    assert report.relation_count == 1
    assert report.type_counts["attacktechnique"] == 1
    assert report.canonical_type_counts["AttackTechnique"] == 1
    assert [entity.name for entity in report.unknown_type_entities] == [
        "ASCII Code",
        "Os Command Filters",
        "PayloadPattern",
        "Traditional SQL Database",
        "Html Code",
        "Attacker",
    ]
    assert [entity.name for entity in report.noise_entities] == [
        "SQLMap",
        "PayloadPattern",
        "Attacker",
    ]
    assert report.missing_expected_entities == ["Web Application Firewall"]
    assert [(item.name, item.expected_type) for item in report.expected_type_mismatches] == [
        ("SQL Injection", "VulnerabilityClass"),
        ("Os Command Filters", "DefensiveControl"),
        ("Traditional SQL Database", "TechnologyStack"),
        ("Html Code", "Artifact"),
    ]
    assert report.has_blocking_issues is True

    updates = plan_entity_type_updates(report)
    assert (updates[0].name, updates[0].target_type, updates[0].reason) == (
        "SQL Injection",
        "VulnerabilityClass",
        "expected_type_mismatch",
    )
    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Input Validation", "DefensiveControl", "non_canonical_type"),
        ("SQLMap", "TechnologyStack", "non_canonical_type"),
        ("Runtime_exec", "TechnologyStack", "non_canonical_type"),
        ("Pipe Symbol", "PayloadPattern", "non_canonical_type"),
        ("Os Command Filters", "DefensiveControl", "expected_type_mismatch"),
        ("Traditional SQL Database", "TechnologyStack", "expected_type_mismatch"),
        ("Html Code", "Artifact", "expected_type_mismatch"),
    }
    assert "ASCII Code" not in {update.name for update in updates}
    assert "PayloadPattern" not in {update.name for update in updates}
    assert "Attacker" not in {update.name for update in updates}

    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )
    assert dry_run["planned_noise_deletes"] == ["Attacker", "PayloadPattern", "SQLMap"]
    assert "SQLMap" not in {
        update["name"] for update in dry_run["planned_updates"]
    }
    assert dry_run["deleted_noise_entities"] == 0


def test_audit_normalizes_or_deletes_wstg_api_residual_unknowns(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Input Vector Enumeration">
      <data key="d0">Input Vector Enumeration</data>
      <data key="d1">methodologystep</data>
    </node>
    <node id="Double Quotes">
      <data key="d0">Double Quotes</data>
      <data key="d1">payloadpatternelement</data>
    </node>
    <node id="SQL Query with LIKE operator">
      <data key="d0">SQL Query with LIKE operator</data>
      <data key="d1">attacksurface</data>
    </node>
    <node id="CONFIG Table">
      <data key="d0">CONFIG Table</data>
      <data key="d1">targetobject</data>
    </node>
    <node id="API Broken Function Level Authorization">
      <data key="d0">API Broken Function Level Authorization</data>
      <data key="d1">ontologyreference</data>
    </node>
    <node id="Testing GraphQL">
      <data key="d0">Testing GraphQL</data>
      <data key="d1">concept</data>
    </node>
    <node id="Babou">
      <data key="d0">Babou</data>
      <data key="d1">targetobject</data>
    </node>
    <node id="HTTP">
      <data key="d0">HTTP</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="secure testing methodology">
      <data key="d0">secure testing methodology</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Input Vector Enumeration", "AttackTechnique", "non_canonical_type"),
        ("Double Quotes", "PayloadPattern", "non_canonical_type"),
        (
            "SQL Query with LIKE operator",
            "PreconditionEnvironment",
            "non_canonical_type",
        ),
        ("CONFIG Table", "Artifact", "non_canonical_type"),
        (
            "API Broken Function Level Authorization",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        ("Testing GraphQL", "AttackTechnique", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Babou",
        "HTTP",
        "secure testing methodology",
    ]
    assert not {
        "Babou",
        "HTTP",
        "secure testing methodology",
    } & {update["name"] for update in dry_run["planned_updates"]}


def test_audit_normalizes_or_deletes_wstg_authentication_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Static Username">
      <data key="d0">Static Username</data>
      <data key="d1">other</data>
    </node>
    <node id="Manual Password Creation">
      <data key="d0">Manual Password Creation</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Invalid Authentication Attempt">
      <data key="d0">Invalid Authentication Attempt</data>
      <data key="d1">attackvector</data>
    </node>
    <node id="AWS Cognito Lockout">
      <data key="d0">AWS Cognito Lockout</data>
      <data key="d1">implementation</data>
    </node>
    <node id="CAPTCHA Challenge">
      <data key="d0">CAPTCHA Challenge</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Testing for Default Credentials Concept">
      <data key="d0">Testing for Default Credentials Concept</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Authentication Testing Category">
      <data key="d0">Authentication Testing Category</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Static Username", "PayloadPattern", "expected_type_mismatch"),
        (
            "Manual Password Creation",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            "Invalid Authentication Attempt",
            "AttackTechnique",
            "non_canonical_type",
        ),
        ("AWS Cognito Lockout", "DefensiveControl", "expected_type_mismatch"),
        ("CAPTCHA Challenge", "DefensiveControl", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Authentication Testing Category",
        "Testing for Default Credentials Concept",
    ]


def test_audit_normalizes_or_deletes_late_wstg_authentication_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Unauthorized Access">
      <data key="d0">Unauthorized Access</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Password Reuse">
      <data key="d0">Password Reuse</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="password_reset_link">
      <data key="d0">password_reset_link</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="CSPRNG">
      <data key="d0">CSPRNG</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="AuthenticationFunctions">
      <data key="d0">AuthenticationFunctions</data>
      <data key="d1">other</data>
    </node>
    <node id="Brute-Force Attack Attempts">
      <data key="d0">Brute-Force Attack Attempts</data>
      <data key="d1">attacktechniques</data>
    </node>
    <node id="TOTP">
      <data key="d0">TOTP</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Email-based MFA Code">
      <data key="d0">Email-based MFA Code</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Authentication">
      <data key="d0">Authentication</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Unauthorized Access", "AttackGoal", "expected_type_mismatch"),
        ("Password Reuse", "VulnerabilityClass", "expected_type_mismatch"),
        ("password_reset_link", "Artifact", "expected_type_mismatch"),
        ("CSPRNG", "DefensiveControl", "expected_type_mismatch"),
        ("AuthenticationFunctions", "TechnologyStack", "expected_type_mismatch"),
        (
            "Brute-Force Attack Attempts",
            "AttackTechnique",
            "non_canonical_type",
        ),
        ("TOTP", "TechnologyStack", "expected_type_mismatch"),
        ("Email-based MFA Code", "Artifact", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == ["Authentication"]


def test_audit_normalizes_or_deletes_wstg_authorization_oauth_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Testing for Bypassing Authorization Schema">
      <data key="d0">Testing for Bypassing Authorization Schema</data>
      <data key="d1">title</data>
    </node>
    <node id="HTTP Header Injection">
      <data key="d0">HTTP Header Injection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Admin Menu">
      <data key="d0">Admin Menu</data>
      <data key="d1">other</data>
    </node>
    <node id="authorization_endpoint">
      <data key="d0">authorization_endpoint</data>
      <data key="d1">serviceendpoint</data>
    </node>
    <node id="client_id">
      <data key="d0">client_id</data>
      <data key="d1">technicalattribute</data>
    </node>
    <node id="authorization_code_exchange">
      <data key="d0">authorization_code_exchange</data>
      <data key="d1">process</data>
    </node>
    <node id="Cross-Site Request Forgery">
      <data key="d0">Cross-Site Request Forgery</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="ROPC grant">
      <data key="d0">ROPC grant</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="response_type=token">
      <data key="d0">response_type=token</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Targets Consent Page">
      <data key="d0">Targets Consent Page</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Security threats">
      <data key="d0">Security threats</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        (
            "Testing for Bypassing Authorization Schema",
            "Artifact",
            "non_canonical_type",
        ),
        ("HTTP Header Injection", "AttackTechnique", "expected_type_mismatch"),
        ("Admin Menu", "Artifact", "expected_type_mismatch"),
        ("authorization_endpoint", "TechnologyStack", "non_canonical_type"),
        ("client_id", "Artifact", "non_canonical_type"),
        ("authorization_code_exchange", "TechnologyStack", "non_canonical_type"),
        (
            "Cross-Site Request Forgery",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        ("ROPC grant", "TechnologyStack", "expected_type_mismatch"),
        ("response_type=token", "PayloadPattern", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Security threats",
        "Targets Consent Page",
    ]


def test_audit_normalizes_invalid_authentication_signal(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Invalid Authentication">
      <data key="d0">Invalid Authentication</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    updates = plan_entity_type_updates(audit_lightrag_graph(graphml))

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        (
            "Invalid Authentication",
            "ObservableSignal",
            "expected_type_mismatch",
        )
    }


def test_audit_normalizes_reprocessed_wstg_batch_zero_variants(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Browser">
      <data key="d0">Browser</data>
      <data key="d1">technicalcomponent</data>
    </node>
    <node id="Pipe (`|`)">
      <data key="d0">Pipe (`|`)</data>
      <data key="d1">logicaloperator</data>
    </node>
    <node id="backslash `\\`">
      <data key="d0">backslash `\\`</data>
      <data key="d1">dangerousinputcharacter</data>
    </node>
    <node id="input_validation_validation_test">
      <data key="d0">input_validation_validation_test</data>
      <data key="d1">testprocedure</data>
    </node>
    <node id="NoSQL databases&lt;|TechnologyStack|&gt;">
      <data key="d0">NoSQL databases&lt;|TechnologyStack|&gt;</data>
      <data key="d1">type</data>
    </node>
    <node id="Dynamic SQL Query Construction">
      <data key="d0">Dynamic SQL Query Construction</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Acme">
      <data key="d0">Acme</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="maps to">
      <data key="d0">maps to</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Browser", "TechnologyStack", "non_canonical_type"),
        ("Pipe (`|`)", "PayloadPattern", "non_canonical_type"),
        ("backslash `\\`", "PayloadPattern", "non_canonical_type"),
        ("input_validation_validation_test", "AttackTechnique", "non_canonical_type"),
        (
            "NoSQL databases<|TechnologyStack|>",
            "TechnologyStack",
            "expected_type_mismatch",
        ),
        (
            "Dynamic SQL Query Construction",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
    }
    assert {entity.name for entity in report.noise_entities} == {"Acme", "maps to"}


def test_audit_normalizes_auth_and_authorization_batch_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Account Access">
      <data key="d0">Account Access</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Device Access">
      <data key="d0">Device Access</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="X-Remote-IP">
      <data key="d0">X-Remote-IP</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Normalization Mismatch">
      <data key="d0">Normalization Mismatch</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    updates = plan_entity_type_updates(audit_lightrag_graph(graphml))

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } == {
        ("Account Access", "AttackGoal", "expected_type_mismatch"),
        ("Device Access", "AttackGoal", "expected_type_mismatch"),
        ("X-Remote-IP", "PayloadPattern", "expected_type_mismatch"),
        ("Normalization Mismatch", "PreconditionEnvironment", "expected_type_mismatch"),
    }


def test_audit_normalizes_initial_business_logic_batch_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Business Logic Data Validation Scenario">
      <data key="d0">Business Logic Data Validation Scenario</data>
      <data key="d1">attacktechniqueset</data>
    </node>
    <node id="Multi-Location Credit Card Use">
      <data key="d0">Multi-Location Credit Card Use</data>
      <data key="d1">attackscenario</data>
    </node>
    <node id="Direct Shipment">
      <data key="d0">Direct Shipment</data>
      <data key="d1">action</data>
    </node>
    <node id="Employee">
      <data key="d0">Employee</data>
      <data key="d1">actor</data>
    </node>
    <node id="Business Logic Integrity">
      <data key="d0">Business Logic Integrity</data>
      <data key="d1">weaknessclass</data>
    </node>
    <node id="Programmatic Logic Flow">
      <data key="d0">Programmatic Logic Flow</data>
      <data key="d1">observable</data>
    </node>
    <node id="Transaction Limit">
      <data key="d0">Transaction Limit</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Access Controls">
      <data key="d0">Access Controls</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="HTTP Traffic">
      <data key="d0">HTTP Traffic</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Log System">
      <data key="d0">Log System</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    updates = plan_entity_type_updates(audit_lightrag_graph(graphml))

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        (
            "Business Logic Data Validation Scenario",
            "AttackTechnique",
            "non_canonical_type",
        ),
        (
            "Multi-Location Credit Card Use",
            "AttackTechnique",
            "non_canonical_type",
        ),
        ("Direct Shipment", "TechnologyStack", "non_canonical_type"),
        ("Employee", "AttackerCapability", "non_canonical_type"),
        (
            "Business Logic Integrity",
            "VulnerabilityClass",
            "non_canonical_type",
        ),
        ("Programmatic Logic Flow", "ObservableSignal", "non_canonical_type"),
        ("Transaction Limit", "DefensiveControl", "expected_type_mismatch"),
        ("Access Controls", "DefensiveControl", "expected_type_mismatch"),
        ("HTTP Traffic", "ObservableSignal", "expected_type_mismatch"),
        ("Log System", "DefensiveControl", "expected_type_mismatch"),
    }


def test_audit_normalizes_late_business_logic_batch_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Business Logic Testing">
      <data key="d0">Business Logic Testing</data>
      <data key="d1">wstgcategory</data>
    </node>
    <node id="Work Flow Vulnerability">
      <data key="d0">Work Flow Vulnerability</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Skipping Steps">
      <data key="d0">Skipping Steps</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="multi-step Workflow">
      <data key="d0">multi-step Workflow</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Attacker-Controlled Script Injection">
      <data key="d0">Attacker-Controlled Script Injection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Test Defenses Against Application Misuse">
      <data key="d0">Test Defenses Against Application Misuse</data>
      <data key="d1">other</data>
    </node>
    <node id="Fuzzing session">
      <data key="d0">Fuzzing session</data>
      <data key="d1">other</data>
    </node>
    <node id="DefensiveControl Detection">
      <data key="d0">DefensiveControl Detection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Test Payment Functionality">
      <data key="d0">Test Payment Functionality</data>
      <data key="d1">concept</data>
    </node>
    <node id="Arbitrary Donation Entry">
      <data key="d0">Arbitrary Donation Entry</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Payment Logic">
      <data key="d0">Payment Logic</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="relationship_keywords">
      <data key="d0">relationship_keywords</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Account">
      <data key="d0">Account</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="VulnerabilityClass: Malicious File Upload">
      <data key="d0">VulnerabilityClass: Malicious File Upload</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Business Logic Testing", "Artifact", "non_canonical_type"),
        ("Work Flow Vulnerability", "VulnerabilityClass", "expected_type_mismatch"),
        ("Skipping Steps", "AttackTechnique", "expected_type_mismatch"),
        ("multi-step Workflow", "TechnologyStack", "expected_type_mismatch"),
        (
            "Attacker-Controlled Script Injection",
            "AttackTechnique",
            "expected_type_mismatch",
        ),
        (
            "Test Defenses Against Application Misuse",
            "Artifact",
            "expected_type_mismatch",
        ),
        ("Fuzzing session", "AttackTechnique", "expected_type_mismatch"),
        (
            "DefensiveControl Detection",
            "ObservableSignal",
            "expected_type_mismatch",
        ),
        ("Test Payment Functionality", "Artifact", "expected_type_mismatch"),
        ("Arbitrary Donation Entry", "PayloadPattern", "expected_type_mismatch"),
        ("Payment Logic", "TechnologyStack", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Account",
        "VulnerabilityClass: Malicious File Upload",
        "relationship_keywords",
    ]


def test_audit_normalizes_initial_client_side_batch_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Browser Developer Console">
      <data key="d0">Browser Developer Console</data>
      <data key="d1">observablesource</data>
    </node>
    <node id="form Element">
      <data key="d0">form Element</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Content Security Policy">
      <data key="d0">Content Security Policy</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="textarea Element">
      <data key="d0">textarea Element</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Browser Redirection">
      <data key="d0">Browser Redirection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="`location.hash`">
      <data key="d0">`location.hash`</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="InnerHTML">
      <data key="d0">InnerHTML</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Document.write()">
      <data key="d0">Document.write()</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Access Control Bypass">
      <data key="d0">Access Control Bypass</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Security Testing Methodologies">
      <data key="d0">Security Testing Methodologies</data>
      <data key="d1">other</data>
    </node>
    <node id="Stefano Di Paulo">
      <data key="d0">Stefano Di Paulo</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Browser Developer Console", "TechnologyStack", "non_canonical_type"),
        ("form Element", "TechnologyStack", "expected_type_mismatch"),
        ("Content Security Policy", "DefensiveControl", "expected_type_mismatch"),
        ("textarea Element", "TechnologyStack", "expected_type_mismatch"),
        ("Browser Redirection", "AttackTechnique", "expected_type_mismatch"),
        ("`location.hash`", "TechnologyStack", "expected_type_mismatch"),
        ("InnerHTML", "TechnologyStack", "expected_type_mismatch"),
        ("Document.write()", "TechnologyStack", "expected_type_mismatch"),
        ("Access Control Bypass", "AttackGoal", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Security Testing Methodologies",
        "Stefano Di Paulo",
    ]


def test_audit_normalizes_cors_flash_clickjacking_batch_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Access-Control-Allow-Origin">
      <data key="d0">Access-Control-Allow-Origin</data>
      <data key="d1">header</data>
    </node>
    <node id="URL Fragment Identifier">
      <data key="d0">URL Fragment Identifier</data>
      <data key="d1">other</data>
    </node>
    <node id="* wildcard header">
      <data key="d0">* wildcard header</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cross-Site Scripting (XSS) Attack">
      <data key="d0">Cross-Site Scripting (XSS) Attack</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Proxy Server">
      <data key="d0">Proxy Server</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Invalid CORS Configuration">
      <data key="d0">Invalid CORS Configuration</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="XSF">
      <data key="d0">XSF</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="ActionScript Process">
      <data key="d0">ActionScript Process</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Network Tab (Developer Tools)">
      <data key="d0">Network Tab (Developer Tools)</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Browser">
      <data key="d0">Web Browser</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Clickjacking Detection">
      <data key="d0">Clickjacking Detection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="true">
      <data key="d0">true</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Test Procedure">
      <data key="d0">Test Procedure</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Access-Control-Allow-Origin", "DefensiveControl", "non_canonical_type"),
        ("URL Fragment Identifier", "Artifact", "expected_type_mismatch"),
        ("* wildcard header", "PayloadPattern", "expected_type_mismatch"),
        (
            "Cross-Site Scripting (XSS) Attack",
            "AttackTechnique",
            "expected_type_mismatch",
        ),
        ("Proxy Server", "TechnologyStack", "expected_type_mismatch"),
        ("Invalid CORS Configuration", "VulnerabilityClass", "expected_type_mismatch"),
        ("XSF", "VulnerabilityClass", "expected_type_mismatch"),
        ("ActionScript Process", "TechnologyStack", "expected_type_mismatch"),
        (
            "Network Tab (Developer Tools)",
            "TechnologyStack",
            "expected_type_mismatch",
        ),
        ("Web Browser", "TechnologyStack", "expected_type_mismatch"),
        ("Clickjacking Detection", "ObservableSignal", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == ["Test Procedure", "true"]


def test_audit_normalizes_websocket_storage_tabnabbing_batch_residuals(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Testing WebSockets">
      <data key="d0">Testing WebSockets</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Concept Testing WebSockets">
      <data key="d0">Concept Testing WebSockets</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="WebSockets">
      <data key="d0">WebSockets</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="false origin check">
      <data key="d0">false origin check</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Crypto API">
      <data key="d0">Web Crypto API</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Insecure Data Storage">
      <data key="d0">Insecure Data Storage</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="CryptoKeys">
      <data key="d0">CryptoKeys</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="target=&quot;_blank&quot;">
      <data key="d0">target=&quot;_blank&quot;</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="user-controlled URL insertion">
      <data key="d0">user-controlled URL insertion</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="window.opener.location redirection">
      <data key="d0">window.opener.location redirection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="HTML5 Application/JSON MIME Type">
      <data key="d0">HTML5 Application/JSON MIME Type</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("WebSockets", "TechnologyStack", "expected_type_mismatch"),
        ("false origin check", "PreconditionEnvironment", "expected_type_mismatch"),
        ("Web Crypto API", "TechnologyStack", "expected_type_mismatch"),
        ("Insecure Data Storage", "VulnerabilityClass", "expected_type_mismatch"),
        ("CryptoKeys", "Artifact", "expected_type_mismatch"),
        ('target="_blank"', "PreconditionEnvironment", "expected_type_mismatch"),
        (
            "user-controlled URL insertion",
            "PayloadPattern",
            "expected_type_mismatch",
        ),
        (
            "window.opener.location redirection",
            "AttackTechnique",
            "expected_type_mismatch",
        ),
        (
            "HTML5 Application/JSON MIME Type",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Concept Testing WebSockets",
        "Testing WebSockets",
    ]


def test_audit_handles_business_logic_batch_entities_and_noise(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Redirect">
      <data key="d0">Redirect</data>
      <data key="d1">integrationmethod</data>
    </node>
    <node id="PciDss">
      <data key="d0">PciDss</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="OrderDatabase">
      <data key="d0">OrderDatabase</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Warren Robinett">
      <data key="d0">Warren Robinett</data>
      <data key="d1">other</data>
    </node>
    <node id="Payment Card Industry">
      <data key="d0">Payment Card Industry</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Redirect", "TechnologyStack", "non_canonical_type"),
        ("PciDss", "DefensiveControl", "expected_type_mismatch"),
        ("OrderDatabase", "TechnologyStack", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Payment Card Industry",
        "Warren Robinett",
    ]
    assert "Payment Card Industry" not in {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_handles_apertus_business_logic_residual_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Temporary Location">
      <data key="d0">Temporary Location</data>
      <data key="d1">location</data>
    </node>
    <node id="SAQ A">
      <data key="d0">SAQ A</data>
      <data key="d1">self-assessmentquestionnaire</data>
    </node>
    <node id="Business Logic">
      <data key="d0">Business Logic</data>
      <data key="d1">other</data>
    </node>
    <node id="Directory Traversal Sequence">
      <data key="d0">Directory Traversal Sequence</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Back-end API">
      <data key="d0">Back-end API</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="contains">
      <data key="d0">contains</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Target System">
      <data key="d0">Target System</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Temporary Location", "Artifact", "non_canonical_type"),
        ("SAQ A", "Artifact", "non_canonical_type"),
        ("Business Logic", "PreconditionEnvironment", "expected_type_mismatch"),
        (
            "Directory Traversal Sequence",
            "PayloadPattern",
            "expected_type_mismatch",
        ),
        ("Back-end API", "TechnologyStack", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == ["Target System", "contains"]
    assert "Target System" not in {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_handles_client_side_batch_entities_and_noise(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Lack of Input Validation">
      <data key="d0">Lack of Input Validation</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="disclosure of session cookies">
      <data key="d0">disclosure of session cookies</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="iframe src">
      <data key="d0">iframe src</data>
      <data key="d1">sink</data>
    </node>
    <node id="attacker-controlled URL">
      <data key="d0">attacker-controlled URL</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="`Access-Control-Allow-Credentials: true` Header">
      <data key="d0">`Access-Control-Allow-Credentials: true` Header</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="iframe with sandbox attribute">
      <data key="d0">iframe with sandbox attribute</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Flasm">
      <data key="d0">Flasm</data>
      <data key="d1">tool</data>
    </node>
    <node id="LoadVars">
      <data key="d0">LoadVars</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Mario Heiderich">
      <data key="d0">Mario Heiderich</data>
      <data key="d1">person</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        (
            "Lack of Input Validation",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("disclosure of session cookies", "AttackGoal", "expected_type_mismatch"),
        ("iframe src", "TechnologyStack", "non_canonical_type"),
        ("attacker-controlled URL", "PayloadPattern", "expected_type_mismatch"),
        (
            "`Access-Control-Allow-Credentials: true` Header",
            "DefensiveControl",
            "expected_type_mismatch",
        ),
        (
            "iframe with sandbox attribute",
            "DefensiveControl",
            "expected_type_mismatch",
        ),
        ("Flasm", "TechnologyStack", "non_canonical_type"),
        ("LoadVars", "TechnologyStack", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == ["Mario Heiderich"]
    assert "Mario Heiderich" not in {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_handles_late_client_and_configuration_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Failure to Validate Origin Header">
      <data key="d0">Failure to Validate Origin Header</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Trust Domain">
      <data key="d0">Trust Domain</data>
      <data key="d1">other</data>
    </node>
    <node id="origin validation check">
      <data key="d0">origin validation check</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="target=&quot;_blank&quot; attribute">
      <data key="d0">target=&quot;_blank&quot; attribute</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="rel=&quot;noopener noreferrer&quot; attribute">
      <data key="d0">rel=&quot;noopener noreferrer&quot; attribute</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="ng-bind">
      <data key="d0">ng-bind</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="v-html">
      <data key="d0">v-html</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Sensitive File Extensions">
      <data key="d0">Sensitive File Extensions</data>
      <data key="d1">other</data>
    </node>
    <node id="NIST's National Checklist Program">
      <data key="d0">NIST's National Checklist Program</data>
      <data key="d1">framework</data>
    </node>
    <node id="ApplicationHost.config">
      <data key="d0">ApplicationHost.config</data>
      <data key="d1">configurationartifact</data>
    </node>
    <node id="User Account Provisioning">
      <data key="d0">User Account Provisioning</data>
      <data key="d1">privilegedfunctionality</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        (
            "Failure to Validate Origin Header",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        ("Trust Domain", "PreconditionEnvironment", "expected_type_mismatch"),
        ("origin validation check", "DefensiveControl", "expected_type_mismatch"),
        (
            'target="_blank" attribute',
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            'rel="noopener noreferrer" attribute',
            "DefensiveControl",
            "expected_type_mismatch",
        ),
        ("ng-bind", "DefensiveControl", "expected_type_mismatch"),
        ("v-html", "TechnologyStack", "expected_type_mismatch"),
        ("Sensitive File Extensions", "Artifact", "expected_type_mismatch"),
        (
            "NIST's National Checklist Program",
            "DefensiveControl",
            "expected_type_mismatch",
        ),
        ("ApplicationHost.config", "Artifact", "non_canonical_type"),
        ("User Account Provisioning", "AttackGoal", "non_canonical_type"),
    }


def test_audit_handles_configuration_and_crypto_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Referrer-Policy">
      <data key="d0">Referrer-Policy</data>
      <data key="d1">securityheader</data>
    </node>
    <node id="FIPS-204">
      <data key="d0">FIPS-204</data>
      <data key="d1">standard</data>
    </node>
    <node id="Arbitrary HTTP Methods">
      <data key="d0">Arbitrary HTTP Methods</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Malicious Internal Actor">
      <data key="d0">Malicious Internal Actor</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Missing frame-ancestors directive">
      <data key="d0">Missing frame-ancestors directive</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="HPKP">
      <data key="d0">HPKP</data>
      <data key="d1">other</data>
    </node>
    <node id="Padding Oracle Attack">
      <data key="d0">Padding Oracle Attack</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="IV">
      <data key="d0">IV</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Misuse">
      <data key="d0">Misuse</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="supports">
      <data key="d0">supports</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Observable Signal">
      <data key="d0">Observable Signal</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Referrer-Policy", "DefensiveControl", "non_canonical_type"),
        ("FIPS-204", "DefensiveControl", "non_canonical_type"),
        ("Arbitrary HTTP Methods", "AttackTechnique", "expected_type_mismatch"),
        (
            "Malicious Internal Actor",
            "AttackerCapability",
            "expected_type_mismatch",
        ),
        (
            "Missing frame-ancestors directive",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        ("HPKP", "DefensiveControl", "expected_type_mismatch"),
        ("Padding Oracle Attack", "AttackTechnique", "expected_type_mismatch"),
        ("IV", "PayloadPattern", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "Misuse",
        "Observable Signal",
        "supports",
    ]
    assert not {
        "Misuse",
        "Observable Signal",
        "supports",
    } & {update["name"] for update in dry_run["planned_updates"]}


def test_audit_handles_identity_crypto_and_info_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Credentials">
      <data key="d0">Credentials</data>
      <data key="d1">other</data>
    </node>
    <node id="AES128">
      <data key="d0">AES128</data>
      <data key="d1">symmetric-keyalgorithm</data>
    </node>
    <node id="SHA256">
      <data key="d0">SHA256</data>
      <data key="d1">messagehash</data>
    </node>
    <node id="PBKDF2">
      <data key="d0">PBKDF2</data>
      <data key="d1">passwordhashing</data>
    </node>
    <node id="RSA2048">
      <data key="d0">RSA2048</data>
      <data key="d1">asymmetricencryption</data>
    </node>
    <node id="Administrator Role">
      <data key="d0">Administrator Role</data>
      <data key="d1">role</data>
    </node>
    <node id="Message Integrity">
      <data key="d0">Message Integrity</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="sensitive admin functionality">
      <data key="d0">sensitive admin functionality</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Registration Process">
      <data key="d0">Registration Process</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="internet-connected devices">
      <data key="d0">internet-connected devices</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="search operators">
      <data key="d0">search operators</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="determines">
      <data key="d0">determines</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="enables Account Enumeration">
      <data key="d0">enables Account Enumeration</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Credentials", "AttackerCapability", "expected_type_mismatch"),
        ("AES128", "TechnologyStack", "non_canonical_type"),
        ("SHA256", "TechnologyStack", "non_canonical_type"),
        ("PBKDF2", "TechnologyStack", "non_canonical_type"),
        ("RSA2048", "TechnologyStack", "non_canonical_type"),
        ("Administrator Role", "AttackerCapability", "non_canonical_type"),
        ("Message Integrity", "DefensiveControl", "expected_type_mismatch"),
        ("sensitive admin functionality", "AttackGoal", "expected_type_mismatch"),
        (
            "Registration Process",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            "internet-connected devices",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("search operators", "PayloadPattern", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == [
        "determines",
        "enables Account Enumeration",
    ]
    assert not {
        "determines",
        "enables Account Enumeration",
    } & {update["name"] for update in dry_run["planned_updates"]}


def test_audit_handles_information_gathering_and_input_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Google">
      <data key="d0">Google</data>
      <data key="d1">organization</data>
    </node>
    <node id="Disallow">
      <data key="d0">Disallow</data>
      <data key="d1">directive</data>
    </node>
    <node id="WebApplication">
      <data key="d0">WebApplication</data>
      <data key="d1">targetsystem</data>
    </node>
    <node id="/wp-admin/">
      <data key="d0">/wp-admin/</data>
      <data key="d1">pathpattern</data>
    </node>
    <node id="Custom PL/SQL Application">
      <data key="d0">Custom PL/SQL Application</data>
      <data key="d1">targetenvironment</data>
    </node>
    <node id="Request Input Field">
      <data key="d0">Request Input Field</data>
      <data key="d1">other</data>
    </node>
    <node id="DNS Enumeration">
      <data key="d0">DNS Enumeration</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Port 8080">
      <data key="d0">Port 8080</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="attack-surface-detector-cli-1.3.5.jar">
      <data key="d0">attack-surface-detector-cli-1.3.5.jar</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Attack Strings">
      <data key="d0">Attack Strings</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SSRF">
      <data key="d0">SSRF</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SQL queries">
      <data key="d0">SQL queries</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Crawler">
      <data key="d0">Web Crawler</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Robot">
      <data key="d0">Web Robot</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Spider">
      <data key="d0">Web Spider</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Attack String Injection">
      <data key="d0">Attack String Injection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Automated Scans">
      <data key="d0">Automated Scans</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Backend Origin Exposure">
      <data key="d0">Backend Origin Exposure</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cloud WAF">
      <data key="d0">Cloud WAF</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Firewall">
      <data key="d0">Firewall</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Frontend/Backend Server Mismatch">
      <data key="d0">Frontend/Backend Server Mismatch</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="IDS/IPS">
      <data key="d0">IDS/IPS</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Inconsistent TimesInconsistent HostnamesInternal IPsLoad-Balancer Cookies">
      <data key="d0">Inconsistent TimesInconsistent HostnamesInternal IPsLoad-Balancer Cookies</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Port Scan">
      <data key="d0">Port Scan</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="WAF">
      <data key="d0">WAF</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="WHOIS Lookup">
      <data key="d0">WHOIS Lookup</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="PathPattern">
      <data key="d0">PathPattern</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="IETF">
      <data key="d0">IETF</data>
      <data key="d1">organization</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("Google", "TechnologyStack", "expected_type_mismatch"),
        ("Disallow", "Artifact", "non_canonical_type"),
        ("WebApplication", "TechnologyStack", "non_canonical_type"),
        ("/wp-admin/", "PayloadPattern", "non_canonical_type"),
        (
            "Custom PL/SQL Application",
            "PreconditionEnvironment",
            "non_canonical_type",
        ),
        ("Request Input Field", "Artifact", "expected_type_mismatch"),
        ("DNS Enumeration", "AttackTechnique", "expected_type_mismatch"),
        ("Port 8080", "PreconditionEnvironment", "expected_type_mismatch"),
        (
            "attack-surface-detector-cli-1.3.5.jar",
            "TechnologyStack",
            "expected_type_mismatch",
        ),
        ("Attack Strings", "PayloadPattern", "expected_type_mismatch"),
        ("SSRF", "VulnerabilityClass", "expected_type_mismatch"),
        ("SQL queries", "PayloadPattern", "expected_type_mismatch"),
        ("Web Crawler", "TechnologyStack", "expected_type_mismatch"),
        ("Web Robot", "TechnologyStack", "expected_type_mismatch"),
        ("Web Spider", "TechnologyStack", "expected_type_mismatch"),
        ("Attack String Injection", "AttackTechnique", "expected_type_mismatch"),
        ("Automated Scans", "AttackTechnique", "expected_type_mismatch"),
        ("Backend Origin Exposure", "ObservableSignal", "expected_type_mismatch"),
        ("Cloud WAF", "DefensiveControl", "expected_type_mismatch"),
        ("Firewall", "DefensiveControl", "expected_type_mismatch"),
        (
            "Frontend/Backend Server Mismatch",
            "ObservableSignal",
            "expected_type_mismatch",
        ),
        ("IDS/IPS", "DefensiveControl", "expected_type_mismatch"),
        (
            "Inconsistent TimesInconsistent HostnamesInternal IPsLoad-Balancer Cookies",
            "ObservableSignal",
            "expected_type_mismatch",
        ),
        ("Port Scan", "AttackTechnique", "expected_type_mismatch"),
        ("WAF", "DefensiveControl", "expected_type_mismatch"),
        ("WHOIS Lookup", "AttackTechnique", "expected_type_mismatch"),
    }
    assert dry_run["planned_noise_deletes"] == ["IETF", "PathPattern"]
    assert not {"IETF", "PathPattern"} & {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_handles_sql_dialect_and_file_inclusion_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="RIPS Tech">
      <data key="d0">RIPS Tech</data>
      <data key="d1">organization</data>
    </node>
    <node id="User Input Vectors">
      <data key="d0">User Input Vectors</data>
      <data key="d1">other</data>
    </node>
    <node id="bruteforcing sysadmin password&lt;|AttackTechnique|&gt;">
      <data key="d0">bruteforcing sysadmin password&lt;|AttackTechnique|&gt;</data>
      <data key="d1">passwordcrackingtechnique</data>
    </node>
    <node id="sysadmin&lt;|Role|&gt;">
      <data key="d0">sysadmin&lt;|Role|&gt;</data>
      <data key="d1">sqlserveradministrativeprivilege</data>
    </node>
    <node id="sp_OACreate&lt;|TechnologyStack|&gt;">
      <data key="d0">sp_OACreate&lt;|TechnologyStack|&gt;</data>
      <data key="d1">sqlserverautomationobjectcreationfunction</data>
    </node>
    <node id="sp_OADestroy&lt;|TechnologyStack|&gt;">
      <data key="d0">sp_OADestroy&lt;|TechnologyStack|&gt;</data>
      <data key="d1">sqlserverautomationobjectdestructionfunction</data>
    </node>
    <node id="sp_OAMethod&lt;|TechnologyStack|&gt;">
      <data key="d0">sp_OAMethod&lt;|TechnologyStack|&gt;</data>
      <data key="d1">sqlserverautomationobjectmethodinvocationfunction</data>
    </node>
    <node id="CONVERT Function&lt;|TechnologyStack|&gt;">
      <data key="d0">CONVERT Function&lt;|TechnologyStack|&gt;</data>
      <data key="d1">sqlserverbuilt-infunction</data>
    </node>
    <node id="xp_log70.dll&lt;|Artifact|&gt;">
      <data key="d0">xp_log70.dll&lt;|Artifact|&gt;</data>
      <data key="d1">sqlserverextendedprocedurelibrary</data>
    </node>
    <node id="xp_cmdshell&lt;|TechnologyStack|&gt;">
      <data key="d0">xp_cmdshell&lt;|TechnologyStack|&gt;</data>
      <data key="d1">sqlserverextendedstoredprocedure</data>
    </node>
    <node id="sp_makewebtask&lt;|TechnologyStack|&gt;">
      <data key="d0">sp_makewebtask&lt;|TechnologyStack|&gt;</data>
      <data key="d1">sqlserverstoredprocedure</data>
    </node>
    <node id="@@VERSION&lt;|ObservableSignal|&gt;">
      <data key="d0">@@VERSION&lt;|ObservableSignal|&gt;</data>
      <data key="d1">sqlserverversionvariable</data>
    </node>
    <node id="4096 Byte Filename Limit">
      <data key="d0">4096 Byte Filename Limit</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="@@VERSION">
      <data key="d0">@@VERSION</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="`create` IMAP Command">
      <data key="d0">`create` IMAP Command</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="`include` Function">
      <data key="d0">`include` Function</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="allows multiple SQL statements with `;`">
      <data key="d0">allows multiple SQL statements with `;`</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Arbitrary File Read">
      <data key="d0">Arbitrary File Read</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Base64-encoded Payload">
      <data key="d0">Base64-encoded Payload</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="BENCHMARK">
      <data key="d0">BENCHMARK</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="bruteforcing sysadmin password">
      <data key="d0">bruteforcing sysadmin password</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="CONVERT Function">
      <data key="d0">CONVERT Function</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="debug.exe">
      <data key="d0">debug.exe</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="File Extension Appending">
      <data key="d0">File Extension Appending</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Input Validation Failure">
      <data key="d0">Input Validation Failure</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Malicious Remote URL Injection">
      <data key="d0">Malicious Remote URL Injection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="PHP `allow_url_include`">
      <data key="d0">PHP `allow_url_include`</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="PHP Zip Wrapper (`zip://`)">
      <data key="d0">PHP Zip Wrapper (`zip://`)</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Remote Code Execution (RCE)">
      <data key="d0">Remote Code Execution (RCE)</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Sensitive Server Files (e.g., `/etc/passwd`)">
      <data key="d0">Sensitive Server Files (e.g., `/etc/passwd`)</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SLEEP">
      <data key="d0">SLEEP</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="sp_addextendedproc">
      <data key="d0">sp_addextendedproc</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SQL Server 2005">
      <data key="d0">SQL Server 2005</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="supports `pg_sleep(n)`">
      <data key="d0">supports `pg_sleep(n)`</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="sysadmin">
      <data key="d0">sysadmin</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="sysadmin privilege">
      <data key="d0">sysadmin privilege</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="sysadmin Role">
      <data key="d0">sysadmin Role</data>
      <data key="d1">DefensiveControl</data>
    </node>
    <node id="Time based Blind Injection">
      <data key="d0">Time based Blind Injection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="truncates SQL with `--`">
      <data key="d0">truncates SQL with `--`</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="User-Submitted `file` Parameter">
      <data key="d0">User-Submitted `file` Parameter</data>
      <data key="d1">UNKNOWN</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("User Input Vectors", "Artifact", "expected_type_mismatch"),
        (
            "bruteforcing sysadmin password<|AttackTechnique|>",
            "AttackTechnique",
            "non_canonical_type",
        ),
        ("sysadmin<|Role|>", "AttackerCapability", "non_canonical_type"),
        (
            "sp_OACreate<|TechnologyStack|>",
            "TechnologyStack",
            "non_canonical_type",
        ),
        (
            "sp_OADestroy<|TechnologyStack|>",
            "TechnologyStack",
            "non_canonical_type",
        ),
        (
            "sp_OAMethod<|TechnologyStack|>",
            "TechnologyStack",
            "non_canonical_type",
        ),
        (
            "CONVERT Function<|TechnologyStack|>",
            "TechnologyStack",
            "non_canonical_type",
        ),
        ("xp_log70.dll<|Artifact|>", "Artifact", "non_canonical_type"),
        (
            "xp_cmdshell<|TechnologyStack|>",
            "TechnologyStack",
            "non_canonical_type",
        ),
        (
            "sp_makewebtask<|TechnologyStack|>",
            "TechnologyStack",
            "non_canonical_type",
        ),
        (
            "@@VERSION<|ObservableSignal|>",
            "ObservableSignal",
            "non_canonical_type",
        ),
        (
            "4096 Byte Filename Limit",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("@@VERSION", "ObservableSignal", "expected_type_mismatch"),
        ("`create` IMAP Command", "PayloadPattern", "expected_type_mismatch"),
        ("`include` Function", "TechnologyStack", "expected_type_mismatch"),
        (
            "allows multiple SQL statements with `;`",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("Arbitrary File Read", "AttackerCapability", "expected_type_mismatch"),
        ("Base64-encoded Payload", "PayloadPattern", "expected_type_mismatch"),
        ("BENCHMARK", "TechnologyStack", "expected_type_mismatch"),
        (
            "bruteforcing sysadmin password",
            "AttackTechnique",
            "expected_type_mismatch",
        ),
        ("CONVERT Function", "TechnologyStack", "expected_type_mismatch"),
        ("debug.exe", "TechnologyStack", "expected_type_mismatch"),
        ("File Extension Appending", "AttackTechnique", "expected_type_mismatch"),
        (
            "Input Validation Failure",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            "Malicious Remote URL Injection",
            "AttackTechnique",
            "expected_type_mismatch",
        ),
        (
            "PHP `allow_url_include`",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("PHP Zip Wrapper (`zip://`)", "TechnologyStack", "expected_type_mismatch"),
        ("Remote Code Execution (RCE)", "AttackGoal", "expected_type_mismatch"),
        (
            "Sensitive Server Files (e.g., `/etc/passwd`)",
            "Artifact",
            "expected_type_mismatch",
        ),
        ("SLEEP", "TechnologyStack", "expected_type_mismatch"),
        ("sp_addextendedproc", "TechnologyStack", "expected_type_mismatch"),
        ("SQL Server 2005", "TechnologyStack", "expected_type_mismatch"),
        (
            "supports `pg_sleep(n)`",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("sysadmin", "AttackerCapability", "expected_type_mismatch"),
        ("sysadmin privilege", "AttackerCapability", "expected_type_mismatch"),
        ("sysadmin Role", "AttackerCapability", "expected_type_mismatch"),
        ("Time based Blind Injection", "AttackTechnique", "expected_type_mismatch"),
        ("truncates SQL with `--`", "PayloadPattern", "expected_type_mismatch"),
        (
            "User-Submitted `file` Parameter",
            "Artifact",
            "expected_type_mismatch",
        ),
    }
    assert dry_run["planned_noise_deletes"] == ["RIPS Tech"]
    assert "RIPS Tech" not in {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_handles_session_and_template_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="@ModelAttribute Annotation">
      <data key="d0">@ModelAttribute Annotation</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Allow Listing&lt;|DefensiveControl|&gt;">
      <data key="d0">Allow Listing&lt;|DefensiveControl|&gt;</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="call_user_func()">
      <data key="d0">call_user_func()</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cleartext HTTP/2 (H2C)">
      <data key="d0">Cleartext HTTP/2 (H2C)</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cookie Value Analysis">
      <data key="d0">Cookie Value Analysis</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="exploits">
      <data key="d0">exploits</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="FreeMaker">
      <data key="d0">FreeMaker</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Input Enumeration">
      <data key="d0">Input Enumeration</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Jinja2">
      <data key="d0">Jinja2</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="RFC Compliance Violation">
      <data key="d0">RFC Compliance Violation</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Sandbox Mechanisms&lt;|DefensiveControl|&gt;">
      <data key="d0">Sandbox Mechanisms&lt;|DefensiveControl|&gt;</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Session Fixation">
      <data key="d0">Session Fixation</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Twig">
      <data key="d0">Twig</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Character Set">
      <data key="d0">Character Set</data>
      <data key="d1">other</data>
    </node>
    <node id="Confidential Information">
      <data key="d0">Confidential Information</data>
      <data key="d1">other</data>
    </node>
    <node id="Expires Header">
      <data key="d0">Expires Header</data>
      <data key="d1">other</data>
    </node>
    <node id="Internal Property">
      <data key="d0">Internal Property</data>
      <data key="d1">other</data>
    </node>
    <node id="Privilege-related Property">
      <data key="d0">Privilege-related Property</data>
      <data key="d1">other</data>
    </node>
    <node id="Process-dependent Property">
      <data key="d0">Process-dependent Property</data>
      <data key="d1">other</data>
    </node>
    <node id="Sensitive Property">
      <data key="d0">Sensitive Property</data>
      <data key="d1">other</data>
    </node>
    <node id="Session ID Space">
      <data key="d0">Session ID Space</data>
      <data key="d1">other</data>
    </node>
    <node id="Black-Box Testing">
      <data key="d0">Black-Box Testing</data>
      <data key="d1">testingmethodology</data>
    </node>
    <node id="Gray-Box Testing">
      <data key="d0">Gray-Box Testing</data>
      <data key="d1">testingmethodology</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        (
            "@ModelAttribute Annotation",
            "TechnologyStack",
            "expected_type_mismatch",
        ),
        (
            "Allow Listing<|DefensiveControl|>",
            "DefensiveControl",
            "expected_type_mismatch",
        ),
        ("call_user_func()", "TechnologyStack", "expected_type_mismatch"),
        (
            "Cleartext HTTP/2 (H2C)",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("Cookie Value Analysis", "AttackTechnique", "expected_type_mismatch"),
        ("FreeMaker", "TechnologyStack", "expected_type_mismatch"),
        ("Input Enumeration", "AttackTechnique", "expected_type_mismatch"),
        ("Jinja2", "TechnologyStack", "expected_type_mismatch"),
        (
            "RFC Compliance Violation",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        (
            "Sandbox Mechanisms<|DefensiveControl|>",
            "DefensiveControl",
            "expected_type_mismatch",
        ),
        ("Session Fixation", "VulnerabilityClass", "expected_type_mismatch"),
        ("Twig", "TechnologyStack", "expected_type_mismatch"),
        ("Character Set", "PreconditionEnvironment", "expected_type_mismatch"),
        ("Confidential Information", "Artifact", "expected_type_mismatch"),
        ("Expires Header", "DefensiveControl", "expected_type_mismatch"),
        ("Internal Property", "Artifact", "expected_type_mismatch"),
        ("Privilege-related Property", "Artifact", "expected_type_mismatch"),
        ("Process-dependent Property", "Artifact", "expected_type_mismatch"),
        ("Sensitive Property", "Artifact", "expected_type_mismatch"),
        ("Session ID Space", "PreconditionEnvironment", "expected_type_mismatch"),
        ("Black-Box Testing", "AttackTechnique", "non_canonical_type"),
        ("Gray-Box Testing", "AttackTechnique", "non_canonical_type"),
    }
    assert dry_run["planned_noise_deletes"] == ["exploits"]
    assert "exploits" not in {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_handles_cookie_session_batch_entities(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="__Secure- Prefix">
      <data key="d0">__Secure- Prefix</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Contains Sensitive Data">
      <data key="d0">Contains Sensitive Data</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cookie Attributes">
      <data key="d0">Cookie Attributes</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cookie Prefixes">
      <data key="d0">Cookie Prefixes</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cookie Protection">
      <data key="d0">Cookie Protection</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cookie Review">
      <data key="d0">Cookie Review</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cookie Scope Control">
      <data key="d0">Cookie Scope Control</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Cross-Site Information Leakage">
      <data key="d0">Cross-Site Information Leakage</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="HTTP/1.0 Cache">
      <data key="d0">HTTP/1.0 Cache</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="HTTP/1.1 Cache">
      <data key="d0">HTTP/1.1 Cache</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="IP Address Restrictions">
      <data key="d0">IP Address Restrictions</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="IP Address Tracking">
      <data key="d0">IP Address Tracking</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Java Vulnerability CVE-2022-21449">
      <data key="d0">Java Vulnerability CVE-2022-21449</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Library Support for Embedded Keys">
      <data key="d0">Library Support for Embedded Keys</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Local Cache">
      <data key="d0">Local Cache</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Loose Path Attribute">
      <data key="d0">Loose Path Attribute</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="None algorithm">
      <data key="d0">None algorithm</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Public Computer Scenario">
      <data key="d0">Public Computer Scenario</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SameSite=None Value">
      <data key="d0">SameSite=None Value</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Session Management Page">
      <data key="d0">Session Management Page</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Source">
      <data key="d0">Source</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SSO System Logout">
      <data key="d0">SSO System Logout</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="SSO System Session">
      <data key="d0">SSO System Session</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Target">
      <data key="d0">Target</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Transport Security">
      <data key="d0">Transport Security</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="User Notification">
      <data key="d0">User Notification</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Application Logout">
      <data key="d0">Web Application Logout</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Web Application Session">
      <data key="d0">Web Application Session</data>
      <data key="d1">UNKNOWN</data>
    </node>
    <node id="Multi-IP Testing">
      <data key="d0">Multi-IP Testing</data>
      <data key="d1">attackmethod</data>
    </node>
    <node id="Multi-Location Testing">
      <data key="d0">Multi-Location Testing</data>
      <data key="d1">attackmethod</data>
    </node>
    <node id="Cookie Name Prefixes">
      <data key="d0">Cookie Name Prefixes</data>
      <data key="d1">concept</data>
    </node>
    <node id="__Host- Prefix">
      <data key="d0">__Host- Prefix</data>
      <data key="d1">cookienameprefix</data>
    </node>
    <node id="Text/plain Encoding">
      <data key="d0">Text/plain Encoding</data>
      <data key="d1">defensivecontrolbypass</data>
    </node>
    <node id="Source Code Review">
      <data key="d0">Source Code Review</data>
      <data key="d1">detectionmethod</data>
    </node>
    <node id="Session State">
      <data key="d0">Session State</data>
      <data key="d1">other</data>
    </node>
    <node id="Lax SameSite Value">
      <data key="d0">Lax SameSite Value</data>
      <data key="d1">samesiteattribute</data>
    </node>
    <node id="None SameSite Value">
      <data key="d0">None SameSite Value</data>
      <data key="d1">samesiteattribute</data>
    </node>
    <node id="Strict SameSite Value">
      <data key="d0">Strict SameSite Value</data>
      <data key="d1">samesiteattribute</data>
    </node>
    <node id="Black-Box Testing">
      <data key="d0">Black-Box Testing</data>
      <data key="d1">testmethodology</data>
    </node>
    <node id="Name">
      <data key="d0">Name</data>
      <data key="d1">type</data>
    </node>
    <node id="Type">
      <data key="d0">Type</data>
      <data key="d1">type</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)
    updates = plan_entity_type_updates(report)
    dry_run = normalize_lightrag_entity_types(
        graphml,
        dry_run=True,
        delete_noise_entities=True,
    )

    assert {
        (update.name, update.target_type, update.reason)
        for update in updates
    } >= {
        ("__Secure- Prefix", "DefensiveControl", "expected_type_mismatch"),
        (
            "Contains Sensitive Data",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("Cookie Attributes", "DefensiveControl", "expected_type_mismatch"),
        ("Cookie Prefixes", "DefensiveControl", "expected_type_mismatch"),
        ("Cookie Protection", "DefensiveControl", "expected_type_mismatch"),
        ("Cookie Review", "AttackTechnique", "expected_type_mismatch"),
        ("Cookie Scope Control", "DefensiveControl", "expected_type_mismatch"),
        (
            "Cross-Site Information Leakage",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        ("HTTP/1.0 Cache", "TechnologyStack", "expected_type_mismatch"),
        ("HTTP/1.1 Cache", "TechnologyStack", "expected_type_mismatch"),
        ("IP Address Restrictions", "DefensiveControl", "expected_type_mismatch"),
        ("IP Address Tracking", "DefensiveControl", "expected_type_mismatch"),
        (
            "Java Vulnerability CVE-2022-21449",
            "VulnerabilityClass",
            "expected_type_mismatch",
        ),
        (
            "Library Support for Embedded Keys",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("Local Cache", "TechnologyStack", "expected_type_mismatch"),
        (
            "Loose Path Attribute",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("None algorithm", "PayloadPattern", "expected_type_mismatch"),
        (
            "Public Computer Scenario",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("SameSite=None Value", "DefensiveControl", "expected_type_mismatch"),
        (
            "Session Management Page",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            "SSO System Logout",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            "SSO System Session",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("Transport Security", "DefensiveControl", "expected_type_mismatch"),
        ("User Notification", "DefensiveControl", "expected_type_mismatch"),
        (
            "Web Application Logout",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        (
            "Web Application Session",
            "PreconditionEnvironment",
            "expected_type_mismatch",
        ),
        ("Multi-IP Testing", "AttackTechnique", "non_canonical_type"),
        ("Multi-Location Testing", "AttackTechnique", "non_canonical_type"),
        ("Cookie Name Prefixes", "DefensiveControl", "expected_type_mismatch"),
        ("__Host- Prefix", "DefensiveControl", "non_canonical_type"),
        ("Text/plain Encoding", "AttackTechnique", "non_canonical_type"),
        ("Source Code Review", "AttackTechnique", "non_canonical_type"),
        ("Session State", "PreconditionEnvironment", "expected_type_mismatch"),
        ("Lax SameSite Value", "DefensiveControl", "non_canonical_type"),
        ("None SameSite Value", "DefensiveControl", "non_canonical_type"),
        ("Strict SameSite Value", "DefensiveControl", "non_canonical_type"),
        ("Black-Box Testing", "AttackTechnique", "non_canonical_type"),
    }
    assert dry_run["planned_noise_deletes"] == ["Name", "Source", "Target", "Type"]
    assert not {"Name", "Source", "Target", "Type"} & {
        update["name"] for update in dry_run["planned_updates"]
    }


def test_audit_blocks_and_plans_update_for_non_canonical_types(tmp_path):
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="d1" for="node" attr.name="entity_type" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Dir">
      <data key="d0">Dir</data>
      <data key="d1">operatingsystemcommands</data>
    </node>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )

    report = audit_lightrag_graph(graphml)

    assert [entity.name for entity in report.unknown_type_entities] == []
    assert [(entity.name, entity.canonical_type) for entity in report.non_canonical_type_entities] == [
        ("Dir", "PayloadPattern")
    ]
    assert report.has_blocking_issues is True
    assert {
        (update.name, update.target_type, update.reason)
        for update in plan_entity_type_updates(report)
    } == {("Dir", "PayloadPattern", "non_canonical_type")}
