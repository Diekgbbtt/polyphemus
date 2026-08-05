# Fault web-relevance rankings (critic pass)

Scored by 4 parallel critic subagents (critical-thinking-logical-reasoning +
prompt-engineering-patterns skills) on web-domain applicability 0.0-1.0.
Kept: score >= 0.6, plus semantic evaluation of the 0.5-0.7 band.
Semantic keeps below 0.6: CWE-841 (logic-flaws topic family), CWE-1394
(default crypto keys - common web finding), CWE-367 (TOCTOU - race-conditions
topic family).

| fault_id | name | score | kept | rationale |
| --- | --- | --- | --- | --- |
| CWE-1004 | Sensitive Cookie Without 'HttpOnly' Flag | 0.95 | KEEP | Direct browser-side cookie protection failure, trivially observed and exploited in any web app. |
| CWE-1007 | Insufficient Visual Distinction of Homoglyphs Presented to User | 0.50 | drop | Anti-phishing UI concern; marginal as a recon-triggerable fault in web apps. |
| CWE-102 | Struts: Duplicate Validation Forms | 0.35 | drop | Legacy Struts framework flaw; rarely present in modern web applications. |
| CWE-1021 | Improper Restriction of Rendered UI Layers or Frames | 0.90 | KEEP | Clickjacking; core browser-layer web vulnerability. |
| CWE-1022 | Use of Web Link to Untrusted Target with window.opener Access | 0.85 | KEEP | Reverse tabnabbing; directly exploitable client-side web issue. |
| CWE-103 | Struts: Incomplete validate() Method Definition | 0.35 | drop | Legacy Struts-specific; effectively extinct in modern web stacks. |
| CWE-1039 | Inadequate Detection or Handling of Adversarial Input Perturbations in Automated Recognition Mechanism | 0.30 | drop | Adversarial-ML concern; only rare ML-backed web endpoints, not mainstream. |
| CWE-104 | Struts: Form Bean Does Not Extend Validation Class | 0.35 | drop | Legacy Struts framework misuse; narrow applicability today. |
| CWE-105 | Struts: Form Field Without Validator | 0.35 | drop | Legacy Struts validation gap; superseded by modern frameworks. |
| CWE-106 | Struts: Plug-in Framework not in Use | 0.30 | drop | Legacy Struts architecture choice; negligible modern web relevance. |
| CWE-108 | Struts: Unvalidated Action Form | 0.35 | drop | Legacy Struts-specific validation omission; dated web framework. |
| CWE-109 | Struts: Validator Turned Off | 0.30 | drop | Legacy Struts configuration fault; obsolete in modern web apps. |
| CWE-11 | ASP.NET Misconfiguration: Creating Debug Binary | 0.70 | KEEP | ASP.NET-specific info disclosure; genuinely web-reachable but framework-bound. |
| CWE-1104 | Use of Unmaintained Third Party Components | 0.70 | KEEP | Supply-chain risk applicable to web apps, though broad and non-mechanistic. |
| CWE-112 | Missing XML Validation | 0.70 | KEEP | XXE-adjacent; web APIs consuming XML are narrower but genuinely affected. |
| CWE-1125 | Excessive Attack Surface | 0.40 | drop | Abstract meta-metric; not a concrete web-detectable fault mechanism. |
| CWE-113 | Improper Neutralization of CRLF Sequences in HTTP Headers | 0.85 | KEEP | HTTP request/response splitting; classic web-protocol injection. |
| CWE-114 | Process Control | 0.60 | KEEP | Command/library execution from untrusted sources; web-reachable via RCE paths. |
| CWE-115 | Misinterpretation of Input | 0.30 | drop | Overly abstract base class; no concrete web exploit mechanism. |
| CWE-117 | Improper Output Neutralization for Logs | 0.80 | KEEP | Log injection in web apps; observable and exploitable. |
| CWE-1173 | Improper Use of Validation Framework | 0.50 | drop | Generic framework-usage fault; indirect web applicability. |
| CWE-1174 | ASP.NET Misconfiguration: Improper Model Validation | 0.60 | KEEP | ASP.NET-specific validation gap; web-relevant but framework-bound. |
| CWE-1188 | Initialization of a Resource with an Insecure Default | 0.60 | KEEP | Applies to web infra defaults (services, credentials) across domains. |
| CWE-12 | ASP.NET Misconfiguration: Missing Custom Error Page | 0.65 | KEEP | ASP.NET-specific information disclosure; web-reachable but framework-bound. |
| CWE-1204 | Generation of Weak Initialization Vector (IV) | 0.35 | drop | Crypto-primitive misuse; web exposure only via app-level crypto, uncommon. |
| CWE-1220 | Insufficient Granularity of Access Control | 0.80 | KEEP | Authorization granularity; direct and common in web apps. |
| CWE-1230 | Exposure of Sensitive Information Through Metadata | 0.70 | KEEP | Metadata leaks (EXIF, git, config) observable via web responses. |
| CWE-1236 | Improper Neutralization of Formula Elements in a CSV File | 0.70 | KEEP | CSV injection in web export features; real but conditional on user action. |
| CWE-1254 | Incorrect Comparison Logic Granularity | 0.40 | drop | Generic comparison bug; web relevance speculative. |
| CWE-1269 | Product Released in Non-Release Configuration | 0.50 | drop | Deployment configuration concern; web-app relevant but generic. |
| CWE-1275 | Sensitive Cookie with Improper SameSite Attribute | 0.95 | KEEP | SameSite cookie handling; direct CSRF-relevant web control. |
| CWE-1284 | Improper Validation of Specified Quantity in Input | 0.40 | drop | Generic input-validation base; possible in web parsers but abstract. |
| CWE-1285 | Improper Validation of Specified Index, Position, or Offset in Input | 0.40 | drop | Buffer/file indexing; more memory-level than typical web handling. |
| CWE-1286 | Improper Validation of Syntactic Correctness of Input | 0.40 | drop | Generic parser validation; indirect web applicability. |
| CWE-1287 | Improper Validation of Specified Type of Input | 0.40 | drop | Generic type-checking base; weak direct web exploitability. |
| CWE-1288 | Improper Validation of Consistency within Input | 0.40 | drop | Generic multi-field consistency; no common web attack mapping. |
| CWE-1289 | Improper Validation of Unsafe Equivalence in Input | 0.40 | drop | Path/identifier equivalence issues; marginal web exposure. |
| CWE-129 | Improper Validation of Array Index | 0.35 | drop | Buffer-overrun family; mostly memory-safety domains, rare in web. |
| CWE-13 | ASP.NET Misconfiguration: Password in Configuration File | 0.60 | KEEP | Config-file secret exposure; ASP.NET-bound but web-reachable. |
| CWE-130 | Improper Handling of Length Parameter Inconsistency | 0.35 | drop | Parser length mismatch; memory-safety adjacent, low web frequency. |
| CWE-1321 | Improperly Controlled Modification of Object Prototype Attributes | 0.90 | KEEP | Prototype pollution; core modern JavaScript web vulnerability. |
| CWE-1327 | Binding to an Unrestricted IP Address | 0.75 | KEEP | Infra misconfiguration exposing services; web-reachable. |
| CWE-1329 | Reliance on Component That is Not Updateable | 0.65 | KEEP | Unpatchable dependencies; applies to web infra and embedded alike. |
| CWE-1336 | Improper Neutralization of Special Elements Used in a Template Engine | 0.90 | KEEP | SSTI; widely exploited server-side web injection. |
| CWE-134 | Use of Externally-Controlled Format String | 0.25 | drop | C-family printf flaw; rare in modern web languages. |
| CWE-1385 | Missing Origin Validation in WebSockets | 0.85 | KEEP | WebSocket hijacking; directly exploitable in web apps. |
| CWE-1386 | Insecure Operation on Windows Junction / Mount Point | 0.15 | drop | Windows filesystem internals; effectively non-web domain. |
| CWE-1392 | Use of Default Credentials | 0.85 | KEEP | Default creds on web services; common recon finding. |
| CWE-1393 | Use of Default Password | 0.85 | KEEP | Default passwords; trivially checked in web recon. |
| CWE-1394 | Use of Default Cryptographic Key | 0.50 | KEEP | Hardcoded keys more typical of devices; web exposure conditional. |
| CWE-1395 | Dependency on Vulnerable Third-Party Component | 0.85 | KEEP | Known-vulnerable web dependencies; primary recon target. |
| CWE-1427 | Improper Neutralization of Input Used for LLM Prompting | 0.85 | KEEP | Prompt injection; relevant wherever web apps integrate LLMs. |
| CWE-1428 | Reliance on HTTP instead of HTTPS | 0.85 | KEEP | Missing TLS; directly observable in web recon. |
| CWE-15 | External Control of System or Configuration Setting | 0.65 | KEEP | Config injection reachable via web endpoints; conditional. |
| CWE-166 | Improper Handling of Missing Special Element | 0.35 | drop | Generic parser robustness; no common web attack mapping. |
| CWE-167 | Improper Handling of Additional Special Element | 0.35 | drop | Generic parser robustness; weak web relevance. |
| CWE-168 | Improper Handling of Inconsistent Special Elements | 0.35 | drop | Generic parser robustness; marginal web applicability. |
| CWE-179 | Incorrect Behavior Order: Early Validation | 0.60 | KEEP | Validation-order bypasses occur in web input handling. |
| CWE-180 | Incorrect Behavior Order: Validate Before Canonicalize | 0.70 | KEEP | Canonicalization bypass (paths, encodings); classic web flaw. |
| CWE-181 | Incorrect Behavior Order: Validate Before Filter | 0.55 | drop | Validation-before-filter logic; web applicable but narrow. |
| CWE-183 | Permissive List of Allowed Inputs | 0.45 | drop | Allow-list philosophy flaw; abstract, indirect web exploitation. |
| CWE-184 | Incomplete List of Disallowed Inputs | 0.45 | drop | Deny-list incompleteness; abstract and indirect. |
| CWE-201 | Insertion of Sensitive Information Into Sent Data | 0.80 | KEEP | Sensitive data leaks in responses; common web finding. |
| CWE-202 | Exposure of Sensitive Information Through Data Queries | 0.40 | drop | Statistical side-channel inference; marginal web exploitability. |
| CWE-203 | Observable Discrepancy | 0.80 | KEEP | User enumeration and oracle behavior; core web recon signal. |
| CWE-204 | Observable Response Discrepancy | 0.80 | KEEP | Response-based oracles (enumeration); classic web technique. |
| CWE-205 | Observable Behavioral Discrepancy | 0.55 | drop | Behavior-based oracles; web relevant but broader. |
| CWE-206 | Observable Internal Behavioral Discrepancy | 0.40 | drop | Fine-grained behavior oracle; narrow web exposure. |
| CWE-207 | Observable Behavioral Discrepancy With Equivalent Products | 0.30 | drop | Product fingerprinting; niche, non-exploit fault. |
| CWE-208 | Observable Timing Discrepancy | 0.85 | KEEP | Timing oracles and side channels; directly usable in web attacks. |
| CWE-209 | Generation of Error Message Containing Sensitive Information | 0.85 | KEEP | Stack-trace/verbose errors; routine web recon finding. |
| CWE-210 | Self-generated Error Message Containing Sensitive Information | 0.75 | KEEP | Verbose app errors; web-reachable info disclosure. |
| CWE-211 | Externally-Generated Error Message Containing Sensitive Information | 0.75 | KEEP | Interpreter/framework error leaks; common in web responses. |
| CWE-213 | Exposure of Sensitive Information Due to Incompatible Policies | 0.40 | drop | Multi-policy information conflict; vague web applicability. |
| CWE-214 | Invocation of Process Using Visible Sensitive Information | 0.30 | drop | OS process-argument visibility; marginal for web apps. |
| CWE-215 | Insertion of Sensitive Information Into Debugging Code | 0.60 | KEEP | Debug leaks in web endpoints; conditional but real. |
| CWE-219 | Storage of File with Sensitive Data Under Web Root | 0.80 | KEEP | Sensitive files served directly; classic web exposure. |
| CWE-22 | Improper Limitation of a Pathname to a Restricted Directory | 0.95 | KEEP | Path traversal; premier web file-access vulnerability. |
| CWE-220 | Storage of File With Sensitive Data Under FTP Root | 0.30 | drop | FTP-server concern; outside the web application stack. |
| CWE-222 | Truncation of Security-relevant Information | 0.45 | drop | Logging truncation; audit concern, indirect web impact. |
| CWE-223 | Omission of Security-relevant Information | 0.45 | drop | Logging omission; audit concern, indirect web impact. |
| CWE-224 | Obscured Security-relevant Information by Alternate Name | 0.35 | drop | Log identity confusion; niche audit-side fault. |
| CWE-229 | Improper Handling of Values | 0.40 | drop | Generic parameter handling; weak direct web exploitability. |
| CWE-23 | Relative Path Traversal | 0.85 | KEEP | Dot-dot path traversal variant; direct web exploitation. |
| CWE-230 | Improper Handling of Missing Values | 0.45 | drop | Null/empty parameter handling; web applicable but generic. |
| CWE-231 | Improper Handling of Extra Values | 0.45 | drop | Extra values; HTTP parameter-related edge cases. |
| CWE-232 | Improper Handling of Undefined Values | 0.45 | drop | Undefined parameter values; web applicable but generic. |
| CWE-233 | Improper Handling of Parameters | 0.40 | drop | Generic parameter mishandling; abstract base. |
| CWE-234 | Failure to Handle Missing Parameter | 0.35 | drop | Stack-pop description indicates C-level fault; web exposure low. |
| CWE-235 | Improper Handling of Extra Parameters | 0.40 | drop | Duplicate parameters; HTTP parameter pollution adjacent. |
| CWE-236 | Improper Handling of Undefined Parameters | 0.40 | drop | Unknown parameter names; generic handling gap. |
| CWE-237 | Improper Handling of Structural Elements | 0.35 | drop | Complex-structure parsing; generic and abstract. |
| CWE-238 | Improper Handling of Incomplete Structural Elements | 0.35 | drop | Parser robustness on incomplete structures; marginal. |
| CWE-239 | Failure to Handle Incomplete Element | 0.35 | drop | Incomplete-element handling; generic parser fault. |
| CWE-24 | Path Traversal: '../filedir' | 0.85 | KEEP | Concrete path traversal form; direct web exploitation. |
| CWE-240 | Improper Handling of Inconsistent Structural Elements | 0.35 | drop | Structural consistency in parsers; marginal web use. |
| CWE-241 | Improper Handling of Unexpected Data Type | 0.40 | drop | Type-mismatch handling; web applicable but generic. |
| CWE-248 | Uncaught Exception | 0.50 | drop | Unhandled exceptions cause 500s/leaks; generic across domains. |
| CWE-25 | Path Traversal: '/../filedir' | 0.85 | KEEP | Concrete path traversal form; direct web exploitation. |
| CWE-250 | Execution with Unnecessary Privileges | 0.35 | drop | Privilege-level concern; OS-centric, rare in web recon. |
| CWE-252 | Unchecked Return Value | 0.40 | drop | Generic error-handling flaw; indirect web security impact. |
| CWE-253 | Incorrect Check of Function Return Value | 0.40 | drop | Generic error-checking flaw; indirect web security impact. |
| CWE-257 | Storing Passwords in a Recoverable Format | 0.80 | KEEP | Weak password storage; core web auth finding. |
| CWE-258 | Empty Password in Configuration File | 0.60 | KEEP | Empty-credential config; web-reachable auth flaw. |
| CWE-26 | Path Traversal: '/dir/../filename' | 0.85 | KEEP | Concrete path traversal form; direct web exploitation. |
| CWE-260 | Password in Configuration File | 0.85 | KEEP | Passwords in web-app config/env files are common, directly exposed via misconfig. |
| CWE-261 | Weak Encoding for Password | 0.80 | KEEP | Trivial base64-style password obfuscation seen in web configs and client code. |
| CWE-262 | Not Using Password Aging | 0.55 | drop | Policy weakness, not a directly observable exploit; web relevance indirect. |
| CWE-263 | Password Aging with Long Expiration | 0.50 | drop | Policy setting only; rarely a matchable web-app fault. |
| CWE-266 | Incorrect Privilege Assignment | 0.85 | KEEP | Directly maps to web-app authorization/role misconfiguration flaws. |
| CWE-267 | Privilege Defined With Unsafe Actions | 0.80 | KEEP | Over-privileged roles are a common web-app RBAC flaw. |
| CWE-268 | Privilege Chaining | 0.75 | KEEP | Escalation via combined privileges occurs in web authorization logic. |
| CWE-27 | Path Traversal: 'dir/../../filename' | 0.95 | KEEP | Canonical web vulnerability, universally exploited through URL/file parameters. |
| CWE-270 | Privilege Context Switching Error | 0.40 | drop | Setuid-style OS privilege switching; web exposure limited to process hardening. |
| CWE-272 | Least Privilege Violation | 0.35 | drop | chroot/root-dropping is OS-process level; only marginal infra relevance. |
| CWE-273 | Improper Check for Dropped Privileges | 0.35 | drop | OS-level privilege drop verification; not reachable via web attack surface. |
| CWE-274 | Improper Handling of Insufficient Privileges | 0.60 | KEEP | Permission-denied handling flaws affect web authorization flows. |
| CWE-276 | Incorrect Default Permissions | 0.60 | KEEP | World-writable web files/configs exploitable via hosting or uploads. |
| CWE-277 | Insecure Inherited Permissions | 0.35 | drop | Filesystem inheritance semantics, predominantly OS-level. |
| CWE-278 | Insecure Preserved Inherited Permissions | 0.35 | drop | Archive-extraction permission preservation; OS-centric despite upload exposure. |
| CWE-279 | Incorrect Execution-Assigned Permissions | 0.30 | drop | Runtime chmod violations, OS filesystem-level, rare in web stack. |
| CWE-28 | Path Traversal: '..\filedir' | 0.90 | KEEP | Backslash traversal hits Windows-hosted web apps commonly. |
| CWE-280 | Improper Handling of Insufficient Permissions or Privileges | 0.55 | drop | Error-path authorization handling; narrower web exposure than CWE-274. |
| CWE-281 | Improper Preservation of Permissions | 0.30 | drop | Copy/restore permission semantics, OS-level filesystem concern. |
| CWE-283 | Unverified Ownership | 0.70 | KEEP | Underlies IDOR/resource-ownership flaws frequent in web APIs. |
| CWE-288 | Authentication Bypass Using an Alternate Path or Channel | 0.90 | KEEP | Alternate endpoints bypassing auth are staple web-app findings. |
| CWE-289 | Authentication Bypass by Alternate Name | 0.70 | KEEP | Alternate hostname/case/file-name auth bypass occurs in web apps. |
| CWE-29 | Path Traversal: '\..\filename' | 0.85 | KEEP | Leading-backslash traversal variant, relevant on Windows web servers. |
| CWE-290 | Authentication Bypass by Spoofing | 0.75 | KEEP | Spoofed headers/IP/client identity used to bypass web auth. |
| CWE-291 | Reliance on IP Address for Authentication | 0.80 | KEEP | IP-allowlist auth is a classic web-app anti-pattern. |
| CWE-293 | Using Referer Field for Authentication | 0.85 | KEEP | HTTP Referer-based CSRF/auth decisions are squarely web-specific. |
| CWE-294 | Authentication Bypass by Capture-replay | 0.60 | KEEP | Replay of API requests possible when TLS/nonce protections absent. |
| CWE-295 | Improper Certificate Validation | 0.90 | KEEP | TLS certificate validation flaws are directly web/TLS-relevant. |
| CWE-296 | Improper Following of a Certificate's Chain of Trust | 0.80 | KEEP | Chain validation defects in web/TLS client stacks. |
| CWE-297 | Improper Validation of Certificate with Host Mismatch | 0.85 | KEEP | Hostname-mismatch acceptance is a common TLS misconfiguration. |
| CWE-298 | Improper Validation of Certificate Expiration | 0.75 | KEEP | Expired-cert acceptance is an observable TLS/web config issue. |
| CWE-299 | Improper Check for Certificate Revocation | 0.70 | KEEP | OCSP/CRL gaps in TLS stacks; visible but often disabled by design. |
| CWE-30 | Path Traversal: '\dir\..\filename' | 0.85 | KEEP | Backslash traversal variant for Windows web deployments. |
| CWE-300 | Channel Accessible by Non-Endpoint | 0.70 | KEEP | MITM/interception relevance across TLS and web channels. |
| CWE-301 | Reflection Attack in an Authentication Protocol | 0.30 | drop | Protocol-level reflection attacks; rarely applies to HTTP auth. |
| CWE-302 | Authentication Bypass by Assumed-Immutable Data | 0.80 | KEEP | Hidden fields/client-controlled state used in web auth bypasses. |
| CWE-303 | Incorrect Implementation of Authentication Algorithm | 0.70 | KEEP | Flawed custom auth crypto appears in web backends. |
| CWE-304 | Missing Critical Step in Authentication | 0.75 | KEEP | Skipped verification steps in web auth flows. |
| CWE-305 | Authentication Bypass by Primary Weakness | 0.70 | KEEP | Auth bypass chains from other web weaknesses; matchable. |
| CWE-306 | Missing Authentication for Critical Function | 0.95 | KEEP | Unauthenticated admin/API endpoints are a flagship web finding. |
| CWE-307 | Improper Restriction of Excessive Authentication Attempts | 0.90 | KEEP | Login brute-force protection gaps are routine web findings. |
| CWE-308 | Use of Single-factor Authentication | 0.70 | KEEP | Password-only web logins without MFA; policy-adjacent but observable. |
| CWE-309 | Use of Password System for Primary Authentication | 0.65 | KEEP | Password-only auth critique; valid web context, policy-flavoured. |
| CWE-31 | Path Traversal: 'dir\..\..\filename' | 0.85 | KEEP | Multi-backslash traversal variant on Windows web apps. |
| CWE-312 | Cleartext Storage of Sensitive Information | 0.85 | KEEP | Plaintext secrets in databases/logs/configs are common web findings. |
| CWE-313 | Cleartext Storage in a File or on Disk | 0.75 | KEEP | Server-side plaintext files accessible through web flaws. |
| CWE-314 | Cleartext Storage in the Registry | 0.30 | drop | Windows registry storage is OS-level, marginal for web apps. |
| CWE-315 | Cleartext Storage of Sensitive Information in a Cookie | 0.90 | KEEP | Plaintext sensitive cookies are a direct web-app finding. |
| CWE-316 | Cleartext Storage of Sensitive Information in Memory | 0.40 | drop | Memory-level concern; weak web observability, mostly non-web. |
| CWE-317 | Cleartext Storage of Sensitive Information in GUI | 0.20 | drop | Desktop GUI display concern; effectively no web relevance. |
| CWE-318 | Cleartext Storage of Sensitive Information in Executable | 0.40 | drop | Embedded secrets in binaries; mobile/desktop-centric, weak web link. |
| CWE-319 | Cleartext Transmission of Sensitive Information | 0.90 | KEEP | Plaintext HTTP transmission of sensitive data is core web finding. |
| CWE-32 | Path Traversal: '...' (Triple Dot) | 0.85 | KEEP | Triple-dot traversal bypass, exploited in web path handling. |
| CWE-322 | Key Exchange without Entity Authentication | 0.60 | KEEP | TLS/SSH-style key exchange; web-relevant but rarely observable. |
| CWE-323 | Reusing a Nonce, Key Pair in Encryption | 0.55 | drop | Crypto primitive misuse; web apps use crypto libraries, narrow exposure. |
| CWE-324 | Use of a Key Past its Expiration Date | 0.50 | drop | Crypto key policy; weak direct web-app observability. |
| CWE-325 | Missing Cryptographic Step | 0.55 | drop | Crypto algorithm step omission; implementation-level, niche in web. |
| CWE-33 | Path Traversal: '....' (Multiple Dot) | 0.85 | KEEP | Multiple-dot traversal bypass variant in web path handling. |
| CWE-331 | Insufficient Entropy | 0.70 | KEEP | Weak random tokens/session IDs directly weaken web security. |
| CWE-332 | Insufficient Entropy in PRNG | 0.70 | KEEP | Predictable session/CSRF tokens from PRNG entropy gaps. |
| CWE-333 | Improper Handling of Insufficient Entropy in TRNG | 0.20 | drop | Hardware TRNG failure handling, embedded/non-web domain. |
| CWE-334 | Small Space of Random Values | 0.70 | KEEP | Brute-forceable tokens are web-relevant (sessions, reset codes). |
| CWE-335 | Incorrect Usage of Seeds in Pseudo-Random Number Generator (PRNG) | 0.65 | KEEP | Seed management flaws yield predictable web tokens. |
| CWE-336 | Same Seed in Pseudo-Random Number Generator (PRNG) | 0.60 | KEEP | Constant seeds cause reproducible web tokens across restarts. |
| CWE-337 | Predictable Seed in Pseudo-Random Number Generator (PRNG) | 0.60 | KEEP | Time/PID-seeded tokens are web-predictable in practice. |
| CWE-338 | Use of Cryptographically Weak Pseudo-Random Number Generator (PRNG) | 0.65 | KEEP | rand()-based web tokens are a classic finding. |
| CWE-339 | Small Seed Space in PRNG | 0.60 | KEEP | Small seed space allows web token brute force. |
| CWE-34 | Path Traversal: '....//' | 0.85 | KEEP | Doubled-dot-slash traversal bypass, web filter evasion. |
| CWE-341 | Predictable from Observable State | 0.60 | KEEP | Observable-state prediction applies to web identifiers/tokens. |
| CWE-342 | Predictable Exact Value from Previous Values | 0.60 | KEEP | Sequence prediction of web tokens/IDs. |
| CWE-343 | Predictable Value Range from Previous Values | 0.55 | drop | Range inference on generated values; narrower token prediction case. |
| CWE-344 | Use of Invariant Value in Dynamically Changing Context | 0.45 | drop | Hardcoded values across environments; weak, indirect web relevance. |
| CWE-347 | Improper Verification of Cryptographic Signature | 0.80 | KEEP | JWT/API signature verification bypasses are major web findings. |
| CWE-348 | Use of Less Trusted Source | 0.45 | drop | Trust-source confusion; indirect, rarely observed in web recon. |
| CWE-349 | Acceptance of Extraneous Untrusted Data With Trusted Data | 0.55 | drop | Contaminating trusted processing; niche but web-reachable. |
| CWE-35 | Path Traversal: '.../...//' | 0.85 | KEEP | Doubled-triple-dot traversal bypass in web filters. |
| CWE-350 | Reliance on Reverse DNS Resolution for a Security-Critical Action | 0.60 | KEEP | rDNS-based decisions appear in web security checks (e.g. email). |
| CWE-351 | Insufficient Type Distinction | 0.50 | drop | Type confusion; web-relevant mostly via serialization edge cases. |
| CWE-352 | Cross-Site Request Forgery (CSRF) | 1.00 | KEEP | The canonical web application vulnerability; fully in-domain. |
| CWE-353 | Missing Support for Integrity Check | 0.45 | drop | Transmission checksums mostly moot under TLS; weak web signal. |
| CWE-354 | Improper Validation of Integrity Check Value | 0.40 | drop | Checksum validation flaws; file/OS-oriented, marginal web. |
| CWE-356 | Product UI does not Warn User of Unsafe Actions | 0.55 | drop | Web-UI consent warnings; social-engineering flavoured, narrow. |
| CWE-357 | Insufficient UI Warning of Dangerous Operations | 0.45 | drop | UI warning subtlety; weak as a technical web finding. |
| CWE-358 | Improperly Implemented Security Check for Standard | 0.50 | drop | Generic protocol/standard implementation defect; indirect web. |
| CWE-36 | Absolute Path Traversal | 0.90 | KEEP | Absolute-path traversal is a classic web file-read vector. |
| CWE-360 | Trust of System Event Data | 0.40 | drop | Trusting spoofable event sources; marginal web applicability. |
| CWE-363 | Race Condition Enabling Link Following | 0.35 | drop | Symlink race in local filesystem; weak web exposure. |
| CWE-366 | Race Condition within a Thread | 0.40 | drop | Concurrency defect; web server-side possible but rarely HTTP-observable. |
| CWE-367 | Time-of-check Time-of-use (TOCTOU) Race Condition | 0.45 | KEEP | TOCTOU on web resources; conditional, usually filesystem/local. |
| CWE-368 | Context Switching Race Condition | 0.30 | drop | OS privilege-switching races; non-web domain. |
| CWE-369 | Divide By Zero | 0.45 | drop | DoS via crafted numeric input; possible but rare in web. |
| CWE-37 | Path Traversal: '/absolute/pathname/here' | 0.90 | KEEP | Slash absolute path input accepted by web apps; classic vector. |
| CWE-370 | Missing Check for Certificate Revocation after Initial Check | 0.60 | KEEP | Long-lived TLS connections skipping re-validation; niche but real. |
| CWE-374 | Passing Mutable Objects to an Untrusted Method | 0.30 | drop | Language-level API flaw; desktop/library-centric, weak web. |
| CWE-375 | Returning a Mutable Object to an Untrusted Caller | 0.30 | drop | Language-level API flaw; desktop/library-centric, weak web. |
| CWE-378 | Creation of Temporary File With Insecure Permissions | 0.35 | drop | Temp-file permissions; local/OS-level, weak web link. |
| CWE-379 | Creation of Temporary File in Directory with Insecure Permissions | 0.35 | drop | Temp-dir permissions; local/OS-level, weak web link. |
| CWE-38 | Path Traversal: '\absolute\pathname\here' | 0.85 | KEEP | Backslash absolute path on Windows web servers. |
| CWE-382 | J2EE Bad Practices: Use of System.exit() | 0.50 | drop | Container shutdown via request; legacy-Java web relevance only. |
| CWE-384 | Session Fixation | 0.95 | KEEP | Session fixation is a staple web-app session flaw. |
| CWE-39 | Path Traversal: 'C:dirname' | 0.85 | KEEP | Drive-letter path handling on Windows web deployments. |
| CWE-390 | Detection of Error Condition Without Action | 0.45 | drop | Error-handling gap; generic, indirect web effect. |
| CWE-391 | Unchecked Error Condition | 0.45 | drop | Ignored errors enabling unexpected behavior; generic and indirect. |
| CWE-392 | Missing Report of Error Condition | 0.40 | drop | Missing error reporting; generic, mostly non-web signal. |
| CWE-393 | Return of Wrong Status Code | 0.40 | drop | Wrong return/status codes; generic API-error semantics, low signal. |
| CWE-394 | Unexpected Status Code or Return Value | 0.40 | drop | Generic return-value checking flaw; security impact indirect and hard to observe from recon. |
| CWE-395 | Use of NullPointerException Catch to Detect NULL Pointer Dereference | 0.30 | drop | Java coding anti-pattern, static-analysis detectable only; no web-specific mechanism. |
| CWE-396 | Declaration of Catch for Generic Exception | 0.30 | drop | Generic exception-handling code smell; not observable nor web-specific. |
| CWE-397 | Declaration of Throws for Generic Exception | 0.30 | drop | Broad exception declaration hides detail; code quality, minimal web exposure. |
| CWE-40 | Path Traversal: '\\UNC\share\name\' (Windows UNC Share) | 0.60 | KEEP | Windows-only path traversal via UNC input; real but platform-limited web vector. |
| CWE-41 | Improper Resolution of Path Equivalence | 0.70 | KEEP | Path-equivalence bypasses defeat traversal filters and access controls in web file endpoints. |
| CWE-419 | Unprotected Primary Channel | 0.85 | KEEP | Unauthenticated admin/management interfaces are a common web-app finding. |
| CWE-42 | Path Equivalence: 'filename.' (Trailing Dot) | 0.55 | drop | Windows trailing-dot equivalence bypass; narrower but exploitable in web file access. |
| CWE-420 | Unprotected Alternate Channel | 0.55 | drop | Alternate web-adjacent channels (FTP, debug ports) less protected; secondary exposure. |
| CWE-421 | Race Condition During Access to Alternate Channel | 0.40 | drop | TOCTOU on alternate channels is rare and hard to confirm from web evidence. |
| CWE-425 | Direct Request ('Forced Browsing') | 0.90 | KEEP | Missing authorization on restricted URLs is a core web access-control flaw. |
| CWE-426 | Untrusted Search Path | 0.35 | drop | Search-path hijacking mainly targets desktop/OS binary loading; weak web path. |
| CWE-427 | Uncontrolled Search Path Element | 0.30 | drop | Search-path resource hijack is OS/desktop domain; web exposure theoretical. |
| CWE-428 | Unquoted Search Path or Element | 0.15 | drop | Windows service binary-loading flaw; outside the web application domain. |
| CWE-43 | Path Equivalence: 'filename....' (Multiple Trailing Dot) | 0.55 | drop | Windows multiple trailing-dot equivalence; narrow but web-reachable file bypass. |
| CWE-433 | Unparsed Raw Web Content Delivery | 0.85 | KEEP | Source disclosure via unhandled file extensions is a classic web server issue. |
| CWE-434 | Unrestricted Upload of File with Dangerous Type | 0.95 | KEEP | Upload-driven RCE is a primary web application vulnerability. |
| CWE-437 | Incomplete Model of Endpoint Features | 0.50 | drop | Proxy/WAF state-model gap; web-adjacent but rarely evidenced in recon. |
| CWE-44 | Path Equivalence: 'file.name' (Internal Dot) | 0.55 | drop | Windows internal-dot equivalence bypass; narrow but web file-reachable. |
| CWE-444 | Inconsistent Interpretation of HTTP Requests ('HTTP Request/Response Smuggling') | 0.95 | KEEP | Request smuggling through proxies/WAFs is a modern web-critical flaw. |
| CWE-447 | Unimplemented or Unsupported Feature in UI | 0.50 | drop | Fake security control in UI is generic; web UI relevance indirect. |
| CWE-45 | Path Equivalence: 'file...name' (Multiple Internal Dot) | 0.55 | drop | Windows multiple internal-dot equivalence; narrow web file bypass. |
| CWE-450 | Multiple Interpretations of UI Input | 0.45 | drop | UI confusion between interpretations; web relevance indirect and uncommon. |
| CWE-453 | Insecure Default Variable Initialization | 0.30 | drop | Default-value flaw in code; no distinctive web mechanism or observability. |
| CWE-454 | External Initialization of Trusted Variables or Data Stores | 0.40 | drop | Untrusted initialization is generic; web form only via unusual env/CLI paths. |
| CWE-455 | Non-exit on Failed Initialization | 0.30 | drop | Fails-open on init error is generic code behavior; web exposure indirect. |
| CWE-46 | Path Equivalence: 'filename ' (Trailing Space) | 0.55 | drop | Windows trailing-space equivalence; narrow web file-access bypass. |
| CWE-460 | Improper Cleanup on Thrown Exception | 0.25 | drop | State/lock cleanup flaw is generic code quality; not web-specific. |
| CWE-462 | Duplicate Key in Associative List (Alist) | 0.15 | drop | Lisp alist implementation detail; effectively non-web domain. |
| CWE-47 | Path Equivalence: ' filename' (Leading Space) | 0.55 | drop | Windows leading-space equivalence; narrow web file-access bypass. |
| CWE-470 | Use of Externally-Controlled Input to Select Classes or Code ('Unsafe Reflection') | 0.85 | KEEP | Reflection-based RCE via API/GraphQL input is a real web backend flaw. |
| CWE-472 | External Control of Assumed-Immutable Web Parameter | 0.85 | KEEP | Tampered hidden fields/cookies break authorization logic in web apps. |
| CWE-476 | NULL Pointer Dereference | 0.45 | drop | Crash-based DoS in web backends; observable but generic and usually incidental. |
| CWE-478 | Missing Default Case in Multiple Condition Expression | 0.20 | drop | Switch handling code smell; no web-specific security mechanism. |
| CWE-48 | Path Equivalence: 'file name' (Internal Whitespace) | 0.55 | drop | Windows internal-whitespace equivalence; narrow web file bypass. |
| CWE-484 | Omitted Break Statement in Switch | 0.20 | drop | Fall-through logic bug; generic code quality, no web mechanism. |
| CWE-488 | Exposure of Data Element to Wrong Session | 0.75 | KEEP | Session boundary confusion leaks data between web sessions. |
| CWE-489 | Active Debug Code | 0.80 | KEEP | Debug endpoints enabled in production are a common web finding. |
| CWE-49 | Path Equivalence: 'filename/' (Trailing Slash) | 0.60 | KEEP | Trailing-slash equivalence bypasses URL-rewriting access controls. |
| CWE-491 | Public cloneable() Method Without Final ('Object Hijack') | 0.30 | drop | Java clone bypass is code-level; no web-reachable mechanism. |
| CWE-492 | Use of Inner Class Containing Sensitive Data | 0.25 | drop | Java package-scope class exposure; static code concern, not web-reachable. |
| CWE-493 | Critical Public Variable Without Final Modifier | 0.25 | drop | Mutable public field in Java/C#; code-level, no web exposure. |
| CWE-494 | Download of Code Without Integrity Check | 0.70 | KEEP | Missing SRI/supply-chain integrity applies to web assets and server-side downloads. |
| CWE-497 | Exposure of Sensitive System Information to an Unauthorized Control Sphere | 0.85 | KEEP | System info disclosure via web responses is a staple web finding. |
| CWE-498 | Cloneable Class Containing Sensitive Information | 0.20 | drop | Java clone-based data exposure; code-level, non-web domain. |
| CWE-499 | Serializable Class Containing Sensitive Data | 0.30 | drop | Java serialization data exposure; code-level, mostly static-analysis domain. |
| CWE-5 | J2EE Misconfiguration: Data Transmission Without Encryption | 0.85 | KEEP | Plaintext HTTP transport is a directly observable web/TLS weakness. |
| CWE-50 | Path Equivalence: '//multiple/leading/slash' | 0.60 | KEEP | Multiple leading slashes bypass normalization in web file/URL handlers. |
| CWE-500 | Public Static Field Not Marked Final | 0.20 | drop | Mutable static field in Java/C#; pure code-level concern. |
| CWE-501 | Trust Boundary Violation | 0.50 | drop | Abstract mixing of trusted/untrusted data; conceptually web but not recon-observable. |
| CWE-502 | Deserialization of Untrusted Data | 0.95 | KEEP | Deserialization RCE via APIs is a critical modern web backend flaw. |
| CWE-507 | Trojan Horse | 0.15 | drop | Malicious-code classification, not a web-app exploitable fault; supply-chain domain. |
| CWE-508 | Non-Replicating Malicious Code | 0.10 | drop | Malware taxonomy category; outside web application applicability. |
| CWE-509 | Replicating Malicious Code (Virus or Worm) | 0.10 | drop | Malware taxonomy category; outside web application applicability. |
| CWE-51 | Path Equivalence: '/multiple//internal/slash' | 0.60 | KEEP | Multiple internal slashes bypass normalization in web URL handlers. |
| CWE-510 | Trapdoor | 0.30 | drop | Hidden backdoor access; overlaps web backdoors but framed as malicious code. |
| CWE-512 | Spyware | 0.10 | drop | Malware taxonomy category; outside web application applicability. |
| CWE-52 | Path Equivalence: '/multiple/trailing/slash//' | 0.60 | KEEP | Multiple trailing slashes bypass normalization in web URL handlers. |
| CWE-520 | .NET Misconfiguration: Use of Impersonation | 0.70 | KEEP | .NET web app privilege escalation via impersonation; server config finding. |
| CWE-521 | Weak Password Requirements | 0.85 | KEEP | Weak credential policy is directly assessable on web auth endpoints. |
| CWE-523 | Unprotected Transport of Credentials | 0.90 | KEEP | Login credentials in cleartext HTTP is a classic web finding. |
| CWE-524 | Use of Cache Containing Sensitive Information | 0.45 | drop | Sensitive server-side cache exposure; web-adjacent, conditions unusual. |
| CWE-525 | Use of Web Browser Cache Containing Sensitive Information | 0.80 | KEEP | Sensitive browser cache via missing cache-control headers is web-specific. |
| CWE-526 | Cleartext Storage of Sensitive Information in an Environment Variable | 0.40 | drop | Server env-var secrets are infra-level; weak web observability. |
| CWE-527 | Exposure of Version-Control Repository to an Unauthorized Control Sphere | 0.85 | KEEP | Exposed .git/.svn on web servers is a common, high-value recon finding. |
| CWE-528 | Exposure of Core Dump File to an Unauthorized Control Sphere | 0.15 | drop | Core dump exposure is OS/process-level; not web domain. |
| CWE-529 | Exposure of Access Control List Files to an Unauthorized Control Sphere | 0.20 | drop | ACL file exposure is filesystem/OS-level; web relevance theoretical. |
| CWE-53 | Path Equivalence: '\multiple\\internal\backslash' | 0.55 | drop | Windows backslash equivalence; narrow but web file-reachable. |
| CWE-530 | Exposure of Backup File to an Unauthorized Control Sphere | 0.80 | KEEP | Backup files left in web-accessible dirs leak source and secrets. |
| CWE-531 | Inclusion of Sensitive Information in Test Code | 0.65 | KEEP | Exposed test endpoints/pages on web apps can leak data; moderately common. |
| CWE-532 | Insertion of Sensitive Information into Log File | 0.75 | KEEP | Sensitive data in web logs; observable when logs leak. |
| CWE-535 | Exposure of Information Through Shell Error Message | 0.70 | KEEP | Shell error disclosure from web app failures aids further attack. |
| CWE-536 | Servlet Runtime Error Message Containing Sensitive Information | 0.75 | KEEP | Java servlet stack traces disclose internals to web users. |
| CWE-537 | Java Runtime Error Message Containing Sensitive Information | 0.70 | KEEP | Unhandled Java exception output discloses internals via web responses. |
| CWE-538 | Insertion of Sensitive Information into Externally-Accessible File or Directory | 0.80 | KEEP | Sensitive files in web-accessible locations are a direct web exposure. |
| CWE-539 | Use of Persistent Cookies Containing Sensitive Information | 0.85 | KEEP | Sensitive session data in persistent cookies is a web-specific flaw. |
| CWE-54 | Path Equivalence: 'filedir\' (Trailing Backslash) | 0.55 | drop | Windows trailing-backslash equivalence; narrow web file bypass. |
| CWE-540 | Inclusion of Sensitive Information in Source Code | 0.70 | KEEP | Secrets in source exposed via web repos or backups; web-relevant. |
| CWE-541 | Inclusion of Sensitive Information in an Include File | 0.75 | KEEP | Exposed .inc/config include files leak credentials on web servers. |
| CWE-544 | Missing Standardized Error Handling Mechanism | 0.35 | drop | Generic error-handling inconsistency; security impact indirect. |
| CWE-547 | Use of Hard-coded, Security-relevant Constants | 0.30 | drop | Hardcoded crypto/security constants are static code issues; weak observability. |
| CWE-548 | Exposure of Information Through Directory Listing | 0.90 | KEEP | Web server directory listing is a trivial and common recon finding. |
| CWE-549 | Missing Password Field Masking | 0.35 | drop | Shoulder-surfing UI concern; marginal for modern web and remote attacks. |
| CWE-55 | Path Equivalence: '/./' (Single Dot Directory) | 0.70 | KEEP | '/./' normalization bypass defeats web traversal filters. |
| CWE-550 | Server-generated Error Message Containing Sensitive Information | 0.70 | KEEP | Server error pages disclose internals; common web info leak. |
| CWE-551 | Incorrect Behavior Order: Authorization Before Parsing and Canonicalization | 0.85 | KEEP | URL canonicalization vs authorization order bypasses web access controls. |
| CWE-552 | Files or Directories Accessible to External Parties | 0.80 | KEEP | Misconfigured web-accessible files/dirs are a direct web exposure. |
| CWE-553 | Command Shell in Externally Accessible Directory | 0.85 | KEEP | Web shells in cgi-bin or docroot give direct web RCE. |
| CWE-554 | ASP.NET Misconfiguration: Not Using Input Validation Framework | 0.65 | KEEP | ASP.NET-specific missing validation; framework-scoped but genuinely web. |
| CWE-555 | J2EE Misconfiguration: Plaintext Password in Configuration File | 0.60 | KEEP | Plaintext passwords in J2EE configs; web backend config finding. |
| CWE-556 | ASP.NET Misconfiguration: Use of Identity Impersonation | 0.60 | KEEP | ASP.NET identity impersonation raises privileges; web server config issue. |
| CWE-56 | Path Equivalence: 'filedir*' (Wildcard) | 0.50 | drop | Windows wildcard equivalence; narrow and increasingly historical. |
| CWE-564 | SQL Injection: Hibernate | 0.90 | KEEP | SQLi through Hibernate dynamic queries is a mainstream web injection flaw. |
| CWE-565 | Reliance on Cookies without Validation and Integrity Checking | 0.85 | KEEP | Tamperable cookies drive web auth bypass and privilege escalation. |
| CWE-566 | Authorization Bypass Through User-Controlled SQL Primary Key | 0.90 | KEEP | IDOR-style record access via controlled keys is a common web API flaw. |
| CWE-57 | Path Equivalence: 'fakedir/../realdir/filename' | 0.70 | KEEP | '..' path equivalence defeats web path-based access controls. |
| CWE-58 | Path Equivalence: Windows 8.3 Filename | 0.45 | drop | Windows 8.3 short-name bypass; platform-specific and rare in modern web. |
| CWE-59 | Improper Link Resolution Before File Access ('Link Following') | 0.55 | drop | Symlink following in web file features; mostly local, reachable via upload/extract. |
| CWE-593 | Authentication Bypass: OpenSSL CTX Object Modified after SSL Objects are Created | 0.55 | drop | OpenSSL lifecycle misuse in TLS servers; web-reachable but very narrow. |
| CWE-598 | Use of HTTP Request With Sensitive Query String | 0.85 | KEEP | Sensitive data in URL query strings is a directly observable web flaw. |
| CWE-599 | Missing Validation of OpenSSL Certificate | 0.75 | KEEP | Skipped certificate verification breaks TLS in web server-side clients. |
| CWE-6 | J2EE Misconfiguration: Insufficient Session-ID Length | 0.80 | KEEP | Weak session ID entropy is a genuine web session-handling flaw. |
| CWE-600 | Uncaught Exception in Servlet | 0.70 | KEEP | Uncaught servlet exceptions leak debugging info via web responses. |
| CWE-601 | URL Redirection to Untrusted Site ('Open Redirect') | 0.95 | KEEP | Open redirect is a top-tier, browser-reachable web vulnerability. |
| CWE-606 | Unchecked Input for Loop Condition | 0.35 | drop | Loop-based DoS is generic code behavior; web exposure conditional and indirect. |
| CWE-608 | Struts: Non-private Field in ActionForm Class | 0.65 | KEEP | Java web framework mass-assignment flaw, web-specific but legacy-stack. |
| CWE-61 | UNIX Symbolic Link (Symlink) Following | 0.40 | drop | OS filesystem attack; only via file-upload/temp-file handling paths. |
| CWE-611 | Improper Restriction of XML External Entity Reference | 0.95 | KEEP | XXE is a classic, common API/web-app vulnerability. |
| CWE-612 | Improper Authorization of Index Containing Sensitive Information | 0.60 | KEEP | Search-index leakage is web-reachable but less common. |
| CWE-613 | Insufficient Session Expiration | 0.90 | KEEP | Core web session-management flaw. |
| CWE-614 | Sensitive Cookie in HTTPS Session Without 'Secure' Attribute | 0.95 | KEEP | Directly observable cookie security attribute, common web flaw. |
| CWE-615 | Inclusion of Sensitive Information in Source Code Comments | 0.70 | KEEP | Credential/URL leakage in web app comments, recon-detectable. |
| CWE-616 | Incomplete Identification of Uploaded File Variables (PHP) | 0.50 | drop | Legacy PHP upload handling, genuinely web but dated. |
| CWE-619 | Dangling Database Cursor ('Cursor Injection') | 0.30 | drop | Database-internal resource concern, weak web exposure. |
| CWE-62 | UNIX Hard Link | 0.30 | drop | OS filesystem-level concern, marginal web reachability. |
| CWE-620 | Unverified Password Change | 0.85 | KEEP | Common web account-takeover flaw. |
| CWE-621 | Variable Extraction Error | 0.55 | drop | PHP extract()-style variable injection, web but narrowing. |
| CWE-622 | Improper Validation of Function Hook Arguments | 0.25 | drop | Library/API internal correctness, not recon-observable. |
| CWE-624 | Executable Regular Expression Error | 0.35 | drop | User-controlled regex is rare; ReDoS mostly local concern. |
| CWE-626 | Null Byte Interaction Error (Poison Null Byte) | 0.60 | KEEP | Legacy path-bypass in web apps, mostly retired. |
| CWE-627 | Dynamic Variable Evaluation | 0.55 | drop | PHP variable-variables injection, web but PHP-specific. |
| CWE-628 | Function Call with Incorrectly Specified Arguments | 0.10 | drop | Generic coding error, no web domain specificity. |
| CWE-637 | Unnecessary Complexity in Protection Mechanism | 0.20 | drop | Design-philosophy weakness, not observable via recon. |
| CWE-638 | Not Using Complete Mediation | 0.70 | KEEP | Authorization enforcement gap, directly web-applicable. |
| CWE-639 | Authorization Bypass Through User-Controlled Key | 0.95 | KEEP | IDOR, one of the most common web auth flaws. |
| CWE-64 | Windows Shortcut Following (.LNK) | 0.15 | drop | Desktop-OS file shortcut attack, non-web. |
| CWE-640 | Weak Password Recovery Mechanism for Forgotten Password | 0.85 | KEEP | Standard web auth-flow weakness. |
| CWE-641 | Improper Restriction of Names for Files and Other Resources | 0.60 | KEEP | File-name handling in uploads/downloads, web-reachable. |
| CWE-643 | Improper Neutralization of Data within XPath Expressions | 0.75 | KEEP | XPath injection in API XML backends, genuine but less common. |
| CWE-644 | Improper Neutralization of HTTP Headers for Scripting Syntax | 0.70 | KEEP | Header-based script injection in web responses. |
| CWE-645 | Overly Restrictive Account Lockout Mechanism | 0.80 | KEEP | Web login DoS via lockout abuse. |
| CWE-646 | Reliance on File Name or Extension of Externally-Supplied File | 0.85 | KEEP | Common web file-upload misclassification. |
| CWE-647 | Use of Non-Canonical URL Paths for Authorization Decisions | 0.85 | KEEP | Web-specific URL canonicalization auth bypass. |
| CWE-648 | Incorrect Use of Privileged APIs | 0.30 | drop | OS/library privilege API misuse, mostly non-web. |
| CWE-649 | Reliance on Obfuscation or Encryption of Security-Relevant Inputs without Integrity Checking | 0.55 | drop | Hidden-field/client-state integrity flaw, narrower web case. |
| CWE-65 | Windows Hard Link | 0.15 | drop | Desktop-OS filesystem attack, non-web. |
| CWE-650 | Trusting HTTP Permission Methods on the Server Side | 0.75 | KEEP | GET-with-state-change is a web-protocol-specific flaw. |
| CWE-651 | Exposure of WSDL File Containing Sensitive Information | 0.75 | KEEP | SOAP web-service metadata leakage. |
| CWE-652 | Improper Neutralization of Data within XQuery Expressions | 0.60 | KEEP | XQuery injection, XML-backend APIs only. |
| CWE-654 | Reliance on a Single Factor in a Security Decision | 0.65 | KEEP | Single-factor auth decisions, web-applicable design flaw. |
| CWE-655 | Insufficient Psychological Acceptability | 0.10 | drop | Human-factors design weakness, no recon signature. |
| CWE-656 | Reliance on Security Through Obscurity | 0.30 | drop | Generic design weakness, weak concrete web mechanism. |
| CWE-676 | Use of Potentially Dangerous Function | 0.25 | drop | Code-quality abstraction, no domain-specific mechanism. |
| CWE-683 | Function Call With Incorrect Order of Arguments | 0.10 | drop | Generic coding error, no web domain specificity. |
| CWE-685 | Function Call With Incorrect Number of Arguments | 0.10 | drop | Generic coding error, no web domain specificity. |
| CWE-686 | Function Call With Incorrect Argument Type | 0.10 | drop | Generic coding error, no web domain specificity. |
| CWE-687 | Function Call With Incorrectly Specified Argument Value | 0.10 | drop | Generic coding error, no web domain specificity. |
| CWE-688 | Function Call With Incorrect Variable or Reference as Argument | 0.10 | drop | Generic coding error, no web domain specificity. |
| CWE-689 | Permission Race Condition During Resource Copy | 0.30 | drop | Filesystem permission TOCTOU, mostly OS-level. |
| CWE-690 | Unchecked Return Value to NULL Pointer Dereference | 0.30 | drop | Generic robustness flaw, only web via crash DoS. |
| CWE-692 | Incomplete Denylist to Cross-Site Scripting | 0.90 | KEEP | XSS bypass variant, directly web. |
| CWE-694 | Use of Multiple Resources with Duplicate Identifier | 0.25 | drop | Generic ID-collision issue across domains, weak web mechanism. |
| CWE-7 | J2EE Misconfiguration: Missing Custom Error Page | 0.85 | KEEP | Web error-page info disclosure, J2EE-specific. |
| CWE-708 | Incorrect Ownership Assignment | 0.25 | drop | File-ownership config issue, OS-level, weak web exposure. |
| CWE-73 | External Control of File Name or Path | 0.90 | KEEP | Path traversal, ubiquitous web vulnerability. |
| CWE-749 | Exposed Dangerous Method or Function | 0.90 | KEEP | Unrestricted API endpoints, direct web attack surface. |
| CWE-75 | Failure to Sanitize Special Elements into a Different Plane | 0.50 | drop | Abstract injection class, real mechanism too generic. |
| CWE-756 | Missing Custom Error Page | 0.80 | KEEP | Web info disclosure via default error pages. |
| CWE-757 | Selection of Less-Secure Algorithm During Negotiation | 0.70 | KEEP | TLS algorithm-downgrade in web protocol stacks. |
| CWE-759 | Use of a One-Way Hash without a Salt | 0.85 | KEEP | Password-hashing flaw, standard web backend issue. |
| CWE-76 | Improper Neutralization of Equivalent Special Elements | 0.65 | KEEP | XSS/encoding bypass via equivalent characters. |
| CWE-760 | Use of a One-Way Hash with a Predictable Salt | 0.80 | KEEP | Password-hashing flaw, web auth backend. |
| CWE-766 | Critical Data Element Declared Public | 0.30 | drop | Language-visibility code flaw, not recon-observable. |
| CWE-767 | Access to Critical Private Variable via Public Method | 0.20 | drop | Code-level accessor flaw, no web mechanism. |
| CWE-776 | Improper Restriction of Recursive Entity References in DTDs | 0.80 | KEEP | Billion-laughs XML DoS, web API-reachable. |
| CWE-778 | Insufficient Logging | 0.75 | KEEP | Missing security-event logging, web operations concern. |
| CWE-78 | Improper Neutralization of Special Elements used in an OS Command | 0.90 | KEEP | OS command injection, common web vulnerability. |
| CWE-780 | Use of RSA Algorithm without OAEP | 0.30 | drop | Crypto primitive misuse, mostly non-web primitives. |
| CWE-784 | Reliance on Cookies without Validation and Integrity Checking in a Security Decision | 0.90 | KEEP | Cookie-based auth bypass, directly web. |
| CWE-785 | Use of Path Manipulation Function without Maximum-sized Buffer | 0.15 | drop | C buffer-overflow concern, non-web domain. |
| CWE-79 | Improper Neutralization of Input During Web Page Generation | 0.95 | KEEP | XSS, the defining web vulnerability. |
| CWE-8 | J2EE Misconfiguration: Entity Bean Declared Remote | 0.70 | KEEP | Remote EJB interface exposure, legacy but web-deployed. |
| CWE-80 | Improper Neutralization of Script-Related HTML Tags in a Web Page | 0.90 | KEEP | Basic XSS, directly web. |
| CWE-804 | Guessable CAPTCHA | 0.80 | KEEP | Web bot-control bypass. |
| CWE-807 | Reliance on Untrusted Inputs in a Security Decision | 0.80 | KEEP | Client-supplied values driving auth decisions, web. |
| CWE-81 | Improper Neutralization of Script in an Error Message Web Page | 0.80 | KEEP | XSS via error pages, web-specific. |
| CWE-82 | Improper Neutralization of Script in Attributes of IMG Tags in a Web Page | 0.80 | KEEP | XSS via img attributes, web-specific. |
| CWE-827 | Improper Control of Document Type Definition | 0.85 | KEEP | DTD/XXE-family API attack, web-reachable. |
| CWE-829 | Inclusion of Functionality from Untrusted Control Sphere | 0.70 | KEEP | Third-party library/CDN inclusion, web supply chain. |
| CWE-83 | Improper Neutralization of Script in Attributes in a Web Page | 0.80 | KEEP | XSS via event-handler attributes, web-specific. |
| CWE-830 | Inclusion of Web Functionality from an Untrusted Source | 0.75 | KEEP | Third-party widget inclusion, browser-context compromise. |
| CWE-836 | Use of Password Hash Instead of Password for Authentication | 0.70 | KEEP | Pass-the-hash client auth design, web-applicable. |
| CWE-837 | Improper Enforcement of a Single, Unique Action | 0.60 | KEEP | Single-use token/replay weakness, conditionally web. |
| CWE-838 | Inappropriate Encoding for Output Context | 0.65 | KEEP | Encoding mismatch enabling XSS, web output handling. |
| CWE-84 | Improper Neutralization of Encoded URI Schemes in a Web Page | 0.75 | KEEP | Encoded URI XSS bypass, web-specific. |
| CWE-841 | Improper Enforcement of Behavioral Workflow | 0.50 | KEEP | Multi-step workflow bypass, web but unusual conditions. |
| CWE-842 | Placement of User into Incorrect Group | 0.40 | drop | Admin configuration error, weak recon observability. |
| CWE-85 | Doubled Character XSS Manipulations | 0.75 | KEEP | Character-doubling XSS bypass, web-specific. |
| CWE-86 | Improper Neutralization of Invalid Characters in Identifiers in Web Pages | 0.75 | KEEP | Invalid-character XSS bypass, web-specific. |
| CWE-862 | Missing Authorization | 0.95 | KEEP | Broken access control, core web vulnerability. |
| CWE-87 | Improper Neutralization of Alternate XSS Syntax | 0.80 | KEEP | Alternate-syntax XSS bypass, web-specific. |
| CWE-88 | Improper Neutralization of Argument Delimiters in a Command | 0.80 | KEEP | Argument injection, web-reachable command context. |
| CWE-89 | Improper Neutralization of Special Elements used in an SQL Command | 0.95 | KEEP | SQL injection, defining web vulnerability. |
| CWE-9 | J2EE Misconfiguration: Weak Access Permissions for EJB Methods | 0.60 | KEEP | EJB method permission weakness, legacy web tier. |
| CWE-90 | Improper Neutralization of Special Elements used in an LDAP Query | 0.80 | KEEP | LDAP injection via auth lookups, web-reachable. |
| CWE-91 | XML Injection (aka Blind XPath Injection) | 0.70 | KEEP | XML document tampering in API pipelines. |
| CWE-914 | Improper Control of Dynamically-Identified Variables | 0.50 | drop | Variable-injection family, PHP-centric, narrowing. |
| CWE-915 | Improperly Controlled Modification of Dynamically-Determined Object Attributes | 0.90 | KEEP | Mass assignment, very common modern web API flaw. |
| CWE-916 | Use of Password Hash With Insufficient Computational Effort | 0.85 | KEEP | Weak password hashing, standard web backend issue. |
| CWE-917 | Improper Neutralization of Special Elements used in an Expression Language Statement | 0.85 | KEEP | EL injection in web frameworks (JSP/Spring). |
| CWE-918 | Server-Side Request Forgery (SSRF) | 0.95 | KEEP | SSRF, hallmark modern web vulnerability. |
| CWE-924 | Improper Enforcement of Message Integrity During Transmission | 0.45 | drop | Transport-layer integrity, TLS-adjacent, indirect web. |
| CWE-93 | Improper Neutralization of CRLF Sequences | 0.80 | KEEP | Header injection/splitting, web protocol-specific. |
| CWE-94 | Improper Control of Generation of Code | 0.90 | KEEP | Code injection via web inputs, directly exploitable. |
| CWE-942 | Permissive Cross-domain Security Policy with Untrusted Domains | 0.85 | KEEP | CSP misconfiguration, browser-context web flaw. |
| CWE-95 | Improper Neutralization of Directives in Dynamically Evaluated Code | 0.85 | KEEP | Eval injection, server-side web code execution. |
| CWE-96 | Improper Neutralization of Directives in Statically Saved Code | 0.60 | KEEP | Injection into config/executable files, conditionally web. |
| CWE-97 | Improper Neutralization of Server-Side Includes (SSI) Within a Web Page | 0.70 | KEEP | SSI injection, legacy web-server directive attack. |
| CWE-98 | Improper Control of Filename for Include/Require Statement in PHP Program | 0.85 | KEEP | PHP RFI, classic web file-inclusion attack. |


## Amendment pass - adversarial critique (2026-08-05)

Three parallel critic subagents (critical-thinking-logical-reasoning skill)
argued against every omission rationale with concrete web target profiles;
full verdicts in docs/design/hunting-66-fault-omit-critique.md. 17 of the
188 omissions were wrong (RESTORE) and are re-admitted to the catalogue
(231 -> 248); 23 rationales were corrected (REASON, no restore). The
restored rows, with the critic's counter-argument:

| fault_id | name | score | verdict | critic counter-argument (condensed) |
| --- | --- | --- | --- | --- |
| CWE-42 | Path Traversal: 'filename.' (Trailing Dot) | 0.55 | RESTORE | Win32 strips trailing dots; `shell.asp.` bypasses extension filters on Windows/IIS file endpoints - documented IIS6->modern class |
| CWE-43 | Path Traversal: '....' (Multiple Dot) | 0.55 | RESTORE | Multi-dot evades filters that learned to block single dots; same Windows family |
| CWE-44 | Path Equivalence: Internal Dot | 0.55 | RESTORE | Internal-dot forms defeat string path checks on IIS/ASP.NET endpoints |
| CWE-45 | Path Equivalence: Multiple Internal Dot | 0.55 | RESTORE | Documented IIS upload/file-access bypass family |
| CWE-46 | Path Traversal: 'file ' (Trailing Space) | 0.55 | RESTORE | MITRE marks web-based; classic IIS trailing-space bypass |
| CWE-53 | Path Traversal: '\dir\file' (Backslash) | 0.55 | RESTORE | Backslash traversal with CVE lineage on Windows-hosted Tomcat/apps where filters block only `/` |
| CWE-54 | Path Traversal: '\dir\filename' (Trailing Backslash) | 0.55 | RESTORE | Classic IIS extension-truncation bypass |
| CWE-56 | Path Equivalence: '*' (Wildcard) | 0.50 | RESTORE | Wildcard semantics bypass denylists on Windows-hosted servers |
| CWE-58 | Path Traversal: Windows 8.3 Filename | 0.45 | RESTORE | `~`/8.3 short-name enumeration exposes backup/source files; NTFS 8.3 still default-on |
| CWE-59 | Improper Link Resolution Before File Access | 0.55 | RESTORE | Symlink-slip via web archive upload-extract is a real CVE class |
| CWE-61 | UNIX Symbolic Link Following | 0.40 | RESTORE | Operative UNIX variant of CWE-59 for the Linux estate |
| CWE-231 | Improper Handling of Extra Values | 0.45 | RESTORE | HTTP parameter pollution / PHP array injection, OWASP-listed with real bypass CVEs |
| CWE-529 | Exposure of Access Control List Files | 0.20 | RESTORE | GET /.htaccess and IIS web.config disclosure are classic, directly probed findings |
| CWE-649 | Reliance on Obfuscation or Encryption of Security-Relevant Inputs | 0.55 | RESTORE | ViewState-without-MAC / CBC padding oracles; RCE-adjacent |
| CWE-1254 | Comparison Logic is Vulnerable to Timing Side-Channel Attacks | 0.40 | RESTORE | Timing side channel on token/API-key comparison is a documented web-auth class |
| CWE-1269 | Incorrect Resource Transfer Between Spheres | 0.50 | RESTORE | Debug-mode-in-production is a first-order recon finding (stack traces, env dumps) |
| CWE-1289 | Improper Validation of Specified Quantity in Input | 0.40 | RESTORE | Unsafe identifier equivalence drives SSRF/URL-parser differential bypasses (CVE-2016-10099 class) |

Score column is the original critic score; the verdict column is the
amendment-pass verdict. Corrected rationales for the 23 REASON entries
are embedded in the critique report (section 2).
