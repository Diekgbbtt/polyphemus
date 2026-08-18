# Hunting #66 - Fault-KB omission critique (adversarial pass)

Status: reported artifact (operator-requested); amendments reframed by the
operator feedback + fold follow-up (2026-08-06). Not a runtime gate.
Date: 2026-08-05 (follow-up 2026-08-06).
Method: three parallel critic subagents (general agents, each loading the
`critical-thinking-logical-reasoning` skill at
`/Users/diekgbbtt/.claude/skills/critical-thinking-logical-reasoning/SKILL.md`),
each argued AGAINST the omission rationales in
`tools/hunting/authoring/10-web-relevance-omit.yaml` for a third of the 188
entries, reflecting per entry on concrete web target profiles where the
fault actually applies. Per-fault verdicts: UPHOLD (omission correct),
RESTORE (omission wrong), REASON (omission correct, rationale flawed).

Verdict totals: UPHOLD 148, RESTORE 17, REASON 23 (188 entries).

## 1. Amendments applied - 17 entries restored

The catalogue grows from 231 to 248 entries. All 17 already carry `nl`
authoring in the range sidecars; `enum_kinds` were added on restore
(CWE-59 was already tagged). All restore verdicts were argued on concrete,
currently-exercised web target profiles, not hypotheticals.

### 1.1 Windows path-equivalence family (9 entries, all three batches converged)

| fault_id | name | critic confidence | target profile |
| --- | --- | --- | --- |
| CWE-42 | Path Traversal: 'filename.' (Trailing Dot) | 0.7 | Windows/IIS apps with upload extension filters and file-serving endpoints; Win32 strips trailing dots, so `shell.asp.` bypasses extension black/allow-lists |
| CWE-43 | Path Traversal: '....' (Multiple Dot) | 0.6 | Filters that learned to strip a single trailing dot; the multi-dot form evades them |
| CWE-44 | Path Equivalence: Internal Dot | 0.55 | IIS/ASP.NET file endpoints; internal-dot forms defeat string-based path checks |
| CWE-45 | Path Equivalence: Multiple Internal Dot | 0.65 | IIS upload and file-access bypass class, documented and probeable |
| CWE-46 | Path Traversal: 'file ' (Trailing Space) | 0.6 | Classic IIS trailing-space bypass; MITRE marks the entry web-based |
| CWE-53 | Path Traversal: '\dir\file' (Backslash) | 0.6 | Windows-hosted Tomcat/Node/Java apps where filters block only `/`; documented CVE lineage |
| CWE-54 | Path Traversal: '\dir\filename' (Trailing Backslash) | 0.65 | Classic IIS extension-truncation bypass (`file.asp\`) |
| CWE-56 | Path Equivalence: '*' (Wildcard) | 0.5 | Windows-hosted file endpoints with wildcard-capable path matching; restore with the family |
| CWE-58 | Path Traversal: Windows 8.3 Filename | 0.6 | IIS `~`/8.3 short-name enumeration exposes backup/source files; NTFS 8.3 still default-on |

Rationale for the family: the retained catalogue already admits
Windows-specific web path faults (CWE-40 UNC at 0.60, CWE-41 at 0.70);
the nine restore variants encode the concrete bypass recipes (extension
truncation, separator bypass, 8.3 enumeration) that the generic kept
entries do not, and all sat just under the 0.6 bar on scores that
underweight the family. CWE-47 (leading space) and CWE-48 (internal
whitespace) stay omitted: Win32 does not strip leading spaces, and
internal whitespace has no documented web exploit lineage.

### 1.2 Recon-observable findings (3 entries)

| fault_id | name | critic confidence | target profile |
| --- | --- | --- | --- |
| CWE-1269 | Incorrect Resource Transfer Between Spheres | 0.75 | `APP_DEBUG=true` / `DEBUG=True` / `display_errors=On` production deployments; verbose stack traces, env-var dumps, dev routes - a first-order OWASP/ASVS recon finding |
| CWE-529 | Exposure of Access Control List Files | 0.55 | `GET /.htaccess` via Apache misconfiguration; documented IIS/ASP.NET `web.config` disclosure class; "web relevance theoretical" is factually wrong |
| CWE-1289 | Improper Validation of Specified Quantity in Input | 0.7 | SSRF/URL-parser differentials (decimal/octal/compressed-IPv6 literals, userinfo tricks, proxy-vs-app parsing disagreement, CVE-2016-10099 class); "marginal web exposure" is wrong and the class is growing |

### 1.3 Web attack classes (5 entries)

| fault_id | name | critic confidence | target profile |
| --- | --- | --- | --- |
| CWE-649 | Reliance on Obfuscation or Encryption of Security-Relevant Inputs | 0.6 | ASP.NET ViewState-without-MAC (.NET deserialisation RCE campaigns), CBC padding-oracle / bit-flipping on encrypted cookies; RCE-adjacent |
| CWE-1254 | Comparison Logic is Vulnerable to Timing Side-Channel Attacks | 0.55 | Custom token / API-key verification comparing byte-by-byte without constant-time; measurable from the network; mechanism-level entry behind CWE-208 |
| CWE-231 | Improper Handling of Extra Values | 0.55 | HTTP parameter pollution and PHP array injection (`?id[]=`), proxy-vs-backend parsing disagreement; OWASP-listed with real bypass CVEs |
| CWE-59 | Improper Link Resolution Before File Access ('Link Following') | 0.6 | "Symlink-slip" via web archive upload-and-extract; real CVE class in file managers and backup/restore features |
| CWE-61 | UNIX Symbolic Link Following | 0.55 | The operative UNIX variant of CWE-59 for the dominant Linux web estate; restore with CWE-59 |

## 2. REASON verdicts - 23 rationales corrected, no restore

The omission stands but the stated rationale mischaracterises the fault.
Highest-value corrections (rationale text kept in
`fault-relevance-rankings.md` amendment section):

- CWE-115/130/437: not "no concrete web mechanism" - they are the
  request-smuggling / parser-length family, superseded by retained CWE-444.
- CWE-348: X-Forwarded-For trust bypass is a common bug-bounty finding,
  not "rarely observed".
- CWE-420: alternate-channel checks (Actuator, debug ports, HTTP variants)
  are core daily recon, not "secondary exposure".
- CWE-454: httpoxy (CVE-2016-5385) was a mass web class; "unusual env/CLI
  paths" misstates history.
- CWE-624: rationale conflates the class with ReDoS; `preg_replace /e`
  was a mass RCE class pre-PHP-7 (now dead; ReDoS retained as CWE-1333).
- CWE-323/353: crypto/checksum rationales misattribute the web-relevant
  gap (missing MAC on app data vs TLS mootness).
- CWE-205/343: behavioural-discrepancy oracles and token predictability
  are core recon techniques, mislabelled "broader"/"narrow".
- CWE-167: double-encoding filter evasion is a core web mechanism,
  mislabelled "weak web relevance".
- CWE-183: permissive allow-lists (SVG upload, redirect URIs, CSP) are
  routinely probed; "abstract, indirect" understates reachability.
- CWE-134: rationale misses the embedded/IoT C web-UI population.
- Struts family (CWE-102/103/104/105/106/108/109): "extinct" overstates -
  Struts 2 OGNL RCEs (CVE-2017-5638) kept the estate alive; omission
  stands because the variants are non-observable architecture signals
  subsumed by retained input-validation entries.

## 3. UPHOLD verdicts - 148 confirmed

Includes all malware-taxonomy entries (CWE-508/509/512), OS-filesystem
faults, hardware TRNG (CWE-333), C-level memory faults (CWE-785),
desktop GUI (CWE-317), Lisp alist (CWE-462), and the generic/abstract
bases whose concrete web forms are already retained (CWE-20/22/79/89/
209/444/502/1333 families). The filter pass is confirmed sound on these.

## 4. Verdict

- Amendment space existed and was applied: 17/188 omissions (9%) were
  wrong, driven by (a) the Windows path-equivalence family sitting just
  under an underweighted threshold and (b) three recon-observable
  findings dismissed as "theoretical" or "marginal".
- 23 rationales misstate the fault; corrections are recorded in the
  rankings artifact so the rationale corpus is honest for future passes.
- The catalogue is now 248 entries; still 100% of the scraped
  PortSwigger ground truth is preserved (the restores only ADD).

## 5. Operator feedback + fold follow-up (2026-08-06)

The operator read the amendments skeptically; that skepticism was
correct on the substance:

- the 17 restored entries are CONCRETE faults, each mappable to a
  retained higher-level capture. The critic mis-targeted: its real
  value is a FAULT-FAULT OVERLAP critique (too many entries, one
  matching loop), not an omission rationale pass;
- the correct grading is "taxed as base, not class": a restored entry
  is captured by its NEAREST retained Base, so its selection cost is
  ~0 and its recipe content survives;
- the "closest parent" aggregation is deterministic (CWE View-1000
  ChildOf chains), not an imprecise many-to-many match.

The fold stage (`fold_variants` in `tools/hunting/curate_fault_kb.py`)
implements exactly that: every Variant/Compound entry gets a
`fold_parent` naming its nearest retained Base/Class ancestor (BFS up
the View-1000 chains, Variant/Compound waypoints skipped); the
matching facet filters folded entries out (`load_fault_entries`,
"fold at curation, filter at read") while the materialisation facet
keeps all 248 recipes by own id.

Applied to the real catalogue: 97 folded, 151 selection-tier entries
(133 Base/Class + 18 orphans kept fail-open). All 9 Windows
path-equivalence restores fold into CWE-41, CWE-529 into CWE-552,
CWE-61 into CWE-59; the 17 restores no longer inflate the matching
loop.

## 6. The overlap critic rerun (2026-08-06)

Three parallel critic subagents (critical-thinking method, one batch
per ~12 fold targets + 6 orphans) reviewed EVERY fold edge and orphan
of the folded catalogue, arguing per closest-parent family (97 family
judgments + 18 orphan decisions; verdicts cross-verified against the
MITRE View-1000 edges by the critics):

- **SPLIT 3** (a folded variant is a genuinely distinct fault class,
  kept as its own selection entry): CWE-1022 (tabnabbing is a
  link-rendering control fault, not privilege assignment; CWE-266's
  authz-gated capture prunes plain presentation units), CWE-539
  (cookies are not files - the CWE-552 capture could never fire for a
  cookie-only unit; true siblings CWE-1004/1275 are selection-tier),
  CWE-827 (DTD control is an XML-parsing fault, not executable-code
  inclusion; CWE-829's predicate would drop XXE-family detection).
- **PROMOTE-AND-FOLD 7**: CWE-1173 (<- CWE-1174/554), CWE-346
  (<- CWE-1385), CWE-229 (<- CWE-231), CWE-524 (<- CWE-525), CWE-248
  (<- CWE-600), CWE-184 (<- CWE-692). CWE-1173/229/248/524/184 were
  curated-but-omitted (web-relevance < 0.5): the promotion REVERSES
  those omits (removed from `10-web-relevance-omit.yaml` with a
  pointer here); CWE-346 was absent from the curated set entirely and
  is added by the promotion stage. The catalogue grows to 254
  entries; the selection tier shrinks to 153 (12 Variants = 3 splits
  + 9 orphans kept).
- **KEEP-STANDALONE 11**: CWE-1004, 1275, 352 (CSRF), 384, 608, 626,
  644, 646, 650, 8, 942 - each candidate parent is non-web (CWE-345),
  umbrella-broad with catalogue-poisoning overlap (CWE-116/436/183),
  or duplicates a retained entry (CWE-668 vs CWE-497).

Carried follow-ups (recorded, not blocking): CWE-266's capture kinds
disjoint from its folded children's (impersonation/tabnabbing units
pruned by tag - widen the capture's enum_kinds/predicate in a later
pass); CWE-553 (RCE-grade recipe under a disclosure-grade capture);
thin recipe materialisation (CWE-550/535/536/537/9/11/615/258/531/6/
85/86/87/7); known multi-fire pairs (traversal 22/23/36 vs CWE-41
equivalence; cookie attributes 315/614/1004/1275; CWE-536 vs CWE-600;
CWE-646 vs CWE-434; CWE-692 vs CWE-79) - accepted as fail-open
multi-fire, deduped by the LLM match stage; dual-parentage notes
(CWE-647/350/784) rechecked if the second parent ever enters the
catalogue.

## 7. The fault-squeeze pass (2026-08-17)

Second screening over the 254-entry catalogue, six parallel critic
subagents (one per failure mode, `critical-thinking-logical-reasoning`
method), each arguing per entry on content - name, `applies_if.nl`,
materialisation description and extended description - never on the CWE
name alone, fail-open (uncertainty -> KEEP) throughout. The six lenses:

- **mode-1 recon-observable / low-impact**: a single atomic legitimate
  interaction (response headers, Set-Cookie, default error pages, TLS
  presentation, directory index) fully establishes the fault, so a
  dedicated hunt adds no signal.
- **mode-2 naive / very-unlikely / recon-reducible**: plain-HTTP
  transport posture, served-certificate presentation, effectively-never
  conditions, and umbrellas whose concrete members are separately
  catalogued.
- **mode-3 very-narrow variants**: the "huntable fault" is the fold
  parent's broader fault; framework/label-only recipes.
- **mode-4 framework/technology-named**: J2EE/ASP.NET/.NET/Servlet/
  Struts/Hibernate/OpenSSL-named entries generalised (kept, name and
  description de-framed) or removed where the mechanism exists only in
  that stack and a selection-tier generic capture already holds the
  hunt shape.
- **mode-5 blatant redundants**: capture + near-verbatim recipe pairs.
- **mode-6 L1-untestable / AI-surface**: faults with no observable HTTP
  interaction under the L1 abstraction model (host bind address, OS
  file-permission bits); the LLM-prompting surface (CWE-1427) is
  declared OUT OF SCOPE and returns when that surface is in scope.

Verdict totals: 51 REMOVE, 14 GENERALISE, 189 KEEP (254 entries).

### 7.1 Conflict resolution

A target appearing under several lenses resolved as:

- REMOVE when the removal lens is the operator-named authority for its
  mode: CWE-296/297/298 (TLS presentation, mode-2), CWE-5/1428
  (plain-HTTP, mode-2), CWE-756/1269 (recon-observable, mode-1);
- REMOVE when a removal lens overruled a generalise: CWE-11/13/555/5/
  12/7/536/537/600/1174/554/556 (mode-3 removes what mode-4 would
  generalise - the recipe's hunt is the fold parent's);
- KEEP when a content-grounds lens overruled a removal: CWE-1393
  (default password, mode-5 keeps the partition child of removed
  CWE-1392), the supply-chain family CWE-1104/1329/1395, the traversal
  family CWE-22/23/24/28 (mode-5 kept for enum coverage / distinct
  payloads).

### 7.2 The removals (51, via `80-fault-squeeze-omit.yaml`)

Selection tier 153 -> 128 (25 selection removals); recipes 101 -> 75
(26 recipe removals). Every removed capture's folded children went with
it (verified: no removed selection capture leaves a surviving folded
child, so no orphan re-folds - and `fold_variants` re-folds any
survivor automatically regardless). Full per-fault rationales live in
the sidecar's `omit_reason` fields and the six verdict reports
(`squeeze-mode-1..6.md`).

Notable families removed wholesale: the cookie-attribute cluster
(CWE-1004/1275/315/614/525 - Set-Cookie recon), the default-error-page
family (CWE-756/12/7), the TLS certificate family (CWE-296/297/298/299/
370), the error-disclosure label cluster (CWE-210/211/550/535/536/537),
the transport-posture pair (CWE-5/1428), and the authn umbrellas
(CWE-303/305/309/654).

### 7.3 The generalises (14, via `81-fault-squeeze-generalise.yaml`)

Kept faults whose name/description carried a framework or manufacturing
label get the materialisation name/description rewritten (matching facet
untouched; `generalise: true` marker, `name`/`description`/
`extended_description` merge per-key in `fold_authoring`):

- capture-widening to absorb removed children: CWE-489 (debug
  artefacts; standalone selection entry, keeps the debug-surface hunt
  that the removed CWE-756/12/7 and the debug-build labels covered),
  CWE-209 (error disclosure, absorbs its folded CWE-550 with the removed
  CWE-210/211/535/536/537 probes), CWE-248 (uncaught exception, absorbs
  its folded CWE-600);
- hardware/domain-framing de-framed: CWE-1220 (silicon/BIOS framing
  nulled); CWE-651 (WSDL framing generalised to service-description
  file);
- framework-named de-framed: CWE-6/9/98/520/564/599/61 (J2EE/ASP.NET/
  PHP/Hibernate/OpenSSL/UNIX tokens removed from name and/or
  description, fault content intact); CWE-917/644 (selection-tier
  descriptions de-framed).

Net effect: catalogue 254 -> 203; selection tier 153 -> 128; fold
families 41 -> 26. The matching loop shrinks 16%, the recipe corpus
keeps its probe content (recipes are materialised by own id regardless
of fold). Carried forward, not blocking: recipe `nl` still carries
framework tokens for a few folded entries (inert under the current
loader, flagged in the mode-4 report); the CWE-7/12 -> CWE-756
post-generalise near-duplicates merged by the removals; a future pass
may widen CWE-266's capture kinds (carried from section 6).
