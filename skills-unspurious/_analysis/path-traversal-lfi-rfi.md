# path-traversal-lfi-rfi - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/path-traversal-lfi-rfi/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/path-traversal-lfi-rfi/SKILL.md`.
Path traversal with local and remote file inclusion here is failure to keep attacker-influenced paths, names, schemes, and archive entries from resolving outside an intended root, entering an interpreter, fetching a remote resource, or writing outside an extract destination.
Scope covers traversal reads with encoding and normalization bypasses, alias and upstream decoding mismatches, operating system specific path semantics, local inclusion through wrappers and poisoning chains, template dynamic resolution, remote inclusion with outbound fetch proof, and archive extraction slip with symlink handling.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | path join of base plus user input into filesystem read | 8, 12, 139 | collapsed into signature feature (file-operation locus side) |
| PreconditionEnvironment | dynamic include or template load into local interpreter | 15, 109, 139 | collapsed into signature feature (file-operation locus side) |
| PreconditionEnvironment | remote-scheme include enabled with fetcher that executes retrieved content | 18, 115, 139 | collapsed into signature feature (file-operation locus side) |
| PreconditionEnvironment | archive extract destination fed by attacker-controlled entries | 22, 130, 139 | collapsed into signature feature (file-operation locus side) |
| PreconditionEnvironment | normalization mismatch between proxy and application decoders | 25, 83, 142 | aspect (enumerated inside traversal-read mismatch sub-step) |
| PreconditionEnvironment | operating system specific path semantics on Windows | 26, 73 | aspect (enumerated inside traversal-read encoding sub-step) |
| TechnologyStack | PHP with wrappers, Smarty Twig Blade, Java JSP FreeMarker Velocity, Node ejs handlebars pug | 34, 89, 109 | non-discriminator (runtime stack, excluded axis) |
| TechnologyStack | nginx alias and root with reverse proxy and CDN decoders | 25, 36, 83 | non-discriminator (runtime stack, excluded axis) |
| TechnologyStack | Windows separators with device names and UNC and alternate streams | 26, 73 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | canonical path resolution with allowlist and root binding after normalization | 150, 162 | aspect (negative oracle inside traversal-read and archive variants) |
| DefensiveControl | wrapper disabling with constant-only templates and forbidden remote schemes | 149, 162 | aspect (negative oracle inside local and remote inclusion variants) |
| DefensiveControl | archive path sanitization with destination enforcement and symlink policy | 134, 150 | aspect (negative oracle inside archive variant) |
| DefensiveControl | consistent normalization at the boundary closest to input output | 162 | aspect (enumerated inside traversal-read defeat step) |
| VulnerabilityClass | path traversal | 12 | collapsed into signature feature (file-operation locus side) |
| VulnerabilityClass | local file inclusion | 15 | collapsed into signature feature (file-operation locus side) |
| VulnerabilityClass | remote file inclusion | 18 | collapsed into signature feature (file-operation locus side) |
| VulnerabilityClass | archive extraction slip | 22, 130 | collapsed into signature feature (file-operation locus side) |
| AttackGoal | sensitive file disclosure with config and source leakage | 8, 50 | collapsed into signature feature (effect-oracle side) |
| AttackGoal | code execution through included local or remote content | 18, 95, 126 | collapsed into signature feature (effect-oracle side) |
| AttackGoal | out-of-directory write with config overwrite and webshell persistence | 61, 130 | collapsed into signature feature (effect-oracle side) |
| AttackGoal | remote pivot through server-side fetch and execution bridge | 8, 117 | non-discriminator (downstream impact of proven remote inclusion, no bent step) |
| AttackerCapability | ability to submit path-like input through file and template parameters | 32, 139 | non-discriminator (shared precondition of all candidates) |
| AttackerCapability | ability to poison logs and sessions and race temporary uploads | 97, 100 | collapsed into signature feature (local inclusion chain side) |
| AttackerCapability | ability to host a remote payload and observe outbound callbacks | 59, 126 | collapsed into signature feature (remote inclusion chain side) |
| AttackerCapability | ability to supply archives with traversal entries and symlinks | 61, 130 | collapsed into signature feature (archive chain side) |
| AttackTechnique | traversal probing with encodings and separators and dot tricks and absolute paths | 40, 68, 79 | collapsed into signature feature (file-operation locus side) |
| AttackTechnique | alias escape and upstream double-decode comparison | 83, 87, 142 | aspect (mismatch sub-step inside traversal-read variant) |
| AttackTechnique | wrapper invocation with filter and zip and data and expect schemes | 89, 91 | collapsed into signature feature (file-operation locus side) |
| AttackTechnique | log and session poisoning with upload temp race and proc and cache reads | 97, 100, 103 | collapsed into signature feature (file-operation locus side) |
| AttackTechnique | template dynamic resolution with user-controlled theme and language names | 109, 111 | secondary divergence inside local inclusion variant (engine render sub-step) |
| AttackTechnique | remote hosting with beacon payload and deterministic output proof | 122, 126 | collapsed into signature feature (file-operation locus side) |
| AttackTechnique | synthetic archive crafting with traversal entries and symlink handling | 61, 130, 132 | collapsed into signature feature (file-operation locus side) |
| PayloadPattern | dot-dot-slash with single and double encoding and overlong UTF8 and Unicode dots | 41, 70 | aspect (encoding inside traversal-read variant) |
| PayloadPattern | mixed separators with trailing dots and slashes and appended valid extension | 73, 76 | aspect (encoding inside traversal-read variant) |
| PayloadPattern | absolute rooted paths for join bypass | 44, 79 | aspect (encoding inside traversal-read variant) |
| PayloadPattern | alias escape with semicolon folding and encoded slashes | 44, 83 | aspect (encoding inside traversal-read variant) |
| PayloadPattern | wrapper URIs with filter base64 and zip fragment and data payload | 91, 93 | aspect (encoding inside local inclusion variant) |
| PayloadPattern | remote URLs with http and ftp and stream handler schemes | 122, 126 | aspect (encoding inside remote inclusion variant) |
| PayloadPattern | archive entry paths with traversal segments and absolute names | 132, 134 | aspect (encoding inside archive variant) |
| Artifact | disclosed file content with base64 wrapper output | 50, 92 | non-discriminator (success residue read through the owning variant oracle) |
| Artifact | canonicalized paths exposed in errors and include warnings | 51, 54 | non-discriminator (tester-observed residue shared across candidates) |
| Artifact | extracted outside files with directory listing follow-up | 62, 134 | non-discriminator (success residue read through the archive oracle) |
| Artifact | outbound callback receipts from wrapper and remote fetches | 59, 127 | non-discriminator (success residue read through the inclusion oracles) |
| Artifact | poisonable logs with session files and temporary upload names | 97, 100 | non-discriminator (intermediate material inside the local inclusion chain) |
| ObservableSignal | response body disclosure with error path echo | 50, 54 | collapsed into signature feature (oracle side) |
| ObservableSignal | outbound fetch proving wrapper or remote execution | 59, 127 | collapsed into signature feature (oracle side) |
| ObservableSignal | unexpected outside writes verified by listings or follow-up reads | 62, 134 | collapsed into signature feature (oracle side) |
| ObservableSignal | content-length and ETag shifts under masked content | 154 | aspect (masked-content oracle inside traversal-read variant) |
| ObservableSignal | virtual-path and safe-store denial with strict allowlist constraint | 147, 148 | non-discriminator (shared negative exclusion predicate) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: download and preview and template and log and export parameters plus upload and conversion pipelines plus archive importers plus proxy-served static paths; invariant is user influence reaching a filesystem or interpreter or fetcher or extractor sink, what varies is which sink consumes the input and which oracle proves the crossing.
Adversarial capabilities: submitting path-like input and crafting archives and poisoning logs and hosting remote payloads and observing callbacks; invariant is no control over server code or include policy, what varies is whether the attacker only sends a path or also poisons state or hosts remote content or supplies an archive.
Common trust assumptions: server assumes join plus normalization keeps paths inside the root and assumes dynamic includes use constant templates and assumes remote schemes stay forbidden and assumes extractor entries stay inside the destination; invariant is containment trust, what varies is which containment boundary is violated.
Testing methodology: the five parent steps P1 through P5 listed in section 5; invariant is the inventory-to-escalation spine, what varies is which sink-specific oracle bends per candidate procedure.
Proxy techniques: none held by this class except the SSRF-to-execution bridge named as a remote inclusion companion, which is routed to the companion skill rather than restated here.
Defence bypass techniques: encodings with double decoding and mixed separators and dot tricks and absolute paths and alias escapes and wrapper scheme abuse and poisoning and remote hosting and traversal archives; invariant is defeating containment or handler policy, what varies is only the defeated value except where poisoning and hosting and archive crafting need their own chain procedures.
Techniques anti-patterns: trusting virtual paths blindly and trusting pre-normalization checks and leaving wrappers enabled with dynamic names and extracting without canonicalization; these are invariant warnings.
Scripted tests (references/): none shipped with this skill; validation is described inline at lines 145 through 158 with canonical reads and wrapper proofs and OAST beacons and synthetic archives.
False positives: virtual paths mapped to safe stores and post-normalization allowlist roots and disabled wrappers with constant templates and sanitizing extractors; these are invariant exclusion predicates.
Chaining: disclosed secrets enabling lateral movement and poisoned logs enabling inclusion execution and overwritten templates enabling persistence and remote fetches enabling server-side request pivots; chaining targets are invariant companions, not variant axes.

## 4. Runtime parametrisation
Consumed L0 and L1 runtime entities are the concrete Service under test, the Endpoint and its Parameter and Header carriers for path and template and download fields, the BaseURL and storage identity, the DataItem for the file object surfacing at those carriers, the System mechanism overlays for language runtime and template engine and proxy and extractor, and the HTTP history showing traversal and inclusion and fetch and extraction requests.
The concrete filenames, parameter names, encoding literals, wrapper strings, remote URLs, archive entry names, header values, and operating system paths are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, product version, payload literal, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding a file-operation inventory with proxy visibility and needing to prove that crafted input escapes its intended root, enters an interpreter, fetches remote content, or writes outside an extract destination.
Parent methodology steps with completion conditions: P1 inventory file operations, complete when downloads and previews and templates and logs and exports and uploads and archive extractors are recorded.
Parent methodology steps with completion conditions: P2 identify input joins, complete when path joins and include loads and resource fetchers and extract destinations are recorded.
Parent methodology steps with completion conditions: P3 probe normalization, complete when separators and encodings and double decodes and case and trailing dots and slashes are attempted and acceptance recorded.
Parent methodology steps with completion conditions: P4 compare behaviors, complete when web server handling is contrasted with application handling for mismatch escapes.
Parent methodology steps with completion conditions: P5 escalate, complete when disclosure is pushed toward influence and execution through wrapper and engine chains.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| TechnologyStack values and versions (language, engine, proxy, operating system) | No | N/A | non-discriminator | Parent steps perform the same kind of action across stacks, so stacks are excluded axes. |
| Runtime asset identity (Endpoint, Parameter, Header, BaseURL, DataItem) | No | N/A | non-discriminator | Concrete carriers parametrise every candidate without bending any parent step. |
| Observation channel alone (direct, error, OAST, side effect) | No | N/A | non-discriminator | Channels read out whichever oracle the owning variant proves and never bend a step by themselves. |
| Downstream remote pivot impact (AttackGoal) | No | N/A | non-discriminator | Pure consequence of proven remote inclusion with no bent step of its own. |
| Shared path-submission capability (AttackerCapability) | No | N/A | non-discriminator | Shared precondition where every candidate starts from the same submission shape. |
| Denial and residue apparatus (Artifact, negative ObservableSignal) | No | N/A | non-discriminator | Tester-produced residue and shared exclusion predicates bend no parent step. |
| Encoding and separator and dot-trick values (AttackTechnique, PayloadPattern) | Yes | Yes | aspect | P3 performs the same kind of normalization probe and enumerates every encoding value. |
| Alias and upstream decoding mismatch values (PreconditionEnvironment) | Yes | Yes | aspect | P4 performs the same kind of server-versus-application comparison and covers mismatch values. |
| Wrapper URI spellings and remote URL spellings and archive entry spellings (PayloadPattern) | Yes | Yes | aspect | Owning variant chain steps enumerate every spelling value with no new step. |
| Template engine name resolution (AttackTechnique) | Yes | Yes | aspect | Local inclusion chain covers dynamic resolution as an engine render sub-step with no new step. |
| Local filesystem read outside the root (PreconditionEnvironment, AttackTechnique, AttackGoal) | Yes | No | discriminator | P5 asks about disclosure but never names canonical-read proof with in-root control. |
| Local inclusion into the interpreter through wrappers and poisoning (PreconditionEnvironment, AttackerCapability, AttackTechnique) | Yes | No | discriminator | P5 names wrapper and engine chains but never names poison-then-include or handler-invocation proof. |
| Remote-scheme inclusion with outbound fetch proof (PreconditionEnvironment, AttackerCapability, AttackTechnique) | Yes | No | discriminator | P2 names resource fetchers yet never names scheme enablement checks with hosted-payload OAST proof. |
| Archive extraction write outside the destination (PreconditionEnvironment, AttackerCapability, AttackTechnique) | Yes | No | discriminator | P5 names influence through extract yet never names synthetic-archive proof with outside-write location. |

## 7. Step-coverage falsification
Local filesystem read outside the root: parent step P5 says escalate from disclosure to influence and execution through wrapper and engine chains.
The uncovered reality is canonical small-file reads with same-endpoint in-root controls plus masked-content length adjudication, which needs a read-oracle procedure that P5 never names.
Local inclusion into the interpreter: parent step P5 says escalate to execution through wrapper and engine chains.
The uncovered reality is handler invocation with filter base64 proof plus log and session poisoning plus temp race plus proc reads, which needs a poison-then-include chain procedure that P5 never names.
Remote-scheme inclusion with outbound fetch: parent step P2 says identify resource fetchers and parent step P5 says escalate to execution.
The uncovered reality is scheme enablement verification plus attacker-hosted minimal payload plus OAST beacon confirmation, which needs a host-then-fetch proof procedure that neither P2 nor P5 names.
Archive extraction write outside the destination: parent step P5 says escalate to influence through extract.
The uncovered reality is synthetic archives with traversal entries and symlinks plus extraction plus outside-write location by listings or follow-up reads, which needs an extract-then-locate procedure that P5 never names.
Encoding and mismatch values: no falsification holds because P3 enumerates separators and encodings and P4 covers server-versus-application mismatch escapes.
Payload spelling values: no falsification holds because each owning chain step enumerates its wrapper and URL and entry spellings.
Template resolution: no falsification holds because the local inclusion chain covers dynamic theme resolution as a render sub-step.
Technology and runtime and channel and impact values: no falsification holds because those values parametrise or follow the owning oracle without changing any step kind.
Defence exclusion predicates: no falsification holds because allowlist roots and disabled wrappers and sanitizing extractors are shared negative oracles rather than chain steps.

## 8. Hypotheses
H1 (single-feature, file-operation locus): if the class is partitioned by where user control takes effect into local read versus local inclusion versus remote inclusion versus extract write, then each partition owns a distinct first non-coverable step and jointly covers all four falsifications above.
This hypothesis is falsified if any partition lacks its own non-coverable step or if two partitions claim the same falsification.
H2 (combined-feature, locus crossed with defense layer defeated): if each H1 partition is further split by encoding defeat versus handler-policy defeat versus scheme-policy defeat versus sanitizer defeat, then each cell adds its own non-coverable defeat step.
This hypothesis is falsified if the defeat action kind is identical across cells and P3 plus per-variant defeat enumeration already covers every defense value, leaving cells with no divergence delta.
H3 (combined-feature, locus crossed with technology stack): if each H1 partition is further split by PHP versus Java versus Node versus nginx versus Windows, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the oracle and chain procedure unchanged and only swaps runtime parameters, violating stability.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | traversal-read | Prove out-of-root reads with canonical files plus in-root controls plus masked-content adjudication. |
| H1 | lfi-include-execution | Invoke handlers and wrappers and poison-then-include logs and sessions and temp files with execution proof. |
| H1 | rfi-remote-include | Verify scheme enablement and host a minimal payload and confirm outbound fetch with OAST proof. |
| H1 | archive-zipslip-write | Craft synthetic archives with traversal entries and symlinks and locate outside writes after extraction. |
| H2 | H1 four plus per-defense cells (encoding, handler policy, scheme policy, sanitizer per locus) | Same four first steps; cells add only a parametrized defeat sub-step with no new non-coverable step. |
| H3 | H1 four plus per-stack cells (language, engine, proxy, operating system per locus) | Same four first steps; cells add only stack parameter swaps with no new non-coverable step. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified locus value belongs to exactly one variant.
H1 scores disjointness pass because read-oracle proof and handler chain proof and hosted-fetch proof and extract-locate proof each complete on a distinct oracle, with routing by first non-coverable step in methodology order.
H1 scores divergence delta pass because each variant adds the non-coverable step named in section 9 over P2 or P5.
H1 scores stability pass because swapping language and engine and proxy and operating system and payload literal and endpoint asset leaves each procedure intact.
H1 scores parsimony pass with one collapsed feature family and four variants.
H2 fails divergence delta and parsimony because defeat cells repeat P3 enumeration with no new step and multiply the set size, so H2 is discarded per STATE 4 branch 4a.
H3 fails stability and parsimony because stack cells swap runtime parameters only and multiply variants by technology, so H3 is discarded per STATE 4 branch 4a.
Winner is H1 with losing reason for H2 being zero-delta defeat cells and for H3 being technology-axis instability.
No return to STATE 3 is needed because the winner passes coverage and disjointness.
STATE 1 completed with five parent steps and full entity inventory and no malformed-class outlier.
STATE 2 completed with six non-discriminators and four aspects recorded alongside four discriminator values collapsed per STATE 3 branch 3a into one locus feature.
STATE 3 branch 3b was not needed because every signature value partitions cleanly with no continuous or overlapping range.

## 11. Recommended set
Discrimination function in one sentence: Path traversal with file inclusion decomposes by where attacker-controlled input takes effect, namely the local filesystem read, the local interpreter inclusion, the remote resource inclusion, or the archive extract destination.
Recommended variant traversal-read diverges by proving out-of-root reads with canonical files and in-root controls and masked-content adjudication over parent step P5, which never names read-oracle proof.
Recommended variant lfi-include-execution diverges by invoking wrappers and poisoning logs and sessions and racing temp files with handler-execution proof over parent step P5, which never names poison-then-include chains.
Recommended variant rfi-remote-include diverges by verifying scheme enablement and hosting a minimal payload with OAST fetch confirmation over parent steps P2 and P5, which name fetchers and execution but never name host-then-fetch proof.
Recommended variant archive-zipslip-write diverges by crafting synthetic traversal and symlink archives with outside-write location over parent step P5, which names extract influence but never names extract-then-locate proof.
Non-discriminators are technology stack with versions as excluded runtime axis, runtime asset identity with payload literals as parametrisation, observation channel as oracle readout, downstream pivot impact as consequence, shared submission capability with residue and denial predicates as shared apparatus, and all encoding and mismatch and spelling and template values as aspects inside their owning variants.
Open questions: none at FAIL level; the analysis leaves no uncovered falsification and no skipped state.
Grey points: template dynamic resolution rides inside lfi-include-execution as a render sub-step rather than a standalone variant, which holds only while resolution uses the same poison-then-include chain shape.
Grey points: SSRF-to-execution bridges route to the companion server-side request skill with rfi-remote-include keeping only the fetch-to-execution proof, which holds only while the fetch mechanism needs no separate request-forgery procedure.
Grey points: proxy double-decode ordering rides inside traversal-read as a mismatch sub-step rather than a standalone variant, which holds only while the comparison needs no procedure beyond server-versus-application contrast.
