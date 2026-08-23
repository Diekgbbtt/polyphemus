"""The fault-risk scheduling policy (the candidates-rewrite, operator-authored).

The orchestration schedule is order-based: the per-fault work items are
processed in the order the intake first emitted them, which is the fault-KB
catalogue's authoring order (alphabetical by CWE id). That order carries NO
risk semantics - a budget-capped pass would reason about `CWE-1021` before
`CWE-639` purely because of lexicographic accident.

This module owns the deterministic correction: an OPERATOR-AUTHORED risk tier
per selection-tier fault (lower tier = higher risk = processed FIRST), grounded
in the operator's criteria (2026-08-21):

  * broken access control - the A01 spearhead: any fault whose compromise is
    unauthorized access to another actor's data or functions;
  * missing or weak validation - the injection/input-validation families whose
    failure mode is direct code/data compromise;
  * sophisticated-system targets - faults whose locus is an AuthenticationMechanism,
    AuthorizationSystem, or session-management System.

Within a tier, faults are ordered by exploitation impact (RCE / full-account
takeover > data exfiltration > degradation). The tiers are a SCHEDULING policy,
never a prune signal: every fault keeps its catalogue rank as the stable
tie-break inside its tier, and an UNANALYSED fault_id falls to `_DEFAULT_TIER`
(conservative: the policy never claims a criticality the analysis has not
granted). Pure and deterministic; no I/O.
"""
from __future__ import annotations

from typing import Mapping

# Tier 1 - BROKEN ACCESS CONTROL (the operator's first criterion): the A01
# spearhead. Compromise = acting as another actor (read/write their data,
# reach their functions); highest chaining potential in the web estate.
_TIER_ACCESS_CONTROL = frozenset({
    "CWE-639",   # Authorization Bypass Through User-Controlled Key (IDOR)
    "CWE-862",   # Missing Authorization
    "CWE-425",   # Direct Request ('Forced Browsing')
    "CWE-638",   # Not Using Complete Mediation
    "CWE-266",   # Incorrect Privilege Assignment
    "CWE-267",   # Privilege Defined With Unsafe Actions
    "CWE-268",   # Privilege Chaining
    "CWE-283",   # Unverified Ownership
    "CWE-551",   # Incorrect Behavior Order: Authorization Before Parsing
    "CWE-1220",  # Insufficient Granularity of Access Control
    "CWE-841",   # Improper Enforcement of Behavioral Workflow
    "CWE-274",   # Improper Handling of Insufficient Privileges
    "CWE-650",   # Trusting HTTP Permission Methods (verb-tampering bypass)
    "CWE-419",   # Unprotected Primary Channel (unprotected admin surface)
})

# Tier 2 - MISSING OR WEAK VALIDATION (the second criterion): the input-
# validation families whose failure mode is DIRECT compromise (code execution,
# data exfiltration, file read/write) - ordered RCE-first, then data-read.
_TIER_VALIDATION = frozenset({
    "CWE-78",    # OS Command Injection
    "CWE-89",    # SQL Injection
    "CWE-502",   # Deserialization of Untrusted Data
    "CWE-94",    # Code Injection
    "CWE-1336",  # Template Engine Injection (SSTI)
    "CWE-917",   # Expression Language Injection
    "CWE-611",   # XXE
    "CWE-88",    # Argument Injection
    "CWE-90",    # LDAP Injection
    "CWE-643",   # XPath Injection
    "CWE-91",    # XML Injection
    "CWE-96",    # Static Code Injection
    "CWE-918",   # SSRF (weak URL validation -> internal pivot / metadata)
    "CWE-434",   # Unrestricted Upload of Dangerous Type
    "CWE-22",    # Path Traversal
    "CWE-73",    # External Control of File Name or Path
    "CWE-79",    # Cross-site Scripting
    "CWE-915",   # Mass Assignment / Prototype Pollution
    "CWE-15",    # External Control of System or Configuration Setting
    "CWE-472",   # External Control of Assumed-Immutable Web Parameter
    "CWE-807",   # Reliance on Untrusted Inputs in a Security Decision
    "CWE-1289",  # Improper Validation of Unsafe Equivalence in Input
    "CWE-184",   # Incomplete List of Disallowed Inputs
    "CWE-179",   # Incorrect Behavior Order: Early Validation
    "CWE-1173",  # Improper Use of Validation Framework
    "CWE-112",   # Missing XML Validation
    "CWE-76",    # Improper Neutralization of Equivalent Special Elements
    "CWE-838",   # Inappropriate Encoding for Output Context
    "CWE-93",    # CRLF Injection
    "CWE-470",   # Unsafe Reflection
    "CWE-646",   # Reliance on File Name or Extension of Supplied File
    "CWE-626",   # Poison Null Byte (validation-bypass enabler)
})

# Tier 3 - SOPHISTICATED-SYSTEM TARGETS (the third criterion): faults whose
# locus is an AuthenticationMechanism / AuthorizationSystem / session System -
# full-account takeover power, but gated behind the mechanism itself.
_TIER_SOPHISTICATED_SYSTEMS = frozenset({
    "CWE-306",   # Missing Authentication for Critical Function
    "CWE-288",   # Authentication Bypass Using an Alternate Path
    "CWE-290",   # Authentication Bypass by Spoofing
    "CWE-304",   # Missing Critical Step in Authentication
    "CWE-302",   # Authentication Bypass by Assumed-Immutable Data
    "CWE-294",   # Authentication Bypass by Capture-replay
    "CWE-289",   # Authentication Bypass by Alternate Name
    "CWE-620",   # Unverified Password Change
    "CWE-640",   # Weak Password Recovery Mechanism
    "CWE-613",   # Insufficient Session Expiration
    "CWE-384",   # Session Fixation
    "CWE-352",   # Cross-Site Request Forgery
    "CWE-346",   # Origin Validation Error
    "CWE-488",   # Exposure of Data Element to Wrong Session
    "CWE-565",   # Reliance on Cookies without Validation
    "CWE-307",   # Improper Restriction of Excessive Auth Attempts
    "CWE-308",   # Use of Single-factor Authentication
    "CWE-521",   # Weak Password Requirements
    "CWE-1393",  # Use of Default Password
    "CWE-444",   # HTTP Request/Response Smuggling (intermediary systems)
    "CWE-644",   # HTTP Header Scripting Syntax
})

# Tier 4 - SENSITIVE-DATA EXPOSURE & HYGIENE: real findings, but disclosure /
# degradation rather than direct compromise. Includes the transitional
# password-storage cluster (257/260/261) kept by the operator pass.
_TIER_EXPOSURE = frozenset({
    "CWE-201",   # Sensitive Information Into Sent Data
    "CWE-532",   # Sensitive Information into Log File
    "CWE-312",   # Cleartext Storage of Sensitive Information
    "CWE-524",   # Use of Cache Containing Sensitive Information
    "CWE-612",   # Improper Authorization of Index Containing Sensitive Info
    "CWE-1230",  # Exposure of Sensitive Information Through Metadata
    "CWE-538",   # Sensitive Information into Externally-Accessible File
    "CWE-540",   # Inclusion of Sensitive Information in Source Code
    "CWE-552",   # Files or Directories Accessible to External Parties
    "CWE-248",   # Uncaught Exception
    "CWE-489",   # Active Debug Code
    "CWE-749",   # Exposed Dangerous Method or Function
    "CWE-229",   # Improper Handling of Values
    "CWE-117",   # Improper Output Neutralization for Logs
    "CWE-1236",  # CSV Formula Injection
    "CWE-837",   # Improper Enforcement of a Single, Unique Action
    "CWE-776",   # XML Entity Expansion
    "CWE-827",   # Improper Control of Document Type Definition
    "CWE-645",   # Overly Restrictive Account Lockout (availability)
    "CWE-257",   # Storing Passwords in a Recoverable Format
    "CWE-260",   # Password in Configuration File
    "CWE-261",   # Weak Encoding for Password
})

# Tier 5 - RESIDUAL: phishing-grade redirects, UI redress, supply-chain posture,
# race conditions - valid checklist entries, lowest phase-1 hunting yield.
_TIER_RESIDUAL = frozenset({
    "CWE-601",   # Open Redirect
    "CWE-1021",  # Clickjacking
    "CWE-1022",  # window.opener Access (reverse tabnabbing)
    "CWE-1104",  # Unmaintained Third Party Components
    "CWE-1395",  # Dependency on Vulnerable Third-Party Component
    "CWE-367",   # TOCTOU Race Condition
    "CWE-494",   # Download of Code Without Integrity Check
    "CWE-829",   # Inclusion of Functionality from Untrusted Control Sphere
})

#: An unanalysed fault_id lands here - AFTER every analysed tier (conservative:
#: the policy never claims a criticality the analysis has not granted).
_DEFAULT_TIER = 5

_TIERS: tuple[tuple[int, frozenset[str]], ...] = (
    (0, _TIER_ACCESS_CONTROL),
    (1, _TIER_VALIDATION),
    (2, _TIER_SOPHISTICATED_SYSTEMS),
    (3, _TIER_EXPOSURE),
    (4, _TIER_RESIDUAL),
)

_RISK_TIERS: Mapping[str, int] = {
    fault_id: tier
    for tier, ids in _TIERS
    for fault_id in ids
}


def risk_tier(fault_id: str) -> int:
    """The fault's risk tier (lower = riskier = processed earlier).

    Total and deterministic: an unanalysed id falls to `_DEFAULT_TIER` (after
    every analysed tier) rather than raising - the schedule must stay total
    over whatever the catalogue carries."""
    return _RISK_TIERS.get(fault_id, _DEFAULT_TIER)


def sort_risk_desc(fault_ids: list[str]) -> list[str]:
    """The faults re-sorted RISK-DESCENDING (tier ascending), stable within a
    tier so equal-risk faults keep their intake (catalogue) relative order -
    determinism is preserved, only the risk semantics change."""
    return sorted(fault_ids, key=risk_tier)
