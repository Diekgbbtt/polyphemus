import json
from pathlib import Path

from agent.lightrag.preprocess import (
    build_preprocessed_documents,
    classify_fragment,
    is_relation_fragment,
    parse_markdown_source,
    preprocess_sources_for_lightrag,
    preprocess_writeups_for_lightrag,
    preprocess_wstg_for_lightrag,
    qa_wstg_preprocessed_corpus,
)


def test_preprocess_builds_relation_briefs_and_facet_documents(tmp_path):
    source = tmp_path / "waf-bypass.md"
    source.write_text(
        """# WAF Bypass Methodology

## Controlled Facts

Alternate encoding probe is an AttackTechnique.

Web application firewall is a DefensiveControl.

Normalization mismatch is a PreconditionEnvironment.

Alternate encoding probe bypasses Web application firewall when Normalization mismatch is present.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "preprocessed"
    result = preprocess_sources_for_lightrag([source], output_dir)

    assert (output_dir / "relation-briefs.md").exists()
    assert (output_dir / "attack-methods.md").exists()
    assert (output_dir / "defenses-and-detections.md").exists()
    assert (output_dir / "prerequisites-and-environment.md").exists()

    relation_briefs = (output_dir / "relation-briefs.md").read_text(encoding="utf-8")
    assert "Alternate encoding probe bypasses Web application firewall" in relation_briefs
    assert "Ontology boundary: relation briefs are source-grounded and ontology-agnostic." in relation_briefs

    attack_methods = (output_dir / "attack-methods.md").read_text(encoding="utf-8")
    assert "Alternate encoding probe is an AttackTechnique." in attack_methods
    assert "LightRAG ontology" not in attack_methods.split("##", 1)[-1]

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["primary_document"] == "relation-briefs.md"
    assert manifest["fragments"]
    assert any(fragment["is_relation_brief"] for fragment in manifest["fragments"])
    assert result.generated_files[-1].name == ".manifest.json"


def test_wstg_static_qa_requires_ontology_anchor_block(tmp_path):
    source = tmp_path / "99-Testing_GraphQL.md"
    source.write_text(
        """# Testing GraphQL

ID
---
WSTG-APIT-99

## Summary

GraphQL introspection can reveal the schema and support object authorization testing.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)
    qa_result = qa_wstg_preprocessed_corpus(output_dir)

    methodology_text = (output_dir / "wstg-apit-99-methodology.md").read_text(
        encoding="utf-8"
    )
    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))

    assert qa_result.passed is True
    assert "## Ontology Query Anchors" in methodology_text
    assert "GraphQL Introspection Enabled" in methodology_text
    assert (
        manifest["scenarios"][0]["ontology_query_anchors"]["TechnologyStack"]
        == ["GraphQL", "Apollo Server"]
    )


def test_wstg_static_qa_flags_missing_required_anchor(tmp_path):
    output_dir = tmp_path / "wstg"
    output_dir.mkdir()
    (output_dir / "wstg-apit-99-methodology.md").write_text(
        "# Methodology Scenario\n\n- WSTG ID: WSTG-APIT-99\n",
        encoding="utf-8",
    )
    (output_dir / ".manifest.json").write_text(
        json.dumps(
            {
                "profile": "wstg",
                "scenarios": [
                    {
                        "wstg_id": "WSTG-APIT-99",
                        "title": "Testing GraphQL",
                        "primary_document": "wstg-apit-99-methodology.md",
                        "ontology_query_anchors": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    qa_result = qa_wstg_preprocessed_corpus(output_dir)

    assert qa_result.passed is False
    assert "missing_scenario_anchor" in {issue.code for issue in qa_result.issues}


def test_preprocess_preserves_code_blocks_in_payload_facet(tmp_path):
    source = tmp_path / "payload-example.md"
    source.write_text(
        """# Payload Notes

## Example

Use this HTTP request shape only as a documentation example.

```http
GET /items?id=1%20OR%201=1 HTTP/1.1
Host: example.test
```
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "preprocessed"
    preprocess_sources_for_lightrag([source], output_dir)

    code_doc = (output_dir / "code-and-payload-examples.md").read_text(encoding="utf-8")
    assert "```http" in code_doc
    assert "GET /items?id=1%20OR%201=1 HTTP/1.1" in code_doc
    assert "Block type: code" in code_doc


def test_build_result_keeps_relation_classification_separate_from_facets(tmp_path):
    source = tmp_path / "idor.md"
    source.write_text(
        """# IDOR Chaining

Object identifier harvesting enables Cross account object access.
""",
        encoding="utf-8",
    )

    result = build_preprocessed_documents([source])

    assert len(result.fragments) == 1
    fragment = result.fragments[0]
    assert is_relation_fragment(fragment) is True
    assert "attack-methods" in result.fragment_facets[fragment.fragment_id]


def test_classifier_avoids_substring_false_positives(tmp_path):
    source = tmp_path / "terms.md"
    source.write_text(
        """# Term Notes

Multi factor authentication bypass is a VulnerabilityClass.

User-controlled SQL input is a PreconditionEnvironment.
""",
        encoding="utf-8",
    )

    fragments = parse_markdown_source(source)
    bypass_facets = classify_fragment(fragments[0])
    controlled_facets = classify_fragment(fragments[1])

    assert bypass_facets == ["vulnerability-classes"]
    assert controlled_facets == ["prerequisites-and-environment"]


def test_wstg_profile_generates_scenario_scoped_documents(tmp_path):
    source = tmp_path / "05-Testing_for_SQL_Injection.md"
    source.write_text(
        """# Testing for SQL Injection

ID
---
WSTG-INPV-05

## Summary

SQL injection testing checks whether user-controlled data can influence SQL query construction without adequate input validation.

An SQL injection attack consists of insertion of either a partial or complete SQL query via the data input.

Reconnaissance is an important step in any testing activity. This includes API pentesting. Reconnaissance significantly enhances the effectiveness of the testing process by gathering information about the API and developing an understanding of the target. This phase not only increases the likelihood of discovering critical security issues but also ensures a comprehensive evaluation of the API security behavior.

This guide has a section on Information Gathering which can apply when auditing APIs. However, there are some differences. As security researchers, we often focus on specific areas and searching this guide for the sections that apply can be time consuming. To ensure the researcher has a single location to focus on APIs this section concentrates on those items that apply to APIs and provides references to supporting content elsewhere in the guide.

## Test Objectives

- Identify SQL injection points.
- Assess the level of access that can be achieved.

## How to Test

The tester lists input fields and parameters, then tests them separately to interfere with the query.

`https://www.example.com/news.php?id=1 AND 1=1`

The very first test usually consists of adding a single quote `'` or a semicolon `;` to the field or parameter under test. The first is used in SQL as a string terminator and, if not filtered by the application, would lead to an incorrect query. The second is used to end a SQL statement and, if it is not filtered, it is also likely to generate an error.

The blind SQL injection attack needs a high volume of queries. The tester may need an automatic tool to exploit the vulnerability.

For example, if you use `SQLMap`, this situation confuses the tool and the output gets messed up. Because the delays will not be as expected.

This is basically what all automatic tools do, they look for a marker in the response.

1. Extract the original query using `SQLMap` and blind injection.

```console
sqlmap -u "https://example.org/search?query=abcd'AND 1=2 UNION SELECT \"*\"-- -"
```

- ASCII (char): it gives back the ASCII value of the input character. A null value is returned if char is 0.

`$Id=1' OR ASCII(SUBSTRING(username,1,1))=97 AND '1'='1`

The tester can set up a web server (e.g. Apache) or use the Netcat tool:

Host: testerserver.com

```bash
/home/tester/nc –nLp 80
```

For the purpose of the OWASP Testing Guide, only the security threats related to web applications will be considered and not threats to web servers (e.g., the infamous `%5c` escape code into Microsoft IIS web server). Further reading suggestions will be provided in the references section for interested readers.

However, a full list of entities is defined by the HTML and XML specifications. Wikipedia has a complete reference.

For a more complete reference, see the Mozilla JavaScript guide.

### API Directories

- GitHub Public APIs Repository
- RapidAPI
- Postman API Network

### Analyze Intercepted Requests

When auditing REST APIs, use an interception proxy to collect full HTTP requests.

`robots.txt` is a text file that site owners create to instruct web crawlers (such as search engine bots) on how to crawl and index their site. It is part of the Robots Exclusion Protocol (REP), which regulates how bots interact with sites.

### Google Dorking

Using passive reconnaissance techniques such as Google Dorking with directives such as `site` and `inurl` helps identify API keywords indexed by the Google indexer.

### Look Back, Way Back

To discover older versions we can use the Wayback Machine to help find older endpoints.

- WayBackUrls
- waymore

Regular expression is more straightforward by searching JS or HTML content for known patterns. However, this approach can miss content not explicitly identified in the Regular Expression. Given the structure of some JS this approach can miss a lot. ASTs on the other hand are tree-like structures that represent the syntax of source code. Each node in the tree corresponds to a part of the code. For JavaScript, an AST breaks the code into basic components, allowing tools and compilers to understand and modify the code easily.

### Kiterunner

KiteRunner is a tool that performs traditional content discovery and bruteforcing routes/endpoints in modern applications and APIs.

```console
kr scan https://www.example.com/api -w routes-large.kite --fail-status-codes 404,403
```

## Remediation

Use parameterized queries and strict input validation.

- To secure the application from SQL injection vulnerabilities, refer to the SQL Injection Prevention CheatSheet.
- To secure the SQL server, refer to the Database Security CheatSheet.

For generic input validation security, refer to the Input Validation CheatSheet.

## References

### OWASP Resources

- REST Assessment Cheat Sheet
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    result = preprocess_wstg_for_lightrag([source], output_dir)

    methodology_doc = output_dir / "wstg-inpv-05-methodology.md"

    assert methodology_doc.exists()
    assert not (output_dir / "wstg-inpv-05-relation-briefs.md").exists()
    assert not (output_dir / "wstg-inpv-05-attack-methods.md").exists()

    methodology_text = methodology_doc.read_text(encoding="utf-8")
    assert "# Methodology Scenario" in methodology_text
    assert "## Methodology Scope" in methodology_text
    assert "## WSTG Scenario Anchor" in methodology_text
    assert "- WSTG ID: WSTG-INPV-05" in methodology_text
    assert "- WSTG title: Testing for SQL Injection" in methodology_text
    assert "- WSTG category: Input Validation Testing (INPV)" in methodology_text
    assert "Canonical aliases: WSTG-INPV-05, Testing for SQL Injection, SQL Injection" in methodology_text
    assert "Canonical VulnerabilityClass entities: SQL Injection" in methodology_text
    assert "SQL Injection is a VulnerabilityClass for WSTG scenario WSTG-INPV-05." in methodology_text
    assert "## Canonical Relation Anchors" in methodology_text
    assert "Concept SQL Injection maps to WSTG scenario WSTG-INPV-05." in methodology_text
    assert "Anchor: WSTG ID WSTG-INPV-05; WSTG title Testing for SQL Injection; WSTG category Input Validation Testing." in methodology_text
    assert "Source:" not in methodology_text
    assert "Source path:" not in methodology_text
    assert "OWASP WSTG" not in methodology_text
    assert "GitHub Public APIs Repository" not in methodology_text
    assert "RapidAPI" not in methodology_text
    assert "Postman API Network" not in methodology_text
    assert "WayBackUrls" not in methodology_text
    assert "TomNomNom" not in methodology_text
    assert "KiteRunner" not in methodology_text
    assert "kr scan" not in methodology_text
    assert "SQLMap" not in methodology_text
    assert "sqlmap" not in methodology_text
    assert "automatic tool" not in methodology_text
    assert "automatic tools" not in methodology_text
    assert "SQL Injection Prevention CheatSheet" not in methodology_text
    assert "Database Security CheatSheet" not in methodology_text
    assert "Input Validation CheatSheet" not in methodology_text
    assert "Netcat" not in methodology_text
    assert "Apache" not in methodology_text
    assert "testerserver" not in methodology_text
    assert "OWASP Testing Guide" not in methodology_text
    assert "Mozilla JavaScript guide" not in methodology_text
    assert "Wikipedia has a complete reference" not in methodology_text
    assert "/home/tester/nc" not in methodology_text
    assert "ASCII" not in methodology_text
    assert "SQL Injection attacks" not in methodology_text
    assert "An SQL injection attack" not in methodology_text
    assert "single quote" not in methodology_text
    assert "semicolon `;`" not in methodology_text
    assert "REST Assessment Cheat Sheet" not in methodology_text
    assert "an request" not in methodology_text
    assert "vulnerability classes" not in methodology_text
    assert "Security researchers" not in methodology_text
    assert "site owners" not in methodology_text
    assert "web crawlers" not in methodology_text
    assert "search engine indexer" not in methodology_text
    assert "API pentesting" not in methodology_text
    assert "API security behavior" not in methodology_text
    assert "Wordlists are helpful" not in methodology_text
    assert "request capture workflow" not in methodology_text
    assert "Blind SQL injection can require a high volume of requests" in methodology_text
    assert "SQL Injection as a vulnerability class" in methodology_text
    assert "<single_quote_string_terminator>" in methodology_text
    assert "<semicolon_statement_terminator>" in methodology_text
    assert "CHAR_CODE(SUBSTRING(username,1,1))=97" in methodology_text
    assert "attacker-controlled HTTP listener" in methodology_text
    assert "This scenario focuses on web application path traversal and file include behavior" in methodology_text
    assert "Capture full HTTP requests as artifacts" in methodology_text
    assert "search engine dorking" in methodology_text
    assert "Historical URL lookup can discover older target API route locations" in methodology_text
    assert "## Overview" in methodology_text
    assert "## Attack Methods" in methodology_text
    assert "## Defenses And Detections" in methodology_text
    assert "## Code And Payload Examples" in methodology_text
    assert "## Relation Briefs" in methodology_text
    assert "user-controlled data can influence SQL query construction" in methodology_text
    assert "parameterized queries" in methodology_text
    assert "https://www.example.com/news.php?id=1" not in methodology_text
    assert "<scheme>://<host>/<path> AND 1=1" in methodology_text

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "wstg"
    assert manifest["primary_document_pattern"] == "<wstg-id>-methodology.md"
    assert manifest["debug_facets"] is False
    assert manifest["scenarios"][0]["wstg_id"] == "WSTG-INPV-05"
    assert manifest["scenarios"][0]["category_code"] == "INPV"
    assert manifest["scenarios"][0]["category"] == "Input Validation Testing"
    assert "SQL Injection" in manifest["scenarios"][0]["canonical_aliases"]
    assert manifest["scenarios"][0]["canonical_vulnerability_classes"] == ["SQL Injection"]
    assert manifest["scenarios"][0]["primary_document"] == "wstg-inpv-05-methodology.md"
    assert result.generated_files[-1].name == ".manifest.json"


def test_wstg_profile_removes_reference_titles_from_ingestion_text(tmp_path):
    source = tmp_path / "09-Testing_for_XPath_Injection.md"
    source.write_text(
        """# Testing for XPath Injection

ID
---
WSTG-INPV-09

## Summary

The XPath attack pattern was first published by Amit Klein and is very similar to the usual SQL Injection.

Blind XPath Injection is explained in more detail by Amit Klein in the referenced paper.

## How to Test

For a comprehensive list of potential test strings see the XSS Filter Evasion Cheat Sheet.

The XSS Filter Evasion Cheat Sheet documents common filter evasion tests.

See the XSS Filter Evasion Cheat Sheet for a more detailed list of filter evasion techniques. Finally, analyzing answers can get complex.

More file inclusion payloads can be found at PayloadsAllTheThings - File Inclusion

You can find encoding techniques and ready to use directory traversal payloads at PayloadsAllTheThings - Directory Traversal

SSRF is known to be one of the hardest attacks to defeat without the use of allow lists that require specific IPs and URLs to be allowed. For more on SSRF prevention, read the Server Side Request Forgery Prevention Cheatsheet.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-inpv-09-methodology.md").read_text(encoding="utf-8")
    assert "PayloadsAllTheThings" not in methodology_text
    assert "XSS Filter Evasion Cheat Sheet" not in methodology_text
    assert "Server Side Request Forgery Prevention Cheatsheet" not in methodology_text
    assert "XPath attack pattern" not in methodology_text
    assert "Amit Klein" not in methodology_text
    assert "vulnerability classes" not in methodology_text
    assert "XPath Injection is similar to SQL Injection" in methodology_text
    assert "Blind XPath Injection can reconstruct data structure" in methodology_text
    assert "Finally, analyzing answers can get complex." in methodology_text
    assert "SSRF can be difficult to mitigate without strict allow lists" in methodology_text


def test_wstg_profile_filters_visual_taxonomy_and_raw_code_noise(tmp_path):
    source = tmp_path / "99-Testing_GraphQL.md"
    source.write_text(
        """# Testing GraphQL

ID
---
WSTG-APIT-99

## Summary

This vulnerability maps to [OWASP API Security Top 10 API3:2023 Broken Object Property Level Authorization](https://owasp.org/API-Security/editions/2023/en/0xa3-broken-object-property-level-authorization/).

In computer security, authentication is the process of attempting to verify the digital identity of the sender of a communication. A common example of such a process is the log on process. Testing the authentication schema means understanding how the authentication process works and using that information to circumvent the authentication mechanism.

![Parameter Modified Request](images/Basm-parammod.jpg)

*Figure 4.4.4-1: Parameter Modified Request*

## How to Test

Apollo Server can be configured to hide schema details from client errors.

The most straightforward way is to send an HTTP request (using a personal proxy) with the following payload, taken from an article on Medium:

Cross-site scripting occurs when an attacker injects executable code that is subsequently run by the browser. Learn about tests for XSS in the Input Validation chapter. You may test for reflected XSS using a payload from Testing for Reflected Cross Site Scripting.

Another method to bypass filters is the HTTP Parameter Pollution, this technique was first presented by Stefano di Paola and Luca Carettoni in 2009 at the OWASP Poland conference. See the Testing for HTTP Parameter pollution for more information. This evasion technique consists of splitting an attack vector between multiple request input fields that have the same name.

```text
javax.xml.parsers.DocumentBuilder
javax.xml.parsers.SAXParser
XMLReaderFactory
XMLInputFactory
```

```console
Exec Results for 'cmd.exe /c type "C:\\httpd\\public\\doc\\"Doc=Doc1.pdf+|+Dir c:\\'
Directory of c:\\
```
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-apit-99-methodology.md").read_text(encoding="utf-8")
    assert "OWASP API Security Top 10" not in methodology_text
    assert "digital identity" not in methodology_text
    assert "log on process" not in methodology_text
    assert "Parameter Modified Request" not in methodology_text
    assert "Figure" not in methodology_text
    assert "javax.xml.parsers" not in methodology_text
    assert "DocumentBuilder" not in methodology_text
    assert "XMLReaderFactory" not in methodology_text
    assert "Exec Results" not in methodology_text
    assert "Directory of c:" not in methodology_text
    assert "Medium" not in methodology_text
    assert "Input Validation chapter" not in methodology_text
    assert "Testing for Reflected Cross Site Scripting" not in methodology_text
    assert "Stefano di Paola" not in methodology_text
    assert "Luca Carettoni" not in methodology_text
    assert "OWASP Poland conference" not in methodology_text
    assert "This scenario concerns Broken Object Property Level Authorization." in methodology_text
    assert "Authentication schema testing analyzes" in methodology_text
    assert "Apollo Server can be configured to hide schema details" in methodology_text
    assert "GraphQL cross-site scripting testing sends reflected XSS payloads" in methodology_text
    assert "HTTP Parameter Pollution can bypass filters" in methodology_text


def test_wstg_profile_removes_editorial_easter_egg_history(tmp_path):
    source = tmp_path / "02-Test_Ability_to_Forge_Requests.md"
    source.write_text(
        """# Test Ability to Forge Requests

ID
---
WSTG-BUSL-02

## Summary

Also, forged requests may allow subversion of programmatic or business logic flow by invoking "hidden" features or functionality such as debugging initially used by developers and testers sometimes referred to as an "Easter egg"). "An Easter egg is an intentional inside joke, hidden message, or feature in a work such as a computer program, movie, book, or crossword. According to game designer Warren Robinett, the term was coined at Atari by personnel who were alerted to the presence of a secret message which had been hidden by Robinett in his already widely distributed game, Adventure. The name has been said to evoke the idea of a traditional Easter egg hunt."
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-busl-02-methodology.md").read_text(encoding="utf-8")
    assert "Warren Robinett" not in methodology_text
    assert "Atari" not in methodology_text
    assert "Adventure" not in methodology_text
    assert "traditional Easter egg hunt" not in methodology_text
    assert "hidden or debugging functionality" in methodology_text


def test_wstg_profile_removes_business_logic_editorial_references(tmp_path):
    source = tmp_path / "06-Testing_for_the_Circumvention_of_Work_Flows.md"
    source.write_text(
        """# Testing for the Circumvention of Work Flows

ID
---
WSTG-BUSL-06

## Summary

Definition of a workflow on Wikipedia:

> A workflow consists of a sequence of connected steps where each step follows without delay or gap and ends just before the subsequent step may begin. It is a depiction of a sequence of operations, declared as work of a person or group, an organization of staff, or one or more simple or complex mechanisms. Workflow may be seen as any abstraction of real work.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-busl-06-methodology.md").read_text(encoding="utf-8")
    assert "Wikipedia" not in methodology_text
    assert "A workflow is a sequence of connected application steps" in methodology_text


def test_wstg_profile_removes_inline_wikipedia_reference_text(tmp_path):
    source = tmp_path / "10-Map_Application_Architecture.md"
    source.write_text(
        """# Map Application Architecture

ID
---
WSTG-INFO-10

## Summary

The easiest way to detect a CDN is to perform a WHOIS lookup for the IP addresses that the domain resolves to. If they belong to a CDN company (such as Akamai, Cloudflare or Fastly - see Wikipedia for a more complete list), it is then likely that a CDN is in use.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-info-10-methodology.md").read_text(encoding="utf-8")
    assert "Wikipedia" not in methodology_text
    assert "Akamai, Cloudflare or Fastly" in methodology_text


def test_wstg_profile_compacts_architecture_mapping_scenario(tmp_path):
    source = tmp_path / "10-Map_Application_Architecture.md"
    source.write_text(
        """# Map Application Architecture

ID
---
WSTG-INFO-10

## Summary

Modern web applications can vary significantly in complexity.

## Test Objectives

- Understand the architecture of the application and the technologies in use.

## How to Test

### Network Components

#### Content Delivery Network (CDN)

The easiest way to detect a CDN is to perform a WHOIS lookup for the IP addresses that the domain resolves to. If they belong to a CDN company (such as Akamai, Cloudflare or Fastly - see Wikipedia for a more complete list), it is then likely that a CDN is in use.

#### Web Application Firewall (WAF)

Because a WAF blocks malicious requests, it can be detected by adding common attack strings to parameters and observing whether or not they are blocked.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-info-10-methodology.md").read_text(encoding="utf-8")
    assert len(methodology_text) < 8000
    assert "Wikipedia" not in methodology_text
    assert "Map Application Architecture" in methodology_text
    assert "Akamai, Cloudflare or Fastly" in methodology_text
    assert "WHOIS lookup" in methodology_text
    assert "Web Application Firewall" in methodology_text
    assert "## Relation Briefs" in methodology_text


def test_wstg_profile_compacts_api_recon_and_bola_scenarios(tmp_path):
    api_recon = tmp_path / "01-API_Reconnaissance.md"
    api_recon.write_text(
        """# API Reconnaissance

ID
---
WSTG-APIT-01

## Summary

API reconnaissance discovers documented and undocumented API endpoints.

## How to Test

### API Directories

- GitHub Public APIs Repository
- RapidAPI
- Postman API Network

### Look Back, Way Back

- WayBackUrls

### Kiterunner

KiteRunner can brute-force API endpoints.
""",
        encoding="utf-8",
    )
    bola = tmp_path / "02-API_Broken_Object_Level_Authorization.md"
    bola.write_text(
        """# API Broken Object Level Authorization

ID
---
WSTG-APIT-02

## Summary

Broken Object Level Authorization occurs when object identifiers are accepted without ownership checks.

## Tools

- Burp Suite
- ZAP
- Postman
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([api_recon, bola], output_dir)
    qa_result = qa_wstg_preprocessed_corpus(output_dir)

    apit01_text = (output_dir / "wstg-apit-01-methodology.md").read_text(encoding="utf-8")
    apit02_text = (output_dir / "wstg-apit-02-methodology.md").read_text(encoding="utf-8")

    assert qa_result.passed is True
    assert len(apit01_text) < 8500
    assert len(apit02_text) < 7500
    assert apit01_text.count("Anchor: WSTG ID") == 0
    assert apit02_text.count("Anchor: WSTG ID") == 0
    assert "## Ontology Query Anchors" in apit01_text
    assert "Historical URL Lookup" in apit01_text
    assert "Captured HTTP Request" in apit01_text
    assert "Deprecated API Route" in apit01_text
    assert "## Canonical Relation Anchors" in apit01_text
    assert "## Relation Briefs" in apit01_text
    assert "GitHub Public APIs Repository" not in apit01_text
    assert "RapidAPI" not in apit01_text
    assert "Postman API Network" not in apit01_text
    assert "WayBackUrls" not in apit01_text
    assert "KiteRunner" not in apit01_text
    assert "Broken Object-Level Authorization" in apit02_text
    assert "Tenant Scoped Object IDs" in apit02_text
    assert "Object ID Tampering" in apit02_text
    assert "Adjacent Account ID Accessible" in apit02_text
    assert "## Canonical Relation Anchors" in apit02_text
    assert "## Relation Briefs" in apit02_text
    assert "Burp Suite" not in apit02_text
    assert "ZAP" not in apit02_text
    assert "Postman" not in apit02_text


def test_wstg_profile_rewrites_well_known_external_reference_text(tmp_path):
    source = tmp_path / "03-Review_Webserver_Metafiles_for_Information_Leakage.md"
    source.write_text(
        """# Review Webserver Metafiles for Information Leakage

ID
---
WSTG-INFO-03

## How to Test

### Other .well-known Information Sources

There are other RFCs and internet drafts which suggest standardized uses of files within the `.well-known/` directory. Lists of these can be found [here on WikiPedia](https://en.wikipedia.org/wiki/List_of_/.well-known/_services_offered_by_webservers) or [here via IANA](https://www.iana.org/assignments/well-known-uris/well-known-uris.xhtml).
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-info-03-methodology.md").read_text(encoding="utf-8")
    assert "WikiPedia" not in methodology_text
    assert "Wikipedia" not in methodology_text
    assert "IANA" not in methodology_text
    assert "RFCs and internet drafts define additional standardized uses" in methodology_text
    assert "within the `.well-known/` directory." in methodology_text


def test_wstg_profile_rewrites_pci_dss_editorial_scope(tmp_path):
    source = tmp_path / "10-Test_Payment_Functionality.md"
    source.write_text(
        """# Test Payment Functionality

ID
---
WSTG-BUSL-10

## Summary

The Payment Card Industry Data Security Standard (PCI DSS) is a standard that organizations are required to follow in order process debit and card payments (although it's important to note that it is not a law). A full discussion of this standard is outside of the scope of this guide (and of most penetration tests) - but it's useful for testers to understand a few key points.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    methodology_text = (output_dir / "wstg-busl-10-methodology.md").read_text(encoding="utf-8")
    assert "Payment Card Industry" not in methodology_text
    assert "PCI DSS provides cardholder-data security requirements" in methodology_text


def test_wstg_profile_can_write_debug_facet_documents(tmp_path):
    source = tmp_path / "05-Testing_for_SQL_Injection.md"
    source.write_text(
        """# Testing for SQL Injection

ID
---
WSTG-INPV-05

## How to Test

The tester changes a parameter and observes whether SQL behavior changes.

## Remediation

Use parameterized queries.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir, debug_facets=True)

    assert (output_dir / "wstg-inpv-05-methodology.md").exists()
    assert (output_dir / "_debug_facets" / "wstg-inpv-05-relation-briefs.md").exists()
    assert (output_dir / "_debug_facets" / "wstg-inpv-05-attack-methods.md").exists()
    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["debug_facets"] is True
    assert manifest["scenarios"][0]["debug_files"]


def test_wstg_profile_avoids_overwriting_duplicate_id_outputs(tmp_path):
    main_source = tmp_path / "05-Testing_for_SQL_Injection.md"
    main_source.write_text(
        """# Testing for SQL Injection

ID
---
WSTG-INPV-05

## Summary

Main SQL injection testing methodology.
""",
        encoding="utf-8",
    )
    oracle_source = tmp_path / "05.1-Testing_for_Oracle.md"
    oracle_source.write_text(
        """# Testing for Oracle

ID
---
WSTG-INPV-05

## Summary

Oracle-specific SQL injection testing methodology.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([main_source, oracle_source], output_dir)

    primary_doc = output_dir / "wstg-inpv-05-methodology.md"
    oracle_doc = output_dir / "wstg-inpv-05-05-1-testing-for-oracle-methodology.md"

    assert primary_doc.exists()
    assert oracle_doc.exists()
    assert "Main SQL injection" in primary_doc.read_text(encoding="utf-8")
    assert "Oracle-specific SQL injection" in oracle_doc.read_text(encoding="utf-8")

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    generated_names = {Path(path).name for path in manifest["generated_files"]}
    assert primary_doc.name in generated_names
    assert oracle_doc.name in generated_names


def test_wstg_profile_infers_decimal_scenario_id_from_path(tmp_path):
    source_dir = tmp_path / "07-Input_Validation_Testing"
    source_dir.mkdir()
    source = source_dir / "05.7-Testing_for_ORM_Injection.md"
    source.write_text(
        """# Testing for ORM Injection

## Summary

ORM injection testing checks whether generated query layers accept unsanitized input.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir)

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenarios"][0]["wstg_id"] == "WSTG-INPV-05-7"
    assert manifest["scenarios"][0]["primary_document"] == "wstg-inpv-05-7-methodology.md"
    assert (output_dir / "wstg-inpv-05-7-methodology.md").exists()
    assert not list(output_dir.glob("wstg-unkn-*-methodology.md"))


def test_wstg_profile_skips_merged_placeholder_documents(tmp_path):
    source = tmp_path / "01-Testing_for_Credentials_Transported_over_an_Encrypted_Channel.md"
    source.write_text(
        """# Testing for Credentials Transported over an Encrypted Channel

ID
---
WSTG-ATHN-01

[merged]: # (WSTG-CRYP-03)

This content has been merged into: Testing for Sensitive Information Sent via Unencrypted Channels
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "wstg"
    stale = output_dir / "wstg-athn-01-methodology.md"
    output_dir.mkdir()
    stale.write_text("stale generated content", encoding="utf-8")

    preprocess_wstg_for_lightrag([source], output_dir)

    assert not stale.exists()
    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenarios"] == []


def test_wstg_profile_skips_removed_placeholder_documents(tmp_path):
    source = tmp_path / "13-Testing_for_Buffer_Overflow.md"
    source.write_text(
        """# Testing for Buffer Overflow

ID
---
WSTG-INPV-13

This content has been removed
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "wstg"

    preprocess_wstg_for_lightrag([source], output_dir)

    assert not (output_dir / "wstg-inpv-13-methodology.md").exists()
    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenarios"] == []


def test_writeup_profile_generates_overlay_methodology_document(tmp_path):
    source = tmp_path / "htb-trick.html"
    source.write_text(
        """<!doctype html>
<html>
  <head>
    <title>HTB: Trick | 0xdf hacks stuff</title>
    <link rel="canonical" href="https://0xdf.gitlab.io/2022/10/29/htb-trick.html">
  </head>
  <body>
    <main class="page-content">
      <h1 class="post-title">HTB: Trick</h1>
      <time datetime="2022-10-29">Oct 29, 2022</time>
      <span class="tag-list"><a href="/tags#sqli" class="post-tag">sqli</a></span>
      <h2>SQL Injection</h2>
      <p>The login form is vulnerable to SQL injection and the auth bypass works with or 1=1-- -.</p>
      <p>sqlmap --file-read=/etc/passwd gives file read and confirms Linux host access.</p>
      <h2>Find Marketing Subdomain</h2>
      <p>Reading the NGINX config reveals a server_name virtual host and enables vhost discovery.</p>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "writeups"
    result = preprocess_writeups_for_lightrag([source], output_dir)

    methodology_doc = output_dir / "htb-trick-methodology.md"
    assert methodology_doc.exists()
    text = methodology_doc.read_text(encoding="utf-8")
    assert "# Writeup Methodology Overlay" in text
    assert "## Methodology Scope" in text
    assert "## Source Metadata" not in text
    assert "## Source Context" not in text
    assert "Source URL: https://0xdf.gitlab.io/2022/10/29/htb-trick.html" not in text
    assert "Source path:" not in text
    assert "0xdf" not in text
    assert "Evidence:" not in text
    assert "Evidence ids:" not in text
    assert "fragment f" not in text
    assert "## Attack Chain Summary" in text
    assert "## Technology And Preconditions" in text
    assert "## Technique Cards" in text
    assert "SQL Injection Auth Bypass" in text
    assert "SQL Injection File Read" in text
    assert "## Relation Briefs" in text
    assert "can produce artifact Config File" in text
    assert "Artifact Config File can reveal precondition Name-Based Virtual Host Routing" in text

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "writeup"
    assert manifest["knowledge_tier"] == "review_overlay"
    assert manifest["writeups"][0]["primary_document"] == "htb-trick-methodology.md"
    assert result.generated_files[-1].name == ".manifest.json"
