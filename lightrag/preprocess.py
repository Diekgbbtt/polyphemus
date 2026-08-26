from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_OUTPUT_DIR = Path("lightrag/data/lightrag/inputs/__preprocessed__")
DEFAULT_WSTG_OUTPUT_DIR = Path("lightrag/data/lightrag/inputs/wstg_preprocessed")
DEFAULT_WRITEUP_OUTPUT_DIR = Path("lightrag/data/lightrag/inputs/writeups_overlay")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WSTG_ID_RE = re.compile(r"\bWSTG-[A-Z]{4}-\d{2}(?:[-.]\d+)?\b")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_URL_RE = re.compile(r"https?://[^\s)>`]+")
_WSTG_PATH_NUMBER_RE = re.compile(r"^(?P<major>\d{2})(?:[._-](?P<minor>\d+))?[-_]")
_WSTG_CATEGORY_CODES = {
    "01-Information_Gathering": "INFO",
    "02-Configuration_and_Deployment_Management_Testing": "CONF",
    "03-Identity_Management_Testing": "IDNT",
    "04-Authentication_Testing": "ATHN",
    "05-Authorization_Testing": "ATHZ",
    "06-Session_Management_Testing": "SESS",
    "07-Input_Validation_Testing": "INPV",
    "08-Testing_for_Error_Handling": "ERRH",
    "09-Testing_for_Weak_Cryptography": "CRYP",
    "10-Business_Logic_Testing": "BUSL",
    "11-Client-side_Testing": "CLNT",
    "12-API_Testing": "APIT",
}
_WSTG_CATEGORY_NAMES = {
    "INFO": "Information Gathering",
    "CONF": "Configuration and Deployment Management Testing",
    "IDNT": "Identity Management Testing",
    "ATHN": "Authentication Testing",
    "ATHZ": "Authorization Testing",
    "SESS": "Session Management Testing",
    "INPV": "Input Validation Testing",
    "ERRH": "Error Handling",
    "CRYP": "Weak Cryptography",
    "BUSL": "Business Logic Testing",
    "CLNT": "Client-side Testing",
    "APIT": "API Testing",
}
_WSTG_EXTERNAL_REFERENCE_HEADINGS = (
    "api directories",
    "references",
    "owasp resources",
    "books",
    "general tools",
    "regular expression tools",
    "ast tools",
    "other recon tools",
)
_WSTG_TOOL_SPECIFIC_HEADINGS = (
    "kiterunner",
    "ffuf/dirbuster/gobuster",
    "ffuf",
    "dirbuster",
    "gobuster",
)
_WSTG_QA_FORBIDDEN_TERMS = (
    "OWASP Testing Guide",
    "Mozilla JavaScript Guide",
    "Wikipedia",
    "PayloadsAllTheThings",
)
_WSTG_CANONICAL_VULNERABILITY_CLASS_ALIASES = {
    "WSTG-ATHZ-01": (
        "Path Traversal",
        "Directory Traversal File Include",
        "Directory Traversal",
        "File Include",
    ),
    "WSTG-INPV-01": (
        "Reflected Cross-Site Scripting",
        "Reflected Cross-site Scripting",
        "Reflected Cross Site Scripting",
        "Reflected XSS",
        "Non-Persistent Cross-Site Scripting",
    ),
    "WSTG-INPV-05": ("SQL Injection",),
    "WSTG-INPV-05-6": ("NoSQL Injection",),
    "WSTG-INPV-06": ("LDAP Injection",),
    "WSTG-INPV-07": ("XML Injection",),
    "WSTG-INPV-09": ("XPath Injection",),
    "WSTG-INPV-12": ("Command Injection", "OS Command Injection"),
    "WSTG-INPV-19": (
        "Server-Side Request Forgery",
        "Server-side Request Forgery",
        "SSRF",
    ),
}

_WSTG_ONTOLOGY_QUERY_ANCHORS: dict[str, dict[str, tuple[str, ...]]] = {
    "WSTG-SESS-01": {
        "PreconditionEnvironment": (
            "Cookie-Backed Session",
            "Server-Side Session Identifier",
        ),
        "Artifact": ("Session Cookie", "Session Identifier"),
        "ObservableSignal": ("Session Token Accepted",),
    },
    "WSTG-SESS-02": {
        "PreconditionEnvironment": ("Cookie-Backed Session", "Remember Me Cookie"),
        "DefensiveControl": ("Secure Cookie Attribute", "HttpOnly Cookie Attribute"),
        "Artifact": ("Session Cookie", "Remember Me Token"),
        "ObservableSignal": ("Weak Cookie Attribute",),
    },
    "WSTG-SESS-03": {
        "PreconditionEnvironment": ("Session Identifier Accepted Before Login",),
        "VulnerabilityClass": ("Session Fixation",),
        "AttackTechnique": ("Session Identifier Fixation",),
        "ObservableSignal": ("Session Identifier Does Not Rotate After Login",),
    },
    "WSTG-SESS-05": {
        "PreconditionEnvironment": ("Cookie-Backed Session", "Cross-Origin Request"),
        "VulnerabilityClass": ("Cross-Site Request Forgery",),
        "DefensiveControl": ("SameSite Cookie Attribute", "CSRF Token"),
        "ObservableSignal": ("Cross-Site State Change",),
    },
    "WSTG-SESS-06": {
        "PreconditionEnvironment": ("Logout Clears Browser Storage Only",),
        "AttackTechnique": ("Logout Functionality Testing",),
        "Artifact": ("Session Token", "Browser Storage Token"),
        "ObservableSignal": ("Token Remains Valid After Logout",),
    },
    "WSTG-SESS-10": {
        "TechnologyStack": ("JSON Web Token", "JWT"),
        "PreconditionEnvironment": (
            "Bearer Token Authentication",
            "JWT Bearer Access Token",
        ),
        "Artifact": ("JWT Access Token",),
        "AttackTechnique": ("JWT Claim Tampering", "JWT Signature Validation Test"),
        "ObservableSignal": ("Accepted Modified JWT",),
    },
    "WSTG-CLNT-01": {
        "TechnologyStack": ("Single Page Application", "Client-Side JavaScript"),
        "PreconditionEnvironment": ("Client-Rendered User Input",),
        "VulnerabilityClass": ("DOM-Based Cross-Site Scripting",),
        "ObservableSignal": ("Browser Executes Injected Script",),
    },
    "WSTG-CLNT-07": {
        "TechnologyStack": ("Browser CORS", "Cross-Origin Resource Sharing"),
        "PreconditionEnvironment": (
            "CORS Allows Reflected Origin",
            "Access-Control-Allow-Credentials True",
        ),
        "DefensiveControl": ("CORS Origin Allowlist",),
        "ObservableSignal": ("Credentialed Cross-Origin Response",),
    },
    "WSTG-CLNT-11": {
        "TechnologyStack": ("Browser PostMessage", "Iframe Widget"),
        "PreconditionEnvironment": (
            "postMessage Wildcard Origin",
            "Embedded Admin Widget",
        ),
        "AttackTechnique": ("Cross-Origin Message Injection",),
        "ObservableSignal": ("Privileged UI Action Triggered By Message",),
    },
    "WSTG-CLNT-12": {
        "TechnologyStack": ("Browser Storage", "localStorage"),
        "PreconditionEnvironment": ("JWT Stored In LocalStorage",),
        "Artifact": ("Browser Storage Token", "JWT Access Token"),
        "ObservableSignal": ("Sensitive Token Readable By JavaScript",),
    },
    "WSTG-CLNT-13": {
        "TechnologyStack": ("Cross-Site Script Inclusion", "Third-Party Script"),
        "PreconditionEnvironment": ("Third-Party Origin Loads Script",),
        "ObservableSignal": ("Cross-Origin Script Data Exposure",),
    },
    "WSTG-CONF-05": {
        "PreconditionEnvironment": ("Verbose Error Disclosure", "Public Object Storage"),
        "VulnerabilityClass": ("Information Leakage",),
        "Artifact": ("Stack Trace", "Public Download URL"),
        "ObservableSignal": ("Sensitive Error Message",),
    },
    "WSTG-CONF-12": {
        "DefensiveControl": ("Content-Security-Policy", "CSP"),
        "PreconditionEnvironment": ("Missing Content-Security-Policy",),
        "ObservableSignal": ("Script Execution Not Restricted By CSP",),
    },
    "WSTG-ERRH-01": {
        "PreconditionEnvironment": ("Verbose Error Disclosure",),
        "Artifact": ("Stack Trace", "Database Error Message"),
        "ObservableSignal": ("Improper Error Handling",),
    },
    "WSTG-ATHZ-01": {
        "PreconditionEnvironment": (
            "Download By Path Parameter",
            "Template Preview Parameter",
        ),
        "VulnerabilityClass": ("Path Traversal", "File Include"),
        "PayloadPattern": ("../ Path Traversal Payload", "URL Encoded Separator"),
        "ObservableSignal": ("Different Error For Absolute Path",),
    },
    "WSTG-ATHZ-02": {
        "PreconditionEnvironment": ("Tenant Scoped Object IDs",),
        "VulnerabilityClass": ("Authorization Schema Bypass",),
        "AttackTechnique": ("Forced Browsing To Unauthorized Function",),
        "ObservableSignal": ("Authorization Response Difference",),
    },
    "WSTG-ATHZ-05": {
        "PreconditionEnvironment": (
            "Sequential Object Identifier",
            "Adjacent Account ID Request",
        ),
        "VulnerabilityClass": (
            "Insecure Direct Object Reference",
            "Broken Object-Level Authorization",
        ),
        "AttackTechnique": ("Object ID Tampering",),
        "ObservableSignal": ("Cross-Tenant Object Access",),
    },
    "WSTG-INPV-01": {
        "PreconditionEnvironment": (
            "Reflected Search Parameter",
            "User-Controlled HTML Reflected Into Client Route",
        ),
        "VulnerabilityClass": ("Reflected Cross-Site Scripting",),
        "PayloadPattern": ("<script> Payload",),
        "ObservableSignal": ("Browser Executes Injected Script",),
    },
    "WSTG-INPV-05": {
        "TechnologyStack": ("SQL Database", "PostgreSQL"),
        "PreconditionEnvironment": (
            "User-Controlled SQL Input",
            "Sort Expression Accepted As String",
        ),
        "VulnerabilityClass": ("SQL Injection",),
        "PayloadPattern": ("UNION SELECT Payload", "Time-Based SQL Payload"),
        "ObservableSignal": ("Database Error Message", "Response Time Delay"),
    },
    "WSTG-INPV-05-6": {
        "TechnologyStack": ("NoSQL Database", "MongoDB"),
        "PreconditionEnvironment": (
            "Nested JSON Request Body",
            "Raw JSON Operators Preserved",
        ),
        "VulnerabilityClass": ("NoSQL Injection",),
        "PayloadPattern": ("NoSQL Operator Injection Payload",),
        "ObservableSignal": ("NoSQL Query Logic Change",),
    },
    "WSTG-INPV-11": {
        "PreconditionEnvironment": (
            "File Path Request Input",
            "Download By Path Parameter",
        ),
        "VulnerabilityClass": ("Path Traversal",),
        "PayloadPattern": ("../ Path Traversal Payload",),
        "ObservableSignal": ("Sensitive File Read",),
    },
    "WSTG-INPV-11-1": {
        "PreconditionEnvironment": ("Template Preview Parameter",),
        "VulnerabilityClass": ("File Include", "Local File Inclusion"),
        "PayloadPattern": ("File Include Payload",),
        "ObservableSignal": ("Included File Content Returned",),
    },
    "WSTG-INPV-12": {
        "PreconditionEnvironment": ("User-Controlled Command Input",),
        "VulnerabilityClass": ("Command Injection",),
        "PayloadPattern": ("Command Separator Payload",),
        "ObservableSignal": ("Command Output", "Response Time Delay"),
    },
    "WSTG-INPV-19": {
        "PreconditionEnvironment": (
            "Server-Side URL Fetch Feature",
            "Redirects Followed",
            "Metadata Endpoint Reachable",
        ),
        "VulnerabilityClass": ("Server-Side Request Forgery",),
        "PayloadPattern": ("Loopback URL Payload", "Encoded Host Variant"),
        "ObservableSignal": ("Internal Service Response Timing Difference",),
    },
    "WSTG-APIT-01": {
        "TechnologyStack": ("REST API", "GraphQL API", "OpenAPI"),
        "PreconditionEnvironment": (
            "Exposed API Endpoint",
            "API Documentation Available",
            "Deprecated API Version Reachable",
            "Client-Side API Route Reference",
        ),
        "AttackTechnique": (
            "API Documentation Discovery",
            "API Endpoint Enumeration",
            "Historical URL Lookup",
        ),
        "Artifact": (
            "API Documentation",
            "OpenAPI Specification",
            "Endpoint List",
            "Captured HTTP Request",
        ),
        "ObservableSignal": (
            "Discovered API Route",
            "Deprecated API Route",
            "Exposed API Secret",
        ),
    },
    "WSTG-APIT-02": {
        "TechnologyStack": ("REST API", "GraphQL API"),
        "PreconditionEnvironment": ("Tenant Scoped Object IDs",),
        "VulnerabilityClass": ("Broken Object-Level Authorization",),
        "AttackTechnique": ("Object ID Tampering",),
        "ObservableSignal": ("Adjacent Account ID Accessible",),
    },
    "WSTG-APIT-99": {
        "TechnologyStack": ("GraphQL", "Apollo Server"),
        "PreconditionEnvironment": (
            "GraphQL Endpoint",
            "GraphQL Introspection Enabled",
            "Client-Controlled GraphQL Query",
        ),
        "VulnerabilityClass": (
            "Broken Object-Level Authorization",
            "Broken Object Property Level Authorization",
        ),
        "AttackTechnique": ("GraphQL Introspection Query", "GraphQL Field Tampering"),
        "Artifact": ("GraphQL Schema",),
        "ObservableSignal": ("Introspection Response", "GraphQL Authorization Bypass"),
    },
    "WSTG-BUSL-08": {
        "PreconditionEnvironment": ("File Upload Workflow",),
        "VulnerabilityClass": ("Upload Of Unexpected File Types",),
        "DefensiveControl": ("File Extension Allowlist", "MIME Type Validation"),
        "ObservableSignal": ("Unexpected File Type Accepted",),
    },
    "WSTG-BUSL-09": {
        "PreconditionEnvironment": ("Authenticated File Upload Pipeline",),
        "VulnerabilityClass": ("Malicious File Upload",),
        "AttackTechnique": ("Malicious File Upload",),
        "Artifact": ("Uploaded File", "Public Download URL"),
        "ObservableSignal": ("Uploaded File Served From Public URL",),
    },
    "WSTG-INFO-10": {
        "TechnologyStack": (
            "CDN",
            "Object Storage",
            "Reverse Proxy",
            "Web Application Firewall",
        ),
        "PreconditionEnvironment": ("Public Application Edge",),
        "Artifact": ("HTTP Headers", "DNS Records", "Public Download URL"),
        "ObservableSignal": ("Origin Exposure", "WAF Block Page"),
    },
}


@dataclass(frozen=True)
class FacetSpec:
    key: str
    title: str
    description: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class SourceFragment:
    fragment_id: str
    source_id: str
    source_path: str
    document_title: str
    heading_path: tuple[str, ...]
    locator: str
    text: str
    line_start: int
    line_end: int
    block_type: str


@dataclass
class PreprocessResult:
    fragments: list[SourceFragment]
    fragment_facets: dict[str, list[str]]
    generated_files: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class CorpusQAIssue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class WSTGCorpusQAResult:
    passed: bool
    scenario_count: int
    generated_document_count: int
    max_document_chars: int
    issues: list[CorpusQAIssue]

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_FACETS: tuple[FacetSpec, ...] = (
    FacetSpec(
        key="attack-methods",
        title="Attack Methods",
        description=(
            "Reusable offensive techniques, probes, exploit approaches, bypass "
            "methods, and chained attacker actions."
        ),
        keywords=(
            "attack",
            "attacktechnique",
            "technique",
            "probe",
            "exploit",
            "exploits",
            "bypasses",
            "bypass method",
            "bypass technique",
            "tamper",
            "tampering",
            "harvesting",
            "fixation",
            "payload",
            "chaining",
        ),
    ),
    FacetSpec(
        key="defenses-and-detections",
        title="Defenses And Detections",
        description=(
            "Controls, filters, validation layers, mitigations, detection signals, "
            "and conditions under which they observe or block behavior."
        ),
        keywords=(
            "defense",
            "defensive",
            "defensivecontrol",
            "control",
            "firewall",
            "waf",
            "filter",
            "filters",
            "filtered",
            "block",
            "blocking",
            "detect",
            "detects",
            "detectedby",
            "mitigate",
            "mitigates",
            "middleware",
            "enforcement",
            "validation",
        ),
    ),
    FacetSpec(
        key="prerequisites-and-environment",
        title="Prerequisites And Environment",
        description=(
            "Target states, environmental preconditions, and setup facts that "
            "make a method applicable."
        ),
        keywords=(
            "prerequisite",
            "precondition",
            "condition",
            "conditions",
            "environment",
            "preconditionenvironment",
            "requires",
            "require",
            "required",
            "enables",
            "enable",
            "enabled",
            "when",
            "if ",
            "present",
            "state",
            "user-controlled",
            "low privileged",
            "normalization mismatch",
            "session rotation",
        ),
    ),
    FacetSpec(
        key="vulnerability-classes",
        title="Vulnerability Classes",
        description=(
            "Reusable weakness classes, vulnerability families, taxonomy names, "
            "and impact-oriented descriptions."
        ),
        keywords=(
            "vulnerability",
            "vulnerabilityclass",
            "weakness",
            "cwe",
            "owasp",
            "capec",
            "sql injection",
            "insecure direct object reference",
            "idor",
            "authentication bypass",
        ),
    ),
    FacetSpec(
        key="code-and-payload-examples",
        title="Code And Payload Examples",
        description=(
            "Code snippets, HTTP examples, payload examples, command examples, "
            "and concrete request or response material."
        ),
        keywords=(
            "payload",
            "snippet",
            "example request",
            "http request",
            "curl ",
            "code",
            "```",
            "<script",
            "union select",
        ),
    ),
    FacetSpec(
        key="source-context",
        title="Source Context",
        description=(
            "Source material that does not fit a narrower facet but may preserve "
            "document framing, definitions, or assumptions."
        ),
        keywords=(),
    ),
)

RELATION_KEYWORDS: tuple[str, ...] = (
    "bypasses",
    "requires",
    "exploits",
    "mitigates",
    "detectedby",
    "detected by",
    "enables",
    "blocks",
)

WSTG_FACET_TITLES: dict[str, tuple[str, str]] = {
    "overview": (
        "Overview",
        "Scenario summary, vulnerability framing, impact, and core testing purpose.",
    ),
    "test-objectives": (
        "Test Objectives",
        "Explicit objectives a tester should satisfy for this WSTG scenario.",
    ),
    "attack-methods": (
        "Attack Methods",
        "Concrete testing procedures, probes, exploitation approaches, and technique variants.",
    ),
    "prerequisites-and-environment": (
        "Prerequisites And Environment",
        "Target conditions, reachable inputs, side channels, and applicability constraints.",
    ),
    "defenses-and-detections": (
        "Defenses And Detections",
        "Controls, validation behavior, mitigations, detection signals, and defensive limits.",
    ),
    "code-and-payload-examples": (
        "Code And Payload Examples",
        "Payloads, URLs, SQL snippets, command examples, and concrete request material.",
    ),
    "references": (
        "References",
        "Tools, external references, standards, and source reading material.",
    ),
    "source-context": (
        "Source Context",
        "Useful scenario context that did not match a narrower WSTG methodology facet.",
    ),
}

WRITEUP_FACET_TITLES: dict[str, tuple[str, str]] = {
    "attack-chain-summary": (
        "Attack Chain Summary",
        "Ordered chain markers, preconditions, technologies, techniques, capabilities, artifacts, goals, and signals.",
    ),
    "technology-and-preconditions": (
        "Technology And Preconditions",
        "Reusable target technologies and environmental preconditions that influence methodology selection.",
    ),
    "technique-cards": (
        "Technique Cards",
        "Reusable offensive techniques with evidence-grounded preconditions, goals, produced artifacts, signals, and limits.",
    ),
    "artifacts-and-capabilities": (
        "Artifacts And Attacker Capabilities",
        "Concrete objects and attacker capabilities produced or consumed by the chain.",
    ),
    "defensive-controls-and-bypasses": (
        "Defensive Controls And Bypasses",
        "Controls, filters, blockers, and payload or technique variants that bypass or work around them.",
    ),
    "relation-briefs": (
        "Relation Briefs",
        "Normalized operational claims suitable for graph extraction.",
    ),
    "source-context": (
        "Source Context",
        "Useful writeup fragments that did not match a narrower methodology facet.",
    ),
}

WRITEUP_CONCEPT_PATTERNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "PreconditionEnvironment": (
        ("Reachable Login Workflow", ("login form", "log in", "login", "username", "password")),
        ("Accessible Upload Handler", ("upload", "uploaded", "file upload", "uploads/")),
        ("Server-Side URL Fetch Feature", ("import project", "repo by url", "file_url", "url", "fetch")),
        ("Accessible SMB Share", ("smb share", "file share", "smbclient", "smbmap")),
        ("Name-Based Virtual Host Routing", ("vhost", "vhosts", "virtual host", "server_name", "host header")),
        ("Exposed Git Repository", (".git", "git-dumper", "git repo", "source repository")),
        ("Accessible API Endpoint", ("api", "endpoint", "json", "graphql", "swagger")),
        ("LDAP-Backed Query Path", ("ldap", "ldap injection")),
        ("JWT Authentication Flow", ("jwt", "token", "bearer")),
        ("Reachable Admin Panel", ("admin panel", "dashboard", "admin dashboard")),
        ("Writable WebDAV Path", ("webdav", "put ")),
        ("User-Controlled Input Reaches Query", ("user-controlled", "input", "query")),
        ("Verbose Error Disclosure", ("error message", "warning:", "query failed", "unterminated")),
        ("Boolean Response Difference", ("boolean", "true", "false", "different response")),
        ("Uploaded Files Are Web Served", ("uploads/", "available in", "uploaded files", "webshell works")),
        ("Executable Extension Interpreted", (".php", ".phtml", ".aspx", "executes")),
        ("Localhost-Only Service Exists", ("localhost", "127.0.0.1", "only from localhost", "redis")),
        ("Admin Visits Attacker-Controlled Content", ("admin will click", "opened with file explorer", "victim")),
        ("Writable Publish Path", ("write access", "commit", "push", "cicd")),
        ("Weak Or Reused Password Exists", ("password reuse", "rockyou", "cracked")),
    ),
    "TechnologyStack": (
        ("PHP", ("php", ".php", "phtml")),
        ("Python Web Stack", ("python", "flask", "django", "werkzeug", "sentry")),
        ("ASP.NET", ("asp.net", "aspx", "iis")),
        ("Apache", ("apache", "apache2")),
        ("NGINX", ("nginx", "nginx config")),
        ("IIS", ("iis", "microsoft-iis")),
        ("MySQL", ("mysql", "mariadb")),
        ("PostgreSQL", ("postgresql", "postgres", "pg_query")),
        ("MSSQL", ("mssql", "xp_cmdshell")),
        ("Redis", ("redis", "6379")),
        ("GitLab", ("gitlab", "git-upload-pack")),
        ("Windows Active Directory", ("active directory", "kerberos", "ldap", "bloodhound")),
        ("Linux Host", ("linux", "/etc/passwd", "/bin/bash")),
        ("Container", ("container", "docker", "podman")),
    ),
    "DefensiveControl": (
        ("Extension Blacklist", ("extension", "blocked", ".php3", ".php4", ".php5")),
        ("Protocol Allowlist", ("only accepts", "http://", "https://", "git://")),
        ("Localhost Denylist", ("blocks connections to 127.0.0.1", "unacceptable url", "localhost block")),
        ("Command Blacklist", ("command is not allowed", "blocked strings", "strpos")),
        ("Egress Firewall", ("firewall", "no outbound", "outbound traffic")),
        ("Server-Side Authorization", ("server trusts", "validating it against the session")),
        ("WAF Or Request Filter", ("waf", "filter", "filtered")),
    ),
    "VulnerabilityClass": (
        ("SQL Injection", ("sql injection", "sqli", "union select", "sqlmap")),
        ("Server-Side Request Forgery", ("ssrf", "server-side request forgery")),
        ("Local File Inclusion", ("lfi", "local file include", "file include")),
        ("Path Traversal", ("path traversal", "directory traversal", "../")),
        ("Unrestricted File Upload", ("unrestricted file upload", "upload webshell", "webshell upload")),
        ("Command Injection", ("command injection", "system(", "command=", "cmd=")),
        ("Insecure Deserialization", ("deserialization", "pickle", "unserialize")),
        ("LDAP Injection", ("ldap injection",)),
        ("JWT Secret Weakness", ("jwt", "signing secret", "secret", "hs256")),
        ("Client-Side Authorization", ("client-side", "role", "userrole", "server trusts")),
        ("Credential Exposure", ("credentials", "password", "secret", "api key")),
        ("Coerced Authentication", ("net-ntlmv2", "responder", "scf")),
    ),
    "AttackGoal": (
        ("Read Sensitive Data", ("information disclosure", "dump", "leak", "read")),
        ("Obtain Account Access", ("account takeover", "admin access", "logged in as admin")),
        ("Execute Code", ("rce", "code execution", "command execution")),
        ("Escalate Privileges", ("privilege escalation", "privesc", "root", "administrator")),
        ("Move Laterally", ("lateral", "pivot", "winrm", "smb")),
    ),
    "AttackerCapability": (
        ("Authenticated Session", ("logged in", "cookie set", "authenticated", "admin dashboard")),
        ("Credentialed Login Access", ("creds work", "valid credentials", "logged in as")),
        ("Arbitrary File Read", ("file read", "read files", "/etc/passwd", "cat ")),
        ("Source Review Access", ("source code", "source review", ".git", "repo")),
        ("Internal Service Reachability", ("localhost", "internal", "127.0.0.1", "redis")),
        ("Command Execution", ("rce", "code execution", "command execution", "webshell")),
        ("Shell Access", ("shell as", "reverse shell", "forward shell", "evil-winrm")),
        ("Token Signing Ability", ("jwt", "sign", "secret")),
        ("Privilege Escalation Path", ("privesc", "privilege escalation", "root", "administrator")),
    ),
    "AttackTechnique": (
        ("SQL Injection Auth Bypass", ("or 1=1", "auth bypass", "login bypass")),
        ("SQL Injection Enumeration", ("sqlmap", "boolean-based", "time-based", "error-based", "union")),
        ("SQL Injection File Read", ("--file-read", "file read", "/etc/passwd", "read files")),
        ("SSRF Localhost Probing", ("ssrf", "127.0.0.1", "localhost", "internal service")),
        ("Executable Upload Webshell", ("webshell", "upload", "system($_request", "aspx webshell")),
        ("HTA Upload Execution", ("hta", "vbscript", "wscript.shell")),
        ("Coerced SMB Authentication", ("scf", "iconfile", "net-ntlmv2", "responder")),
        ("Offline Password Cracking", ("hashcat", "john", "crack", "wordlist")),
        ("WinRM Credential Login", ("winrm", "evil-winrm", "crackmapexec winrm")),
        ("Source Code Review", ("source code", "source review", "git-dumper", ".git")),
        ("JWT Token Forgery", ("jwt", "sign", "secret", "token")),
        ("Deserialization Gadget Execution", ("deserialization", "pickle", "gadget")),
        ("Virtual Host Discovery", ("vhost", "server_name", "virtual host")),
        ("Forward Shell Fallback", ("forward shell", "reverse shell fail", "outbound traffic")),
    ),
    "PayloadPattern": (
        ("SQL Comment Auth Bypass Payload", ("or 1=1", "-- -", "#")),
        ("UNION SELECT Payload", ("union select",)),
        ("Time-Based SQL Payload", ("sleep(", "pg_sleep", "time-based")),
        ("IPv6-Mapped Localhost Payload", ("0:0:0:0:0:ffff:127.0.0.1",)),
        ("URL Userinfo Confusion Payload", ("@", "userinfo")),
        ("PHP Alternate Extension Payload", (".phtml", ".php3", ".php4", ".php5")),
        ("Double Extension Upload Payload", ("double extension",)),
        ("PHP Filter Chain Payload", ("php filter", "php://filter")),
        ("SCF Icon Path Payload", (".scf", "iconfile", "\\\\")),
        ("HTA Script Payload", (".hta", "vbscript")),
        ("Wildcard Command Filter Bypass", ("wildcard", "filter", "command is not allowed")),
    ),
    "Artifact": (
        ("Config File", ("config", "sites-enabled", "server_name", "apache2")),
        ("Password Hash", ("hash", "net-ntlmv2", "md5", "sha")),
        ("Credentials", ("credential", "credentials", "password", "api key", "secret")),
        ("Source Code", ("source code", ".git", "git-dumper", "repo")),
        ("Database Dump", ("database", "tables", "dump", "dbs")),
        ("JWT Secret", ("jwt", "secret", "api_key")),
        ("Uploaded Webshell", ("webshell", "uploads/", ".php", ".aspx", ".phtml")),
        ("Virtual Host Name", ("vhost", "server_name", "virtual host")),
    ),
    "ObservableSignal": (
        ("SQL Error Message", ("warning:", "query failed", "sql syntax", "unterminated")),
        ("Boolean Response Delta", ("true", "false", "different response", "boolean")),
        ("Time Delay", ("sleep", "time-based", "five seconds")),
        ("HTTP Redirect Or Cookie", ("302", "redirect", "set-cookie", "cookie set")),
        ("Callback Received", ("connection received", "connect back", "responder", "nc -lnvp")),
        ("Uploaded Path Disclosure", ("uploads/", "location:", "available in")),
        ("Command Output", ("uid=", "whoami", "id", "pwn3d")),
        ("Cracked Hash", ("cracked", "hashcat", "john")),
    ),
}


def _slug(value: str, *, fallback: str = "item") -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or fallback


def _clean_heading(value: str) -> str:
    return value.strip().strip("#").strip()


def _source_id(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        stable_path = resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        stable_path = resolved.as_posix()
    suffix = hashlib.sha1(stable_path.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(path.stem)}-{suffix}"


def _iter_source_files(source_paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for source in source_paths:
        path = Path(source)
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file()
                and not child.name.startswith(".")
                and child.suffix.lower() in {".md", ".markdown", ".txt"}
            )
        elif path.is_file():
            files.append(path)
    return sorted(files)


def parse_markdown_text(
    text: str,
    source_path: str | Path,
    *,
    document_title: str | None = None,
) -> list[SourceFragment]:
    path = Path(source_path)
    lines = text.splitlines()
    source_id = _source_id(path)
    title = document_title or path.stem.replace("-", " ").replace("_", " ").title()
    heading_stack: list[tuple[int, str]] = []
    fragments: list[SourceFragment] = []
    pending: list[str] = []
    block_start = 1
    block_type = "text"
    in_code = False
    fence_marker = ""

    def current_heading_path() -> tuple[str, ...]:
        return tuple(title for _, title in heading_stack)

    def flush(end_line: int) -> None:
        nonlocal pending, block_start, block_type
        raw = "\n".join(pending).strip()
        pending = []
        if not raw:
            return
        ordinal = len(fragments) + 1
        locator = f"{source_id}#f{ordinal:03d}"
        fragment_id = locator
        fragments.append(
            SourceFragment(
                fragment_id=fragment_id,
                source_id=source_id,
                source_path=path.as_posix(),
                document_title=title,
                heading_path=current_heading_path(),
                locator=locator,
                text=raw,
                line_start=block_start,
                line_end=max(block_start, end_line),
                block_type=block_type,
            )
        )

    for lineno, line in enumerate(lines, start=1):
        heading_match = _HEADING_RE.match(line)
        if heading_match and not in_code:
            flush(lineno - 1)
            level = len(heading_match.group(1))
            heading_title = _clean_heading(heading_match.group(2))
            if level == 1 and len(fragments) == 0:
                title = heading_title
            heading_stack = [(lvl, value) for lvl, value in heading_stack if lvl < level]
            heading_stack.append((level, heading_title))
            continue

        fence_match = _CODE_FENCE_RE.match(line)
        if fence_match:
            if not pending:
                block_start = lineno
                block_type = "code"
            pending.append(line)
            marker = fence_match.group(1)
            if in_code and marker == fence_marker:
                in_code = False
                fence_marker = ""
                flush(lineno)
            else:
                in_code = True
                fence_marker = marker
            continue

        if in_code:
            pending.append(line)
            continue

        if not line.strip():
            flush(lineno - 1)
            continue

        if not pending:
            block_start = lineno
            stripped = line.strip()
            if stripped.startswith("|"):
                block_type = "table"
            elif _LIST_RE.match(line):
                block_type = "list"
            else:
                block_type = "text"
        pending.append(line)

    flush(len(lines))
    return fragments


def parse_markdown_source(source_path: str | Path) -> list[SourceFragment]:
    path = Path(source_path)
    return parse_markdown_text(path.read_text(encoding="utf-8"), path)


def classify_fragment(fragment: SourceFragment, facets: Sequence[FacetSpec] = DEFAULT_FACETS) -> list[str]:
    haystack = fragment.text.lower()
    matched: list[str] = []
    for facet in facets:
        if facet.key == "source-context":
            continue
        if fragment.block_type == "code" and facet.key == "code-and-payload-examples":
            matched.append(facet.key)
            continue
        if any(_keyword_matches(haystack, keyword) for keyword in facet.keywords):
            matched.append(facet.key)
    if not matched:
        matched.append("source-context")
    return matched


def _keyword_matches(haystack: str, keyword: str) -> bool:
    normalized = keyword.strip().lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9]+", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack) is not None
    return normalized in haystack


def is_relation_fragment(fragment: SourceFragment) -> bool:
    normalized = f" {re.sub(r'\\s+', ' ', fragment.text.lower())} "
    return any(f" {keyword} " in normalized for keyword in RELATION_KEYWORDS)


def build_preprocessed_documents(source_paths: Iterable[str | Path]) -> PreprocessResult:
    fragments: list[SourceFragment] = []
    fragment_facets: dict[str, list[str]] = {}
    for path in _iter_source_files(source_paths):
        for fragment in parse_markdown_source(path):
            fragments.append(fragment)
            fragment_facets[fragment.fragment_id] = classify_fragment(fragment)
    return PreprocessResult(fragments=fragments, fragment_facets=fragment_facets)


def _render_fragment(fragment: SourceFragment, facets: Sequence[str] | None = None) -> list[str]:
    lines = [
        f"## {fragment.locator}",
        "",
        f"- Source ID: {fragment.source_id}",
        f"- Source path: {fragment.source_path}",
        f"- Document title: {fragment.document_title}",
        f"- Heading path: {_format_heading_path(fragment.heading_path)}",
        f"- Source lines: {fragment.line_start}-{fragment.line_end}",
        f"- Block type: {fragment.block_type}",
    ]
    if facets:
        lines.append(f"- Matched facets: {', '.join(facets)}")
    lines.extend(["", fragment.text, ""])
    return lines


def _format_heading_path(heading_path: Sequence[str]) -> str:
    if not heading_path:
        return "(document root)"
    return " > ".join(heading_path)


def _detect_wstg_id(path: Path, fragments: Sequence[SourceFragment]) -> str:
    for value in (path.as_posix(), path.stem):
        match = _WSTG_ID_RE.search(value.upper())
        if match:
            return match.group(0)
    for fragment in fragments:
        match = _WSTG_ID_RE.search(fragment.text.upper())
        if match:
            return match.group(0)
    inferred = _infer_wstg_id_from_path(path)
    if inferred:
        return inferred
    return f"WSTG-UNKN-{hashlib.sha1(path.as_posix().encode('utf-8')).hexdigest()[:2].upper()}"


def _infer_wstg_id_from_path(path: Path) -> str | None:
    category_code = next(
        (
            _WSTG_CATEGORY_CODES[part]
            for part in reversed(path.parts)
            if part in _WSTG_CATEGORY_CODES
        ),
        None,
    )
    number_match = _WSTG_PATH_NUMBER_RE.match(path.name)
    if category_code is None or number_match is None:
        return None

    suffix = number_match.group("major")
    minor = number_match.group("minor")
    if minor:
        suffix = f"{suffix}-{minor}"
    return f"WSTG-{category_code}-{suffix}"


def _detect_wstg_title(path: Path, fragments: Sequence[SourceFragment]) -> str:
    ignored_titles = {"wstg - latest", "id"}
    for fragment in fragments:
        for heading in fragment.heading_path:
            heading_text = heading.strip()
            if heading_text and heading_text.lower() not in ignored_titles:
                return heading_text
    return path.stem.replace("-", " ").replace("_", " ").title()


def _wstg_slug(wstg_id: str) -> str:
    return _slug(wstg_id.lower(), fallback="wstg-scenario")


def _wstg_category_code(wstg_id: str) -> str:
    match = re.match(r"^WSTG-([A-Z]{4})-\d{2}", wstg_id.upper())
    return match.group(1) if match else "UNKN"


def _wstg_category_name(wstg_id: str) -> str:
    category_code = _wstg_category_code(wstg_id)
    return _WSTG_CATEGORY_NAMES.get(category_code, "Unknown WSTG Category")


def _wstg_title_aliases(title: str) -> list[str]:
    aliases = [title.strip()]
    simplified = re.sub(
        r"^(?:test(?:ing)?(?:\s+(?:for|of|the))?\s+)",
        "",
        title,
        flags=re.I,
    ).strip()
    if simplified and simplified.lower() != title.lower():
        aliases.append(simplified)
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _wstg_vulnerability_class_aliases(wstg_id: str, title: str) -> list[str]:
    aliases = list(_WSTG_CANONICAL_VULNERABILITY_CLASS_ALIASES.get(wstg_id, ()))
    if not aliases:
        return []
    for alias in _wstg_title_aliases(title):
        if re.search(r"\b(test|testing)\b", alias, flags=re.I):
            continue
        aliases.append(alias)
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _wstg_anchor_aliases(wstg_id: str, title: str) -> list[str]:
    category_code = _wstg_category_code(wstg_id)
    aliases = [
        wstg_id,
        *(_wstg_title_aliases(title)),
        *(_wstg_vulnerability_class_aliases(wstg_id, title)),
        _wstg_category_name(wstg_id),
        category_code,
    ]
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _wstg_ontology_query_anchors(wstg_id: str) -> dict[str, list[str]]:
    anchors = _WSTG_ONTOLOGY_QUERY_ANCHORS.get(wstg_id.upper(), {})
    return {
        entity_type: list(dict.fromkeys(value for value in values if value))
        for entity_type, values in anchors.items()
        if values
    }


def _flatten_wstg_ontology_query_anchors(wstg_id: str) -> list[str]:
    flattened: list[str] = []
    for values in _wstg_ontology_query_anchors(wstg_id).values():
        flattened.extend(values)
    return list(dict.fromkeys(flattened))


def _render_wstg_ontology_query_anchor_block(wstg_id: str) -> list[str]:
    anchors = _wstg_ontology_query_anchors(wstg_id)
    if not anchors:
        return []
    lines = [
        "## Ontology Query Anchors",
        "",
        (
            "Purpose: Phase 2 ontology anchors."
        ),
        "",
    ]
    for entity_type, values in anchors.items():
        lines.append(f"- {entity_type}: {', '.join(values)}")
    lines.append(
        f"- Retrieval link: matching profile evidence should retrieve WSTG scenario {wstg_id}."
    )
    lines.append("")
    return lines


def _render_wstg_anchor_block(
    *,
    wstg_id: str,
    title: str,
    source_file: Path,
) -> list[str]:
    category_code = _wstg_category_code(wstg_id)
    category_name = _wstg_category_name(wstg_id)
    aliases = _wstg_anchor_aliases(wstg_id, title)
    vulnerability_aliases = _wstg_vulnerability_class_aliases(wstg_id, title)
    lines = [
        "## WSTG Scenario Anchor",
        "",
        f"- WSTG ID: {wstg_id}",
        f"- WSTG title: {title}",
        f"- WSTG category: {category_name} ({category_code})",
        f"- Source file: {source_file.as_posix()}",
        f"- Canonical aliases: {', '.join(aliases)}",
    ]
    if vulnerability_aliases:
        lines.extend(
            [
                (
                    "- Canonical VulnerabilityClass entities: "
                    f"{', '.join(vulnerability_aliases)}"
                ),
                (
                    "- Ontology type contract: Canonical VulnerabilityClass "
                    "entities should be extracted as type VulnerabilityClass. "
                    "Testing steps should be AttackTechnique; payload examples "
                    "should be PayloadPattern; target conditions should be "
                    "PreconditionEnvironment; mitigations should be DefensiveControl."
                ),
            ]
        )
    lines.extend(
        [
            (
                f"- Multi-hop retrieval target: features, technologies, vulnerability "
                f"families, input vectors, payload patterns, observable signals, "
                f"preconditions, and methodology steps in this document map back to "
                f"{wstg_id}."
            ),
            "",
        ]
    )
    lines.extend(_render_wstg_ontology_query_anchor_block(wstg_id))
    return lines


def _render_wstg_relation_anchor_block(
    *,
    wstg_id: str,
    title: str,
) -> list[str]:
    category_code = _wstg_category_code(wstg_id)
    category_name = _wstg_category_name(wstg_id)
    lines = [
        "## Canonical Relation Anchors",
        "",
        (
            "Purpose: provide stable graph targets so multi-hop retrieval can "
            "resolve abstract web features to canonical WSTG test cases."
        ),
        "",
        f"- WSTG scenario {wstg_id} has title {title}.",
        f"- WSTG scenario {wstg_id} belongs to category {category_name} ({category_code}).",
        f"- WSTG category {category_name} contains WSTG scenario {wstg_id}.",
        f"- Methodology for {title} maps to WSTG scenario {wstg_id}.",
        f"- WSTG scenario {wstg_id} contains test objectives, attack methods, prerequisites, defenses, detections, payload examples, and observable signals.",
    ]
    for vulnerability in _wstg_vulnerability_class_aliases(wstg_id, title):
        lines.append(
            f"- {vulnerability} is a VulnerabilityClass for WSTG scenario {wstg_id}."
        )
        lines.append(
            f"- WSTG scenario {wstg_id} tests vulnerability class {vulnerability}."
        )
    for alias in _wstg_title_aliases(title):
        lines.append(f"- Concept {alias} maps to WSTG scenario {wstg_id}.")
    for entity_type, values in _wstg_ontology_query_anchors(wstg_id).items():
        lines.append(
            f"- {entity_type} anchors {', '.join(values)} map to WSTG scenario {wstg_id}."
        )
    lines.append("")
    return lines


def _unique_wstg_slug(wstg_id: str, source_file: Path, used_slugs: set[str]) -> str:
    base_slug = _wstg_slug(wstg_id)
    if base_slug not in used_slugs:
        used_slugs.add(base_slug)
        return base_slug

    source_slug = _slug(source_file.stem, fallback="source")
    candidate = f"{base_slug}-{source_slug}"
    if candidate in used_slugs:
        suffix = hashlib.sha1(source_file.as_posix().encode("utf-8")).hexdigest()[:8]
        candidate = f"{candidate}-{suffix}"
    used_slugs.add(candidate)
    return candidate


def _wstg_heading_text(fragment: SourceFragment) -> str:
    return " > ".join(fragment.heading_path).lower()


def _wstg_leaf_heading_text(fragment: SourceFragment) -> str:
    if not fragment.heading_path:
        return ""
    return fragment.heading_path[-1].lower()


def _wstg_heading_contains(fragment: SourceFragment, markers: Sequence[str]) -> bool:
    heading_path = _wstg_heading_text(fragment)
    return any(marker in heading_path for marker in markers)


def _is_wstg_external_reference_fragment(fragment: SourceFragment) -> bool:
    return _wstg_heading_contains(fragment, _WSTG_EXTERNAL_REFERENCE_HEADINGS)


def _is_wstg_tool_specific_fragment(fragment: SourceFragment) -> bool:
    return _wstg_heading_contains(fragment, _WSTG_TOOL_SPECIFIC_HEADINGS)


def _is_wstg_merged_placeholder_fragment(fragment: SourceFragment) -> bool:
    text = fragment.text.strip().lower()
    return (
        text.startswith("[merged]:")
        or text.startswith("this content has been merged into:")
        or text in {"this content has been removed", "this content has been removed."}
    )


def _looks_like_payload_or_code(fragment: SourceFragment) -> bool:
    text = fragment.text
    lowered = text.lower()
    return (
        fragment.block_type == "code"
        or bool(_INLINE_CODE_RE.search(text))
        or bool(_URL_RE.search(text))
        or "union select" in lowered
        or "select " in lowered and " from " in lowered
        or "sleep(" in lowered
        or "benchmark(" in lowered
        or "--" in text
        or " or " in lowered and "=" in text
    )


def classify_wstg_fragment(fragment: SourceFragment) -> list[str]:
    """Classify one WSTG source fragment into stable methodology facets."""
    heading = _wstg_leaf_heading_text(fragment)
    heading_path = _wstg_heading_text(fragment)
    text = fragment.text.lower()
    facets: list[str] = []

    if _WSTG_ID_RE.search(fragment.text.upper()):
        facets.append("overview")
    if "summary" in heading:
        facets.append("overview")
    if "test objectives" in heading:
        facets.append("test-objectives")
    if (
        "how to test" in heading
        or "black-box" in heading
        or "white-box" in heading
        or "detection techniques" in heading
        or "testing for" in heading
        or "attack" in heading
        or "google dorking" in heading
        or "look back" in heading
    ):
        facets.append("attack-methods")
    if (
        "remediation" in heading
        or "mitigation" in heading
        or "countermeasure" in heading
        or "validation" in text
        or "sanitize" in text
        or "parameterized" in text
        or "prepared statement" in text
        or "detect" in text
    ):
        facets.append("defenses-and-detections")
    if (
        "reference" in heading_path
        or "tools" in heading
        or "suggested reading" in heading
        or "external references" in heading
        or _is_wstg_external_reference_fragment(fragment)
    ):
        facets.append("references")
    if _looks_like_payload_or_code(fragment):
        facets.append("code-and-payload-examples")
    if (
        "requires" in text
        or "condition" in text
        or "privilege" in text
        or "input field" in text
        or "parameter" in text
        or "entry point" in text
        or "side channel" in text
        or "when " in text
        or "if " in text
    ):
        facets.append("prerequisites-and-environment")

    for generic_facet in classify_fragment(fragment):
        if generic_facet != "source-context":
            facets.append(generic_facet)

    deduped = list(dict.fromkeys(facets))
    return deduped or ["source-context"]


def primary_wstg_facet(fragment: SourceFragment, facets: Sequence[str]) -> str:
    heading = _wstg_leaf_heading_text(fragment)
    heading_path = _wstg_heading_text(fragment)
    if (
        "references" in facets
        or "reference" in heading_path
        or "tools" in heading
        or _is_wstg_external_reference_fragment(fragment)
    ):
        return "references"
    if "test-objectives" in facets:
        return "test-objectives"
    if "overview" in facets:
        return "overview"
    if "remediation" in heading or "mitigation" in heading or "defenses-and-detections" in facets:
        if "summary" not in heading:
            return "defenses-and-detections"
    if "code-and-payload-examples" in facets:
        return "code-and-payload-examples"
    if "attack-methods" in facets:
        return "attack-methods"
    if "prerequisites-and-environment" in facets:
        return "prerequisites-and-environment"
    if "vulnerability-classes" in facets or "overview" in facets:
        return "overview"
    return "source-context"


def _is_wstg_relation_candidate(fragment: SourceFragment, facets: Sequence[str]) -> bool:
    heading = _wstg_leaf_heading_text(fragment)
    text = fragment.text.lower()
    if fragment.block_type == "code":
        return False
    return (
        is_relation_fragment(fragment)
        or heading in {"summary", "test objectives", "how to test", "remediation"}
        or any(
            marker in text
            for marker in (
                "allows",
                "can read",
                "can modify",
                "can execute",
                "without proper",
                "without adequate",
                "interact with",
                "input validation",
            )
        )
    )


def _render_wstg_fragment(
    fragment: SourceFragment,
    *,
    wstg_id: str,
    title: str,
    facets: Sequence[str] | None = None,
) -> list[str]:
    lines = [
        f"### {fragment.locator}",
        "",
        (
            f"Source: {wstg_id} | {title} | "
            f"{_format_heading_path(fragment.heading_path)} | "
            f"lines {fragment.line_start}-{fragment.line_end} | "
            f"{fragment.block_type}"
        ),
    ]
    if facets:
        lines.append(f"Facets: {', '.join(facets)}")
    lines.extend(["", fragment.text, ""])
    return lines


def _clean_wstg_ingestion_text(text: str) -> str:
    text = re.sub(r"(?m)^\s*>?\s*!\[[^\]]*\]\([^)]+\)\s*\\?\s*$", "", text)
    text = re.sub(r"(?im)^\s*>?\s*\*?Figure\s+[\d.:-]+.*?\*?\s*$", "", text)
    text = re.sub(
        r"(?im)^\s*This vulnerability maps to (?:\[)?OWASP API Security Top 10 "
        r"API\d+:\d{4}\s+([^\]\n.]+)(?:\]\([^)]+\))?\.?\s*$",
        r"This scenario concerns \1.",
        text,
    )
    text = re.sub(
        r"Another method to bypass filters is the HTTP Parameter Pollution, this "
        r"technique was first presented by Stefano di Paola and Luca Carettoni "
        r"in 2009 at the OWASP Poland conference\. See the Testing for HTTP "
        r"Parameter pollution for more information\. This evasion technique "
        r"consists of splitting an attack vector between multiple request input "
        r"fields that have the same name\.",
        (
            "HTTP Parameter Pollution can bypass filters by splitting an attack "
            "vector between multiple request input fields that have the same name."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r",\s*taken from an article on Medium",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Cross-site scripting occurs when an attacker injects executable code "
        r"that is subsequently run by the browser\. Learn about tests for XSS in "
        r"the Input Validation chapter\. You may test for reflected XSS using a "
        r"payload from Testing for Reflected Cross Site Scripting\.",
        (
            "GraphQL cross-site scripting testing sends reflected XSS payloads "
            "through GraphQL-controlled response fields and observes whether the "
            "browser executes injected code."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"In computer security,\s+authentication is the process of attempting to "
        r"verify the digital identity of the sender of a communication\. A common "
        r"example of such a process is the log on process\. Testing the "
        r"authentication schema means understanding how the authentication process "
        r"works and using that information to circumvent the authentication "
        r"mechanism\.",
        (
            "Authentication schema testing analyzes how the authentication process "
            "works and uses that information to test whether the authentication "
            "mechanism can be bypassed."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(
        r"Another method to bypass filters is the HTTP Parameter Pollution, this "
        r"technique was first presented by Stefano di Paola and Luca Carettoni "
        r"in 2009 at the OWASP Poland conference\. See the Testing for HTTP "
        r"Parameter pollution for more information\. This evasion technique "
        r"consists of splitting an attack vector between multiple (?:request "
        r"input fields|parameters) that have the same name\.",
        (
            "HTTP Parameter Pollution can bypass filters by splitting an attack "
            "vector between multiple request input fields that have the same name."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r",\s*taken from an article on Medium",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Cross-site scripting occurs when an attacker injects executable code "
        r"that is subsequently run by the browser\. Learn about tests for XSS in "
        r"the Input Validation chapter\. You may test for reflected XSS using a "
        r"payload from Testing for Reflected Cross Site Scripting\.",
        (
            "GraphQL cross-site scripting testing sends reflected XSS payloads "
            "through GraphQL-controlled response fields and observes whether the "
            "browser executes injected code."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r'Also,\s+forged requests may allow subversion of programmatic or '
        r'business logic flow by invoking "hidden" features or functionality '
        r'such as debugging initially used by developers and testers sometimes '
        r'referred to as an "Easter egg"\)\. "An Easter egg is an intentional '
        r'inside joke, hidden message, or feature in a work such as a computer '
        r'program, movie, book, or crossword\. According to game designer Warren '
        r'Robinett, the term was coined at Atari by personnel who were alerted '
        r'to the presence of a secret message which had been hidden by Robinett '
        r'in his already widely distributed game, Adventure\. The name has been '
        r'said to evoke the idea of a traditional Easter egg hunt\."',
        (
            "Forged requests may subvert programmatic or business logic flow by "
            "invoking hidden or debugging functionality that was intended only "
            "for development or testing."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Definition of a workflow on Wikipedia:\s*\n+\s*> A workflow consists "
        r"of a sequence of connected steps.*?Workflow may be seen as any "
        r"abstraction of real work\.",
        (
            "A workflow is a sequence of connected application steps that must "
            "be completed in the intended order."
        ),
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"(?im)^\s*Definition of a workflow on Wikipedia:\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*>?\s*A workflow consists of a sequence of connected steps "
        r"where each step follows without delay or gap and ends just before the "
        r"subsequent step may begin\. It is a depiction of a sequence of "
        r"operations, declared as work of a person or group, an organization of "
        r"staff, or one or more simple or complex mechanisms\. Workflow may be "
        r"seen as any abstraction of real work\.\s*$",
        (
            "A workflow is a sequence of connected application steps that must "
            "be completed in the intended order."
        ),
        text,
    )
    text = re.sub(
        r"The Payment Card Industry Data Security Standard \(PCI DSS\) is a "
        r"standard that organizations are required to follow in order process "
        r"debit and card payments \(although it's important to note that it is "
        r"not a law\)\. A full discussion of this standard is outside of the "
        r"scope of this guide \(and of most penetration tests\) - but it's "
        r"useful for testers to understand a few key points\.",
        (
            "PCI DSS provides cardholder-data security requirements for payment "
            "workflows; testing should stay focused on in-scope payment logic "
            "and data-handling controls."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(r"(?im)^\s*(?:[-*]\s*)?To secure .*?CheatSheet\.?\s*$", "", text)
    text = re.sub(
        r"(?im)^\s*For generic input validation security,\s+refer to .*?CheatSheet\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*(?:More file inclusion payloads can be found at|You can find "
        r"encoding techniques and ready to use directory traversal payloads at)\s+"
        r"PayloadsAllTheThings.*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*For a comprehensive list of potential test strings see the "
        r"XSS Filter Evasion Cheat Sheet\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*The XSS Filter Evasion Cheat Sheet documents common filter "
        r"evasion tests\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*For a more complete reference,\s+see the Mozilla JavaScript "
        r"guide\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^.*Wikipedia has a complete reference\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"\s*-\s*see\s+Wikipedia\s+for\s+a\s+more\s+complete\s+list",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"There are other RFCs and internet drafts which suggest standardized "
        r"uses of files within the `\.well-known/` directory\. Lists of these "
        r"can be found here on WikiPedia or here via IANA\.",
        (
            "Other RFCs and internet drafts define additional standardized "
            "uses of files within the `.well-known/` directory."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"For the purpose of the OWASP Testing Guide,\s+only the security threats "
        r"related to web applications will be considered and not threats to web "
        r"servers.*?Further reading suggestions will be provided in the references "
        r"section for interested readers\.",
        (
            "This scenario focuses on web application path traversal and file "
            "include behavior, not general web server threat coverage."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(?im)^\s*You can refer to other scenarios within the OWASP testing guide "
        r"to get some ideas\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*For more on remediating GraphQL weaknesses,\s+refer to the "
        r"GraphQL Cheat Sheet\.?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"See the XSS Filter Evasion Cheat Sheet for a more detailed list of "
        r"filter evasion techniques\.\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"SSRF is known to be one of the hardest attacks to defeat without the "
        r"use of allow lists that require specific IPs and URLs to be allowed\. "
        r"For more on SSRF prevention, read the Server Side Request Forgery "
        r"Prevention Cheatsheet\.",
        (
            "SSRF can be difficult to mitigate without strict allow lists that "
            "constrain allowed IPs and URLs."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"The XPath attack pattern was first published by Amit Klein and is very "
        r"similar to the usual SQL Injection\.",
        (
            "XPath Injection is similar to SQL Injection because crafted input "
            "can alter query behavior."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Blind XPath Injection is explained in more detail by Amit Klein in the "
        r"referenced paper\.",
        (
            "Blind XPath Injection can reconstruct data structure through "
            "inference when errors are not useful."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(?im)^\s*Most of the situations and techniques presented here can be "
        r"performed in an automated way using some tools\..*SQLMap\s*$",
        "",
        text,
    )
    text = re.sub(
        r"The blind SQL injection attack needs a high volume of queries\. "
        r"The tester may need an automatic tool to exploit the vulnerability\.",
        (
            "Blind SQL injection can require a high volume of requests, so "
            "automation may be needed to keep probes consistent."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bautomatic tools\b",
        "automated testing workflows",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"For example,\s+if you use `?SQLMap`?, this situation confuses the tool "
        r"and the output gets messed up\. Because the delays will not be as expected\.",
        (
            "Multiple-query timing can confuse automated exploitation because "
            "observable delays may not match the expected query path."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Extract the original query using `?SQLMap`? and blind injection\.",
        "Infer the original query shape with blind-injection observations.",
        text,
        flags=re.I,
    )
    text = re.sub(r"(?im)^\s*sqlmap\b.*$", "", text)
    text = re.sub(
        r"The very first test usually consists of adding a single quote `?'`? "
        r"or a semicolon `?;`? to the field or parameter under test\. The "
        r"first is used in SQL as a string terminator and, if not filtered by "
        r"the application, would lead to an incorrect query\. The second is "
        r"used to end a SQL statement and, if it is not filtered, it is also "
        r"likely to generate an error\.",
        (
            "The first probe usually sends reusable payload markers such as "
            "`<single_quote_string_terminator>` or "
            "`<semicolon_statement_terminator>` to the request input under "
            "test. These payload patterns can expose missing filtering when "
            "they create an incorrect query or SQL error."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bAn SQL injection attack consists of\b",
        "SQL Injection as a vulnerability class consists of",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bA successful SQL injection attack can\b",
        "Successful exploitation of SQL Injection can",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bA successful SQL Injection attack requires\b",
        "Successful SQL Injection exploitation requires",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bSQL Injection attacks can be divided into\b",
        "SQL Injection weakness variants can be divided into",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bSQL injection attacks are a type of injection attack\b",
        "SQL Injection is a vulnerability class in the injection weakness family",
        text,
        flags=re.I,
    )
    text = re.sub(r"`https?://\s*example\.com/[^`]+`", "`<scheme>://<host>/<path>`", text, flags=re.I)
    text = re.sub(
        r"Reconnaissance is an important step in any testing activity\. "
        r"This includes API pentesting\. Reconnaissance significantly enhances "
        r"the effectiveness of the testing process by gathering information "
        r"about the API and developing an understanding of the target\. This "
        r"phase not only increases the likelihood of discovering critical "
        r"security issues but also ensures a comprehensive evaluation of the "
        r"API security behavior\.",
        (
            "API reconnaissance gathers information about target API "
            "functionality to identify security-relevant endpoints, parameters, "
            "documentation, exposed client-side data, and deprecated versions."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"This guide has a section on Information Gathering.*?elsewhere in the guide\.",
        "",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"The Information Gathering section refers to robots\.txt.*?related testing scenario\.",
        "",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"replacing `https://` with `http://`",
        "switching a request from a secure scheme to an insecure scheme",
        text,
        flags=re.I,
    )
    text = _URL_RE.sub("<scheme>://<host>/<path>", text)
    text = re.sub(r"\bSource:\s+", "Provider: ", text)
    text = re.sub(
        r"A helpful tool known? as TomNomNom's [^.]+ fetches all the URLs "
        r"that [^.]+ knows about for a domain\.",
        "Historical URL archives can reveal known URLs for a domain.",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"`robots\.txt` is a text file that site owners create to instruct "
        r"web crawlers \(such as search engine bots\) on how to crawl and "
        r"index their site\. It is part of the Robots Exclusion Protocol "
        r"\(REP\), which regulates how bots interact with sites\.",
        (
            "A `robots.txt` file can be obtained as an artifact and reviewed "
            "for disclosed path structure or API endpoints."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Using passive reconnaissance techniques such as search engine dorking "
        r"with directives such as `site` and `inurl` allows us to tailor a "
        r"search for common API keywords that the search engine indexer may "
        r"have found\.",
        (
            "Search engine dorking with `site` and `inurl` directives can "
            "discover indexed API paths, endpoints, and exposed secrets."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"To discover older versions we can use the `historical URL archive` "
        r"to help find older endpoints\. Historical URL archives can reveal "
        r"known URLs for a domain\.",
        (
            "Historical URL lookup can discover older API endpoints and "
            "deprecated versions that remain reachable."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"Regular expression is more straightforward by searching JS or HTML "
        r"content for known patterns\..*?allowing tools and compilers to "
        r"understand and modify the code easily\.",
        (
            "Review JavaScript and HTML content for API paths, secrets, "
            "structured data, JSON, XML, and client-side references to target "
            "functionality."
        ),
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"When auditing REST APIs, use a request capture workflow to collect "
        r"full HTTP requests\. REST services utilize more than just URL "
        r"parameters, so capturing the complete request body and headers is "
        r"critical\.",
        (
            "Capture full HTTP requests as artifacts when auditing REST APIs; "
            "request bodies, URL parameters, and HTTP headers can influence "
            "application behavior."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(r"Here are a few API specific examples:\s*", "", text, flags=re.I)
    text = re.sub(
        r"Wordlists are helpful here for a comprehensive list of common words "
        r"used in APIs\.",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bGoogle Dorking\b", "search engine dorking", text, flags=re.I)
    text = re.sub(r"\bGoogle indexer\b", "search engine indexer", text, flags=re.I)
    text = re.sub(r"\bWayback Machine\b", "historical URL archive", text, flags=re.I)
    text = re.sub(r"\bWayback machine\b", "historical URL archive", text, flags=re.I)
    text = re.sub(r"\bWayBackUrls\b", "historical URL archive collection", text, flags=re.I)
    text = re.sub(
        r"The Information Gathering section refers to robots\.txt.*?related testing scenario\.",
        "",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"Using passive reconnaissance techniques such as search engine dorking "
        r"with directives such as `site` and `inurl`.*?found\.",
        (
            "Search engine dorking with `site` and `inurl` directives can "
            "discover indexed API paths, endpoints, and exposed secrets."
        ),
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"To discover older versions we can use the historical URL archive "
        r"to help find older endpoints\.",
        (
            "Historical URL lookup can discover older API endpoints and "
            "deprecated versions that remain reachable."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"To discover older versions we can use the `historical URL archive` "
        r"to help find older endpoints\. Historical URL archives can reveal "
        r"known URLs for a domain\.",
        (
            "Historical URL lookup can discover older API endpoints and "
            "deprecated versions that remain reachable."
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"GitHub, GitLab, or other public facing Git based repositories",
        "public-facing Git-based repositories",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bGitHub accounts\b", "public repository accounts", text, flags=re.I)
    text = re.sub(r"\bintercept(?:ing|ion) proxy\b", "request capture workflow", text, flags=re.I)
    text = re.sub(
        r"When auditing REST APIs,\s+use an? request capture workflow to collect "
        r"full HTTP requests\.",
        "Capture full HTTP requests as artifacts when auditing REST APIs.",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bZAP\b|\bBurp Suite\b|\bBurpSuite\b", "request capture tooling", text)
    text = re.sub(r"\bPostman\b", "API documentation tooling", text)
    text = re.sub(r"\bSQLMap\b", "automated SQL injection testing", text, flags=re.I)
    text = re.sub(r"\bNetcat tool\b", "attacker-controlled listener", text, flags=re.I)
    text = re.sub(r"\bNetcat\b", "attacker-controlled listener", text, flags=re.I)
    text = re.sub(r"\bweb server \(e\.g\. Apache\)", "attacker-controlled HTTP listener", text, flags=re.I)
    text = re.sub(
        r"The tester can set up an? attacker-controlled HTTP listener or use "
        r"the attacker-controlled listener:",
        "The tester can use an attacker-controlled HTTP listener:",
        text,
        flags=re.I,
    )
    text = re.sub(r"\btesterserver(?:\.com)?\b", "<attacker_host>", text, flags=re.I)
    text = re.sub(r"\bASCII\s*\(", "CHAR_CODE(", text, flags=re.I)
    text = re.sub(r"\bASCII\b", "character ordinal", text, flags=re.I)
    text = re.sub(r"\bpublic APIs\b", "externally exposed APIs", text, flags=re.I)
    text = re.sub(r"\bprivate APIs\b", "restricted-consumer APIs", text, flags=re.I)
    text = re.sub(r"\bpentesting engagement\b", "testing activity", text, flags=re.I)
    text = re.sub(r"\bpentest engagement\b", "testing activity", text, flags=re.I)
    text = re.sub(r"\bAPI pentesting\b", "API-focused testing", text, flags=re.I)
    text = re.sub(r"\bAPIs'? security posture\b", "API security behavior", text, flags=re.I)
    text = re.sub(r"\bAPI security behavior\b", "target security behavior", text, flags=re.I)
    text = re.sub(r"\bsearch engine indexer\b", "indexed pages", text, flags=re.I)
    text = re.sub(r"\battack surface\b", "reachable functionality", text, flags=re.I)
    text = re.sub(r"\bAPI endpoints\b", "target API route locations", text, flags=re.I)
    text = re.sub(r"\bAPI endpoint\b", "target API route", text, flags=re.I)
    text = re.sub(r"\bendpoints\b", "route locations", text, flags=re.I)
    text = re.sub(r"\bendpoint\b", "route location", text, flags=re.I)
    text = re.sub(r"\bAPI parameters\b", "target API request input fields", text, flags=re.I)
    text = re.sub(r"\bURL parameters\b", "URL request input fields", text, flags=re.I)
    text = re.sub(r"\bparameters for each route location\b", "request input fields for each route location", text, flags=re.I)
    text = re.sub(r"\bparameters\b", "request input fields", text, flags=re.I)
    text = re.sub(r"\bparameter values\b", "request input values", text, flags=re.I)
    text = re.sub(r"\bURL segment\b", "URL path segment", text, flags=re.I)
    text = re.sub(r"\bOther\b", "Additional", text)
    text = re.sub(r"\ban request\b", "a request", text, flags=re.I)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s*Review [^.]+ for additional information\.", "", text, flags=re.I)
    return text.strip()


def _is_wstg_provenance_only_fragment(fragment: SourceFragment) -> bool:
    text = fragment.text.strip()
    if fragment.block_type == "table" and _WSTG_ID_RE.search(text.upper()) and len(text) < 120:
        return True
    normalized_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() not in {"---", "***", "___"}
    ]
    if (
        len(normalized_lines) <= 2
        and normalized_lines[:1] == ["ID"]
        and len(_WSTG_ID_RE.findall(text.upper())) == 1
    ):
        return True
    plain = re.sub(r"[^A-Z0-9-]+", "", text.upper())
    return bool(_WSTG_ID_RE.fullmatch(plain))


def _is_wstg_ingestion_noise_fragment(fragment: SourceFragment) -> bool:
    if _is_wstg_provenance_only_fragment(fragment):
        return True
    if _is_wstg_merged_placeholder_fragment(fragment):
        return True
    if _is_wstg_external_reference_fragment(fragment) or _is_wstg_tool_specific_fragment(fragment):
        return True
    text = fragment.text.lower()
    if any(
        marker in text
        for marker in (
            "directory of c:",
            "directory of c:\\",
            "exec results for",
            "javax.xml.parsers",
            "documentbuilderfactory",
            "saxparserfactory",
            "transformerfactory",
            "xmlinputfactory",
            "xmlreaderfactory",
        )
    ):
        return True
    if fragment.block_type == "list" and any(
        marker in text
        for marker in (
            "public apis repository",
            "apis.guru",
            "rapidapi",
            "publicapis",
            "postman api network",
            "waybackurls",
            "waymore",
            " alien vault ",
            "urlscan",
            "virustotal",
            "seclists",
            "assetnote",
            "cheat sheet",
            "cheatsheet",
            "sqlmap",
            "automatic sql injection tool",
            "automatic tools",
            "dencoder",
        )
    ):
        return True
    if fragment.block_type == "code" and any(
        marker in text
        for marker in (
            "kr scan",
            "kr [scan",
            "gobuster dir",
            "sqlmap",
            "/home/tester/nc",
            " nc ",
            "nc -",
            "nc –",
            "ncat",
            "netcat",
        )
    ):
        return True
    return False


def _render_wstg_ingestion_fragment(
    fragment: SourceFragment,
    *,
    wstg_id: str,
    title: str,
) -> list[str]:
    if _is_wstg_ingestion_noise_fragment(fragment):
        return []
    text = _clean_wstg_ingestion_text(fragment.text)
    if not text:
        return []
    category_name = _wstg_category_name(wstg_id)
    return [
        f"Anchor: WSTG ID {wstg_id}; WSTG title {title}; WSTG category {category_name}.",
        text,
        "",
    ]


def _render_wstg_document(
    *,
    wstg_id: str,
    title: str,
    facet_key: str,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> str:
    facet_title, description = WSTG_FACET_TITLES[facet_key]
    lines = [
        f"# {wstg_id} - {title}: {facet_title}",
        "",
        f"Purpose: {description}",
        "",
        (
            "Source boundary: this document is generated from OWASP WSTG source "
            "fragments. It is ontology-agnostic; LightRAG extracts the active "
            "ontology during indexing."
        ),
        "",
    ]
    if not fragments:
        lines.extend(["No source fragments matched this WSTG facet.", ""])
    for fragment in fragments:
        lines.extend(
            _render_wstg_fragment(
                fragment,
                wstg_id=wstg_id,
                title=title,
                facets=fragment_facets.get(fragment.fragment_id, []),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_wstg_relation_briefs(
    *,
    wstg_id: str,
    title: str,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> str:
    lines = [
        f"# {wstg_id} - {title}: Relation Briefs",
        "",
        (
            "Purpose: preserve source-grounded operational claims connecting "
            "testing methods, target conditions, defensive behavior, weakness "
            "categories, and payload examples."
        ),
        "",
        (
            "Ontology boundary: these briefs do not encode a fixed entity schema. "
            "They are the preferred LightRAG input when the ontology changes."
        ),
        "",
    ]
    relation_fragments = [
        fragment
        for fragment in fragments
        if _is_wstg_relation_candidate(
            fragment,
            fragment_facets.get(fragment.fragment_id, []),
        )
    ]
    if not relation_fragments:
        lines.extend(["No WSTG relation candidates were found.", ""])
    for fragment in relation_fragments:
        lines.extend(
            _render_wstg_fragment(
                fragment,
                wstg_id=wstg_id,
                title=title,
                facets=fragment_facets.get(fragment.fragment_id, []),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _wstg_relation_fragments(
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> list[SourceFragment]:
    return [
        fragment
        for fragment in fragments
        if _is_wstg_relation_candidate(
            fragment,
            fragment_facets.get(fragment.fragment_id, []),
        )
    ]


def _render_wstg_info_10_compact_document(
    *,
    wstg_id: str,
    title: str,
    source_file: Path,
) -> str:
    # WSTG-INFO-10 is broad architecture mapping material. The normal composite
    # renderer duplicates many concepts across facets and relation briefs, which
    # can make entity extraction time out on slower LLM backends.
    lines = [
        "# Methodology Scenario",
        "",
        "## Methodology Scope",
        "",
        "This document contains reusable web application testing methodology.",
        "",
        *_render_wstg_anchor_block(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        ),
        "## Overview",
        "",
        "Purpose: Scenario summary, vulnerability framing, impact, and core testing purpose.",
        "",
        (
            "Map Application Architecture helps the tester understand what is being "
            "tested, which technologies and components are in use, and which "
            "components may be out-of-scope for a security assessment."
        ),
        "",
        "## Test Objectives",
        "",
        "Purpose: Explicit objectives a tester should satisfy for this WSTG scenario.",
        "",
        "- Understand the architecture of the application and the technologies in use.",
        "- Build a clear black-box picture of application, network, security, and third-party components.",
        "- Use the architecture map to choose relevant follow-on WSTG tests and scope boundaries.",
        "",
        "## Target Conditions And Architecture Components",
        "",
        "- Web Server: a simple application may run on a single server and can be identified with web server fingerprinting.",
        "- Platform-as-a-Service: the provider manages the web server and infrastructure; infrastructure testing is usually out-of-scope.",
        "- Serverless: application code runs as individual hosted functions instead of a traditional webroot deployment.",
        "- Microservices: an application API may be composed of discrete services behind one API gateway or domain.",
        "- Static Storage: cloud object storage can host static files through Amazon S3 bucket or Azure Storage Account domains.",
        "- Database: dynamic applications commonly depend on SQL or NoSQL databases visible through ports, errors, or framework clues.",
        "- Authentication: applications may use HTTP Basic auth, local database accounts, Active Directory, LDAP, NTLM, OAuth, OpenID Connect, or SAML.",
        "- Third Party Services and APIs: active content, passive content, external APIs, social buttons, advertising networks, and payment gateways may affect security but are usually third-party scope.",
        "- Reverse Proxy: a frontend proxy can route to backend servers, implement IP filtering, cache content, act as a load balancer, or act as a WAF.",
        "- Load Balancer: multiple backend servers may produce inconsistent times, hostnames, internal addresses, or load-balancer cookies.",
        "- Content Delivery Network: a CDN such as Akamai, Cloudflare or Fastly can cache content, add rate limiting, add bot detection, and host the public-facing IP space.",
        "- Network Firewall: packet filtering or stateful inspection controls exposed services and port scan behavior.",
        "- Network IDS or IPS: network detection and prevention systems may alert or block vulnerability scanning and port scanning.",
        "- Web Application Firewall: a WAF inspects HTTP requests and can block attack strings associated with SQL injection, cross-site scripting, and other signature-based probes.",
        "",
        "## Concrete Test Methods And Observable Signals",
        "",
        "- Identify PaaS from provider-specific domains such as `*.azurewebsites.net`.",
        "- Identify serverless hints from headers such as `X-Amz-Invocation-Type`, `X-Amz-Log-Type`, `X-Amz-Client-Context`, or `Server: Kestrel`.",
        "- Identify static storage from domains such as `BUCKET.s3.amazonaws.com`, `s3.REGION.amazonaws.com/BUCKET`, or `ACCOUNT.blob.core.windows.net`.",
        "- Infer database technology from open database ports, SQL or NoSQL error messages, operating system, web framework, and application language.",
        "- Inspect authentication prompts, forms, headers such as `WWW-Authenticate: Basic` or `WWW-Authenticate: NTLM`, domain-qualified usernames, and SSO flows.",
        "- Use browser developer tools or an intercepting proxy to list third-party resources loaded by the client.",
        "- Detect reverse proxies through frontend/backend server mismatches, duplicate `Server` headers, and multiple applications behind one IP address or domain.",
        "- Detect load balancers with repeated requests that reveal inconsistent system times, backend hostnames, internal IPs, SSRF-returned addresses, or cookies such as `BIGipServer`.",
        "- Detect CDNs with WHOIS lookup for resolved IP addresses, then look for backend origin exposure through emails, DNS data, certificate transparency, company IP range scans, SSRF, or detailed error messages.",
        "- Detect firewall behavior with port scans: mostly closed ports suggest no packet filter, while filtered ports suggest a firewall.",
        "- Detect IPS behavior by running controlled automated scans and observing whether the tester source IP is blocked.",
        "- Detect WAF behavior by adding common attack strings to request input fields, such as `' UNION SELECT 1` or `><script>alert(1)</script>`, and observing block pages, headers, or cookies.",
        "",
        "## Defensive Controls And Scope Notes",
        "",
        "- CDN, WAF, load balancer, reverse proxy, firewall, IDS, and IPS controls can change what the tester can observe from the public edge.",
        "- Direct backend access can bypass CDN or cloud WAF protections when origin access control is not enforced.",
        "- CDN-owned public IPs and third-party services are commonly out-of-scope for infrastructure testing.",
        "- PaaS and serverless deployments often make provider-managed infrastructure out-of-scope for remediation.",
        "- WAF signatures can help against SQL injection and cross-site scripting but are less effective for access control and business logic weaknesses.",
        "",
        *_render_wstg_relation_anchor_block(wstg_id=wstg_id, title=title),
        "## Relation Briefs",
        "",
        "Purpose: preserve source-grounded operational claims connecting testing methods, target conditions, defensive behavior, weakness categories, and payload examples.",
        "",
        "- Architecture mapping identifies web server, application platform, database, authentication, network, and security components.",
        "- Component fingerprinting produces observable artifacts such as headers, cookies, DNS records, IP ownership, ports, errors, and client-loaded resources.",
        "- Reverse proxies, load balancers, CDNs, WAFs, firewalls, IDS, and IPS can affect reachability and test results.",
        "- Backend origin discovery can bypass CDN or cloud WAF controls when origin access is not restricted.",
        "- Request input attack strings can test WAF filtering behavior and reveal specific WAF technology.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_wstg_apit_01_compact_document(
    *,
    wstg_id: str,
    title: str,
    source_file: Path,
) -> str:
    # APIT-01 is a high-fanout reconnaissance scenario. The normal composite
    # renderer repeats route, parameter, tool, and source fragments enough to
    # increase LightRAG worker extraction timeout risk.
    lines = [
        "# Methodology Scenario",
        "",
        "## Methodology Scope",
        "",
        "This document contains reusable web application testing methodology.",
        "",
        *_render_wstg_anchor_block(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        ),
        "## Overview",
        "",
        "Purpose: Scenario summary, vulnerability framing, impact, and core testing purpose.",
        "",
        (
            "API Reconnaissance maps public or restricted-consumer API behavior "
            "to route locations, request input fields, documentation artifacts, "
            "and client-side references. The methodology covers REST API, "
            "GraphQL API, and OpenAPI evidence and looks for documented, "
            "undocumented, and deprecated API functionality."
        ),
        "",
        "## Test Objectives",
        "",
        "Purpose: Explicit objectives a tester should satisfy for this WSTG scenario.",
        "",
        "- Find documented and undocumented target API route locations supported by backend code.",
        "- Find request input fields for each target API route location, including path, query, body, and header inputs.",
        "- Discover API Documentation, OpenAPI Specification artifacts, Endpoint List material, client-side API references, and exposed secrets.",
        "- Identify deprecated API versions or older routes that remain reachable and need follow-on testing.",
        "",
        "## Target Conditions And Artifacts",
        "",
        "- Exposed API Endpoint: a target exposes REST API or GraphQL API functionality through public routes, partner routes, internal-consumer routes, or subdomains.",
        "- API Documentation Available: documentation may be published, leaked, stale, or available under common paths such as `/api-docs`, `/swagger`, `/swagger.json`, `/openapi.json`, or `/.well-known/schema-discovery`.",
        "- Client-Side API Route Reference: browser-delivered HTML or JavaScript can reveal API paths, GraphQL operations, JSON structures, secrets, or route construction logic.",
        "- Deprecated API Version Reachable: old versions may still respond and can contain weaker authorization, validation, or data-handling controls.",
        "- Captured HTTP Request artifacts preserve request bodies, URL request input fields, and headers that influence target behavior.",
        "",
        "## Concrete Test Methods And Observable Signals",
        "",
        "- Perform API Documentation Discovery by checking common documentation paths, public repository clues, client-visible links, and target-owned subdomains.",
        "- Perform API Endpoint Enumeration by browsing authenticated and unauthenticated workflows, capturing HTTP traffic, and extracting route locations from responses and client-side files.",
        "- Analyze captured requests to identify header-controlled behavior, structured JSON or XML inputs, repeating URL path segments, high-variance URL segments, and extensionless final path elements.",
        "- Use search engine dorking with `site` and `inurl` patterns to find indexed API paths, route references, configuration clues, and Exposed API Secret material.",
        "- Use Historical URL Lookup to find Deprecated API Route evidence, old OpenAPI documents, and previously indexed route locations.",
        "- Review JavaScript and HTML for API route strings, GraphQL API references, secrets, structured data, and lazy-loaded functionality.",
        "- Actively fuzz route locations with scoped wordlists only when authorization, rate limits, and engagement constraints allow it.",
        "",
        "## Defensive Controls And Scope Notes",
        "",
        "- API documentation can be incomplete, inaccurate, or older than deployed backend behavior, so observed traffic should validate the document.",
        "- Sample accounts at different privilege levels improve coverage because lazy loading and authorization can hide routes from unauthenticated browsing.",
        "- Deprecated API versions and leaked client-side references are follow-on test targets, not proof of a vulnerability by themselves.",
        "",
        *_render_wstg_relation_anchor_block(wstg_id=wstg_id, title=title),
        "## Relation Briefs",
        "",
        "Purpose: preserve source-grounded operational claims connecting testing methods, target conditions, defensive behavior, weakness categories, and payload examples.",
        "",
        "- API Documentation Discovery can produce API Documentation, OpenAPI Specification, and Endpoint List artifacts for WSTG-APIT-01.",
        "- API Endpoint Enumeration maps REST API and GraphQL API route locations to WSTG-APIT-01 methodology.",
        "- Historical URL Lookup can reveal Deprecated API Route evidence and Deprecated API Version Reachable target conditions.",
        "- Client-Side API Route Reference can reveal Discovered API Route and Exposed API Secret observable signals.",
        "- Captured HTTP Request artifacts connect request input fields, headers, bodies, and route locations to follow-on API testing.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_wstg_apit_02_compact_document(
    *,
    wstg_id: str,
    title: str,
    source_file: Path,
) -> str:
    # APIT-02 is compact in source form but the normal composite renderer repeats
    # each authorization claim across facets and relation briefs. A fixed card
    # keeps the extraction target clear for the BOLA ontology anchors.
    lines = [
        "# Methodology Scenario",
        "",
        "## Methodology Scope",
        "",
        "This document contains reusable web application testing methodology.",
        "",
        *_render_wstg_anchor_block(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        ),
        "## Overview",
        "",
        "Purpose: Scenario summary, vulnerability framing, impact, and core testing purpose.",
        "",
        (
            "API Broken Object Level Authorization tests whether a REST API or "
            "GraphQL API enforces authorization for every object accessed by the "
            "client. The core target condition is Tenant Scoped Object IDs: object "
            "identifiers appear in API requests and must be checked against the "
            "current account, tenant, role, and ownership rules."
        ),
        "",
        "## Test Objectives",
        "",
        "Purpose: Explicit objectives a tester should satisfy for this WSTG scenario.",
        "",
        "- Determine whether users can access or modify objects they do not own by changing object identifiers.",
        "- Test object-level authorization across read, create, update, patch, delete, and bulk-list behavior.",
        "- Confirm whether Broken Object-Level Authorization is observable through cross-account or cross-tenant access.",
        "",
        "## Target Conditions And Object References",
        "",
        "- Tenant Scoped Object IDs may appear as URL path values, query values, JSON body fields, GraphQL ID arguments, GUIDs, numeric IDs, tokens, or nested object references.",
        "- Useful test setup uses at least two accounts in different ownership contexts, such as account A owning a resource and account B attempting access.",
        "- Candidate object identifiers can come from API documentation, captured traffic, user-visible data, list responses, predictable sequences, or generated test data.",
        "",
        "## Concrete Test Methods And Observable Signals",
        "",
        "- Perform Object ID Tampering by changing an object identifier in a captured request, then replaying the request under a different account or tenant.",
        "- Test common HTTP methods: `GET` for unauthorized reads, `POST` or `PUT` for unauthorized writes, `PATCH` for partial updates, and `DELETE` for unauthorized deletion.",
        "- For REST API paths, compare requests such as `GET /api/users/123/profile` and `GET /api/users/124/profile` under different accounts.",
        "- For GraphQL API requests, modify ID arguments such as `query { user(id: \"124\") { name email } }` and compare authorization behavior.",
        "- Test bulk-list routes such as `GET /api/users` to determine whether responses include only authorized objects.",
        "- Adjacent Account ID Accessible is an observable signal when a modified identifier returns another user's data, changes another user's object, or returns `200 OK` where `401 Unauthorized` or `403 Forbidden` is expected.",
        "- Inconsistent authorization responses across similar route locations indicate incomplete object-level enforcement.",
        "",
        "## Defenses And Detections",
        "",
        "- Enforce server-side object ownership checks for every request that reads or changes an object.",
        "- Bind each object access decision to the authenticated account, tenant, role, and action being performed.",
        "- Apply least privilege so each user can access only objects required for the user's role.",
        "- Prefer non-sequential identifiers such as UUIDs to slow enumeration, while still enforcing authorization on every object access.",
        "- Log cross-account object-access denials and high-volume object ID probing as authorization abuse signals.",
        "",
        *_render_wstg_relation_anchor_block(wstg_id=wstg_id, title=title),
        "## Relation Briefs",
        "",
        "Purpose: preserve source-grounded operational claims connecting testing methods, target conditions, defensive behavior, weakness categories, and payload examples.",
        "",
        "- Broken Object-Level Authorization is a VulnerabilityClass for WSTG-APIT-02.",
        "- Object ID Tampering requires Tenant Scoped Object IDs or equivalent object references in API requests.",
        "- REST API and GraphQL API requests with modified object identifiers can reveal Adjacent Account ID Accessible behavior.",
        "- A successful cross-account read, write, delete, or bulk-list response maps to Broken Object-Level Authorization.",
        "- Object ownership checks, tenant-aware authorization, RBAC, least privilege, and denial logging mitigate or detect object-level authorization bypass.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_wstg_composite_document(
    *,
    wstg_id: str,
    title: str,
    source_file: Path,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> str:
    if wstg_id.upper() == "WSTG-INFO-10":
        return _render_wstg_info_10_compact_document(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        )
    if wstg_id.upper() == "WSTG-APIT-01":
        return _render_wstg_apit_01_compact_document(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        )
    if wstg_id.upper() == "WSTG-APIT-02":
        return _render_wstg_apit_02_compact_document(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        )

    lines = [
        "# Methodology Scenario",
        "",
        "## Methodology Scope",
        "",
        "This document contains reusable web application testing methodology.",
        "",
        *_render_wstg_anchor_block(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
        ),
    ]
    has_ingestion_content = False

    for facet_key, (facet_title, description) in WSTG_FACET_TITLES.items():
        if facet_key in {"source-context", "references"}:
            continue
        facet_fragments = [
            fragment
            for fragment in fragments
            if primary_wstg_facet(
                fragment,
                fragment_facets.get(fragment.fragment_id, []),
            )
            == facet_key
            and not _is_wstg_ingestion_noise_fragment(fragment)
        ]
        if not facet_fragments:
            continue
        lines.extend([f"## {facet_title}", "", f"Purpose: {description}", ""])
        for fragment in facet_fragments:
            rendered = _render_wstg_ingestion_fragment(
                fragment,
                wstg_id=wstg_id,
                title=title,
            )
            if rendered:
                has_ingestion_content = True
                lines.extend(rendered)

    relation_fragments = _wstg_relation_fragments(fragments, fragment_facets)
    relation_fragments = [
        fragment
        for fragment in relation_fragments
        if primary_wstg_facet(
            fragment,
            fragment_facets.get(fragment.fragment_id, []),
        )
        not in {"source-context", "references"}
        and not _is_wstg_ingestion_noise_fragment(fragment)
    ]
    if has_ingestion_content or relation_fragments:
        lines.extend(_render_wstg_relation_anchor_block(wstg_id=wstg_id, title=title))
    if relation_fragments:
        lines.extend(
            [
                "## Relation Briefs",
                "",
                (
                    "Purpose: preserve source-grounded operational claims connecting "
                    "testing methods, target conditions, defensive behavior, weakness "
                    "categories, and payload examples."
                ),
                "",
            ]
        )
    for fragment in relation_fragments:
        rendered = _render_wstg_ingestion_fragment(
            fragment,
            wstg_id=wstg_id,
            title=title,
        )
        if rendered:
            has_ingestion_content = True
            lines.extend(rendered)

    if not has_ingestion_content:
        return ""
    return "\n".join(lines).rstrip() + "\n"


def _render_facet_document(facet: FacetSpec, fragments: Sequence[SourceFragment]) -> str:
    lines = [
        f"# {facet.title}",
        "",
        f"Purpose: {facet.description}",
        "",
        (
            "Ontology boundary: this document groups source material by a stable "
            "methodology facet. It does not encode the active LightRAG ontology."
        ),
        "",
    ]
    if not fragments:
        lines.extend(["No source fragments matched this facet.", ""])
    for fragment in fragments:
        lines.extend(_render_fragment(fragment))
    return "\n".join(lines).rstrip() + "\n"


def _render_relation_briefs(result: PreprocessResult) -> str:
    relation_fragments = [
        fragment for fragment in result.fragments if is_relation_fragment(fragment)
    ]
    lines = [
        "# Relation Briefs",
        "",
        (
            "Purpose: preserve operational claims that connect methods, defenses, "
            "conditions, vulnerabilities, code, and observed limitations."
        ),
        "",
        (
            "Ontology boundary: relation briefs are source-grounded and ontology-"
            "agnostic. The current LightRAG ontology may extract typed edges from "
            "them, but the briefs remain valid when that ontology changes."
        ),
        "",
    ]
    if not relation_fragments:
        lines.extend(["No relation-like source fragments were found.", ""])
    for fragment in relation_fragments:
        facets = result.fragment_facets.get(fragment.fragment_id, [])
        lines.extend(_render_fragment(fragment, facets=facets))
    return "\n".join(lines).rstrip() + "\n"


def _iter_writeup_source_files(source_paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for source in source_paths:
        path = Path(source)
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file()
                and not child.name.startswith(".")
                and child.suffix.lower() in {".html", ".htm", ".md", ".markdown", ".txt"}
            )
        elif path.is_file() and path.suffix.lower() in {".html", ".htm", ".md", ".markdown", ".txt"}:
            files.append(path)
    return sorted(files)


def _clean_html_text(value: str) -> str:
    without_tags = re.sub(r"(?is)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _extract_html_attr(source: str, pattern: str) -> str | None:
    match = re.search(pattern, source, flags=re.I | re.S)
    if not match:
        return None
    return html.unescape(match.group(1).strip())


def _extract_html_body(source: str) -> str:
    for pattern in (
        r"<article\b[^>]*>(.*?)</article>",
        r"<main\b[^>]*>(.*?)</main>",
        r"<div\b[^>]*class=[\"'][^\"']*(?:post-content|entry-content|content)[^\"']*[\"'][^>]*>(.*?)</div>",
    ):
        match = re.search(pattern, source, flags=re.I | re.S)
        if match:
            return match.group(1)
    return source


def _html_to_markdown(source: str) -> str:
    body = _extract_html_body(source)
    body = re.sub(r"(?is)<script\b.*?</script>", "\n", body)
    body = re.sub(r"(?is)<style\b.*?</style>", "\n", body)
    body = re.sub(r"(?is)<nav\b.*?</nav>", "\n", body)
    body = re.sub(r"(?is)<footer\b.*?</footer>", "\n", body)

    code_blocks: list[str] = []

    def code_repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        text = _clean_html_text(inner)
        code_blocks.append(f"```text\n{text}\n```")
        return f"\n\n@@POLYPHEMUS_CODE_BLOCK_{len(code_blocks) - 1}@@\n\n"

    body = re.sub(r"(?is)<pre\b[^>]*>(.*?)</pre>", code_repl, body)

    def heading_repl(match: re.Match[str]) -> str:
        level = int(match.group(1))
        title = _clean_html_text(match.group(2))
        if not title:
            return "\n"
        return f"\n\n{'#' * min(level, 6)} {title}\n\n"

    body = re.sub(r"(?is)<h([1-6])\b[^>]*>(.*?)</h\1>", heading_repl, body)

    def list_repl(match: re.Match[str]) -> str:
        text = _clean_html_text(match.group(1))
        return f"\n- {text}\n" if text else "\n"

    body = re.sub(r"(?is)<li\b[^>]*>(.*?)</li>", list_repl, body)
    body = re.sub(r"(?i)<br\s*/?>", "\n", body)
    body = re.sub(r"(?i)</(?:p|div|section|blockquote|ul|ol|table|tr)>", "\n\n", body)
    body = re.sub(r"(?i)<(?:p|div|section|blockquote|ul|ol|table|tr|td|th)\b[^>]*>", "\n", body)
    body = re.sub(r"(?is)<[^>]+>", " ", body)
    body = html.unescape(body)

    for index, code_block in enumerate(code_blocks):
        body = body.replace(f"@@POLYPHEMUS_CODE_BLOCK_{index}@@", code_block)

    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in body.splitlines()]
    compacted: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                compacted.append("")
            blank = True
            continue
        compacted.append(line)
        blank = False
    return "\n".join(compacted).strip() + "\n"


def _extract_writeup_metadata_from_html(path: Path, source: str, markdown: str) -> dict:
    title = None
    for pattern in (
        r"<h1\b[^>]*class=[\"'][^\"']*post-title[^\"']*[\"'][^>]*>(.*?)</h1>",
        r"<h1\b[^>]*>(.*?)</h1>",
        r"<title\b[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, source, flags=re.I | re.S)
        if match:
            title = _clean_html_text(match.group(1))
            break
    if title:
        title = re.sub(r"\s+\|\s+0xdf.*$", "", title, flags=re.I).strip()
    if not title:
        title_match = re.search(r"^#\s+(.+)$", markdown, flags=re.M)
        title = title_match.group(1).strip() if title_match else path.stem.replace("-", " ").title()

    source_url = (
        _extract_html_attr(source, r"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']([^\"']+)[\"']")
        or _extract_html_attr(source, r"<meta\b[^>]*property=[\"']og:url[\"'][^>]*content=[\"']([^\"']+)[\"']")
    )
    source_date = (
        _extract_html_attr(source, r"<time\b[^>]*datetime=[\"']([^\"']+)[\"']")
        or _extract_html_attr(source, r"<meta\b[^>]*property=[\"']article:published_time[\"'][^>]*content=[\"']([^\"']+)[\"']")
    )
    tags = [
        _clean_html_text(tag)
        for tag in re.findall(r"class=[\"']post-tag[\"'][^>]*>(.*?)</a>", source, flags=re.I | re.S)
    ]
    tags = [tag for tag in tags if tag]
    return {
        "source_url": source_url,
        "source_title": title,
        "source_date": source_date,
        "source_tags": list(dict.fromkeys(tags)),
        "source_type": "0xdf_writeup",
        "confidence": "review_overlay",
    }


def _extract_writeup_metadata_from_markdown(path: Path, markdown: str) -> dict:
    title_match = re.search(r"^#\s+(.+)$", markdown, flags=re.M)
    return {
        "source_url": None,
        "source_title": title_match.group(1).strip() if title_match else path.stem.replace("-", " ").title(),
        "source_date": None,
        "source_tags": [],
        "source_type": "writeup",
        "confidence": "review_overlay",
    }


def _load_writeup_manifest_entry(path: Path) -> dict:
    manifest_path = path.parent / ".manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = manifest.get("writeups", [])
    for entry in entries:
        source_path = Path(entry.get("source_path", ""))
        if source_path == path or source_path.as_posix() == path.as_posix() or source_path.name == path.name:
            return entry
    return {}


def _read_writeup_source(path: Path) -> tuple[str, dict]:
    source = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        markdown = _html_to_markdown(source)
        metadata = _extract_writeup_metadata_from_html(path, source, markdown)
    else:
        markdown = source
        metadata = _extract_writeup_metadata_from_markdown(path, markdown)

    manifest_entry = _load_writeup_manifest_entry(path)
    if manifest_entry:
        metadata.update(
            {
                "source_url": manifest_entry.get("url") or metadata.get("source_url"),
                "source_title": manifest_entry.get("title") or metadata.get("source_title"),
                "source_date": manifest_entry.get("date") or metadata.get("source_date"),
                "source_tags": manifest_entry.get("tags") or metadata.get("source_tags", []),
                "sha256": manifest_entry.get("sha256"),
                "fetched_at": manifest_entry.get("fetched_at"),
            }
        )
    return markdown, metadata


def _writeup_concepts_for_text(text: str) -> dict[str, list[str]]:
    lowered = text.lower()
    concepts: dict[str, list[str]] = {}
    for concept_type, entries in WRITEUP_CONCEPT_PATTERNS.items():
        matched = []
        for name, patterns in entries:
            if any(_keyword_matches(lowered, pattern) for pattern in patterns):
                matched.append(name)
        if matched:
            concepts[concept_type] = list(dict.fromkeys(matched))
    return concepts


def _writeup_fragment_concepts(fragment: SourceFragment) -> dict[str, list[str]]:
    heading = " ".join(fragment.heading_path)
    return _writeup_concepts_for_text(f"{heading}\n{fragment.text}")


def classify_writeup_fragment(fragment: SourceFragment) -> list[str]:
    concepts = _writeup_fragment_concepts(fragment)
    text = f"{' '.join(fragment.heading_path)} {fragment.text}".lower()
    facets: list[str] = []

    if concepts.get("PreconditionEnvironment") or concepts.get("TechnologyStack"):
        facets.append("technology-and-preconditions")
    if (
        concepts.get("AttackTechnique")
        or concepts.get("VulnerabilityClass")
        or concepts.get("PayloadPattern")
        or concepts.get("AttackGoal")
    ):
        facets.append("technique-cards")
    if concepts.get("AttackerCapability") or concepts.get("Artifact") or concepts.get("ObservableSignal"):
        facets.append("artifacts-and-capabilities")
    if concepts.get("DefensiveControl") or "bypass" in text or "blocked" in text or "filter" in text:
        facets.append("defensive-controls-and-bypasses")
    if _is_writeup_relation_candidate(fragment, concepts):
        facets.append("relation-briefs")
    if not facets:
        facets.append("source-context")
    return list(dict.fromkeys(facets))


def _is_writeup_relation_candidate(fragment: SourceFragment, concepts: dict[str, list[str]] | None = None) -> bool:
    if fragment.block_type == "code":
        return False
    concepts = concepts or _writeup_fragment_concepts(fragment)
    text = f" {' '.join(fragment.heading_path).lower()} {fragment.text.lower()} "
    concept_count = sum(1 for values in concepts.values() if values)
    relation_markers = (
        " allows ",
        " enables ",
        " gives ",
        " gets ",
        " grants ",
        " works ",
        " fails ",
        " blocked ",
        " bypass ",
        " vulnerable ",
        " exploit ",
        " shell ",
        " credentials ",
        " read ",
    )
    return is_relation_fragment(fragment) or concept_count >= 2 and any(marker in text for marker in relation_markers)


def _format_concept_values(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "Not observed in evidence."


def _writeup_concepts_by_type(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
    concept_type: str,
) -> dict[str, list[SourceFragment]]:
    grouped: dict[str, list[SourceFragment]] = {}
    for fragment in fragments:
        for concept in fragment_concepts.get(fragment.fragment_id, {}).get(concept_type, []):
            grouped.setdefault(concept, []).append(fragment)
    return grouped


def _all_writeup_concepts(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
    concept_type: str,
) -> list[str]:
    seen: dict[str, None] = {}
    for fragment in fragments:
        for concept in fragment_concepts.get(fragment.fragment_id, {}).get(concept_type, []):
            seen.setdefault(concept, None)
    return list(seen.keys())


def _render_writeup_metadata(metadata: dict, source_file: Path) -> list[str]:
    return [
        "## Methodology Scope",
        "",
        "This document contains reusable attack-methodology observations extracted from a writeup.",
        "Provenance metadata is stored in the manifest and omitted from this ingestion document.",
        "",
    ]


def _render_writeup_attack_chain_summary(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines = [
        "## Attack Chain Summary",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['attack-chain-summary'][1]}",
        "",
        f"- Preconditions: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'PreconditionEnvironment'))}",
        f"- Technology stacks: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'TechnologyStack'))}",
        f"- Observed techniques: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'AttackTechnique'))}",
        f"- Attack goals: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'AttackGoal'))}",
        f"- Attacker capabilities: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'AttackerCapability'))}",
        f"- Produced or consumed artifacts: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'Artifact'))}",
        f"- Expected observable signals: {_format_concept_values(_all_writeup_concepts(fragments, fragment_concepts, 'ObservableSignal'))}",
        "",
    ]
    return lines


def _render_writeup_environment_and_technology(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines = [
        "## Technology And Preconditions",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['technology-and-preconditions'][1]}",
        "",
    ]
    for concept_type, title in (
        ("PreconditionEnvironment", "Preconditions"),
        ("TechnologyStack", "Technology Stacks"),
        ("VulnerabilityClass", "Weakness Classes"),
    ):
        lines.extend([f"### {title}", ""])
        grouped = _writeup_concepts_by_type(fragments, fragment_concepts, concept_type)
        if not grouped:
            lines.extend(["No concepts detected.", ""])
            continue
        for concept, evidence in grouped.items():
            lines.append(f"- {concept}")
        lines.append("")
    return lines


def _render_writeup_technique_cards(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines = [
        "## Technique Cards",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['technique-cards'][1]}",
        "",
    ]
    grouped = _writeup_concepts_by_type(fragments, fragment_concepts, "AttackTechnique")
    if not grouped:
        lines.extend(["No technique concepts detected.", ""])
        return lines

    for technique, evidence in grouped.items():
        related: dict[str, list[str]] = {}
        for fragment in evidence:
            concepts = fragment_concepts.get(fragment.fragment_id, {})
            for concept_type, values in concepts.items():
                if concept_type == "AttackTechnique":
                    continue
                related.setdefault(concept_type, [])
                related[concept_type].extend(values)
        related = {key: list(dict.fromkeys(values)) for key, values in related.items()}
        lines.extend(
            [
                f"### Technique: {technique}",
                "",
                f"- Preconditions: {_format_concept_values(related.get('PreconditionEnvironment', []))}",
                f"- Technology stacks: {_format_concept_values(related.get('TechnologyStack', []))}",
                f"- Tests or exploits: {_format_concept_values(related.get('VulnerabilityClass', []))}",
                f"- Attack goals: {_format_concept_values(related.get('AttackGoal', []))}",
                f"- Payload patterns: {_format_concept_values(related.get('PayloadPattern', []))}",
                f"- Attacker capabilities: {_format_concept_values(related.get('AttackerCapability', []))}",
                f"- Produced artifacts: {_format_concept_values(related.get('Artifact', []))}",
                f"- Expected signals: {_format_concept_values(related.get('ObservableSignal', []))}",
                f"- Defensive controls: {_format_concept_values(related.get('DefensiveControl', []))}",
            ]
        )
        lines.append("")
    return lines


def _render_writeup_artifacts_and_capabilities(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines = [
        "## Artifacts And Attacker Capabilities",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['artifacts-and-capabilities'][1]}",
        "",
    ]
    for concept_type, title in (
        ("AttackerCapability", "Attacker Capabilities"),
        ("Artifact", "Artifacts"),
        ("ObservableSignal", "Observable Signals"),
        ("AttackGoal", "Attack Goals"),
    ):
        lines.extend([f"### {title}", ""])
        grouped = _writeup_concepts_by_type(fragments, fragment_concepts, concept_type)
        if not grouped:
            lines.extend(["No concepts detected.", ""])
            continue
        for concept, evidence in grouped.items():
            lines.append(f"- {concept}")
        lines.append("")
    return lines


def _render_writeup_defenses_and_bypasses(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines = [
        "## Defensive Controls And Bypasses",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['defensive-controls-and-bypasses'][1]}",
        "",
    ]
    for concept_type, title in (
        ("DefensiveControl", "Defensive Controls"),
        ("PayloadPattern", "Payload Or Bypass Patterns"),
    ):
        lines.extend([f"### {title}", ""])
        grouped = _writeup_concepts_by_type(fragments, fragment_concepts, concept_type)
        if not grouped:
            lines.extend(["No concepts detected.", ""])
            continue
        for concept, evidence in grouped.items():
            lines.append(f"- {concept}")
        lines.append("")
    return lines


def _add_relation_statement(
    statements: list[str],
    seen: set[str],
    claim: str,
) -> None:
    if claim in seen:
        return
    seen.add(claim)
    statements.append(f"- {claim}.")


def _render_writeup_relation_briefs(
    fragments: Sequence[SourceFragment],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines = [
        "## Relation Briefs",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['relation-briefs'][1]}",
        "",
        (
            "These relation briefs are normalized from writeup evidence and remain "
            "an overlay until reviewed for base promotion."
        ),
        "",
    ]
    statements: list[str] = []
    seen: set[str] = set()
    relation_fragments = [
        fragment
        for fragment in fragments
        if _is_writeup_relation_candidate(
            fragment,
            fragment_concepts.get(fragment.fragment_id, {}),
        )
    ]
    for fragment in relation_fragments:
        concepts = fragment_concepts.get(fragment.fragment_id, {})
        techniques = concepts.get("AttackTechnique", [])
        payloads = concepts.get("PayloadPattern", [])
        text = fragment.text.lower()
        for technique in techniques:
            for vulnerability in concepts.get("VulnerabilityClass", []):
                _add_relation_statement(
                    statements,
                    seen,
                    f"{technique} tests or exploits {vulnerability}",
                )
            for payload in payloads:
                _add_relation_statement(
                    statements,
                    seen,
                    f"{technique} uses payload pattern {payload}",
                )
            for technology in concepts.get("TechnologyStack", []):
                _add_relation_statement(
                    statements,
                    seen,
                    f"{technique} is relevant to technology stack {technology}",
                )
            for condition in concepts.get("PreconditionEnvironment", []):
                _add_relation_statement(
                    statements,
                    seen,
                    f"{technique} is applicable when {condition} is present",
                )
            for goal in concepts.get("AttackGoal", []):
                _add_relation_statement(
                    statements,
                    seen,
                    f"{technique} can support attack goal {goal}",
                )
            for signal in concepts.get("ObservableSignal", []):
                _add_relation_statement(
                    statements,
                    seen,
                    f"{signal} can indicate the result of {technique}",
                )
            for artifact in concepts.get("Artifact", []):
                _add_relation_statement(
                    statements,
                    seen,
                    f"{technique} can produce artifact {artifact}",
                )
            for capability in concepts.get("AttackerCapability", []):
                if any(marker in text for marker in (" gives ", " gets ", " grants ", " shell ", " works", " produces")):
                    _add_relation_statement(
                        statements,
                        seen,
                        f"{technique} can establish attacker capability {capability}",
                    )
            for control in concepts.get("DefensiveControl", []):
                if "bypass" in text or "works" in text:
                    claim = f"{technique} may bypass defensive control {control}"
                else:
                    claim = f"{technique} may be blocked by defensive control {control}"
                _add_relation_statement(statements, seen, claim)
        for payload in payloads:
            for control in concepts.get("DefensiveControl", []):
                if "bypass" in text or "works" in text:
                    _add_relation_statement(
                        statements,
                        seen,
                        f"Payload pattern {payload} may bypass defensive control {control}",
                    )
        for artifact in concepts.get("Artifact", []):
            for capability in concepts.get("AttackerCapability", []):
                if any(marker in text for marker in (" enables ", " gives ", " gets ", " reveals ", " read ")):
                    _add_relation_statement(
                        statements,
                        seen,
                        f"Artifact {artifact} can support attacker capability {capability}",
                    )
            for condition in concepts.get("PreconditionEnvironment", []):
                if "vhost" in text or "server_name" in text or "config" in text:
                    _add_relation_statement(
                        statements,
                        seen,
                        f"Artifact {artifact} can reveal precondition {condition}",
                    )

    if not statements:
        lines.extend(["No writeup relation candidates were found.", ""])
        return lines

    lines.extend(statements[:250])
    lines.append("")
    return lines


def _render_writeup_source_context(
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> list[str]:
    source_context = [
        fragment
        for fragment in fragments
        if fragment_facets.get(fragment.fragment_id) == ["source-context"]
    ]
    if not source_context:
        return []
    lines = [
        "## Source Context",
        "",
        f"Purpose: {WRITEUP_FACET_TITLES['source-context'][1]}",
        "",
    ]
    for fragment in source_context[:25]:
        lines.extend(_render_fragment(fragment, facets=fragment_facets.get(fragment.fragment_id, [])))
    return lines


def _render_writeup_composite_document(
    *,
    source_file: Path,
    metadata: dict,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
    fragment_concepts: dict[str, dict[str, list[str]]],
) -> str:
    lines = [
        "# Writeup Methodology Overlay",
        "",
    ]
    lines.extend(_render_writeup_metadata(metadata, source_file))
    lines.extend(_render_writeup_attack_chain_summary(fragments, fragment_concepts))
    lines.extend(_render_writeup_environment_and_technology(fragments, fragment_concepts))
    lines.extend(_render_writeup_technique_cards(fragments, fragment_concepts))
    lines.extend(_render_writeup_artifacts_and_capabilities(fragments, fragment_concepts))
    lines.extend(_render_writeup_defenses_and_bypasses(fragments, fragment_concepts))
    lines.extend(_render_writeup_relation_briefs(fragments, fragment_concepts))
    return "\n".join(lines).rstrip() + "\n"


def _writeup_manifest_payload(
    result: PreprocessResult,
    writeups: Sequence[dict],
) -> dict:
    return {
        "schema_version": 1,
        "profile": "writeup",
        "primary_document_pattern": "<source-slug>-methodology.md",
        "knowledge_tier": "review_overlay",
        "ontology_boundary": (
            "Generated writeup documents are normalized methodology overlays. "
            "They preserve source-grounded chain claims without promoting them "
            "to validated base knowledge."
        ),
        "writeups": list(writeups),
        "fragments": [
            {
                **asdict(fragment),
                "facets": result.fragment_facets.get(fragment.fragment_id, []),
                "concepts": _writeup_fragment_concepts(fragment),
            }
            for fragment in result.fragments
        ],
        "generated_files": [path.as_posix() for path in result.generated_files],
    }


def preprocess_writeups_for_lightrag(
    source_paths: Iterable[str | Path],
    output_dir: str | Path = DEFAULT_WRITEUP_OUTPUT_DIR,
) -> PreprocessResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    all_fragments: list[SourceFragment] = []
    all_fragment_facets: dict[str, list[str]] = {}
    generated_files: list[Path] = []
    writeups: list[dict] = []
    used_slugs: set[str] = set()

    for source_file in _iter_writeup_source_files(source_paths):
        markdown, metadata = _read_writeup_source(source_file)
        title = metadata.get("source_title") or source_file.stem.replace("-", " ").title()
        fragments = parse_markdown_text(markdown, source_file, document_title=title)
        if not fragments:
            continue
        fragment_facets = {
            fragment.fragment_id: classify_writeup_fragment(fragment)
            for fragment in fragments
        }
        fragment_concepts = {
            fragment.fragment_id: _writeup_fragment_concepts(fragment)
            for fragment in fragments
        }
        all_fragments.extend(fragments)
        all_fragment_facets.update(fragment_facets)

        base_slug = _slug(title, fallback=source_file.stem)
        slug = base_slug
        if slug in used_slugs:
            suffix = hashlib.sha1(source_file.as_posix().encode("utf-8")).hexdigest()[:8]
            slug = f"{base_slug}-{suffix}"
        used_slugs.add(slug)
        composite_path = output_path / f"{slug}-methodology.md"
        composite_path.write_text(
            _render_writeup_composite_document(
                source_file=source_file,
                metadata=metadata,
                fragments=fragments,
                fragment_facets=fragment_facets,
                fragment_concepts=fragment_concepts,
            ),
            encoding="utf-8",
        )
        generated_files.append(composite_path)
        writeups.append(
            {
                "title": title,
                "source_url": metadata.get("source_url"),
                "source_path": source_file.as_posix(),
                "fragments": len(fragments),
                "primary_document": composite_path.name,
                "confidence": metadata.get("confidence", "review_overlay"),
            }
        )

    result = PreprocessResult(
        fragments=all_fragments,
        fragment_facets=all_fragment_facets,
        generated_files=generated_files,
    )
    manifest_path = output_path / ".manifest.json"
    manifest_path.write_text(
        json.dumps(
            _writeup_manifest_payload(result, writeups),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    generated_files.append(manifest_path)
    return result


def _manifest_payload(result: PreprocessResult) -> dict:
    return {
        "schema_version": 1,
        "primary_document": "relation-briefs.md",
        "ontology_boundary": (
            "Generated documents are ontology-agnostic methodology views. "
            "LightRAG ontology extraction happens after this preprocessing step."
        ),
        "fragments": [
            {
                **asdict(fragment),
                "facets": result.fragment_facets.get(fragment.fragment_id, []),
                "is_relation_brief": is_relation_fragment(fragment),
            }
            for fragment in result.fragments
        ],
        "generated_files": [path.as_posix() for path in result.generated_files],
    }


def write_preprocessed_documents(
    result: PreprocessResult,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    facets: Sequence[FacetSpec] = DEFAULT_FACETS,
) -> PreprocessResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated_files: list[Path] = []

    relation_path = output_path / "relation-briefs.md"
    relation_path.write_text(_render_relation_briefs(result), encoding="utf-8")
    generated_files.append(relation_path)

    for facet in facets:
        facet_fragments = [
            fragment
            for fragment in result.fragments
            if facet.key in result.fragment_facets.get(fragment.fragment_id, [])
        ]
        doc_path = output_path / f"{facet.key}.md"
        doc_path.write_text(_render_facet_document(facet, facet_fragments), encoding="utf-8")
        generated_files.append(doc_path)

    result.generated_files = generated_files
    manifest_path = output_path / ".manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_payload(result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    generated_files.append(manifest_path)
    return result


def _wstg_manifest_payload(
    result: PreprocessResult,
    scenarios: Sequence[dict],
    *,
    debug_facets: bool,
) -> dict:
    return {
        "schema_version": 3,
        "profile": "wstg",
        "primary_document_pattern": "<wstg-id>-methodology.md",
        "debug_facets": debug_facets,
        "ontology_boundary": (
            "Generated WSTG composite documents are ontology-agnostic methodology "
            "views. LightRAG v1.5 applies the active entity prompt profile during "
            "indexing."
        ),
        "scenarios": list(scenarios),
        "fragments": [
            {
                **asdict(fragment),
                "facets": result.fragment_facets.get(fragment.fragment_id, []),
            }
            for fragment in result.fragments
        ],
        "generated_files": [path.as_posix() for path in result.generated_files],
    }


def preprocess_wstg_for_lightrag(
    source_paths: Iterable[str | Path],
    output_dir: str | Path = DEFAULT_WSTG_OUTPUT_DIR,
    *,
    debug_facets: bool = False,
) -> PreprocessResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for stale_path in output_path.glob("wstg-*-methodology.md"):
        stale_path.unlink()
    all_fragments: list[SourceFragment] = []
    all_fragment_facets: dict[str, list[str]] = {}
    generated_files: list[Path] = []
    scenarios: list[dict] = []
    used_slugs: set[str] = set()

    for source_file in _iter_source_files(source_paths):
        fragments = parse_markdown_source(source_file)
        if not fragments:
            continue
        wstg_id = _detect_wstg_id(source_file, fragments)
        title = _detect_wstg_title(source_file, fragments)
        slug = _unique_wstg_slug(wstg_id, source_file, used_slugs)
        fragment_facets = {
            fragment.fragment_id: classify_wstg_fragment(fragment)
            for fragment in fragments
        }

        all_fragments.extend(fragments)
        all_fragment_facets.update(fragment_facets)

        composite_path = output_path / f"{slug}-methodology.md"
        composite_text = _render_wstg_composite_document(
            wstg_id=wstg_id,
            title=title,
            source_file=source_file,
            fragments=fragments,
            fragment_facets=fragment_facets,
        )
        if not composite_text.strip():
            continue
        composite_path.write_text(composite_text, encoding="utf-8")
        generated_files.append(composite_path)

        debug_files: list[str] = []
        if debug_facets:
            debug_dir = output_path / "_debug_facets"
            debug_dir.mkdir(parents=True, exist_ok=True)
            relation_path = debug_dir / f"{slug}-relation-briefs.md"
            relation_path.write_text(
                _render_wstg_relation_briefs(
                    wstg_id=wstg_id,
                    title=title,
                    fragments=fragments,
                    fragment_facets=fragment_facets,
                ),
                encoding="utf-8",
            )
            generated_files.append(relation_path)
            debug_files.append(relation_path.as_posix())

            for facet_key in WSTG_FACET_TITLES:
                facet_fragments = [
                    fragment
                    for fragment in fragments
                    if facet_key in fragment_facets.get(fragment.fragment_id, [])
                ]
                if not facet_fragments and facet_key != "source-context":
                    continue
                doc_path = debug_dir / f"{slug}-{facet_key}.md"
                doc_path.write_text(
                    _render_wstg_document(
                        wstg_id=wstg_id,
                        title=title,
                        facet_key=facet_key,
                        fragments=facet_fragments,
                        fragment_facets=fragment_facets,
                    ),
                    encoding="utf-8",
                )
                generated_files.append(doc_path)
                debug_files.append(doc_path.as_posix())

        scenarios.append(
            {
                "wstg_id": wstg_id,
                "title": title,
                "category_code": _wstg_category_code(wstg_id),
                "category": _wstg_category_name(wstg_id),
                "canonical_aliases": _wstg_anchor_aliases(wstg_id, title),
                "canonical_vulnerability_classes": _wstg_vulnerability_class_aliases(
                    wstg_id,
                    title,
                ),
                "ontology_query_anchors": _wstg_ontology_query_anchors(wstg_id),
                "ontology_query_anchor_terms": _flatten_wstg_ontology_query_anchors(
                    wstg_id
                ),
                "source_path": source_file.as_posix(),
                "fragments": len(fragments),
                "primary_document": composite_path.name,
                "debug_files": debug_files,
            }
        )

    result = PreprocessResult(
        fragments=all_fragments,
        fragment_facets=all_fragment_facets,
        generated_files=generated_files,
    )
    manifest_path = output_path / ".manifest.json"
    manifest_path.write_text(
        json.dumps(
            _wstg_manifest_payload(result, scenarios, debug_facets=debug_facets),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    generated_files.append(manifest_path)
    return result


def preprocess_sources_for_lightrag(
    source_paths: Iterable[str | Path],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> PreprocessResult:
    result = build_preprocessed_documents(source_paths)
    return write_preprocessed_documents(result, output_dir)


def qa_wstg_preprocessed_corpus(
    input_dir: str | Path = DEFAULT_WSTG_OUTPUT_DIR,
    *,
    max_document_chars: int = 60000,
) -> WSTGCorpusQAResult:
    input_path = Path(input_dir)
    issues: list[CorpusQAIssue] = []
    manifest_path = input_path / ".manifest.json"
    if not manifest_path.exists():
        return WSTGCorpusQAResult(
            passed=False,
            scenario_count=0,
            generated_document_count=0,
            max_document_chars=max_document_chars,
            issues=[
                CorpusQAIssue(
                    severity="error",
                    code="missing_manifest",
                    path=manifest_path.as_posix(),
                    message="WSTG preprocessed manifest is missing.",
                )
            ],
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return WSTGCorpusQAResult(
            passed=False,
            scenario_count=0,
            generated_document_count=0,
            max_document_chars=max_document_chars,
            issues=[
                CorpusQAIssue(
                    severity="error",
                    code="invalid_manifest_json",
                    path=manifest_path.as_posix(),
                    message=str(exc),
                )
            ],
        )

    scenarios = [
        scenario
        for scenario in manifest.get("scenarios", [])
        if isinstance(scenario, Mapping)
    ]
    generated_documents = sorted(input_path.glob("wstg-*-methodology.md"))
    if manifest.get("profile") != "wstg":
        issues.append(
            CorpusQAIssue(
                severity="error",
                code="wrong_manifest_profile",
                path=manifest_path.as_posix(),
                message="Manifest profile must be wstg.",
            )
        )

    seen_wstg_ids: set[str] = set()
    for scenario in scenarios:
        wstg_id = str(scenario.get("wstg_id", "")).upper()
        title = str(scenario.get("title", ""))
        primary_document = str(scenario.get("primary_document", ""))
        canonical_classes = [
            str(value)
            for value in scenario.get("canonical_vulnerability_classes", [])
        ]
        ontology_anchors = scenario.get("ontology_query_anchors", {})

        if not wstg_id or wstg_id.startswith("WSTG-UNKN"):
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code="invalid_wstg_id",
                    path=primary_document or manifest_path.as_posix(),
                    message=f"Scenario has invalid WSTG ID {wstg_id!r}.",
                )
            )
        if wstg_id in seen_wstg_ids:
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code="duplicate_wstg_id",
                    path=primary_document or manifest_path.as_posix(),
                    message=f"Duplicate WSTG ID {wstg_id}.",
                )
            )
        seen_wstg_ids.add(wstg_id)

        if not primary_document:
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code="missing_primary_document",
                    path=manifest_path.as_posix(),
                    message=f"Scenario {wstg_id or title} has no primary document.",
                )
            )
            continue

        document_path = input_path / primary_document
        if not document_path.exists():
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code="missing_primary_document_file",
                    path=document_path.as_posix(),
                    message=f"Primary document for {wstg_id} does not exist.",
                )
            )
            continue

        text = document_path.read_text(encoding="utf-8")
        _add_wstg_document_qa_issues(
            issues,
            document_path=document_path,
            text=text,
            wstg_id=wstg_id,
            title=title,
            canonical_classes=canonical_classes,
            ontology_anchors=ontology_anchors,
            max_document_chars=max_document_chars,
        )

    primary_documents = {
        str(scenario.get("primary_document", ""))
        for scenario in scenarios
        if scenario.get("primary_document")
    }
    for document_path in generated_documents:
        if document_path.name not in primary_documents:
            issues.append(
                CorpusQAIssue(
                    severity="warning",
                    code="unmanifested_document",
                    path=document_path.as_posix(),
                    message="Generated methodology document is not listed in manifest scenarios.",
                )
            )

    passed = not any(issue.severity == "error" for issue in issues)
    return WSTGCorpusQAResult(
        passed=passed,
        scenario_count=len(scenarios),
        generated_document_count=len(generated_documents),
        max_document_chars=max_document_chars,
        issues=issues,
    )


def _add_wstg_document_qa_issues(
    issues: list[CorpusQAIssue],
    *,
    document_path: Path,
    text: str,
    wstg_id: str,
    title: str,
    canonical_classes: Sequence[str],
    ontology_anchors: Any,
    max_document_chars: int,
) -> None:
    checks = {
        "missing_methodology_scenario": "# Methodology Scenario",
        "missing_scenario_anchor": "## WSTG Scenario Anchor",
        "missing_wstg_id_anchor": f"- WSTG ID: {wstg_id}",
        "missing_wstg_title_anchor": f"- WSTG title: {title}",
        "missing_relation_anchors": "## Canonical Relation Anchors",
    }
    for code, required_text in checks.items():
        if required_text and required_text not in text:
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code=code,
                    path=document_path.as_posix(),
                    message=f"Required anchor text is missing: {required_text}",
                )
            )

    if canonical_classes and "Canonical VulnerabilityClass entities:" not in text:
        issues.append(
            CorpusQAIssue(
                severity="error",
                code="missing_canonical_vulnerability_classes",
                path=document_path.as_posix(),
                message="Canonical VulnerabilityClass anchor is missing.",
            )
        )
    for canonical_class in canonical_classes:
        if (
            f"{canonical_class} is a VulnerabilityClass for WSTG scenario {wstg_id}."
            not in text
        ):
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code="missing_vulnerability_relation_anchor",
                    path=document_path.as_posix(),
                    message=(
                        "Canonical vulnerability relation anchor is missing for "
                        f"{canonical_class}."
                    ),
                )
            )

    expected_anchors = _wstg_ontology_query_anchors(wstg_id)
    if expected_anchors and "## Ontology Query Anchors" not in text:
        issues.append(
            CorpusQAIssue(
                severity="error",
                code="missing_ontology_query_anchor_block",
                path=document_path.as_posix(),
                message=f"Ontology query anchor block is missing for {wstg_id}.",
            )
        )
    if expected_anchors and not isinstance(ontology_anchors, Mapping):
        issues.append(
            CorpusQAIssue(
                severity="error",
                code="missing_manifest_ontology_anchors",
                path=document_path.as_posix(),
                message=f"Manifest ontology anchors are missing for {wstg_id}.",
            )
        )
    for entity_type, values in expected_anchors.items():
        manifest_values = set(ontology_anchors.get(entity_type, ())) if isinstance(ontology_anchors, Mapping) else set()
        for value in values:
            if value not in text:
                issues.append(
                    CorpusQAIssue(
                        severity="error",
                        code="missing_ontology_anchor_term",
                        path=document_path.as_posix(),
                        message=f"Ontology anchor term is missing from document: {value}",
                    )
                )
            if value not in manifest_values:
                issues.append(
                    CorpusQAIssue(
                        severity="error",
                        code="missing_manifest_ontology_anchor_term",
                        path=document_path.as_posix(),
                        message=f"Ontology anchor term is missing from manifest: {value}",
                    )
                )

    if len(text) > max_document_chars:
        issues.append(
            CorpusQAIssue(
                severity="warning",
                code="large_document",
                path=document_path.as_posix(),
                message=(
                    f"Document has {len(text)} characters; this can increase "
                    "LightRAG extraction latency and timeout risk."
                ),
            )
        )

    for forbidden in _WSTG_QA_FORBIDDEN_TERMS:
        if forbidden.casefold() in text.casefold():
            issues.append(
                CorpusQAIssue(
                    severity="error",
                    code="forbidden_noise_term",
                    path=document_path.as_posix(),
                    message=f"Forbidden ingestion noise term found: {forbidden}",
                )
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preprocess methodology documents into LightRAG-ready facet documents."
    )
    parser.add_argument("sources", nargs="*", help="Source Markdown/text files or directories.")
    parser.add_argument(
        "--profile",
        choices=("generic", "wstg", "writeup"),
        default="generic",
        help="Preprocessing profile to apply.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where generated LightRAG input documents are written.",
    )
    parser.add_argument(
        "--debug-facets",
        action="store_true",
        help="For the WSTG profile, also write per-facet debug documents under _debug_facets/.",
    )
    parser.add_argument(
        "--qa",
        action="store_true",
        help="For the WSTG profile, run static QA after preprocessing.",
    )
    parser.add_argument(
        "--qa-only",
        action="store_true",
        help="Run static QA for an existing WSTG preprocessed directory without rewriting it.",
    )
    parser.add_argument(
        "--fail-on-qa-issues",
        action="store_true",
        help="Return non-zero when WSTG static QA reports blocking errors.",
    )
    parser.add_argument(
        "--max-document-chars",
        type=int,
        default=60000,
        help="Warn when a generated WSTG methodology document exceeds this size.",
    )
    args = parser.parse_args(argv)

    if args.qa_only:
        if args.profile != "wstg":
            parser.error("--qa-only is only supported with --profile wstg")
        output_dir = args.output_dir or DEFAULT_WSTG_OUTPUT_DIR
        qa_result = qa_wstg_preprocessed_corpus(
            output_dir,
            max_document_chars=args.max_document_chars,
        )
        print(
            json.dumps(
                {
                    "profile": "wstg",
                    "output_dir": str(output_dir),
                    "qa": qa_result.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        if args.fail_on_qa_issues and not qa_result.passed:
            return 1
        return 0

    if not args.sources:
        parser.error("sources are required unless --qa-only is set")

    if args.profile == "wstg":
        output_dir = args.output_dir or DEFAULT_WSTG_OUTPUT_DIR
        result = preprocess_wstg_for_lightrag(
            args.sources,
            output_dir,
            debug_facets=args.debug_facets,
        )
    elif args.profile == "writeup":
        output_dir = args.output_dir or DEFAULT_WRITEUP_OUTPUT_DIR
        result = preprocess_writeups_for_lightrag(args.sources, output_dir)
    else:
        output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
        result = preprocess_sources_for_lightrag(args.sources, output_dir)
    if args.profile == "wstg":
        relation_count = sum(
            1
            for fragment in result.fragments
            if _is_wstg_relation_candidate(
                fragment,
                result.fragment_facets.get(fragment.fragment_id, []),
            )
        )
    elif args.profile == "writeup":
        relation_count = sum(
            1
            for fragment in result.fragments
            if _is_writeup_relation_candidate(fragment)
        )
    else:
        relation_count = sum(1 for fragment in result.fragments if is_relation_fragment(fragment))
    summary = {
        "profile": args.profile,
        "fragments": len(result.fragments),
        "relation_briefs": relation_count,
        "generated_files": [path.as_posix() for path in result.generated_files],
    }
    qa_result = None
    if args.profile == "wstg" and args.qa:
        qa_result = qa_wstg_preprocessed_corpus(
            output_dir,
            max_document_chars=args.max_document_chars,
        )
        summary["qa"] = qa_result.to_dict()
    print(json.dumps(summary, indent=2, sort_keys=True))
    if qa_result is not None and args.fail_on_qa_issues and not qa_result.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
