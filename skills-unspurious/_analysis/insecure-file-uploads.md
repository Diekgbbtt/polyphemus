# insecure-file-uploads - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/insecure-file-uploads/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/insecure-file-uploads/SKILL.md`.
Insecure file uploads here is pipeline-wide failure to keep attacker-controlled file content from executing, rendering, escaping, or exhausting the system across ingress, storage, processors, and serving.
Scope covers extension and MIME bypass families, polyglot and magic-byte spoofs, webshell and handler-config placement, stored script rendering, archive traversal and bombs, converter-toolchain exploits, presigned and resumable deferred-trust flows, processing races, metadata abuse, and serving-header control.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | staged upload pipeline (client, ingress, storage, processors, serving) with validation split across stages | 8, 144 | collapsed into signature feature (pipeline trust-timing side) |
| PreconditionEnvironment | direct-to-cloud presigned flow with attacker-influenced headers, keys, and ACL | 12, 23, 82-87 | collapsed into signature feature (pipeline trust-timing side) |
| PreconditionEnvironment | resumable multipart flow with late metadata control at finalize | 12, 23, 91-94 | collapsed into signature feature (pipeline trust-timing side) |
| PreconditionEnvironment | archive extraction path with traversal and symlink risk | 14, 31, 72-74 | collapsed into signature feature (effect-locus side) |
| PreconditionEnvironment | background processor plus AV/CDR queue with pre-verdict access window | 24, 49-51, 101-104 | collapsed into signature feature (pipeline trust-timing side) |
| PreconditionEnvironment | inline versus attachment serving context with sniffing behavior | 30, 45-47 | collapsed into signature feature (effect-locus side) |
| TechnologyStack | PHP, ASP, JSP, IIS with .htaccess, .user.ini, web.config handler mapping | 37, 56-59 | non-discriminator (runtime stack, excluded axis) |
| TechnologyStack | ImageMagick, GraphicsMagick, Ghostscript, ExifTool, PDF and office converters | 13, 38, 76-80 | non-discriminator (product identity parametrises the toolchain variant) |
| TechnologyStack | S3, GCS, Azure, tus, S3 MPU, CDN, Lambda, Workers, mobile SDK, RTE | 12, 15, 82-87, 116-127 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | extension allowlist with or without server-side content inspection | 131-135 | aspect (enumerated inside server and client variant defeat steps) |
| DefensiveControl | multipart part-header and browser MIME trust | 132-133 | aspect (enumerated inside server and client variant defeat steps) |
| DefensiveControl | magic-byte and content-inspection gate | 28-29, 66-70 | aspect (enumerated inside server and client variant defeat steps) |
| DefensiveControl | AV/CDR quarantine with scan-before-serve enforcement | 49-51, 150-154 | aspect except its timing gap, which is collapsed into signature (pipeline trust-timing side) |
| DefensiveControl | nosniff plus attachment serving headers and presigned policy constraints | 45-47, 82-87 | aspect (enumerated inside client and pipeline variant defeat steps) |
| DefensiveControl | sandboxed converters with no external IO and no script engines | 152 | aspect (negative oracle inside toolchain variant) |
| VulnerabilityClass | insecure file upload | 6-8 | non-discriminator (the class itself) |
| AttackGoal | server-side code execution | 35-38 | collapsed into signature feature (effect-locus side) |
| AttackGoal | client-side script execution | 40-42 | collapsed into signature feature (effect-locus side) |
| AttackGoal | out-of-directory write and overwrite | 72-74 | collapsed into signature feature (effect-locus side) |
| AttackGoal | converter-host execution and file read | 76-80 | collapsed into signature feature (effect-locus side) |
| AttackGoal | resource exhaustion (zip bomb, heavy conversion) | 74, 104 | aspect (exhaustion oracle inside archive and pipeline variants) |
| AttackGoal | malware distribution and storage takeover | 8, 84-85 | non-discriminator (downstream impact of served content, no bent step) |
| AttackerCapability | ability to submit files through app or presigned path | 10-15 | non-discriminator (shared precondition of all candidates) |
| AttackerCapability | ability to fetch the object before the verdict completes | 49-51, 101-104 | collapsed into signature feature (pipeline trust-timing side) |
| AttackerCapability | ability to alter metadata or headers at finalize or presign time | 23, 82-87, 91-94 | collapsed into signature feature (pipeline trust-timing side) |
| AttackTechnique | webshell and handler-config placement with reachable execution | 56-59 | collapsed into signature feature (effect-locus side) |
| AttackTechnique | stored script delivery for inline rendering | 61-64 | collapsed into signature feature (effect-locus side) |
| AttackTechnique | extension games, mixed case, dot tricks, multipart discrepancies | 66-70, 96-100, 137-140 | aspect (encoding inside server and client variants) |
| AttackTechnique | archive traversal, symlink-in-zip, nested zips, zip bomb | 72-74 | collapsed into signature feature (effect-locus side) |
| AttackTechnique | toolchain payload crafting (SVG, PS, EPS, PDF operators, EXIF blocks) | 76-80, 106-109 | collapsed into signature feature (effect-locus side) |
| AttackTechnique | presigned header, ACL, and key control plus signed URL reuse | 82-87 | collapsed into signature feature (pipeline trust-timing side) |
| AttackTechnique | finalize metadata swap and benign-chunk then swap-source | 91-94 | collapsed into signature feature (pipeline trust-timing side) |
| AttackTechnique | pre-verdict fetch loop with window widening | 101-104 | collapsed into signature feature (pipeline trust-timing side) |
| AttackTechnique | header and cache-key manipulation for inline and poisoned serving | 111-114 | aspect (serving sub-step inside client and pipeline variants) |
| PayloadPattern | double extension, mixed case, extra dots, trailing dots and spaces | 68, 96-100, 137-140 | aspect (encoding inside server and client variants) |
| PayloadPattern | magic-byte prefix with embedded server script | 56, 66-70 | aspect (encoding inside server variant) |
| PayloadPattern | SVG and HTML with event handlers and script | 61-64 | aspect (encoding inside client variant) |
| PayloadPattern | zip entry with traversal path, symlink, nested archive, bomb ratio | 72-74 | aspect (encoding inside archive variant) |
| PayloadPattern | oversized EXIF, XMP, IPTC blocks and document properties | 80, 106-109 | aspect (encoding inside toolchain variant) |
| PayloadPattern | handler-directive file content (AddType, AddHandler, auto_prepend) | 56-59 | aspect (encoding inside server variant) |
| PayloadPattern | presigned parameter set (Content-Type, Disposition, key, acl, meta) | 82-87 | aspect (encoding inside pipeline variant) |
| Artifact | uploaded object with serving URL and download headers | 146-148, 158-160 | non-discriminator (tester-produced per attempt, not a variant axis) |
| Artifact | presigned and signed URLs with policy blobs | 82-87 | non-discriminator (runtime credential material parametrising the pipeline variant) |
| Artifact | extracted out-of-directory file and derived thumbnail or conversion | 24, 72-74 | non-discriminator (success residue read through the variant oracle) |
| Artifact | EICAR and tiny polyglot probes | 30-31, 160-164 | non-discriminator (shared probe apparatus across variants) |
| ObservableSignal | interpreter output proving server execution | 35-38 | collapsed into signature feature (oracle side) |
| ObservableSignal | inline script execution proving client execution | 40-42 | collapsed into signature feature (oracle side) |
| ObservableSignal | server-set versus reflected Content-Type with inline versus attachment and nosniff | 30, 45-47 | collapsed into signature feature (oracle side) |
| ObservableSignal | out-of-directory file presence and resource exhaustion | 72-74 | collapsed into signature feature (oracle side) |
| ObservableSignal | pre-verdict accessibility and quarantine transition | 49-51 | collapsed into signature feature (oracle side) |
| ObservableSignal | never-served storage and always-attachment strict-nosniff denial | 150-154 | non-discriminator (shared negative exclusion predicate) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: app and API uploads, avatar and import fields, direct-to-cloud presigned parameters, resumable create-chunk-complete APIs, image and document pipelines, archive and template importers, and app, bucket, CDN, preview, and attachment serving paths; invariant is the staged pipeline shape, what varies is which stage evaluates trust and which stage lets content take effect.
Adversarial capabilities: submitting crafted files, steering presigned and finalize metadata, and fetching objects before verdicts complete; invariant is no control over server code or pipeline policy, what varies is whether the attacker acts only at submission time or also at a late control point.
Common trust assumptions: server assumes extension, MIME headers, magic bytes, or client checks prove type safety, and assumes init-time validation still holds at finalize, presign, extraction, conversion, and serving time; invariant is type-and-timing trust, what varies is which stage assumption is violated.
Testing methodology: the five parent steps P1-P5 listed in section 6; invariant is the map-to-validate spine, what varies is which effect-oracle or late-control step bends per candidate procedure.
Proxy techniques: none held by this class; presigned and resumable flows are first-party deferred control points rather than proxy relays.
Defence bypass techniques: extension games, MIME and magic spoofing, polyglots, multipart discrepancies, filename normalization abuse, finalize swaps, presigned header control, race fetching, and header manipulation; invariant is defeating type or timing checks, what varies is only the check value defeated except where timing defeat needs its own polling procedure, hence mostly aspects with one timing exception.
Techniques anti-patterns: trusting client checks, trusting part headers blindly, allowlisting without content inspection, and delegating security decisions to frontends; these are invariant warnings.
Scripted tests (references/): none shipped with this skill; validation is described inline at methodology step P5 and the detection channels at lines 33-52.
False positives: stored-but-never-served content, always-attachment strict-nosniff serving, sandboxed converters, and quarantine-before-access enforcement; these are invariant exclusion predicates.
Chaining: stored XSS with session theft, webshell with command execution, traversal write with config overwrite, toolchain read with secret theft, and CDN poisoning with broad distribution; chaining targets are invariant companions, not variant axes.

## 4. Runtime parametrisation
Consumed L0/L1 runtime entities are the concrete Service under test, the Endpoint and its Parameter and Header carriers for the upload field, the BaseURL and storage bucket identity, the DataItem for the file object and its metadata surfacing at those carriers, the System mechanism overlays (language runtime, converter toolchain, object store, CDN, AV queue), and the HTTP history showing upload and download requests with serving headers.
The concrete filenames, extensions, MIME strings, magic bytes, size limits, storage keys, ACL strings, presigned URLs, header values, and payload literals are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, product version, payload literal, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding an upload endpoint inventory with pipeline visibility and needing to prove that a crafted file crosses a validation or timing boundary and takes effect somewhere downstream.
Parent methodology steps with completion conditions: P1 map the pipeline, complete when client, ingress, storage, processors, serving, and each validation and auth point are recorded.
P2 identify allowed types, complete when size limits, filename rules, storage keys, and serving party are recorded.
P3 collect baselines, complete when legitimate upload URLs and download headers are captured.
P4 exercise bypass families, complete when extension games, MIME and content-type, magic bytes, polyglots, metadata payloads, and archive structure are attempted and acceptance recorded.
P5 validate execution, complete when server or client execution is demonstrated or its impossibility is established under the false-positive predicates.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Staged pipeline shape (PreconditionEnvironment) | No | N/A | non-discriminator | It frames every candidate; no parent step changes kind when stage names vary. |
| TechnologyStack values and versions (language, converter product, cloud vendor, CDN, SDK) | No | N/A | non-discriminator | Parent steps perform the same kind of action across stacks; stacks are excluded axes. |
| Malware-distribution and takeover impact (AttackGoal) | No | N/A | non-discriminator | Pure downstream impact with no bent step; execution was already proven by the owning variant. |
| Shared file-submission capability (AttackerCapability) | No | N/A | non-discriminator | Shared precondition; every candidate uploads through the same submission shape. |
| Probe artifacts and negative exclusion signals (Artifact, ObservableSignal) | No | N/A | non-discriminator | Tester-produced per attempt and shared denial predicates; no step bends. |
| Extension, MIME, magic-byte, polyglot, and filename encodings (AttackTechnique, PayloadPattern) | Yes | Yes | aspect | P4 performs the same kind of content-bypass attempt and its description enumerates every encoding value, so coverage is complete. |
| Handler-directive file content (PayloadPattern) | Yes | Yes | aspect | P4 content attempts plus server-variant placement cover directive payloads with no new step. |
| Header and cache-key serving tweaks (AttackTechnique) | Yes | Yes | aspect | Client and pipeline serving sub-steps enumerate inline, nosniff, and cache-key values, so coverage is complete. |
| Document-property metadata payloads for previewers (AttackTechnique) | Yes | Yes | aspect | Client-variant render confirmation covers previewer-served properties with no new step. |
| Server interpreter acceptance with webshell placement (PreconditionEnvironment, AttackTechnique, AttackGoal) | Yes | No | discriminator | P5 asks about execution but never names handler mapping, execution-URL discovery, and language-placement confirmation, so it bends. |
| Inline-serving acceptance with browser execution (PreconditionEnvironment, AttackTechnique, AttackGoal) | Yes | No | discriminator | P5 asks about execution but never names serving-header capture, sniffing analysis, and script-fire confirmation, so it bends. |
| Extraction-path acceptance with traversal or symlink content (PreconditionEnvironment, AttackTechnique, AttackGoal) | Yes | No | discriminator | P4 names archive structure and P5 names execution, but neither describes proving out-of-directory writes or exhaustion, so both fail. |
| Converter acceptance with command or file-operator content (PreconditionEnvironment, AttackTechnique, AttackGoal) | Yes | No | discriminator | P5 names server execution but never names conversion triggering with processor side-effect oracles, which differ in kind from requesting an execution URL, so it bends. |
| Late-control acceptance with finalize, presign, or pre-verdict timing (PreconditionEnvironment, AttackerCapability, AttackTechnique) | Yes | No | discriminator | P4 exercises content bypasses at submission but never names late-metadata swaps, presigned header and ACL and key control, or pre-verdict fetch polling, so it bends. |

## 7. Step-coverage falsification
Server interpreter acceptance with webshell placement: parent step P5 says validate whether uploaded content can execute on server or client.
The uncovered reality is handler-mapping discovery plus language-specific placement plus requesting the execution URL for interpreter output, which needs a place-then-invoke-handler procedure that P5 never names.
Inline-serving acceptance with browser execution: parent step P5 says validate whether uploaded content can execute on server or client.
The uncovered reality is download-header capture plus reflection-versus-server-set analysis plus inline-versus-attachment and nosniff adjudication plus script-fire proof, which needs a capture-headers-then-prove-render procedure that P5 never names.
Extraction-path acceptance with traversal content: parent steps P4 and P5 say exercise archive structure and validate execution.
The uncovered reality is extraction-oracle proof of out-of-directory writes, symlink escapes, nested archives, and compression-ratio exhaustion, which needs an extract-then-locate-outside procedure that neither P4 nor P5 names.
Converter acceptance with command content: parent step P5 says validate whether uploaded content can execute on server or client.
The uncovered reality is triggering thumbnail, conversion, and metadata-parse jobs and reading processor side effects such as command output, file reads, and pipe operators, which needs a trigger-job-then-read-side-effect procedure that P5 never names.
Late-control acceptance with finalize and presign timing: parent step P4 says exercise bypass families over extension, MIME, magic bytes, polyglots, metadata, and archive structure.
The uncovered reality is swapping Content-Type and Disposition at finalize, setting presigned headers with ACL and key injection and URL reuse, and polling the object before AV and CDR verdicts with window widening, which needs an act-after-the-gate procedure that P4 never names.
Extension and filename encodings: no falsification holds because P4 enumerates double extensions, casing, dots, homoglyphs, truncation, collisions, and multipart discrepancies.
Handler-directive content: no falsification holds because P4 content attempts combined with server-variant placement cover directive files.
Header and cache-key tweaks: no falsification holds because the serving sub-steps enumerate inline, attachment, nosniff, reflection, and cache-key values.
Previewer document properties: no falsification holds because client-variant render confirmation covers previewer-served script content.

## 8. Hypotheses
H1 (single-feature, effect locus crossed with pipeline trust-timing): if the class is partitioned by where attacker content takes effect into server interpreter, client renderer, extractor filesystem, converter process, and late pipeline control point, then each partition owns a distinct first non-coverable step and jointly covers all five falsifications above.
This hypothesis is falsified if any partition lacks its own non-coverable step or if two partitions claim the same falsification.
H2 (combined-feature, effect locus crossed with defense layer defeated): if each H1 partition is further split by allowlist defeat versus content-inspection defeat versus header-policy defeat versus scan-policy defeat, then each cell adds its own non-coverable defeat step.
This hypothesis is falsified if the defeat action kind is identical across cells and P4 plus per-variant defeat enumeration already covers every defense value, leaving cells with no divergence delta.
H3 (combined-feature, effect locus crossed with technology stack): if each H1 partition is further split by language runtime versus converter product versus cloud vendor versus CDN versus client SDK, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the effect-oracle procedure unchanged and only swaps runtime parameters, violating stability.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | upload-server-execution | Place webshell or handler-config content then discover the execution URL and confirm interpreter output. |
| H1 | upload-client-execution | Capture serving headers then prove inline script fire under reflection, sniffing, and disposition analysis. |
| H1 | upload-archive-extraction | Submit traversal, symlink, nested, and bomb archives then prove out-of-directory writes or exhaustion. |
| H1 | upload-toolchain-execution | Trigger conversion and metadata-parse jobs then confirm processor side effects such as command execution or file reads. |
| H1 | upload-pipeline-deferred-trust | Exercise late control points (finalize swap, presigned header with ACL and key control, pre-verdict fetch polling) then confirm gate bypass with serving effect. |
| H2 | H1 five plus per-defense cells (allowlist, inspection, header policy, scan policy per effect) | Same five first steps; cells add only a parametrized defeat sub-step with no new non-coverable step. |
| H3 | H1 five plus per-stack cells (runtime, converter product, cloud vendor, CDN, SDK) | Same five first steps; cells add only stack parameter swaps with no new non-coverable step. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified locus and timing value belongs to exactly one variant.
H1 scores disjointness pass because interpreter output, inline script fire, out-of-directory presence, processor side effects, and post-gate bypass each complete on a distinct oracle, with routing by first non-coverable step in methodology order.
H1 scores divergence delta pass because each variant adds the non-coverable step named in section 9 over P4 or P5.
H1 scores stability pass because swapping language, converter product, cloud vendor, CDN, payload literal, or endpoint asset leaves each procedure intact.
H1 scores parsimony pass with one collapsed feature family and five variants.
H2 fails divergence delta and parsimony because defeat cells repeat P4 enumeration with no new step and multiply the set size, so H2 is discarded per STATE 4 branch 4a.
H3 fails stability and parsimony because stack cells swap runtime parameters only and multiply variants by technology, so H3 is discarded per STATE 4 branch 4a.
Winner is H1 with losing reason for H2 being zero-delta defeat cells and for H3 being technology-axis instability.
No return to STATE 3 is needed because the winner passes coverage and disjointness.
STATE 1 completed with five parent steps and full entity inventory and no malformed-class outlier.
STATE 2 completed with eight aspects and eight non-discriminators recorded alongside five discriminator values collapsed per STATE 3 branch 3a into one feature family.
STATE 3 branch 3b was not needed because every signature value partitions cleanly with no continuous or overlapping range.

## 11. Recommended set
Discrimination function in one sentence: Insecure file uploads decompose by where attacker-controlled file content takes effect, namely the server interpreter, the client renderer, the extractor filesystem, the converter process, or a late pipeline control point that bypasses an earlier validation gate.
Recommended variant upload-server-execution diverges by placing webshell or handler-config content with execution-URL discovery and interpreter-output confirmation over parent step P5, which never names handler mapping or language placement.
Recommended variant upload-client-execution diverges by capturing serving headers with reflection, sniffing, and disposition analysis plus script-fire proof over parent step P5, which never names header adjudication or render confirmation.
Recommended variant upload-archive-extraction diverges by proving out-of-directory writes, symlink escapes, and compression exhaustion over parent steps P4 and P5, which name archive structure and execution but never name extraction-oracle proof.
Recommended variant upload-toolchain-execution diverges by triggering conversion and metadata-parse jobs with processor side-effect confirmation over parent step P5, which never names job triggering or side-effect oracles.
Recommended variant upload-pipeline-deferred-trust diverges by exercising finalize swaps, presigned header with ACL and key control, and pre-verdict fetch polling over parent step P4, which covers only submission-time content bypasses and never names act-after-the-gate control.
Non-discriminators are staged pipeline shape as shared framing, technology stack with versions as excluded runtime axis, malware-distribution impact as downstream consequence, shared file-submission capability with probe artifacts and negative exclusion signals as shared apparatus, and all content-encoding values as aspects inside their owning variants.
Open questions: none at FAIL level; the analysis leaves no uncovered falsification and no skipped state.
Grey points: presigned SVG that renders inline routes to pipeline-deferred-trust by first-divergence order with render confirmation kept as a secondary divergence, which holds only while the presigned control plane is the finding and inline rendering is its effect.
Grey points: CDN cache-key poisoning rides inside pipeline-deferred-trust as a serving-stage secondary divergence rather than a standalone variant, which holds only while poisoning needs no cache-oracle procedure beyond serving-header comparison.
Grey points: heavy-conversion window widening rides inside pipeline-deferred-trust as a timing secondary divergence rather than inside toolchain-execution, which holds only while the conversion load serves timing rather than command execution.
