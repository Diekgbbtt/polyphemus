# sql-injection - variant decomposition analysis

## 1. Class and scope
The sql-injection class covers testing for user input that alters SQL query structure through in-band rendering, error disclosure, boolean inference, timing inference, or out-of-band callbacks.
Its authority is `skills-unspurious/sql-injection/SKILL.md` (175 lines), consulted against `skills/sql-injection/SKILL.md` only for extra methodology detail.
The class spans SELECT and INSERT and UPDATE and DELETE shapes with WHERE and ORDER BY and GROUP BY and HAVING and LIMIT and OFFSET presence, identifier versus value influence, ORM and query-builder raw fragments, JSON and XML and CTE and full-text surfaces, and DBMS-specific primitives for MySQL and PostgreSQL and MSSQL and Oracle.
The analysis finds five genuine variants discriminated by extraction channel rather than by DBMS product alone.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | User input reaches SQL construction; string concatenation present; UNION-capable SELECT rendering; error text reflected; stable boolean oracle; sleep-capable function reachable; DNS or HTTP egress from DB primitive; FILE or superuser or directory privilege for write primitives; raw ORM fragment reachable | 8, 10-26, 28-43, 52-53, 61, 67-69, 74-78, 104-123 | Discriminator candidate (enables channel values, folded into channel per STATE 3) |
| TechnologyStack | MySQL and MariaDB; PostgreSQL with JSONB and lateral and CTE; MSSQL with xp_dirtree and xp_cmdshell and OPENROWSET; Oracle with UTL_HTTP and DBMS_LDAP and UTL_FILE; ORM and query builder and stored procedure and search server and reporting exporter | 12-18, 46-78, 110-115 | Non-discriminator (excluded axis per stability criterion, dialects ride inside channel variants) |
| DefensiveControl | Parameterized queries; dynamic-identifier avoidance; WAF filtering; keyword and whitespace and comment filtering; secure_file_priv restriction; disabled xp_cmdshell; least-privilege DB accounts | 124-142, 157-158, 160-170, 173-175 | Non-discriminator (each control is detected inside its own step and never bends a step into a new kind of action) |
| VulnerabilityClass | SQL injection as query-structure injection | 6-8, 173-175 | Non-discriminator (this is the class definition itself, not a value that bends a step) |
| AttackGoal | Data extraction; authentication bypass; privilege change; file read; file write; OS command execution; job or procedure persistence | 104-108, 170-175 | Non-discriminator (every goal is reachable through a channel variant and goal never changes the oracle kind) |
| AttackerCapability | Anonymous HTTP request ability; low-privilege authenticated session; attacker-controlled DNS or HTTP listener for OAST; privileged DB role where granted | 41-43, 95-101, 104-108 | Non-discriminator (capability ladder is shared setup across all variants) |
| AttackTechnique | ORDER BY column counting; UNION SELECT alignment with CAST; error-shaping casts; boolean predicate-pair diffing; binary-search bit extraction; subselect-gated sleep inference; DNS and HTTP label embedding; tautology auth bypass; UPDATE privilege change; OUTFILE and COPY TO and xp_cmdshell writes; whereRaw and orderByRaw audit; ORDER BY CASE WHEN channels; LIMIT and OFFSET shaping | 28-43, 82-123 | Discriminator source (values partition into five channel families, see section 6) |
| PayloadPattern | ORDER BY n plus UNION SELECT null fragments; CAST and CONVERT coercions; extractvalue and updatexml and convert and to_number error shapers; SUBSTRING and ASCII and LEFT and RIGHT predicates; SLEEP and pg_sleep and WAITFOR DELAY and dbms_lock.sleep timers; xp_dirtree and UTL_HTTP and LOAD_FILE UNC callbacks; comment and case-folding and char and CONCAT_ws evasions; CTE and derived-table relocations | 46-78, 82-101, 126-142 | Discriminator instrument (co-varies with technique and is collapsed into one feature per STATE 3 branch 3a) |
| Artifact | Version and user and database metadata; extracted table rows; session from auth bypass; written file; executed-command output; job or procedure handle | 46-78, 104-108, 145-151 | Non-discriminator (runtime-produced evidence that parametrises proof inside every variant) |
| ObservableSignal | Rendered UNION rows; type and constraint and parser error text; status and body and length and ETag difference; response time delay; DNS or HTTP callback receipt | 28-43, 82-101, 153-158 | Non-discriminator standalone (oracle reading co-varies with channel and is collapsed per STATE 3 branch 3a) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: path and query and body and header and cookie inputs with mixed encodings plus DBMS fingerprinting plus error and boolean and timing probes form the surface (lines 10-26, 28-43, 46-78).
This notion varies by channel because each channel needs its own confirmation grammar and no single probe text covers rendered rows plus error text plus differentials plus delays plus callbacks.
Adversarial capabilities: anonymous baseline with optional authenticated session plus attacker listener for OAST is the ladder (lines 41-43, 95-101, 104-108).
This notion is invariant setup because every variant starts from the same request ability and differs only afterward.
Common trust assumptions: concatenation is safe and ORM fragments are safe and identifiers are safe and errors are silent and timing is stable are the assumptions under test (lines 8, 22-25, 110-115, 153-158).
This notion varies only as the negation of each channel and therefore tracks the discriminator without adding its own axis.
Testing methodology: the seven parent steps S1 to S7 (lines 145-151) are the step-test substrate.
This notion is the authority for accuracy and exhaustiveness and S3 plus S5 are compound across channel sub-values.
Proxy techniques: OAST DNS and HTTP callbacks via DB primitives are the proxy-adjacent values (lines 41-43, 51-78, 95-101).
This notion invokes no foreign skill because the callback primitive is native SQLi procedure rather than a separate proxy class.
Defence bypass techniques: whitespace and comment and keyword-splitting and numeric and encoding and clause-relocation evasions are the bypasses named (lines 124-142).
This notion is an aspect inside each channel variant because every evasion preserves the underlying oracle kind.
Techniques anti-patterns: no dedicated anti-pattern section is present beyond the false-positive guards and the quietest-oracle discipline.
This notion is invariant across all candidates.
Scripted tests (`references/`): none are shipped with the class skill.
No invariant is stated beyond the inline payload documents.
False positives: generic errors plus templated sizes plus network jitter plus verified parameterization are the named non-findings (lines 153-158).
This notion is invariant across all candidates.
Chaining: metadata then business-critical tables plus OUTFILE plus COPY TO plus xp_cmdshell plus job creation are the named chains (lines 104-108, 145-151).
This notion is invariant plumbing after extraction rather than a split axis.

## 4. Runtime parametrisation
Each procedure consumes the concrete Service under test and the database System mechanism it lies on.
It consumes the Endpoint path, the BaseURL, the Header set including cookies and content type, the Parameter atoms where the logical DataItem surfaces as filter or sort or limit inputs, and the prior HTTP history of baseline responses.
The operator knowledge base supplies the test credentials, the table and column name hints, the DBMS version and privilege notes, and the OAST listener address from prior enumeration.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is a deployed application where the agent holds anonymous HTTP access plus low-privilege test credentials and suspects that user input reaches a SQL query path.
S1 Identify query shape: enumerate SELECT and INSERT and UPDATE and DELETE shapes with WHERE and ORDER and GROUP and LIMIT presence, with completion when each candidate sink has a named shape.
S2 Determine input influence: classify value literals versus identifier positions versus ORDER BY and LIMIT contexts versus ORM raw fragments, with completion when each input has a named influence class.
S3 Confirm injection class: submit quote probes and observe reflective errors versus boolean diffs versus timing versus callbacks, with completion when an oracle class or its absence is recorded.
S4 Choose quietest oracle: rank working oracles by noise and prefer error or boolean over timing, with completion when the selected oracle is named with justification.
S5 Establish extraction channel: run UNION alignment or error shaping or boolean bit extraction or gated timing or OAST embedding as the selected channel dictates, with completion when the channel yields repeatable control.
S6 Pivot to metadata: extract version plus current user plus database name through the established channel, with completion when verifiable metadata is recorded.
S7 Target high-value tables: pivot from metadata to auth bypass plus role changes plus filesystem access where feasible, with completion when a non-trivial target is read or modified or proven unreachable.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Extraction channel (UNION versus error versus boolean versus time versus OAST) | Yes (each value performs a different kind of action across S3 plus S5) | No (no single S5 sentence covers column alignment plus error shaping plus binary search plus gated sleep plus DNS embedding) | Discriminator (class signature) | S3 at 147 versus S5 at 149 versus Detection Channels at 28-43 versus Key Vulnerabilities at 82-101 |
| DBMS dialect (MySQL versus PostgreSQL versus MSSQL versus Oracle) | No (swapping SLEEP for pg_sleep preserves the timing kind of action) | Not applicable (dialect changes function names while channel procedure stays fixed) | Non-discriminator by stability criterion | Lines 46-78 versus S5 at 149 |
| Query shape (SELECT versus INSERT versus UPDATE versus DELETE with clause presence) | No (shape changes where input lands while confirmation and extraction kinds stay channel-defined) | Yes as enumeration (S1 names every shape) | Aspect inside each variant, not a variant axis | S1 at 145 versus lines 117-123 |
| Input influence (value literal versus identifier versus ORDER BY versus LIMIT versus ORM raw fragment) | Partial for identifiers (quoting analysis differs) but No as split (confirmation still proceeds through the same five oracles) | Yes as classification (S2 plus ORM and Uncommon Contexts enumerate every position) | Aspect inside each variant, not a variant axis | S2 at 146 versus lines 22-25, 110-123 |
| UNION column-count and type-alignment detail | Yes (counting plus CAST alignment differs from predicate diffing) | No (S5 names UNION without stating ORDER BY n or null-arity or CAST rules) | Discriminator value inside channel signature | Lines 82-86 versus S5 at 149 |
| Error-shaping detail | Yes (provoking parser errors differs from rendering rows) | No (S5 names error-based without stating extractvalue or convert or XMLType shapers) | Discriminator value inside channel signature | Lines 30-31, 49-78 versus S5 at 149 |
| Boolean predicate-pair and binary-search detail | Yes (paired true-versus-false diffing differs from row rendering) | No (S5 names boolean bit extraction without stating SUBSTRING plus ASCII plus hex encoding plus normalization) | Discriminator value inside channel signature | Lines 33-37, 88-93 versus S5 at 149 |
| Time-gated sleep detail | Yes (calibrated delay measurement differs from content diffing) | No (S5 names time-based without stating subselect gating or noise calibration) | Discriminator value inside channel signature | Lines 37-39, 88-93 versus S5 at 149 |
| OAST DNS and HTTP embedding detail | Yes (listener-correlated exfiltration differs from in-band reading) | No (S5 names OAST and DNS without stating label embedding or xp_dirtree or UTL_HTTP primitives) | Discriminator value inside channel signature | Lines 41-43, 95-101 versus S5 at 149 |
| Attack goal (read versus auth bypass versus privilege change versus file versus exec) | No (goal changes the objective while the channel action stays the same) | Not applicable (goals are achieved through channels, not instead of them) | Non-discriminator | Lines 104-108 versus S7 at 151 |
| Attacker capability (anonymous versus authenticated versus listener owner) | No (one credential versus another is the same kind of action) | Not applicable | Non-discriminator and runtime parameter | Lines 41-43, 95-108 |
| Defensive control and bypass encoding (WAF plus comments plus splitting plus CTE relocation) | No (an evasion preserves the oracle kind) | Yes as detection (each step records enforcement versus bypass) | Non-discriminator, aspect inside each variant | Lines 124-142, 160-170 |
| Concrete Service, System, Endpoint, Parameter, DataItem, BaseURL, Header, HTTP history, payload literal, library version | No (swapping any runtime asset preserves the procedure) | Not applicable | Non-discriminator by stability criterion | SPEC section 4 runtime list |

## 7. Step-coverage falsification
UNION value: parent S5 covers channel selection but parent S5 cannot cover ORDER BY n column counting because S5 never states arity discovery.
UNION value: parent S5 cannot cover CAST and CONVERT type alignment because S5 lists UNION without describing rendering coercion from lines 82-86.
Error value: parent S3 covers reflective errors but parent S3 plus S5 cannot cover error shaping because neither states extractvalue or convert or to_number or XMLType construction from lines 46-78.
Boolean value: parent S5 cannot cover predicate-pair diffing because S5 names boolean bit extraction without stating true-versus-false pairing or length and ETag normalization from lines 33-37.
Boolean value: parent S5 cannot cover binary search because S5 never states SUBSTRING plus ASCII iteration or hex and base64 encoding from lines 88-93.
Time value: parent S5 cannot cover gated inference because S5 never states subselect CASE WHEN gating from lines 37-39 and 88-93.
Time value: parent S4 prefers quieter oracles but parent S4 cannot cover noise calibration because S4 never states delay baselining against global latency.
OAST value: parent S3 covers callbacks but parent S3 plus S5 cannot cover label embedding because neither states DNS-label data encoding or HTTP query-param embedding from lines 95-101.
OAST value: parent S5 cannot cover primitive selection because S5 never states xp_dirtree versus UTL_HTTP versus LOAD_FILE UNC choice from lines 51-78.
Identifier and ORM value: no new step is uncovered because S2 plus ORM text states influence classification and the oracle still falls in one of the five channels.
DBMS-dialect value: no new step is uncovered because swapping SLEEP for pg_sleep or WAITFOR preserves the channel kind and S5 plus DBMS Primitives covers the rename.
STATE 2 therefore exits through branch 2b with one signature feature carrying five values.

## 8. Hypotheses
H1 Single-feature hypothesis on extraction channel: if channel discriminates, then UNION plus error plus boolean plus time plus OAST each deserve a variant, and it is falsified if any proposed variant lacks its own non-coverable parent step.
H2 Single-feature hypothesis on DBMS dialect: if dialect discriminates, then MySQL plus PostgreSQL plus MSSQL plus Oracle each deserve a variant, and it is falsified if any dialect pair shares one channel procedure or if one dialect internally needs two procedures.
H3 Combined-feature hypothesis on channel by input influence: if channel combined with identifier-versus-value discriminates, then identifier-UNION and value-UNION and identifier-blind products emerge, and it is falsified if the combination adds no step beyond S2 plus S5.
H4 Combined-feature hypothesis on channel by query shape: if channel combined with SELECT-versus-INSERT discriminates, then SELECT-UNION and INSERT-blind products emerge, and it is falsified if shape adds no step beyond S1 plus S5.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | sqli-union-extraction | S5 UNION sub-value | ORDER BY n counting, null-arity discovery, CAST alignment, JSON coercion for rendering |
| H1 | sqli-error-based-extraction | S5 error sub-value | Error shaping via casts and XML functions, stack and version disclosure, UNION fallback when filtered |
| H1 | sqli-boolean-blind-extraction | S5 boolean sub-value | Predicate-pair diffing, SUBSTRING and ASCII iteration, binary search, hex encoding, ETag normalization, ORDER BY CASE WHEN and LIMIT shaping |
| H1 | sqli-time-blind-extraction | S5 time sub-value | Subselect-gated sleep, delay baselining, binary search under latency, OFFSET timing shaping |
| H1 | sqli-oast-exfiltration | S5 OAST sub-value | DNS-label and HTTP-param embedding, primitive selection per DBMS, listener correlation, OAST-first noise avoidance |
| H2 | mysql-only; postgres-only; mssql-only; oracle-only | none cleanly (each dialect reuses all five channel procedures with renamed functions) | Dialect dictionaries as aspects inside H1 variants |
| H3 | identifier-UNION; value-UNION; identifier-blind | none per product (each reuses S5 channel logic plus S2 classification) | Identifier quoting and ORM raw-fragment audit as aspects inside channel variants |
| H4 | select-UNION; insert-blind | none per product (each reuses S5 channel logic plus S1 shape) | Clause presence as S1 aspect inside channel variants |

## 10. Well-formedness evaluation
Coverage (critical): H1 covers every non-coverable step with exactly one owner per channel sub-value, while H2 leaves error versus blind versus OAST uncovered inside single-dialect buckets.
Disjointness (critical): H1 is disjoint because rendered rows plus error text plus response differentials plus delays plus callbacks admit no shared technique, while H2 fails because one boolean payload belongs in every dialect bucket and H3 fails because one UNION attempt is simultaneously an identifier attempt.
Divergence delta (high): every H1 variant adds a positive step delta over the parent, while every H2 dialect label and every H3 and H4 product without its own step carries zero delta and is deleted.
Stability (high): H1 survives swaps of DBMS and version and payload and runtime asset, while H2 depends on product names that function renames directly falsify.
Parsimony (medium): H1 uses one feature with five values which is the fewest that still covers, while H2 uses one feature with four overlapping buckets and H3 and H4 add features without adding coverage.
Winner: H1 is well-formed and H2 loses on coverage plus disjointness plus stability with zero-delta buckets, and H3 and H4 lose on zero divergence delta.
No return to STATE 3 was needed because the H1 signature needs no collapse beyond the documented payload and oracle folding.

## 11. Recommended set
Discrimination function: sql-injection discriminates by extraction channel, namely whether data returns as rendered UNION rows, as shaped database errors, as boolean response differentials, as gated timing delays, or as out-of-band DNS or HTTP callbacks.
Recommended variant sqli-union-extraction diverges first at S5 UNION sub-value with delta of ORDER BY n column counting plus null-arity discovery plus CAST type alignment that S5 lists without describing.
Recommended variant sqli-error-based-extraction diverges first at S5 error sub-value with delta of cast-driven error shaping plus version and path disclosure that S3 plus S5 name without specifying.
Recommended variant sqli-boolean-blind-extraction diverges first at S5 boolean sub-value with delta of predicate-pair diffing plus binary-search bit extraction plus response normalization that S5 names without specifying.
Recommended variant sqli-time-blind-extraction diverges first at S5 time sub-value with delta of subselect-gated sleep plus latency baselining that S4 plus S5 prefer without describing.
Recommended variant sqli-oast-exfiltration diverges first at S5 OAST sub-value with delta of DNS-label embedding plus DBMS primitive selection plus listener correlation that S5 lists without describing.
Non-discriminators: all DBMS dialect labels as TechnologyStack, all query shapes, all identifier-versus-value positions, all ORM envelopes, all attack goals, the full capability ladder, all defensive controls and bypass encodings, all produced artifacts, and all L0 and L1 runtime assets including Service and System and Endpoint and Parameter and DataItem and BaseURL and Header and HTTP history.
STATE 1 inventoried seven parent steps S1 to S7 with no malformed-class stop.
STATE 2 tested every ledger value with both halves and exited through branch 2b with one signature feature.
STATE 3 enumerated five channel values and collapsed payload patterns and oracle readings into that feature without needing continuous-value folding.
STATE 4 hypothesised two single-feature and two combined-feature falsifiable splits.
STATE 5 derived four variant sets and kept no combined product because no combination added its own non-coverable step.
STATE 6 scored all sets on weighted criteria and selected H1 for coverage plus disjointness plus delta plus stability plus parsimony.
STATE 7 recommends the five-variant set stated in this section.
Outlier: stacked-query execution and second-order SQLi have no dedicated procedure in the parent skill and are left as out-of-scope rather than forced into a channel.
Grey point: UNION output that surfaces inside error text stays in UNION extraction when column alignment proves the channel, while crafted conversion errors stay in error extraction.
Grey point: boolean inference that degrades into timing under jitter stays in boolean extraction until gated sleep becomes the sole oracle, at which point time extraction owns it.
Grey point: OAST fallback to blind extraction on egress-blocked targets is recorded as a secondary divergence rather than a dual membership.
Open questions: no FAIL-level uncertainty blocks this recommendation.
Open question at note level: privilege-gated file and exec primitives remain goal-driven extensions inside each channel and do not split further by DBMS permission model.
