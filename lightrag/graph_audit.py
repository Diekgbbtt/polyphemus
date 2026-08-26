from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib import error as urlerror
from urllib import request as urlrequest

from lightrag.ontology import ENTITY_TYPES


_GRAPHML_NS = {"g": "http://graphml.graphdrawing.org/xmlns"}
_CANONICAL_BY_NORMALIZED_TYPE = {
    re.sub(r"[^a-z0-9]+", "", entity_type.lower()): entity_type
    for entity_type in ENTITY_TYPES
}
_CANONICAL_BY_NORMALIZED_TYPE.update(
    {
        "environmentalcondition": "PreconditionEnvironment",
        "condition": "PreconditionEnvironment",
        "configurationartifact": "Artifact",
        "configurationartifacts": "Artifact",
        "defensivetechnology": "DefensiveControl",
        "defense": "DefensiveControl",
        "asymmetricencryption": "TechnologyStack",
        "asymmetricencryptions": "TechnologyStack",
        "messagehash": "TechnologyStack",
        "messagehashes": "TechnologyStack",
        "passwordhashing": "TechnologyStack",
        "role": "AttackerCapability",
        "roles": "AttackerCapability",
        "symmetrickeyalgorithm": "TechnologyStack",
        "symmetrickeyalgorithms": "TechnologyStack",
        "framework": "TechnologyStack",
        "frameworks": "TechnologyStack",
        "vulnerability": "VulnerabilityClass",
        "weakness": "VulnerabilityClass",
        "technique": "AttackTechnique",
        "payload": "PayloadPattern",
        "signal": "ObservableSignal",
        "dangerousapi": "TechnologyStack",
        "dangerousapis": "TechnologyStack",
        "dangerousfunction": "TechnologyStack",
        "dangerousfunctions": "TechnologyStack",
        "integrationmethod": "TechnologyStack",
        "integrationmethods": "TechnologyStack",
        "location": "Artifact",
        "locations": "Artifact",
        "sink": "TechnologyStack",
        "sinks": "TechnologyStack",
        "operatingsystemcommand": "PayloadPattern",
        "operatingsystemcommands": "PayloadPattern",
        "privilegedfunctionality": "AttackGoal",
        "privilegedfunctionalities": "AttackGoal",
        "selfassessmentquestionnaire": "Artifact",
        "selfassessmentquestionnaires": "Artifact",
        "securityheader": "DefensiveControl",
        "securityheaders": "DefensiveControl",
        "header": "DefensiveControl",
        "headers": "DefensiveControl",
        "specialcharacter": "PayloadPattern",
        "specialcharacters": "PayloadPattern",
        "standard": "DefensiveControl",
        "standards": "DefensiveControl",
        "targetenvironment": "PreconditionEnvironment",
        "targetenvironments": "PreconditionEnvironment",
        "targetsystem": "TechnologyStack",
        "targetsystems": "TechnologyStack",
        "directive": "Artifact",
        "directives": "Artifact",
        "pathpattern": "PayloadPattern",
        "pathpatterns": "PayloadPattern",
        "attackmethod": "AttackTechnique",
        "attackmethods": "AttackTechnique",
        "defensivecontrolbypass": "AttackTechnique",
        "defensivecontrolbypasses": "AttackTechnique",
        "attackvector": "AttackTechnique",
        "attackvectors": "AttackTechnique",
        "attacktechniques": "AttackTechnique",
        "detectionmethod": "AttackTechnique",
        "detectionmethods": "AttackTechnique",
        "testmethodology": "AttackTechnique",
        "testmethodologies": "AttackTechnique",
        "testingmethodology": "AttackTechnique",
        "testingmethodologies": "AttackTechnique",
        "methodology": "AttackTechnique",
        "testprocedure": "AttackTechnique",
        "testprocedures": "AttackTechnique",
        "category": "Artifact",
        "methodologystep": "AttackTechnique",
        "methodologysteps": "AttackTechnique",
        "technicalcomponent": "TechnologyStack",
        "technicalcomponents": "TechnologyStack",
        "attacksurface": "PreconditionEnvironment",
        "attacksurfaces": "PreconditionEnvironment",
        "targetobject": "Artifact",
        "targetobjects": "Artifact",
        "dangerousinputcharacter": "PayloadPattern",
        "dangerousinputcharacters": "PayloadPattern",
        "payloadpatternelement": "PayloadPattern",
        "payloadpatternelements": "PayloadPattern",
        "logicaloperator": "PayloadPattern",
        "logicaloperators": "PayloadPattern",
        "cookienameprefix": "DefensiveControl",
        "cookienameprefixes": "DefensiveControl",
        "samesiteattribute": "DefensiveControl",
        "samesiteattributes": "DefensiveControl",
        "passwordcrackingtechnique": "AttackTechnique",
        "passwordcrackingtechniques": "AttackTechnique",
        "sqlserveradministrativeprivilege": "AttackerCapability",
        "sqlserveradministrativeprivileges": "AttackerCapability",
        "sqlserverautomationobjectcreationfunction": "TechnologyStack",
        "sqlserverautomationobjectcreationfunctions": "TechnologyStack",
        "sqlserverautomationobjectdestructionfunction": "TechnologyStack",
        "sqlserverautomationobjectdestructionfunctions": "TechnologyStack",
        "sqlserverautomationobjectmethodinvocationfunction": "TechnologyStack",
        "sqlserverautomationobjectmethodinvocationfunctions": "TechnologyStack",
        "sqlserverbuiltinfunction": "TechnologyStack",
        "sqlserverbuiltinfunctions": "TechnologyStack",
        "sqlserverextendedprocedurelibrary": "Artifact",
        "sqlserverextendedprocedurelibraries": "Artifact",
        "sqlserverextendedstoredprocedure": "TechnologyStack",
        "sqlserverextendedstoredprocedures": "TechnologyStack",
        "sqlserverstoredprocedure": "TechnologyStack",
        "sqlserverstoredprocedures": "TechnologyStack",
        "sqlserverversionvariable": "ObservableSignal",
        "sqlserverversionvariables": "ObservableSignal",
        "tool": "TechnologyStack",
        "tools": "TechnologyStack",
        "title": "Artifact",
        "titles": "Artifact",
        "serviceendpoint": "TechnologyStack",
        "serviceendpoints": "TechnologyStack",
        "technicalattribute": "Artifact",
        "technicalattributes": "Artifact",
        "process": "TechnologyStack",
        "processes": "TechnologyStack",
        "action": "TechnologyStack",
        "actions": "TechnologyStack",
        "actor": "AttackerCapability",
        "actors": "AttackerCapability",
        "attackscenario": "AttackTechnique",
        "attackscenarios": "AttackTechnique",
        "attacktechniqueset": "AttackTechnique",
        "attacktechniquesets": "AttackTechnique",
        "observable": "ObservableSignal",
        "observables": "ObservableSignal",
        "observablesource": "TechnologyStack",
        "observablesources": "TechnologyStack",
        "weaknessclass": "VulnerabilityClass",
        "weaknessclasses": "VulnerabilityClass",
        "wstgcategory": "Artifact",
        "wstgcategories": "Artifact",
        "alternativehttpmethodheader": "PayloadPattern",
        "configparameter": "DefensiveControl",
        "cspdirective": "DefensiveControl",
        "cspdirectivevalue": "DefensiveControl",
        "dangerousvalue": "PayloadPattern",
        "defensivecontrolimplementationerror": "VulnerabilityClass",
        "defensivecontrolmethodology": "DefensiveControl",
        "defensivecontrolgap": "PreconditionEnvironment",
        "guidingstandard": "DefensiveControl",
        "httpsecurityheader": "DefensiveControl",
        "httpmethod": "TechnologyStack",
        "measure": "Artifact",
        "payloadformat": "PayloadPattern",
        "policyconfiguration": "DefensiveControl",
        "scenariotitle": "Artifact",
        "targetdata": "Artifact",
        "targetresource": "Artifact",
        "testcase": "Artifact",
        "attacktargetenvironment": "PreconditionEnvironment",
        "categorization": "Artifact",
        "defensivecontrolcategory": "Artifact",
        "inputvector": "Artifact",
        "interfaceelement": "Artifact",
        "responsestatuscode": "ObservableSignal",
        "workflow": "AttackTechnique",
        "application": "TechnologyStack",
        "methodologyname": "AttackTechnique",
        "parametertype": "Artifact",
        "target": "Artifact",
        "targetentity": "Artifact",
        "techniquetarget": "Artifact",
        "technicalcontext": "PreconditionEnvironment",
        "wstgscenario": "Artifact",
        "attackmethodology": "AttackTechnique",
        "defensivecontrolattempt": "DefensiveControl",
        "fingerprintmethod": "AttackTechnique",
        "function": "TechnologyStack",
        "attackmitigationpattern": "DefensiveControl",
        "attr": "PayloadPattern",
        "escapecharacter": "PayloadPattern",
        "techonologystack": "TechnologyStack",
        "attacktarget": "AttackGoal",
        "componentof": "Artifact",
        "dataasset": "Artifact",
        "document": "Artifact",
        "entitytype": "PreconditionEnvironment",
        "procedure": "AttackTechnique",
    }
)
_EMBEDDED_TYPE_MARKER_RE = re.compile(r"<\|(?P<entity_type>[A-Za-z]+)\|>")

DEFAULT_NOISE_PATTERNS: tuple[str, ...] = (
    r"^PreconditionEnvironment$",
    r"^TechnologyStack$",
    r"^DefensiveControl$",
    r"^VulnerabilityClass$",
    r"^AttackGoal$",
    r"^AttackerCapability$",
    r"^AttackTechnique$",
    r"^PayloadPattern$",
    r"^Artifact$",
    r"^ObservableSignal$",
    (
        r"^(?:PreconditionEnvironment|TechnologyStack|DefensiveControl|"
        r"VulnerabilityClass|AttackGoal|AttackerCapability|AttackTechnique|"
        r"PayloadPattern|Artifact|ObservableSignal)>$"
    ),
    r"\bwstg\b",
    r"\blightrag\b",
    r"#f\d+\b",
    r"\bcheat\s*sheet\b",
    r"\bcheatsheet\b",
    r"\bowasp\s+testing\s+guide\b",
    r"\bowasp\s+api\s+security\s+top\s+10\b",
    r"^owasp$",
    r"^owasp\s+poland\s+conference$",
    r"\bmozilla\s+javascript\s+guide\b",
    r"\bwikipedia\b",
    r"\bsqlmap\b",
    r"\bwfuzz\b",
    r"\bburp(?:\s+suite)?\b",
    r"\bzap\b",
    r"\bnetcat\b",
    r"\bexample\.(?:com|org|net)\b",
    r"\btesterserver\b",
    r"\bpayloadsallthethings\b",
    r"\bautomatic\s+tool\b",
    r"^application/system$",
    r"^automated\s+testing\s+tool$",
    r"^contains$",
    r"^adventure$",
    r"^atari$",
    r"\bmethodology\s+scope\b",
    r"\bmethodology\s+scenario\b",
    r"^Testing\s+WebSockets$",
    r"^Concept\s+Testing\s+WebSockets$",
    r"^Overview$",
    r"^Digital Identity$",
    r"^Attack Methods$",
    r"^Relation Briefs$",
    r"\bprovenance\s+metadata\b",
    r"\bmethodology\s+entities\b",
    r"\bvulnerability\s+framing\b",
    r"\bcore\s+testing\s+purpose\b",
    r"\bxpath\s+attack\s+pattern\b",
    r"^attacker\s+capability$",
    r"^observable\s+signal$",
    r"^relationship_keywords$",
    r"^misuse$",
    r"^provides\s+baseline$",
    r"^uses$",
    r"^applies$",
    r"^supports$",
    r"^enabled\s+by$",
    r"^(?:enables|evaluates|exploits|conflicts\s+with|accesses|maps\s+to)\b",
    r"^(?:Targets|Relies\s+on|Used\s+in|Issues|Utilizes|Handles)\b",
    r"^exploits$",
    r"^enables$",
    r"^targets$",
    r"^requires$",
    r"^prevents$",
    r"^determines$",
    r"^affects$",
    r"^enables\s+account\s+enumeration$",
    r"^pathpattern$",
    r"^ietf$",
    r"^input\s+validation\s+chapter$",
    r"^luca\s+carettoni$",
    r"^mario\s+heiderich$",
    r"^medium$",
    r"^payment\s+card\s+industry$",
    r"^stefano\s+di\s+paola$",
    r"^stefano\s+di\s+paulo$",
    r"^target\s+system$",
    r"^warren\s+robinett$",
    r"^rips\s+tech$",
    r"^Attacker$",
    r"^Source$",
    r"^Target$",
    r"^Name$",
    r"^Type$",
    r"^Test\s+Objectives$",
    r"^Intrusion\s+Testing$",
    r"^Authentication$",
    r"^Account$",
    r"^true$",
    r"^Test\s+Procedure$",
    r"^Performance\s+and\s+Scaling\s+Benefits$",
    r"^looser\s+consistency\s+checks\s+compared\s+to$",
    r"^Rfc\d+$",
    r"^Acme$",
    r"^Alice$",
    r"^HTTP$",
    r"^User\s+Input$",
    r"^Babou(?:ne)?$",
    r"^Babylon$",
    r".+\s+Concept$",
    r".+\s+Testing\s+Category$",
    r"^security\s+testing$",
    r"^security\s+testing\s+methodologies$",
    r"^secure\s+testing\s+(?:process|methodology)$",
    r"^Security\s+threats$",
    r"^vulnerability\s+class\s+missing$",
    r"^belongs\s+to$",
    r"^None\s+to\s+extract$",
    r"^Other$",
    (
        r"^(?:PreconditionEnvironment|TechnologyStack|DefensiveControl|"
        r"VulnerabilityClass|AttackGoal|AttackerCapability|AttackTechnique|"
        r"PayloadPattern|Artifact|ObservableSignal):\s+.+"
    ),
)

DEFAULT_EXPECTED_ENTITY_TYPES: dict[str, str] = {
    "SQL Injection": "VulnerabilityClass",
    "Blind SQL Injection": "VulnerabilityClass",
    "NoSQL Injection": "VulnerabilityClass",
    "LDAP Injection": "VulnerabilityClass",
    "XML Injection": "VulnerabilityClass",
    "Xml Injection": "VulnerabilityClass",
    "XPath Injection": "VulnerabilityClass",
    "Command Injection": "VulnerabilityClass",
    "Path Traversal": "VulnerabilityClass",
    "Directory Traversal File Include": "VulnerabilityClass",
    "Directory Traversal": "VulnerabilityClass",
    "File Include": "VulnerabilityClass",
    "Input Vector": "Artifact",
    "Input Vectors Enumeration": "AttackTechnique",
    "Path Traversal/File Include": "VulnerabilityClass",
    "Testing Techniques": "AttackTechnique",
    "Identify Input Handling Functions": "AttackTechnique",
    "Methodology for Testing Directory Traversal File Include": "AttackTechnique",
    "Find Path Traversal Patterns": "AttackTechnique",
    "Find Path Traversal Flaws": "AttackTechnique",
    "Authorization Testing": "AttackTechnique",
    "Regex Pattern for Path Traversal": "PayloadPattern",
    "Online Code Search Engine": "TechnologyStack",
    "Web Server": "TechnologyStack",
    "Loading Dynamic Files": "AttackTechnique",
    "Dynamic File Loading": "AttackTechnique",
    "Server-Side Request Forgery": "VulnerabilityClass",
    "Input Validation": "DefensiveControl",
    "Web Application Firewall": "DefensiveControl",
    "Intrusion Prevention System": "DefensiveControl",
    "Account Access": "AttackGoal",
    "Device Access": "AttackGoal",
    "Error Message": "ObservableSignal",
    "Database Error Messages": "ObservableSignal",
    "Invalid Authentication": "ObservableSignal",
    "HTTP Header Injection": "AttackTechnique",
    "IP Spoofing Technique": "AttackTechnique",
    "Authorization Bypass Use Case": "AttackTechnique",
    "HTTP Request": "Artifact",
    "Admin Menu": "Artifact",
    "User Role": "AttackerCapability",
    "Profile Parameter": "Artifact",
    "Privilege Escalation Vulnerability": "VulnerabilityClass",
    "Error Message (Misleading)": "ObservableSignal",
    "client_id": "Artifact",
    "Client_id": "Artifact",
    "authorization_endpoint": "TechnologyStack",
    "token_endpoint": "TechnologyStack",
    "authorization_code_exchange": "TechnologyStack",
    "OAuth Authorization Server (AS)": "TechnologyStack",
    "Client Application": "TechnologyStack",
    "URL Validation": "DefensiveControl",
    "Anti-CSRF protection": "DefensiveControl",
    "Code_verifier": "Artifact",
    "Clickjacking": "AttackTechnique",
    "Clickjacking Attacks": "AttackTechnique",
    "clickjacking": "AttackTechnique",
    "Public clients": "TechnologyStack",
    "Redirect URI": "Artifact",
    "Cross-Site Request Forgery Attack": "AttackTechnique",
    "Cross-Site Request Forgery": "VulnerabilityClass",
    "Cross-Site Scripting": "VulnerabilityClass",
    "invalid_access_token": "ObservableSignal",
    "expired_refresh_token": "ObservableSignal",
    "invalid_redirect_uri": "ObservableSignal",
    "invalid_client_secret": "ObservableSignal",
    "Insecure Token Storage Scenarios": "VulnerabilityClass",
    "Single-Page Application": "TechnologyStack",
    "Access Token Injection": "AttackTechnique",
    "Authz Flow": "TechnologyStack",
    "OAuth2.1": "TechnologyStack",
    "Access Token Leakage Risk": "VulnerabilityClass",
    "Machine-to-machine communication": "PreconditionEnvironment",
    "Deprecated grant types": "VulnerabilityClass",
    "CORS relaxation": "PreconditionEnvironment",
    "Authorization Code flow with PKCE": "TechnologyStack",
    "Limited input capability devices": "PreconditionEnvironment",
    "Access token expiration": "DefensiveControl",
    "Arbitrary client": "AttackerCapability",
    "Confidential clients": "TechnologyStack",
    "Same-Origin Policy relaxation": "PreconditionEnvironment",
    "Authorization Code grant": "TechnologyStack",
    "client_id + client_secret": "Artifact",
    "ROPC grant": "TechnologyStack",
    "resource owner password": "TechnologyStack",
    "code_challenge=sha256(xyz)": "PayloadPattern",
    "response_type=token": "PayloadPattern",
    "ROPC": "TechnologyStack",
    "Client Credentials grant": "TechnologyStack",
    "leak vector": "VulnerabilityClass",
    "response_mode=form_post OR URL fragment": "PayloadPattern",
    "Single Quote": "PayloadPattern",
    "Semicolon": "PayloadPattern",
    "Null Byte": "PayloadPattern",
    "Pipe": "PayloadPattern",
    "Pipe Symbol": "PayloadPattern",
    "Os Command Filters": "DefensiveControl",
    "OS Command Filters": "DefensiveControl",
    "Operating System Command Filters": "DefensiveControl",
    "Traditional SQL Database": "TechnologyStack",
    "Html Code": "Artifact",
    "SAXParser": "TechnologyStack",
    "DocumentBuilder": "TechnologyStack",
    "Transformer": "TechnologyStack",
    "XMLReader": "TechnologyStack",
    "XMLInput": "TechnologyStack",
    "Api Route Locations": "Artifact",
    "Hide Schema Details": "DefensiveControl",
    "Hide Schema Details From Client Errors": "DefensiveControl",
    "Denylist": "DefensiveControl",
    "Authentication Form": "DefensiveControl",
    "Authentication Control": "DefensiveControl",
    "Application Source Code": "Artifact",
    "Password Storage": "DefensiveControl",
    "Account Credentials": "AttackerCapability",
    "Cache Directives": "DefensiveControl",
    "Normalization Mismatch": "PreconditionEnvironment",
    "OrderDatabase": "TechnologyStack",
    "Order Database": "TechnologyStack",
    "PciDss": "DefensiveControl",
    "X-Remote-IP": "PayloadPattern",
    "User Account": "Artifact",
    "Bypassing Session Management Schema": "AttackTechnique",
    "Session Variable": "Artifact",
    "Application Logic Checks": "DefensiveControl",
    "Business Logic": "PreconditionEnvironment",
    "Manual Testing": "AttackTechnique",
    "Misuse Case": "AttackTechnique",
    "Diagram": "Artifact",
    "Process Execution Analysis": "AttackTechnique",
    "Reordering Requests": "AttackTechnique",
    "Manipulating State Identifiers": "AttackTechnique",
    "Application-Level Defenses": "DefensiveControl",
    "Transaction Limit": "DefensiveControl",
    "Access Controls": "DefensiveControl",
    "HTTP Traffic": "ObservableSignal",
    "Log System": "DefensiveControl",
    "Work Flow Vulnerability": "VulnerabilityClass",
    "Invalid State Identifier": "PayloadPattern",
    "Skipping Steps": "AttackTechnique",
    "multi-step Workflow": "TechnologyStack",
    "Manipulating Status Fields": "AttackTechnique",
    "Attacker-Controlled Script Injection": "AttackTechnique",
    "Test Defenses Against Application Misuse": "Artifact",
    "User-controlled input": "Artifact",
    "Fuzzing session": "AttackTechnique",
    "Server-Side File Processing": "TechnologyStack",
    "DefensiveControl Detection": "ObservableSignal",
    "Test Payment Functionality": "Artifact",
    "Keeping a Record": "DefensiveControl",
    "Arbitrary Donation Entry": "PayloadPattern",
    "Valid Quantity Dropdown": "Artifact",
    "Validation Check on Donation": "DefensiveControl",
    "Cancellation and Refund": "DefensiveControl",
    "Payment Logic": "TechnologyStack",
    "Bypassing Application-Level Defenses": "AttackTechnique",
    "Uploaded File": "Artifact",
    "Sensitive System File": "Artifact",
    "Directory Traversal Sequence": "PayloadPattern",
    ".htaccess Configuration File": "Artifact",
    "Archive Extraction": "AttackTechnique",
    "Sensitive File Contents": "Artifact",
    "Back-end API": "TechnologyStack",
    "Configuration Files": "Artifact",
    "Backup Site Data": "Artifact",
    "Success.php": "Artifact",
    "Failure.php": "Artifact",
    "Discount Code Application": "AttackTechnique",
    "Minimum Basket Value": "DefensiveControl",
    "Lack of Input Validation": "PreconditionEnvironment",
    "disclosure of session cookies": "AttackGoal",
    "phishing attack": "AttackTechnique",
    "bypass access control": "AttackGoal",
    "UI manipulation": "AttackTechnique",
    "attack chaining": "AttackTechnique",
    "XMLHttpRequest URL": "TechnologyStack",
    "Script src Sink": "TechnologyStack",
    "iframe.src": "TechnologyStack",
    "iframe src Sink": "TechnologyStack",
    "a.href": "TechnologyStack",
    "attacker-controlled URL": "PayloadPattern",
    "attacker-controlled CSS": "PayloadPattern",
    "img.src": "TechnologyStack",
    "malicious iframe": "PayloadPattern",
    "external resource": "Artifact",
    "remote image from attacker": "Artifact",
    "script.src": "TechnologyStack",
    "link.href": "TechnologyStack",
    "xhr.url": "TechnologyStack",
    "malicious object content": "PayloadPattern",
    "object.data": "TechnologyStack",
    "`Access-Control-Allow-Credentials: true` Header": "DefensiveControl",
    "iframe with sandbox attribute": "DefensiveControl",
    "flash.external.ExternalInterface.call": "TechnologyStack",
    "HTML TextField": "TechnologyStack",
    "Browser Developer Console": "TechnologyStack",
    "form Element": "TechnologyStack",
    "Content Security Policy": "DefensiveControl",
    "textarea Element": "TechnologyStack",
    "Browser Redirection": "AttackTechnique",
    "`location.hash`": "TechnologyStack",
    "InnerHTML": "TechnologyStack",
    "Document.write()": "TechnologyStack",
    "Access Control Bypass": "AttackGoal",
    "LoadVars": "TechnologyStack",
    "Failure to Validate Origin Header": "VulnerabilityClass",
    "wss:// or ws://": "PreconditionEnvironment",
    "URL Fragment Identifier": "Artifact",
    "* wildcard header": "PayloadPattern",
    "Access-Control-Allow-Origin": "DefensiveControl",
    "Access-Control-Allow-Credentials": "DefensiveControl",
    "Access-Control-Allow-Method": "DefensiveControl",
    "Access-Control-Allow-Headers": "DefensiveControl",
    "Access-Control-Max-Age": "DefensiveControl",
    "Access-Control-Expose-Headers": "DefensiveControl",
    "Access-Control-Allow-Method header": "DefensiveControl",
    "Cross-Site Scripting (XSS) Attack": "AttackTechnique",
    "Proxy Server": "TechnologyStack",
    "Injected Content from attacker.bar": "PayloadPattern",
    "Invalid CORS Configuration": "VulnerabilityClass",
    "FlashVar destination validation failure": "VulnerabilityClass",
    "HTML page (JavaScript)": "TechnologyStack",
    "browser-side JavaScript": "TechnologyStack",
    "XSF": "VulnerabilityClass",
    "ActionScript Process": "TechnologyStack",
    "Network Tab (Developer Tools)": "TechnologyStack",
    "Web Browser": "TechnologyStack",
    "Clickjacking Detection": "ObservableSignal",
    "Half-duplex Behavior": "PreconditionEnvironment",
    "WebSockets": "TechnologyStack",
    "false origin check": "PreconditionEnvironment",
    "Web Crypto API": "TechnologyStack",
    "Insecure Data Storage": "VulnerabilityClass",
    "XSS Vulnerability": "VulnerabilityClass",
    "Unprotected Browser Storage": "VulnerabilityClass",
    "CryptoKeys": "Artifact",
    "encryptable_private_key_material": "Artifact",
    "phishing page": "Artifact",
    "target=\"_blank\"": "PreconditionEnvironment",
    "original page": "Artifact",
    "input validation": "DefensiveControl",
    "user-controlled URL insertion": "PayloadPattern",
    "script injection": "AttackTechnique",
    "window.opener.location redirection": "AttackTechnique",
    "HTML5 Application/JSON MIME Type": "PreconditionEnvironment",
    "Trust Domain": "PreconditionEnvironment",
    "Untrusted Domain": "PreconditionEnvironment",
    "trusted domain filter": "DefensiveControl",
    "origin validation check": "DefensiveControl",
    "eval() usage": "TechnologyStack",
    "trusted domains list": "DefensiveControl",
    "Invalid Input Validation": "PreconditionEnvironment",
    "innerHTML injection": "AttackTechnique",
    "Secure Messaging Validation": "DefensiveControl",
    "* wildcard domain": "PayloadPattern",
    "Security Validation": "DefensiveControl",
    "lack of origin check": "PreconditionEnvironment",
    "extractable flag": "DefensiveControl",
    "target=\"_blank\" attribute": "PreconditionEnvironment",
    "rel=\"noopener noreferrer\" attribute": "DefensiveControl",
    "script tag": "TechnologyStack",
    "compromised third-party site": "PreconditionEnvironment",
    "compromised domain": "PreconditionEnvironment",
    "ng-bind": "DefensiveControl",
    "v-html": "TechnologyStack",
    "ng-bind-html": "TechnologyStack",
    "Angular sandbox": "DefensiveControl",
    "Angular `ng-bind-html`": "TechnologyStack",
    "Vue.js `v-html`": "TechnologyStack",
    "Vue.js v-html": "TechnologyStack",
    "Sanitization Library": "DefensiveControl",
    "Sanitization Library (e.g., DOMPurify)": "DefensiveControl",
    "Offline Compilation": "DefensiveControl",
    "v-text": "DefensiveControl",
    "Sensitive File Extensions": "Artifact",
    "Compressed Archive Files": "Artifact",
    "Office Documents": "Artifact",
    "Backup Files": "Artifact",
    "NIST's National Checklist Program": "DefensiveControl",
    "Web Server Content": "Artifact",
    "CVE-1999-0449": "Artifact",
    "IIS Server Software": "TechnologyStack",
    "Server Overload": "ObservableSignal",
    "CAN-2002-1744": "Artifact",
    "Proper Configuration": "DefensiveControl",
    "Creating and Maintaining Architecture": "DefensiveControl",
    "Generic Server Installations": "PreconditionEnvironment",
    "Reviewing Configurations": "AttackTechnique",
    "Security of Whole Architecture": "DefensiveControl",
    "Specific Site Tasks": "PreconditionEnvironment",
    "Backend Database Configuration": "DefensiveControl",
    "Authentication System Configuration": "DefensiveControl",
    "Removing Inappropriate Server Modules": "DefensiveControl",
    "Server Software Running With Minimal Privileges": "DefensiveControl",
    "Default and Known Files": "Artifact",
    "CAN-2002-1630": "Artifact",
    "Production Environments": "PreconditionEnvironment",
    "CAN-2003-1172": "Artifact",
    "Debugging Code or Extensions": "Artifact",
    "Authentication Bypass": "AttackGoal",
    "Traffic Proxying": "AttackGoal",
    "Custom HTTP Header Injection": "AttackTechnique",
    "Access Control Policy": "DefensiveControl",
    "Arbitrary HTTP Methods": "AttackTechnique",
    "User Accounts": "Artifact",
    "CORS Preflight": "TechnologyStack",
    "OPTIONS Preflight": "TechnologyStack",
    "RESTful Applications": "TechnologyStack",
    "Program Configuration": "Artifact",
    "Allowed Methods Header": "ObservableSignal",
    "Custom HTTP Headers": "PayloadPattern",
    "DELETE": "TechnologyStack",
    "Input Validation Weakness": "VulnerabilityClass",
    "CONNECT": "TechnologyStack",
    "Information Disclosure": "VulnerabilityClass",
    "ServerBehavior": "PreconditionEnvironment",
    "Reverse Proxy Bypass": "AttackTechnique",
    "OPTIONS": "TechnologyStack",
    "TRACE": "TechnologyStack",
    "Unknown HTTP Method Support": "PreconditionEnvironment",
    "WAF Evasion Strategy": "AttackTechnique",
    "Absence of HSTS header": "PreconditionEnvironment",
    "Information Exposure": "VulnerabilityClass",
    "Invalid Certificate Acceptance": "VulnerabilityClass",
    "World-readable permissions": "PreconditionEnvironment",
    "Non-existing Resource": "PreconditionEnvironment",
    "Cloud Provider Service": "TechnologyStack",
    "domain (primary)": "Artifact",
    "victim.com": "Artifact",
    "domain (secondary)": "Artifact",
    "victimotherdomain.com": "Artifact",
    "CNAME Record": "Artifact",
    "Fingerprint-based detection tool": "TechnologyStack",
    "Test Objectives: Enumerate Subdomains": "AttackTechnique",
    "External Resource (expired/deprovisioned)": "PreconditionEnvironment",
    "Non-standard Filename": "Artifact",
    "Legacy Filename (8.3 Format)": "Artifact",
    "Long Filename": "Artifact",
    "Improper File Extension Handling": "VulnerabilityClass",
    "Administrator Functionality": "TechnologyStack",
    "Site Design and Layout": "Artifact",
    "Data Manipulation": "AttackGoal",
    "Configuration Changes": "AttackGoal",
    "Malicious Internal Actor": "AttackerCapability",
    "Incorrect Protocol Usage": "VulnerabilityClass",
    "Read Unauthorized Data": "AttackGoal",
    "Upload Arbitrary File": "AttackTechnique",
    "Vulnerable DNS Resource Record": "VulnerabilityClass",
    "DNS Zone Control": "AttackGoal",
    "CDN": "TechnologyStack",
    "Wildcard Source": "PayloadPattern",
    "Missing frame-ancestors directive": "VulnerabilityClass",
    "Report-Only CSP mode": "PreconditionEnvironment",
    "Partial Wildcard Source Such as `*.cdn.com`": "PayloadPattern",
    "Cross Site Scripting Vulnerability": "VulnerabilityClass",
    "Content-Security-Policy (Enforced)": "DefensiveControl",
    "Testing Thoroughness": "AttackTechnique",
    "nonces": "DefensiveControl",
    "inline scripts": "PayloadPattern",
    "dynamic code execution": "AttackTechnique",
    "observed CSP violations": "ObservableSignal",
    "Methodology for Test Path Confusion": "AttackTechnique",
    "Path misconfiguration": "VulnerabilityClass",
    "prerequisites": "PreconditionEnvironment",
    "defenses": "DefensiveControl",
    "detections": "ObservableSignal",
    "payload examples": "PayloadPattern",
    "observable signals": "ObservableSignal",
    "HTTP Header (invalid or typos)": "VulnerabilityClass",
    "HTTP Header (overpermissive)": "VulnerabilityClass",
    "HTTP Header (duplicate)": "VulnerabilityClass",
    "HTTP Header (deprecated)": "VulnerabilityClass",
    "HTTP Security Policy Scheme (Header vs Meta)": "DefensiveControl",
    "Missing or Invalid Security Header": "VulnerabilityClass",
    "Browsers Ignore Headers": "ObservableSignal",
    "Security Risk": "VulnerabilityClass",
    "Use of Legacy Header X-Permitted-Cross-Domain-Policies": "VulnerabilityClass",
    "Echo Page": "Artifact",
    "Duplicate or Conflicting Headers": "VulnerabilityClass",
    "PHP Info Page": "Artifact",
    "Public Key Infrastructure": "TechnologyStack",
    "Cipher Suite (insecure settings)": "VulnerabilityClass",
    "TLS": "TechnologyStack",
    "BEAST": "AttackTechnique",
    "CRIME": "AttackTechnique",
    "LOGJAM": "AttackTechnique",
    "developer tools": "TechnologyStack",
    "hostname (SAN value)": "Artifact",
    "valid certificate": "DefensiveControl",
    "Block Cipher CBC Mode": "TechnologyStack",
    "Secure Cookie Flag (": "DefensiveControl",
    "Plain Text Credentials": "Artifact",
    "Secure flag)": "DefensiveControl",
    "Untitled Technique (using curl via HTTP)": "AttackTechnique",
    "Source Code or Configuration File": "Artifact",
    "Form based authentication credentials": "Artifact",
    "Untitled Technique (log or source code search)": "AttackTechnique",
    "Hardcoded Credentials": "Artifact",
    "Sensitive Data (e.g., credit card details)": "Artifact",
    "PII (Personally Identifiable Information)": "Artifact",
    "Recommended Encryption": "DefensiveControl",
    "SecureRandom": "TechnologyStack",
    "ECB Mode": "VulnerabilityClass",
    "Functionality": "Artifact",
    "RBAC Setup": "DefensiveControl",
    "RBAC": "DefensiveControl",
    "Vulnerable Role": "VulnerabilityClass",
    "Role Definitions": "DefensiveControl",
    "MFA": "DefensiveControl",
    "Identify Requirements": "DefensiveControl",
    "Delete Users Dropdown": "Artifact",
    "Resource Ownership Management": "DefensiveControl",
    "Authorization Verification": "DefensiveControl",
    "Brute-Force Testing Tool": "TechnologyStack",
    "Tool (not explicitly required by system taxonomies but relevant in context)": "TechnologyStack",
    "Default System Accounts": "Artifact",
    "Authentication Interface": "TechnologyStack",
    "Test Accounts": "Artifact",
    "Predictable Username Patterns": "PayloadPattern",
    "Error Message \"Valid username...\"": "ObservableSignal",
    "Historical Snapshots": "Artifact",
    "Web Server Identification": "ObservableSignal",
    "Apache mod_headers Module": "TechnologyStack",
    "web spiders/robots/crawlers": "TechnologyStack",
    "User-Agent": "Artifact",
    "robots.txt directives": "Artifact",
    "Public Key Metadata Fields": "Artifact",
    "Key ID": "Artifact",
    "Key Fingerprint": "Artifact",
    "Key Algorithm": "TechnologyStack",
    "Key Size": "Artifact",
    "Key Creation Date": "Artifact",
    "Key Expiration Date": "Artifact",
    "User IDs": "Artifact",
    "Webpage": "Artifact",
    "Webserver": "TechnologyStack",
    "site Operator": "PayloadPattern",
    "Web Search Indexing": "PreconditionEnvironment",
    "Attack Surface Identification": "AttackTechnique",
    "HTTP/HTTPS Service": "TechnologyStack",
    "Web Application Discovery": "AttackTechnique",
    "Domain": "Artifact",
    "Authoritative Nameserver": "TechnologyStack",
    "Domain Discovery": "AttackTechnique",
    "Web Application Discovery Process": "AttackTechnique",
    "Subdomains Discovery": "AttackTechnique",
    "Review Web Page Content": "AttackTechnique",
    "Download Generated Files": "AttackTechnique",
    "Metadata Fields (Producer, Creator, Application, Creation Tool, Library Version)": "Artifact",
    "Metadata Fields": "Artifact",
    "Frontend Javascript Code": "Artifact",
    "Office Documents Metadata Fields": "Artifact",
    "Minified Assets": "Artifact",
    "Identify Application Entry Points": "AttackTechnique",
    "RAILSgoat": "TechnologyStack",
    "Request Body": "Artifact",
    "HTTP HEAD Method": "TechnologyStack",
    "Path Approach": "AttackTechnique",
    "Data Flow Approach": "AttackTechnique",
    "Race Approach": "AttackTechnique",
    "Test Documentation Spreadsheet": "Artifact",
    "Fingerprint Web Application Framework": "AttackTechnique",
    "uses Server-Side Scripting Language": "TechnologyStack",
    "HTML headers and cookies": "Artifact",
    "Web Application Framework": "TechnologyStack",
    "Framework masking attempts": "DefensiveControl",
    "directory structures": "Artifact",
    "Architecture Mapping": "AttackTechnique",
    "PaaS": "TechnologyStack",
    "Artifact HTTP Headers": "Artifact",
    "Component Fingerprinting": "AttackTechnique",
    "Reachability": "PreconditionEnvironment",
    "Artifact DNS Records": "Artifact",
    "Test Effectiveness": "ObservableSignal",
    "Request Input Attack Strings": "PayloadPattern",
    "Remediation Scope": "PreconditionEnvironment",
    "Artifact Public Download URL": "Artifact",
    "Stored XSS": "VulnerabilityClass",
    "Input Field of index2.php": "Artifact",
    "Arbitrary MIME Type Header": "PayloadPattern",
    "Web Proxy or Modify Request Tool": "TechnologyStack",
    "Uploaded File Handler": "TechnologyStack",
    "Cookies (incl. Session Cookies)": "Artifact",
    "HTML Output Context": "PreconditionEnvironment",
    "JavaScript Execution Context": "PreconditionEnvironment",
    "Uploaded HTML File Contents": "Artifact",
    "Web Page DOM": "TechnologyStack",
    "Parameter Pollution Vulnerability": "VulnerabilityClass",
    "HAS_PROCEDURE": "TechnologyStack",
    "<404>": "ObservableSignal",
    "SQL injection": "VulnerabilityClass",
    "MySQL Versions": "TechnologyStack",
    "MySQL pre-4.0.x": "TechnologyStack",
    "Password Field Injection": "AttackTechnique",
    "boolean-based blind injection": "AttackTechnique",
    "SQL injection vulnerability": "VulnerabilityClass",
    "MYSQL Server": "TechnologyStack",
    "HTTP Browseable Files": "Artifact",
    "FTP": "TechnologyStack",
    "Firewall Blocking": "DefensiveControl",
    "SQL statement": "Artifact",
    "FILE SYSTEM DATA DIRECTORY": "Artifact",
    "OS Command Execution": "AttackTechnique",
    "msaccess_query_construction": "AttackTechnique",
    "Methodology for Testing for MS Access": "AttackTechnique",
    "Concept Testing for MS Access": "AttackTechnique",
    "Concept MS Access": "TechnologyStack",
    "SQL injection explanation": "VulnerabilityClass",
    "ASC function example": "TechnologyStack",
    "CHR function example": "TechnologyStack",
    "LEN function example": "TechnologyStack",
    "IIF function example": "TechnologyStack",
    "MID function example": "TechnologyStack",
    "TOP function example": "TechnologyStack",
    "LAST function example": "TechnologyStack",
    "ORMGenerator": "TechnologyStack",
    "ORM Layers": "TechnologyStack",
    "Testing for Client-side": "Artifact",
    "Vulnerable Web SQL Database": "PreconditionEnvironment",
    "Methodology for Testing for Client-side": "AttackTechnique",
    "Concept Testing for Client-side": "AttackTechnique",
    "Concept Client-side": "Artifact",
    "SSI Directive Support": "PreconditionEnvironment",
    ".exec SSI Directive": "PayloadPattern",
    "SSI Directives": "PayloadPattern",
    ".shtml File Extension": "Artifact",
    ".include SSI Directive": "PayloadPattern",
    "File Inclusion API": "TechnologyStack",
    "No Internet Backend": "PreconditionEnvironment",
    "Recommendation for Direct Testing": "AttackTechnique",
    "Passed ID Parameter": "ObservableSignal",
    "External URL Injection": "AttackTechnique",
    "Path Sanitization Failure": "VulnerabilityClass",
    ".php Extension": "PayloadPattern",
    "File Request Input": "Artifact",
    "Malicious URL (Payload)": "PayloadPattern",
    "Legal Notice Field (`notice` column in `footer` table)`": "Artifact",
    "Output Validation": "DefensiveControl",
    "Input Field Bypass": "AttackTechnique",
    "URL Parameter Injection": "AttackTechnique",
    "Frontend Backend Parsing Mismatch": "VulnerabilityClass",
    "HTTP Protocol Version Inconsistency": "VulnerabilityClass",
    "Strict RFC-compliant Parsing": "DefensiveControl",
    "Implicit Downgrade": "AttackTechnique",
    "Content-Length Header": "Artifact",
    "Transfer-Encoding Header": "Artifact",
    "Smuggled Request (Second HTTP Request)": "PayloadPattern",
    "Backed HTTP Parser": "TechnologyStack",
    "Protocol Downgrade": "AttackTechnique",
    "Redirect Response (HTTP 302)": "ObservableSignal",
    "Concept Host Header Injection": "AttackTechnique",
    "Test for Server-side Template Injection Methodology": "AttackTechnique",
    "Self Object": "Artifact",
    "Sensitive Properties": "Artifact",
    "HTTP Request Bodies (Various Forms)": "Artifact",
    "User Interaction Testing": "AttackTechnique",
    "Privileged User Role": "AttackerCapability",
    "Controller": "TechnologyStack",
    "Anonymous/Low-Privilege User": "AttackerCapability",
    "Pagination/ID-Based Endpoints": "TechnologyStack",
    "HYPERLINK()": "PayloadPattern",
    "Formula-Triggering Characters `": "PayloadPattern",
    "`Spreadsheet Application Formula Interpretion": "PreconditionEnvironment",
    "Gadget": "TechnologyStack",
    "Http POST Request Body": "Artifact",
    "Object Prototype": "TechnologyStack",
    "Pollution Attempt with __proto__ Key": "AttackTechnique",
    "Node.js Runtime": "TechnologyStack",
    "Recursive Merge Function": "TechnologyStack",
    "Node.js Package": "TechnologyStack",
    "Gadget Code Path": "TechnologyStack",
    "Client-Side Scripts": "TechnologyStack",
    "Network Eavesdropping": "AttackTechnique",
    "Memory Area": "Artifact",
    "Cookie Manipulation": "AttackTechnique",
    "Authenticated Session": "PreconditionEnvironment",
    "Subdomain": "Artifact",
    "SameSite": "DefensiveControl",
    "Path": "DefensiveControl",
    "SameSite=Strict": "DefensiveControl",
    "SameSite=Lax": "DefensiveControl",
    "SameSite=None": "DefensiveControl",
    "HttpOnly": "DefensiveControl",
    "Persistent Cookie": "Artifact",
    "Top Level Domain": "Artifact",
    "Testing for Cookies Attributes": "AttackTechnique",
    "None": "DefensiveControl",
    "Path=/": "DefensiveControl",
    "Secure attribute": "DefensiveControl",
    "loose Domain Attribute configuration": "PreconditionEnvironment",
    "Domain attribute": "DefensiveControl",
    "loose Path Attribute configuration": "PreconditionEnvironment",
    "Two Test Accounts": "Artifact",
    "Single Machine Variant": "AttackTechnique",
    "Authentication Request": "Artifact",
    "Different Machine/Browser Setup": "PreconditionEnvironment",
    "Cookie Name `__Host-`": "DefensiveControl",
    "Cookie Name `__Secure-`": "DefensiveControl",
    "Cache-Control Directive": "DefensiveControl",
    "Caches": "TechnologyStack",
    "Request/Response": "Artifact",
    "Proxy/Firewall Logs": "Artifact",
    "Testing for Exposed Session Variables": "AttackTechnique",
    "Compromise": "AttackGoal",
    "Email Message Containing Malicious Image": "PayloadPattern",
    "Browser Cookie Submission": "ObservableSignal",
    "Vulnerable Application (Web Interface)": "PreconditionEnvironment",
    "Logout Functionality Testing": "AttackTechnique",
    "Central Portal / Application Directory": "TechnologyStack",
    "Server-side Session State": "Artifact",
    "Individual Application Session": "PreconditionEnvironment",
    "Single Sign-On (SSO) System": "TechnologyStack",
    "Application-Specific Logout": "AttackTechnique",
    "Log Out in SSO Portal": "AttackTechnique",
    "Web Application": "TechnologyStack",
    "Sensitive Data": "Artifact",
    "Idle Session": "PreconditionEnvironment",
    "Session Hijacking Test": "AttackTechnique",
    "Secure Function": "TechnologyStack",
    "HSTS": "DefensiveControl",
    "Cookie Filtering Conditions": "PreconditionEnvironment",
    "Testing Environment": "PreconditionEnvironment",
    "Step 3: Cookie Snapshot": "Artifact",
    "Cookie Jar Snapshot": "Artifact",
    "Two Machines/Browsers": "PreconditionEnvironment",
    "Step 6: Cookie Injection": "AttackTechnique",
    "Single Testing Account": "PreconditionEnvironment",
    "Clear Cookie Jar": "AttackTechnique",
    "JWS Header": "Artifact",
    "JSON Web Signature (JWS)": "TechnologyStack",
    "HMAC Key": "Artifact",
    "Public Key Verification Step": "DefensiveControl",
    "HMAC Token Validation": "DefensiveControl",
    "Concurrent Sessions": "PreconditionEnvironment",
    "Concurrent User Sessions": "PreconditionEnvironment",
    "Single User Account": "Artifact",
    "User Dashboard": "TechnologyStack",
    "Management Panel": "TechnologyStack",
    "Private Browsing Mode": "TechnologyStack",
    "Multi-Account Container": "TechnologyStack",
    "Security Vulnerability": "VulnerabilityClass",
    "Concurrent Sessions Testing Methodology": "AttackTechnique",
    "Personally Identifiable Information (PII)": "Artifact",
    "Multiple Active Sessions": "PreconditionEnvironment",
    "User Generated Session": "PreconditionEnvironment",
    "Stored In Browser": "PreconditionEnvironment",
    "Session Access": "DefensiveControl",
    "Trusted IP Range": "DefensiveControl",
    "Multiple sessions from different IPs": "ObservableSignal",
    "Unauthorized Session Access": "AttackGoal",
    "Web Application Testing Methodology": "AttackTechnique",
    "HPKP": "DefensiveControl",
    "ALLOW-FROM": "DefensiveControl",
    "Hop-by-Hop Header Injection": "AttackTechnique",
    "Duplicate Security Headers": "VulnerabilityClass",
    "Overpermissive Security Headers": "VulnerabilityClass",
    "Obsolete Header": "VulnerabilityClass",
    "Obsolete Headers": "VulnerabilityClass",
    "Echo Pages (e.g., /phpinfo, /debug)": "Artifact",
    "Error Pages": "ObservableSignal",
    "MitM Attack": "AttackTechnique",
    "Hybrid Ciphers": "TechnologyStack",
    "Public Certificate Authority": "TechnologyStack",
    "Internal Certificate Authority": "TechnologyStack",
    "Post-Quantum Key Exchange ML-KEM-768": "TechnologyStack",
    "Validity Period": "PreconditionEnvironment",
    "Encrypted Data": "Artifact",
    "Padding Oracle Attack": "AttackTechnique",
    "IV": "PayloadPattern",
    "Credentials": "AttackerCapability",
    "Message Integrity": "DefensiveControl",
    "Encryption": "DefensiveControl",
    "debug and fix issues on customer accounts": "AttackGoal",
    "review application transactions": "AttackGoal",
    "sensitive admin functionality": "AttackGoal",
    "Account Limits or Uniqueness Rules": "DefensiveControl",
    "Registration Process": "PreconditionEnvironment",
    "Resource Management Decision": "PreconditionEnvironment",
    "Production Release": "PreconditionEnvironment",
    "internet-connected infrastructure": "PreconditionEnvironment",
    "internet-connected devices": "PreconditionEnvironment",
    "search operators": "PayloadPattern",
    "advanced search keywords": "PayloadPattern",
    "search syntax": "PayloadPattern",
    "indexing": "PreconditionEnvironment",
    "Request Input Field": "Artifact",
    "Google": "TechnologyStack",
    ".well-known/<path>": "PayloadPattern",
    "HTMLPage": "Artifact",
    "Hidden Web Applications": "PreconditionEnvironment",
    "Non-standard Ports": "PreconditionEnvironment",
    "HTTP Host Header": "TechnologyStack",
    "IP Address": "Artifact",
    "DNS Enumeration": "AttackTechnique",
    "Site Operator": "PayloadPattern",
    "Subdomains": "Artifact",
    "Digital Certificates": "Artifact",
    "Reverse DNS Lookup": "AttackTechnique",
    "Port 80": "PreconditionEnvironment",
    "Port 443": "PreconditionEnvironment",
    "Certificate Transparency Logs": "Artifact",
    "Port 901": "PreconditionEnvironment",
    "Port 1241": "PreconditionEnvironment",
    "Port 8080": "PreconditionEnvironment",
    "Port 3690": "PreconditionEnvironment",
    "Port 8000": "PreconditionEnvironment",
    "TargetInfrastructure": "PreconditionEnvironment",
    "Route Location": "Artifact",
    "Parameter Type": "Artifact",
    "Parameter Name": "Artifact",
    "Data Type": "Artifact",
    "attack-surface-detector-cli-1.3.5.jar": "TechnologyStack",
    "HTTP Responses": "ObservableSignal",
    "Application Resource": "Artifact",
    "Data Assignment": "AttackTechnique",
    "Concurrent Instances": "PreconditionEnvironment",
    "Web Crawler": "TechnologyStack",
    "Web Robot": "TechnologyStack",
    "Web Spider": "TechnologyStack",
    "URL Discovery": "AttackTechnique",
    "Requests": "Artifact",
    "IPS": "DefensiveControl",
    "Network Traffic": "ObservableSignal",
    "Attack Strings": "PayloadPattern",
    "Attack String Injection": "AttackTechnique",
    "4096 Byte Filename Limit": "PreconditionEnvironment",
    "@@VERSION": "ObservableSignal",
    "`create` IMAP Command": "PayloadPattern",
    "`include` Function": "TechnologyStack",
    "allows multiple SQL statements with `;`": "PreconditionEnvironment",
    "Arbitrary File Read": "AttackerCapability",
    "Automated Scans": "AttackTechnique",
    "Base64-encoded Payload": "PayloadPattern",
    "Backend Origin Exposure": "ObservableSignal",
    "BENCHMARK": "TechnologyStack",
    "bruteforcing sysadmin password": "AttackTechnique",
    "Cloud WAF": "DefensiveControl",
    "CONVERT Function": "TechnologyStack",
    "debug.exe": "TechnologyStack",
    "File Extension Appending": "AttackTechnique",
    "Firewall": "DefensiveControl",
    "Frontend/Backend Server Mismatch": "ObservableSignal",
    "IDS/IPS": "DefensiveControl",
    "Inconsistent TimesInconsistent HostnamesInternal IPsLoad-Balancer Cookies": "ObservableSignal",
    "Input Validation Failure": "PreconditionEnvironment",
    "Malicious Remote URL Injection": "AttackTechnique",
    "PHP `allow_url_include`": "PreconditionEnvironment",
    "PHP Zip Wrapper (`zip://`)": "TechnologyStack",
    "Port Scan": "AttackTechnique",
    "Remote Code Execution (RCE)": "AttackGoal",
    "Sensitive Server Files (e.g., `/etc/passwd`)": "Artifact",
    "SLEEP": "TechnologyStack",
    "sp_addextendedproc": "TechnologyStack",
    "SQL Server 2005": "TechnologyStack",
    "supports `pg_sleep(n)`": "PreconditionEnvironment",
    "sysadmin": "AttackerCapability",
    "sysadmin privilege": "AttackerCapability",
    "sysadmin Role": "AttackerCapability",
    "Time based Blind Injection": "AttackTechnique",
    "truncates SQL with `--`": "PayloadPattern",
    "User Input Vectors": "Artifact",
    "User-Submitted `file` Parameter": "Artifact",
    "WAF": "DefensiveControl",
    "WHOIS Lookup": "AttackTechnique",
    "SSRF": "VulnerabilityClass",
    "Session Token Theft": "AttackGoal",
    "Pseudo Defacement": "AttackGoal",
    "Internal Port Scanning": "AttackGoal",
    "Arbitrary MIME Type Setting": "PreconditionEnvironment",
    "SQL queries": "PayloadPattern",
    "@ModelAttribute Annotation": "TechnologyStack",
    "Allow Listing<|DefensiveControl|>": "DefensiveControl",
    "call_user_func()": "TechnologyStack",
    "Cleartext HTTP/2 (H2C)": "PreconditionEnvironment",
    "Cookie Value Analysis": "AttackTechnique",
    "FreeMaker": "TechnologyStack",
    "Input Enumeration": "AttackTechnique",
    "Jinja2": "TechnologyStack",
    "RFC Compliance Violation": "VulnerabilityClass",
    "Sandbox Mechanisms<|DefensiveControl|>": "DefensiveControl",
    "Session Fixation": "VulnerabilityClass",
    "Twig": "TechnologyStack",
    "Character Set": "PreconditionEnvironment",
    "Confidential Information": "Artifact",
    "Expires Header": "DefensiveControl",
    "Internal Property": "Artifact",
    "Privilege-related Property": "Artifact",
    "Process-dependent Property": "Artifact",
    "Sensitive Property": "Artifact",
    "Session ID Space": "PreconditionEnvironment",
    "__Secure- Prefix": "DefensiveControl",
    "__Host- Prefix": "DefensiveControl",
    "Contains Sensitive Data": "PreconditionEnvironment",
    "Cookie Attributes": "DefensiveControl",
    "Cookie Prefixes": "DefensiveControl",
    "Cookie Protection": "DefensiveControl",
    "Cookie Review": "AttackTechnique",
    "Cookie Scope Control": "DefensiveControl",
    "Cross-Site Information Leakage": "VulnerabilityClass",
    "HTTP/1.0 Cache": "TechnologyStack",
    "HTTP/1.1 Cache": "TechnologyStack",
    "IP Address Restrictions": "DefensiveControl",
    "IP Address Tracking": "DefensiveControl",
    "Java Vulnerability CVE-2022-21449": "VulnerabilityClass",
    "Library Support for Embedded Keys": "PreconditionEnvironment",
    "Local Cache": "TechnologyStack",
    "Loose Path Attribute": "PreconditionEnvironment",
    "None algorithm": "PayloadPattern",
    "Public Computer Scenario": "PreconditionEnvironment",
    "SameSite=None Value": "DefensiveControl",
    "Session Management Page": "PreconditionEnvironment",
    "SSO System Logout": "PreconditionEnvironment",
    "SSO System Session": "PreconditionEnvironment",
    "Transport Security": "DefensiveControl",
    "User Notification": "DefensiveControl",
    "Web Application Logout": "PreconditionEnvironment",
    "Web Application Session": "PreconditionEnvironment",
    "Cookie Name Prefixes": "DefensiveControl",
    "Text/plain Encoding": "AttackTechnique",
    "Source Code Review": "AttackTechnique",
    "Session State": "PreconditionEnvironment",
    "Input Validation Flaw": "PreconditionEnvironment",
    "Grey-box Testing": "AttackTechnique",
    "File Inclusion Function": "TechnologyStack",
    "Unsanitized User Input": "PreconditionEnvironment",
    "Custom Input Sanitation Code": "DefensiveControl",
    "Malicious Input Data": "PayloadPattern",
    "Input Field / Text Input": "Artifact",
    "Script Injection Attempt": "AttackTechnique",
    "Sanitization Logical Combinations": "DefensiveControl",
    "White-Box Testing": "AttackTechnique",
    "Src Attribute Bypass Payload": "PayloadPattern",
    "Http Response Reflection": "ObservableSignal",
    "NoSQL API Call": "TechnologyStack",
    "$$ Operator Injection": "PayloadPattern",
    "Special Character Injection": "PayloadPattern",
    "Reserved NoSQL Variable Name": "PayloadPattern",
    "MongoDB API Call": "TechnologyStack",
    "Database Error as Observable Signal": "ObservableSignal",
    "Reserved API Parameter": "PayloadPattern",
    "SELECT Statement": "PayloadPattern",
    "Database Management System (DBMS)": "TechnologyStack",
    "Union-Based Injection Technique": "AttackTechnique",
    "Error-Based Exploitation Technique": "AttackTechnique",
    "Boolean-based SQL Injection Technique": "AttackTechnique",
    "SQL comment `--` / `/*`": "PayloadPattern",
    "Time Delay SQL Injection Technique": "AttackTechnique",
    "Back-end Database": "TechnologyStack",
    "Union Select SQL Query": "PayloadPattern",
    "Union Select": "PayloadPattern",
    "ORDER BY Clause Attack": "AttackTechnique",
    "ORDER BY Clause": "PayloadPattern",
    "Syntax Error Message": "ObservableSignal",
    "Information Leakage": "AttackGoal",
    "Query Syntax Dependency": "PreconditionEnvironment",
    "Username parameter": "Artifact",
    "get_report stored procedure": "TechnologyStack",
    "Password column": "Artifact",
    "UNION SELECT ... FROM Users WHERE name='admin'--": "PayloadPattern",
    "Hex Encoding": "PayloadPattern",
    "database tables": "Artifact",
    "Response Time": "ObservableSignal",
    "database": "TechnologyStack",
    "web server": "TechnologyStack",
    "Parentheses (())": "PayloadPattern",
    "Input Validation Testing": "AttackTechnique",
    "Deny List Filtering": "DefensiveControl",
    "Obfuscated Input": "PayloadPattern",
    "Insecure Input Handling": "PreconditionEnvironment",
    "JavaScript Execution": "AttackGoal",
    "Parameter Pollution": "AttackTechnique",
    "Recursive Sanitization": "DefensiveControl",
    "JavaScript Payload": "PayloadPattern",
    "Untrusted User Input": "PreconditionEnvironment",
    "&": "PayloadPattern",
    r"\|": "PayloadPattern",
    "!": "PayloadPattern",
    "=": "PayloadPattern",
    "<=": "PayloadPattern",
    "≈": "PayloadPattern",
    "*": "PayloadPattern",
    "()": "PayloadPattern",
    "Basic Authentication": "TechnologyStack",
    "Corporate LDAP Structure": "PreconditionEnvironment",
    "`XML Entities": "Artifact",
    "ampersand `&` `": "PayloadPattern",
    "Ineffective Input Encode `&`": "PreconditionEnvironment",
    "XML External Entity (`<!ENTITY xxe SYSTEM ...>`)": "VulnerabilityClass",
    "Methodology for Testing for XML Injection": "AttackTechnique",
    "XmlDB": "Artifact",
    "Single Quote (`'`)": "PayloadPattern",
    "Error messages generated by XML parser / application": "ObservableSignal",
    "Boolean expression (' or '1' = '1')": "PayloadPattern",
    "Authentication mechanism": "DefensiveControl",
    "Local Resource": "Artifact",
    "Methodology for Testing for Server-Side Request Forgery": "AttackTechnique",
    "IP Address Obfuscations": "PayloadPattern",
    "URL Fragmentation": "AttackTechnique",
    "Concept Testing for Server-Side Request Forgery": "AttackTechnique",
    "Concept Server-Side Request Forgery": "VulnerabilityClass",
    "Userinfo-Host Separator (`@`)": "PayloadPattern",
    "Base64 Encoded Authorization Header": "PayloadPattern",
    "HTTP Headers": "Artifact",
    "application/x-www-form-urlencoded": "Artifact",
    "Windows Command Prompt": "TechnologyStack",
    "cmd1 && cmd2 logic": "PayloadPattern",
    "`whoami` command": "PayloadPattern",
    "Linux file descriptor redirection": "PayloadPattern",
    "`tr` command": "PayloadPattern",
    "Windows Command Environment": "TechnologyStack",
    "Local File Inclusion": "VulnerabilityClass",
    "Remote File Inclusion": "VulnerabilityClass",
    "URL Fragment Identifier Injection": "AttackTechnique",
    "Octal IP Address Encoding Bypass": "AttackTechnique",
    "Shortened IP Notation": "PayloadPattern",
    "Parameter Injection (via URL)": "AttackTechnique",
    "XML Injection Testing": "AttackTechnique",
    "XML Structure": "Artifact",
    "Denial of Service": "AttackGoal",
    "XML Document Type Definition": "Artifact",
    "Special Characters": "PayloadPattern",
    "URL encoding": "PayloadPattern",
    "Environment Variables (Linux)": "PayloadPattern",
    "Remote Verification Server": "TechnologyStack",
    r"\<backtick\> (```cmd```)": "PayloadPattern",
    "Filepath Parameter": "Artifact",
    "Time Delay System Command (sleep)": "PayloadPattern",
    "Pipe Character |": "PayloadPattern",
    "System Command Output Redirection (Output File)": "PayloadPattern",
    "URL-Encoded Semicolon %3B": "PayloadPattern",
    "Bash Brace Expansion {}": "PayloadPattern",
    "Database Error Response": "ObservableSignal",
    "External Communication Channel": "ObservableSignal",
    "SQL Query Logic": "PreconditionEnvironment",
    "Database Response Time": "ObservableSignal",
    "Input Validation Mechanism": "DefensiveControl",
    "Dynamic SQL Query Construction": "PreconditionEnvironment",
    "' OR '1' = '1'": "PayloadPattern",
    "Parent Query Result": "Artifact",
    "Version Query": "PayloadPattern",
    "LIMIT Clause": "PayloadPattern",
    "Remote API Endpoint": "TechnologyStack",
    "Inband": "AttackTechnique",
    "Out-of-band": "AttackTechnique",
    "Inferential (Blind)": "AttackTechnique",
    "Null Character (%00)": "PayloadPattern",
    "UNC Filepath": "PayloadPattern",
    "Malicious Path Traversal String": "PayloadPattern",
    "Batch/Iterative Testing": "AttackTechnique",
    "Social Engineering Step": "AttackTechnique",
    "User Variable Manipulation": "AttackTechnique",
    "HTML Response": "Artifact",
    "Sanitization Mechanism": "DefensiveControl",
    "Non-Persistent XSS": "VulnerabilityClass",
    "HTTP Request Function (`UTL_HTTP.request`)": "TechnologyStack",
    "Comment Delimiter": "PayloadPattern",
    "Database Engine": "TechnologyStack",
    "Boolean Payload": "PayloadPattern",
    "Access Unauthorized Content": "AttackGoal",
    "Evasion Application Restrictions": "AttackGoal",
    "Gather Unauthorized Information": "AttackGoal",
    "Add Modify LDAP Objects": "AttackGoal",
    "Identify LDAP Injection Points": "AttackTechnique",
    "Assess LDAP Injection Severity": "AttackTechnique",
    "Invalid XPath Syntax": "PayloadPattern",
    "XML Data Store": "TechnologyStack",
    "username field": "Artifact",
    "password field": "Artifact",
    "XML Query Syntax": "PreconditionEnvironment",
    "XML Query Validation": "DefensiveControl",
    "Syntax Error Analysis": "AttackTechnique",
    "Blind Inference": "AttackTechnique",
    "Comment Tag Injection": "AttackTechnique",
    "Angular Bracket Injection": "AttackTechnique",
    "XML Document Parsing": "TechnologyStack",
    "XML Document Structure": "Artifact",
    "URL Parsing Misconfiguration": "VulnerabilityClass",
    "URL Fuzzing": "AttackTechnique",
    "Public DNS Resolved to Loopback IP": "PayloadPattern",
    "Alternative IP Representation": "PayloadPattern",
    "String Obfuscation": "PayloadPattern",
    "Backtick `` ``": "PayloadPattern",
    "Special Characters (space, new line)": "PayloadPattern",
    "API Broken Function Level Authorization": "VulnerabilityClass",
    "Exploited Administrative functions": "ObservableSignal",
    "REST API Endpoint invocation by Regular User": "AttackTechnique",
    "Incorrect response (200 OK)": "ObservableSignal",
    "403 Forbidden response": "ObservableSignal",
    "Error Response Sanitization": "DefensiveControl",
    "GraphQLAPI": "TechnologyStack",
    "Testing GraphQL": "AttackTechnique",
    "GraphQL Response": "Artifact",
    "Development Environment": "PreconditionEnvironment",
    "GraphQL Schema Introspection Errors": "ObservableSignal",
    "GraphQL response fields": "Artifact",
    "query rate limiting defenses": "DefensiveControl",
    "mutations": "AttackTechnique",
    "rate limiting defenses": "DefensiveControl",
    "HTTP Header": "Artifact",
    "Static Username": "PayloadPattern",
    "Static Password": "PayloadPattern",
    "Manual Password Creation": "PreconditionEnvironment",
    "Organization Specific Details": "PayloadPattern",
    "Application Authentication Form": "Artifact",
    "PHP Side‑Channel Suppression": "AttackTechnique",
    "Session ID Dependency": "PreconditionEnvironment",
    "Web Application Firewall Evasion": "AttackTechnique",
    "AWS Cognito Lockout": "DefensiveControl",
    "Account Lockout Duration Scaling": "DefensiveControl",
    "Bypassing Authentication Steps": "AttackTechnique",
    "CAPTCHA Challenge": "DefensiveControl",
    "Back Button Press": "AttackTechnique",
    "Unauthorized Access": "AttackGoal",
    "Password Reuse": "VulnerabilityClass",
    "Common Passwords": "PayloadPattern",
    "Security Questions and Answers": "DefensiveControl",
    "Primary Account Identifier": "Artifact",
    "password_reset_link": "Artifact",
    "account_authentication": "DefensiveControl",
    "password_change_request": "Artifact",
    "user_id_parameter_in_url": "Artifact",
    "Brute-Force Attack": "AttackTechnique",
    "CSPRNG": "DefensiveControl",
    "Attacker Account Access": "AttackerCapability",
    "Password Reset Form": "Artifact",
    "Email Spoofing": "AttackTechnique",
    "Short Token Length": "VulnerabilityClass",
    "Account Compromise": "AttackGoal",
    "SPF, DKIM, DMARC": "DefensiveControl",
    "Manual Contact Process": "PreconditionEnvironment",
    "Online Brute-Force Attack": "AttackTechnique",
    "Unencrypted HTTP": "PreconditionEnvironment",
    "Token Transmission": "Artifact",
    "AuthenticationFunctions": "TechnologyStack",
    "Authentication flow": "TechnologyStack",
    "support MFA methods": "DefensiveControl",
    "Email": "TechnologyStack",
    "SMS": "TechnologyStack",
    "TOTP": "TechnologyStack",
    "Phone-based Notification": "TechnologyStack",
    "Email-based MFA Code": "Artifact",
    "SMS-based MFA Code": "Artifact",
    "Voice Call": "TechnologyStack",
    "HOTP": "TechnologyStack",
}


@dataclass(frozen=True)
class GraphEntity:
    name: str
    entity_type: str
    canonical_type: str | None
    description: str = ""
    source_id: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class GraphRelation:
    source: str
    target: str
    keywords: str = ""
    description: str = ""
    source_id: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class EntityTypeMismatch:
    name: str
    actual_type: str
    canonical_actual_type: str | None
    expected_type: str


@dataclass(frozen=True)
class EntityTypeUpdate:
    name: str
    actual_type: str
    target_type: str
    reason: str


@dataclass(frozen=True)
class EntityTypeUpdateResult:
    update: EntityTypeUpdate
    status_code: int
    status: str
    message: str = ""


@dataclass(frozen=True)
class EntityDeleteResult:
    entity_name: str
    status_code: int
    status: str
    message: str = ""


@dataclass(frozen=True)
class GraphAuditReport:
    graphml_path: str
    entity_count: int
    relation_count: int
    type_counts: dict[str, int]
    canonical_type_counts: dict[str, int]
    unknown_type_entities: list[GraphEntity]
    non_canonical_type_entities: list[GraphEntity]
    noise_entities: list[GraphEntity]
    missing_expected_entities: list[str]
    expected_type_mismatches: list[EntityTypeMismatch]

    @property
    def has_blocking_issues(self) -> bool:
        return bool(
            self.unknown_type_entities
            or self.non_canonical_type_entities
            or self.noise_entities
            or self.expected_type_mismatches
        )

    def to_dict(self) -> dict:
        return asdict(self) | {"has_blocking_issues": self.has_blocking_issues}


def canonicalize_entity_type(entity_type: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "", entity_type.strip().lower())
    if not normalized or normalized == "other":
        return None
    return _CANONICAL_BY_NORMALIZED_TYPE.get(normalized)


def infer_expected_entity_type(name: str) -> str | None:
    marker_match = _EMBEDDED_TYPE_MARKER_RE.search(name)
    if marker_match:
        return canonicalize_entity_type(marker_match.group("entity_type"))
    return None


def plan_entity_type_updates(report: GraphAuditReport) -> list[EntityTypeUpdate]:
    """Build deterministic post-extraction type updates for a LightRAG graph."""
    updates_by_name: dict[str, EntityTypeUpdate] = {}
    for mismatch in report.expected_type_mismatches:
        updates_by_name[mismatch.name] = EntityTypeUpdate(
            name=mismatch.name,
            actual_type=mismatch.actual_type,
            target_type=mismatch.expected_type,
            reason="expected_type_mismatch",
        )

    for entity in report.non_canonical_type_entities:
        if entity.name in updates_by_name or entity.canonical_type is None:
            continue
        updates_by_name[entity.name] = EntityTypeUpdate(
            name=entity.name,
            actual_type=entity.entity_type,
            target_type=entity.canonical_type,
            reason="non_canonical_type",
        )
    return list(updates_by_name.values())


def plan_noise_entity_deletes(report: GraphAuditReport) -> list[str]:
    """Build deterministic post-extraction deletes for known noise entities."""
    return sorted({entity.name for entity in report.noise_entities})


def normalize_lightrag_entity_types(
    graphml_path: str | Path,
    *,
    base_url: str = "http://127.0.0.1:9621",
    api_key: str | None = None,
    timeout: float = 60,
    dry_run: bool = False,
    delete_noise_entities: bool = False,
) -> dict:
    """Apply planned entity type updates through the LightRAG graph API."""
    report = audit_lightrag_graph(graphml_path)
    noise_deletes = plan_noise_entity_deletes(report) if delete_noise_entities else []
    noise_delete_names = set(noise_deletes)
    updates = [
        update
        for update in plan_entity_type_updates(report)
        if update.name not in noise_delete_names
    ]
    if dry_run:
        return {
            "dry_run": True,
            "planned_updates": [asdict(update) for update in updates],
            "planned_noise_deletes": noise_deletes,
            "updated": 0,
            "deleted_noise_entities": 0,
            "failed": [],
            "delete_failed": [],
        }

    results = [
        _update_lightrag_entity_type(
            base_url=base_url,
            update=update,
            api_key=api_key,
            timeout=timeout,
        )
        for update in updates
    ]
    failed = [
        asdict(result)
        for result in results
        if result.status_code >= 400 or result.status != "success"
    ]
    delete_results = [
        _delete_lightrag_entity(
            base_url=base_url,
            entity_name=entity_name,
            api_key=api_key,
            timeout=timeout,
        )
        for entity_name in noise_deletes
    ]
    delete_failed = [
        asdict(result)
        for result in delete_results
        if result.status_code >= 400 or result.status != "success"
    ]
    return {
        "dry_run": False,
        "planned_updates": len(updates),
        "updated": len(results) - len(failed),
        "planned_noise_deletes": len(noise_deletes),
        "deleted_noise_entities": len(delete_results) - len(delete_failed),
        "failed": failed,
        "delete_failed": delete_failed,
    }


def parse_lightrag_graphml(graphml_path: str | Path) -> tuple[list[GraphEntity], list[GraphRelation]]:
    path = Path(graphml_path)
    root = ET.parse(path).getroot()
    key_names = {
        key.attrib["id"]: key.attrib.get("attr.name", key.attrib["id"])
        for key in root.findall("g:key", _GRAPHML_NS)
        if "id" in key.attrib
    }

    entities: list[GraphEntity] = []
    for node in root.findall(".//g:node", _GRAPHML_NS):
        values = _data_values(node, key_names)
        name = values.get("entity_id") or node.attrib.get("id", "")
        entity_type = values.get("entity_type", "")
        entities.append(
            GraphEntity(
                name=name,
                entity_type=entity_type,
                canonical_type=canonicalize_entity_type(entity_type),
                description=values.get("description", ""),
                source_id=values.get("source_id", ""),
                file_path=values.get("file_path", ""),
            )
        )

    relations: list[GraphRelation] = []
    for edge in root.findall(".//g:edge", _GRAPHML_NS):
        values = _data_values(edge, key_names)
        relations.append(
            GraphRelation(
                source=edge.attrib.get("source", ""),
                target=edge.attrib.get("target", ""),
                keywords=values.get("keywords", ""),
                description=values.get("description", ""),
                source_id=values.get("source_id", ""),
                file_path=values.get("file_path", ""),
            )
        )
    return entities, relations


def audit_lightrag_graph(
    graphml_path: str | Path,
    *,
    expected_entity_types: Mapping[str, str] | None = None,
    noise_patterns: Sequence[str] = DEFAULT_NOISE_PATTERNS,
) -> GraphAuditReport:
    path = Path(graphml_path)
    entities, relations = parse_lightrag_graphml(path)
    expected = expected_entity_types or DEFAULT_EXPECTED_ENTITY_TYPES
    compiled_noise = [re.compile(pattern, flags=re.I) for pattern in noise_patterns]
    entities_by_name = {entity.name: entity for entity in entities}

    type_counts = _count_values(entity.entity_type for entity in entities)
    canonical_type_counts = _count_values(
        entity.canonical_type or "<unknown>" for entity in entities
    )
    unknown_type_entities = [
        entity for entity in entities if entity.canonical_type is None
    ]
    non_canonical_type_entities = [
        entity
        for entity in entities
        if entity.canonical_type is not None and entity.entity_type != entity.canonical_type
    ]
    noise_entities = [
        entity
        for entity in entities
        if any(pattern.search(entity.name) for pattern in compiled_noise)
    ]
    missing_expected_entities = [
        name for name in sorted(expected) if name not in entities_by_name
    ]
    expected_type_mismatches = []
    expected_by_name = dict(expected)
    for entity in entities:
        inferred_type = infer_expected_entity_type(entity.name)
        if inferred_type and entity.name not in expected_by_name:
            expected_by_name[entity.name] = inferred_type

    for name, expected_type in expected_by_name.items():
        entity = entities_by_name.get(name)
        if entity is None:
            continue
        if entity.canonical_type != expected_type:
            expected_type_mismatches.append(
                EntityTypeMismatch(
                    name=name,
                    actual_type=entity.entity_type,
                    canonical_actual_type=entity.canonical_type,
                    expected_type=expected_type,
                )
            )

    return GraphAuditReport(
        graphml_path=path.as_posix(),
        entity_count=len(entities),
        relation_count=len(relations),
        type_counts=type_counts,
        canonical_type_counts=canonical_type_counts,
        unknown_type_entities=unknown_type_entities,
        non_canonical_type_entities=non_canonical_type_entities,
        noise_entities=noise_entities,
        missing_expected_entities=missing_expected_entities,
        expected_type_mismatches=expected_type_mismatches,
    )


def _data_values(element: ET.Element, key_names: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for data in element.findall("g:data", _GRAPHML_NS):
        key = data.attrib.get("key", "")
        values[key_names.get(key, key)] = data.text or ""
    return values


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _update_lightrag_entity_type(
    *,
    base_url: str,
    update: EntityTypeUpdate,
    api_key: str | None,
    timeout: float,
) -> EntityTypeUpdateResult:
    payload = {
        "entity_name": update.name,
        "updated_data": {"entity_type": update.target_type},
        "allow_rename": False,
        "allow_merge": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urlrequest.Request(
        f"{base_url.rstrip('/')}/graph/entity/edit",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            response_payload = json.loads(body) if body else {}
            return EntityTypeUpdateResult(
                update=update,
                status_code=response.status,
                status=str(response_payload.get("status", "")),
                message=str(response_payload.get("message", "")),
            )
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return EntityTypeUpdateResult(
            update=update,
            status_code=exc.code,
            status="http_error",
            message=body,
        )
    except urlerror.URLError as exc:
        return EntityTypeUpdateResult(
            update=update,
            status_code=599,
            status="url_error",
            message=str(exc.reason),
        )


def _delete_lightrag_entity(
    *,
    base_url: str,
    entity_name: str,
    api_key: str | None,
    timeout: float,
) -> EntityDeleteResult:
    payload = {"entity_name": entity_name}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urlrequest.Request(
        f"{base_url.rstrip('/')}/documents/delete_entity",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="DELETE",
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            response_payload = json.loads(body) if body else {}
            return EntityDeleteResult(
                entity_name=entity_name,
                status_code=response.status,
                status=str(response_payload.get("status", "")),
                message=str(response_payload.get("message", "")),
            )
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return EntityDeleteResult(
            entity_name=entity_name,
            status_code=exc.code,
            status="http_error",
            message=body,
        )
    except urlerror.URLError as exc:
        return EntityDeleteResult(
            entity_name=entity_name,
            status_code=599,
            status="url_error",
            message=str(exc.reason),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a LightRAG GraphML store.")
    parser.add_argument(
        "graphml_path",
        nargs="?",
        default="lightrag/data/lightrag/rag_storage/graph_chunk_entity_relation.graphml",
    )
    parser.add_argument(
        "--fail-on-blocking-issues",
        action="store_true",
        help="Exit non-zero when unknown types, noise entities, or expected type mismatches are present.",
    )
    parser.add_argument(
        "--normalize-types",
        action="store_true",
        help="Update entity types through the LightRAG API before printing the final audit report.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:9621",
        help="LightRAG API base URL used with --normalize-types.",
    )
    parser.add_argument("--api-key", default=None, help="Optional LightRAG API key.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned normalization updates.",
    )
    parser.add_argument(
        "--delete-noise-entities",
        action="store_true",
        help="Delete entities matching the graph-audit noise patterns after extraction.",
    )
    args = parser.parse_args(argv)

    report = audit_lightrag_graph(args.graphml_path)
    if args.normalize_types:
        normalization = normalize_lightrag_entity_types(
            args.graphml_path,
            base_url=args.base_url,
            api_key=args.api_key,
            dry_run=args.dry_run,
            delete_noise_entities=args.delete_noise_entities,
        )
        if args.dry_run:
            print(json.dumps(normalization, indent=2, sort_keys=True))
            return 0
        report = audit_lightrag_graph(args.graphml_path)
        print(
            json.dumps(
                {
                    "normalization": normalization,
                    "audit": report.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        if args.fail_on_blocking_issues and report.has_blocking_issues:
            return 1
        return 0

    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if args.fail_on_blocking_issues and report.has_blocking_issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
