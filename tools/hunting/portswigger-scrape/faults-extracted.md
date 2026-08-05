### sql-injection.md
- SQL injection (SQLi)
- SQL injection in the WHERE clause of SELECT queries (retrieving hidden data)
- SQL injection to subvert application logic (authentication bypass)
- SQL injection in UPDATE statements
- SQL injection in INSERT statements
- SQL injection in the table or column name
- SQL injection in the ORDER BY clause
- UNION attacks to retrieve data from other tables
- Blind SQL injection via conditional responses
- Error-based SQL injection via conditional errors
- Error-based SQL injection extracting data via verbose errors
- Blind SQL injection via time delays
- Blind SQL injection via out-of-band (OAST)
- Out-of-band data exfiltration via blind SQLi
- Second-order SQL injection (stored SQLi)
- SQL injection in different contexts (JSON/XML)
- SQL injection obfuscation to bypass WAFs
- Examining the database (version, tables, columns)
- Batched (stacked) query platform differences

### nosql-injection.md
- NoSQL injection
- NoSQL syntax injection
- Overriding existing conditions with always-true injected conditions
- Null character injection to truncate queries
- NoSQL operator injection ($where, $ne, $in, $regex)
- Authentication bypass via operator injection
- JavaScript injection via $where and mapReduce()
- Data exfiltration via JavaScript injection
- Timing-based NoSQL injection
- NoSQL injection enabling denial of service
- NoSQL injection enabling code execution
- NoSQL injection via request method/content-type conversion

### os-command-injection.md
- OS command injection (shell injection)
- OS command injection via command separators
- OS command injection via inline execution
- OS command injection in quoted contexts
- Blind OS command injection via time delays
- Blind OS command injection via output redirection
- Blind OS command injection via OAST
- Blind OS command injection via OAST data exfiltration

### file-path-traversal.md
- Path traversal (directory traversal)
- Path traversal to read arbitrary files
- Path traversal enabling arbitrary file write
- Windows path traversal
- Absolute path traversal
- Nested traversal sequence bypass
- URL encoding / double encoding bypass
- Non-standard encoding bypass
- Base-folder prefix check bypass
- File-extension requirement bypass via null byte

### server-side-template-injection.md
- Server-side template injection (SSTI)
- SSTI enabling remote code execution
- SSTI enabling arbitrary file read
- SSTI in plaintext context
- XSS via template injection
- SSTI in code context
- Client-side template injection
- SSTI via privileged custom template editing
- Template engine sandbox bypass

### xxe.md
- XML external entity (XXE) injection
- XXE to retrieve files
- XXE to perform SSRF attacks
- Blind SSRF via XXE
- Blind XXE exfiltrating data out-of-band
- Blind XXE retrieving data via error messages
- Blind XXE via local DTD repurposing
- XInclude injection
- XXE via file upload (SVG, DOCX)
- XXE via modified content type
- Hidden XXE attack surface
- XML-encoded XSS and SQL injection

### ssrf.md
- Server-side request forgery (SSRF)
- SSRF against the server itself (loopback)
- SSRF against other back-end systems
- SSRF with blacklist-based input filters
- Blacklist bypass via alternative IP representations
- Blacklist bypass via own domain resolving to 127.0.0.1
- Blacklist bypass via URL encoding / case variation
- Blacklist bypass via redirects
- SSRF with whitelist-based input filters
- Whitelist bypass via URL parsing inconsistencies
- SSRF filter bypass via open redirection
- Blind SSRF vulnerabilities
- SSRF via partial URLs in requests
- SSRF via URLs within data formats (via XXE)
- SSRF via the Referer header
- SSRF enabling arbitrary command execution

### deserialization.md
- Insecure deserialization
- Object injection
- Deserialization-based remote code execution
- Deserialization-based privilege escalation
- Deserialization-based arbitrary file access
- Deserialization-based denial of service
- Manipulating serialized object attributes
- Magic method exploitation (PHP)
- Gadget chains
- PHAR deserialization
- Serialized data tampering (no integrity checks)
- Binary serialization format manipulation

### api-testing.md
- Mass assignment vulnerabilities (auto-binding)
- Hidden (undocumented) API parameters
- Hidden (undocumented) API endpoints
- Publicly accessible API documentation exposure
- Verbose API error messages
- Content-type confusion (XML vs JSON)
- Additional endpoint functionality via HTTP methods
- Server-side parameter pollution (query string truncation)
- Server-side parameter pollution (injecting invalid parameters)
- Server-side parameter pollution (overriding existing parameters)
- Server-side parameter pollution in REST paths
- Server-side parameter pollution in structured data formats

### graphql.md
- GraphQL endpoint exposure
- GraphQL introspection disclosure
- GraphQL schema information disclosure
- Suggestions-based schema disclosure
- Introspection defense bypass
- GraphQL access control vulnerabilities (IDOR via arguments)
- Bypassing rate limiting using aliases
- GraphQL CSRF
- GraphQL brute force
- GraphQL DoS via nested queries (query depth)
- GraphQL DoS via excessive fields/aliases
- GraphQL DoS via oversized queries
- GraphQL DoS via computationally expensive queries
- Schema exposure of private user fields
### access-control.md
- Broken access control
- Vertical privilege escalation
- Unprotected functionality
- Parameter-based access control (admin=true)
- Access control bypass via platform misconfiguration
- Access control bypass via X-Original-URL / X-Rewrite-URL
- Access control bypass via HTTP method override
- Access control bypass via URL-matching discrepancies
- Horizontal privilege escalation via parameter tampering (IDOR)
- IDOR with unpredictable GUID identifiers
- IDOR via direct references to database objects
- IDOR via direct references to static files
- Access control vulnerabilities in multi-step processes
- Referer-based access control bypass
- Location-based access control bypass

### authentication.md
- Weak authentication mechanisms (brute-force)
- Broken authentication (logic flaws)
- Brute-force attacks (usernames, passwords)
- Username enumeration
- Flaws in brute-force protection (account locking, rate limiting)
- Exploiting HTTP basic authentication
- Vulnerabilities in multi-factor authentication
- Bypassing two-factor authentication (flawed verification)
- Brute-forcing two-factor authentication codes
- Vulnerabilities in other authentication mechanisms (remember-me)
- Resetting passwords (URL-based, email)
- Changing user passwords
- Vulnerabilities in OAuth authentication

### logic-flaws.md
- Business logic vulnerabilities
- Excessive trust in client-side controls
- Failing to handle unconventional input
- Making flawed assumptions about user behavior
- Providing an encryption oracle
- Email address parser discrepancies
- Broken validation of user-supplied data
- Completing a transaction outside the intended workflow
- Flawed logic in authentication (privilege escalation)
- Flawed logic in financial transactions

### information-disclosure.md
- Information disclosure (hidden directories, structure, contents)
- Exposing source code via temporary backups
- Database schema disclosure via error messages
- Exposing highly sensitive information
- Hard-coded API keys, IP addresses, database credentials
- Behavior-based resource/usernames enumeration
- Developer comments left in production markup
- Debugging and diagnostic features left enabled
- Verbose error messages from default configurations
- Error-state response differentiation enabling enumeration
- Framework/version disclosure

### file-upload.md
- File upload vulnerabilities (insufficient validation)
- Unrestricted file upload to deploy a web shell (RCE)
- Filename collision overwrite
- Directory traversal in filenames
- DoS via disk space exhaustion (unchecked file size)
- Flawed file type validation via trusted Content-Type
- Bypassing execution restrictions by uploading to a different directory
- Insufficient blacklisting of dangerous file types
- Overriding server configuration via .htaccess / web.config
- File extension obfuscation (case, multiple extensions, trailing chars, encoding, null bytes, unicode)
- Polyglot files bypassing content validation
- File upload race conditions (upload-then-delete)
- Stored XSS via uploaded scripts (HTML/SVG)
- XXE via parsing of uploaded XML-based files
- Source code disclosure via served script contents
- Uploading files via HTTP PUT method

### race-conditions.md
- Race conditions (concurrent processing collisions)
- Limit overrun race conditions
- Redeeming a gift card multiple times
- Reusing a single CAPTCHA solution
- Bypassing anti-brute-force rate limits
- TOCTOU (time-of-check to time-of-use) flaws
- Hidden multi-step sequences (sub-state abuse)
- MFA bypass via race on login sub-state
- Multi-endpoint race conditions
- Single-endpoint race conditions (password reset session collision)
- Email-based operation race conditions
- Partial construction race conditions
- Time-sensitive attacks (predictable tokens from timestamps)

### host-header.md
- HTTP Host header attacks (implicit trust in Host)
- Password reset poisoning via Host header
- Web cache poisoning via Host header
- Classic server-side vulnerability injection via Host header
- Authentication bypass via Host header
- Virtual host brute-forcing
- Routing-based SSRF via Host header
- Connection state attacks
- SSRF via a malformed request line
- Host override via injected headers (X-Forwarded-Host)
- Access to internal-only virtual hosts

### request-smuggling.md
- HTTP request smuggling
- CL.TE request smuggling
- TE.CL request smuggling
- TE.TE request smuggling (obfuscated Transfer-Encoding)
- HTTP/2 request smuggling (H2.CL, H2.TE)
- CRLF injection via header names / pseudo-headers
- Request smuggling to bypass front-end security controls
- Request smuggling to capture other users' requests
- Request smuggling to exploit reflected XSS
- Request smuggling for web cache poisoning / deception
- Response queue poisoning
- HTTP request tunnelling
- CL.0 request smuggling
- Browser-powered request smuggling (client-side desync)
- Pause-based desync attacks

### web-cache-poisoning.md
- Web cache poisoning
- Cache poisoning via unkeyed input manipulation (unkeyed headers)
- Cache poisoning delivering XSS
- Cache poisoning via unsafe handling of resource imports
- Cache poisoning via cookie-handling vulnerabilities
- Cache poisoning via multiple headers
- Cache poisoning via cache-control / Vary header flaws
- Cache poisoning exploiting DOM-based vulnerabilities
- Cache key flaws (unkeyed port, unkeyed query string)
- Cache parameter cloaking
- Normalized cache keys / cache key injection

### web-cache-deception.md
- Web cache deception
- Cache deception via static file extension cache rules
- Cache deception via path mapping discrepancies
- Cache deception via delimiter discrepancies
- Cache deception via delimiter decoding discrepancies
- Cache deception via static directory cache rules
- Cache deception via normalization discrepancies
- Cache deception via file name cache rules
- Cache rules overriding Cache-Control directives
### cross-site-scripting.md
- Reflected XSS
- Stored XSS (persistent, second-order)
- Stored XSS via untrusted non-HTTP sources
- DOM-based XSS via innerHTML sink
- DOM XSS via URL query string parameter
- DOM XSS in third-party dependencies (jQuery, AngularJS)
- Client-side template injection
- AngularJS sandbox escape
- XSS in contexts (HTML tags, attributes, JavaScript)
- XSS circumventing same-origin policy
- Dangling markup injection
- Content Security Policy bypass
- XSS bypassing input filters

### dom-based.md
- Taint-flow vulnerabilities (source to sink)
- DOM-based XSS (document.write, innerHTML)
- DOM-based open redirection (window.location)
- DOM-based cookie manipulation
- DOM-based JavaScript injection (eval)
- DOM-based document-domain manipulation
- WebSocket-URL poisoning
- DOM-based link manipulation
- Web message manipulation (postMessage)
- Ajax request-header manipulation
- Local file-path manipulation
- Client-side SQL injection
- HTML5-storage manipulation
- Client-side XPath injection
- Client-side JSON injection
- DOM-data manipulation (setAttribute)
- DOM-based denial of service (RegExp)
- Web message vulnerabilities (origin verification failures)
- DOM clobbering

### csrf.md
- Cross-site request forgery (CSRF)
- CSRF with non-cookie automatic credentials (Basic, certificate)
- Self-contained CSRF via GET
- CSRF token validation flaws (method-dependent, presence-dependent, not session-tied)
- CSRF token tied to non-session cookie / duplicated in cookie
- Bypassing SameSite restrictions (Lax bypass via GET, on-site gadgets, sibling domains)
- Bypassing Referer-based CSRF defenses

### clickjacking.md
- Clickjacking (UI redressing)
- Clickjacking with prefilled form input
- Clickjacking combined with DOM XSS
- Multistep clickjacking
- Frame busting script bypass
- Clickjacking unaffected by CSRF tokens
- Missing X-Frame-Options / CSP frame-ancestors (frameable pages)

### cors.md
- CORS misconfiguration (reflected Origin with credentials)
- CORS origin whitelist parsing errors (prefix/suffix matching)
- Whitelisted null Origin value
- Exploiting XSS via CORS trust relationships
- Breaking TLS with poorly configured CORS
- Intranet CORS without credentials (browser-as-proxy)
- CORS wildcard usage in internal networks

### jwt.md
- Flawed JWT signature verification (accepting arbitrary signatures)
- Accepting tokens with no signature (alg: none)
- Brute-forcing JWT secret keys
- JWT header parameter injection (jwk, jku, kid)
- SSRF via jku
- kid directory traversal to arbitrary filesystem key
- SQL injection via the kid header parameter
- cty header injection (XXE / deserialization)
- x5c header injection (certificate parsing)
- JWT algorithm confusion attacks (symmetric vs asymmetric)

### oauth.md
- Improper implementation of the implicit grant type
- Flawed CSRF protection in OAuth client (missing state)
- OAuth login CSRF (account hijacking)
- Leaking authorization codes and access tokens
- Flawed redirect_uri validation (whitelist bypass)
- redirect_uri parsing-discrepancy bypass
- Server-side parameter pollution via duplicate redirect_uri
- Token theft via open redirect proxy page
- Token theft via XSS / HTML injection / web messaging
- Flawed scope validation (scope upgrade)
- Unverified user registration at OAuth provider
- OpenID Connect: unprotected dynamic client registration

### prototype-pollution.md
- Client-side prototype pollution
- Server-side prototype pollution
- Prototype pollution via constructor (bypassing key sanitization)
- Prototype pollution in external libraries
- Prototype pollution gadgets
- Prototype pollution leading to DOM XSS
- Server-side prototype pollution leading to RCE

### llm-attacks.md
- Prompt injection (direct)
- Indirect prompt injection (training data, API output, web pages, emails)
- Indirect prompt injection via fake markup
- Excessive agency
- Chaining vulnerabilities in LLM APIs (SQLi, path traversal via LLM)
- Insecure output handling (LLM output -> XSS, CSRF)
- Training data poisoning
- Leaking sensitive training data
- Jailbreaker prompts
- AI-powered scanner vulnerabilities (indirect prompt injection, data exfiltration, routing SSRF)

### websockets-full.md
- WebSocket message tampering (SQLi, XXE via WebSockets)
- XSS delivered via WebSocket messages
- Blind vulnerabilities reachable only via WebSockets
- WebSocket handshake design flaws (misplaced trust in HTTP headers)
- WebSocket handshake session handling flaws
- Cross-site WebSocket hijacking (CSWSH)
- CSWSH: unauthorized actions / capturing sensitive data
