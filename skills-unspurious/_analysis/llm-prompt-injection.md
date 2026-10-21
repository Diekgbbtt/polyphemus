# llm-prompt-injection - variant decomposition analysis

## 1. Class and scope
The llm-prompt-injection class covers testing of LLM-backed features for prompt injection, jailbreaks, system-prompt leakage, tool or agent abuse, and unsafe output handling.
Its authority is `skills-unspurious/llm-prompt-injection/SKILL.md` (107 lines), consulted against `skills/llm-prompt-injection/SKILL.md` only for extra methodology detail.
The class frames every LLM feature as a confused deputy that holds the application's privileges over untrusted text, so impact is defined by what the model can do through tools, data, and sinks rather than by what it can say.
The analysis derives five variants from the class's own ontology values plus the two-half step test, with STATE 1 through STATE 7 worked without skipping.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | LLM-backed feature reachable; prompt entry via direct chat input versus ingested content (web pages, PDFs, emails, RAG documents, filenames, HTML metadata, alt-text, code comments); tool or agent layer present (function calling, plugins, code execution, SQL or HTTP tools, file access, browsing, send actions); output sink present (HTML renderer, SQL, shell, redirect or URL); guard layer present in-band or out-of-band | 10-22, 26-31 | Discriminator candidate (entry channel bends S2 versus S3; tool-layer and sink presence bend S5 and S6) |
| TechnologyStack | Framework and provider names appear only in the live skill (LangChain or LangGraph, OpenAI Assistants or function calling, Anthropic tool use, LlamaIndex or RAG pipelines, NeMo Guardrails or LLM Guard); the authority skill names none | Live 87-115; authority none | Non-discriminator (excluded axis under the stability criterion) |
| DefensiveControl | In-band same-model moderation versus out-of-band guard; input filters; output encoding or sanitization; sandboxed tools; server-side argument validation | 30, 46, 56, 72-75, 89-93; live 112-115 | Aspect inside S7 and S6, not a variant axis (placement changes where the agent checks, never the kind of checking action) |
| VulnerabilityClass | Prompt injection as the weakness, with jailbreak as an evasion manner and the confused-deputy framing as the class definition | 6-8, 72-75 | Non-discriminator (this value is the class itself, never a value that bends a step) |
| AttackGoal | Override developer instructions; extract system prompt, tool schemas, or cross-tenant data; invoke privileged tools for exfiltration or state change; achieve XSS or downstream injection through model output; bypass content policy | 8, 55-70, 72-75 | Discriminator candidate through the sink trio (leakage, tool abuse, output handling bend S4, S5, S6); pure policy-bypass chatter without a sink is an aspect under the false-positive rule |
| AttackerCapability | Ability to submit direct chat input in the attacker's own session versus ability to author content the model later ingests plus a victim trigger versus co-authorship of multi-tenant RAG or memory | 12-16, 50-53; live 117-130 | Discriminator candidate (the channel values bend S2 versus S3); credential and role specifics are non-discriminators |
| AttackTechnique | Instruction override with fake roles and delimiter breakout; encoded or obfuscated smuggling; indirect planting with RAG poisoning and victim-triggered retrieval; verbatim-repeat leakage extraction with refusal-boilerplate inference; tool steering and chaining with argument injection; HTML or markdown or SQL bearing output emission; multi-turn laundering and request-splitting jailbreaks | 33-46, 48-75, 79-85 | Discriminator candidate in five families (override, plant, leak, steer, emit); jailbreak wrappings are aspects of the family they wrap |
| PayloadPattern | Ignore-previous-instructions template; fake SYSTEM markers; delimiter closers; base64, ROT13, homoglyph, zero-width, translation, and leetspeak wrappers; hidden white-on-white, comment, alt-text, and metadata placements; markdown image exfiltration URL; img-onerror HTML | 42-46, 50-52, 58, 68-70 | Non-discriminator (each pattern is the documented instrument of its own step, and swapping one wrapper for another never changes the kind of action) |
| Artifact | System-prompt text; tool schemas; cross-tenant secrets or data; tool invocation log; rendered DOM, outbound request, or sink transcript | 33-36, 55-58, 62, 68-70, 89 | Non-discriminator (runtime-produced proof that parametrises confirmation) |
| ObservableSignal | Behavior change against developer intent; tool call performed with attacker arguments; exfiltrated data at a sink; executed script or rendered image request; refusal pattern or boilerplate shift; properly encoded output as a negative; non-reproducible chatter as a negative | 33-36, 87-93 | Non-discriminator (detection signals are read the same way by every split) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: the four surfaces are direct chat entry, ingested content, the tool or agent layer, and output sinks, with recon identifying prompt entry, model capabilities, output destination, and guard placement (lines 10-31).
This notion varies by entry channel and sink presence, and that variation is exactly what the step test promotes to discriminators.
Adversarial capabilities: the ladder runs from anonymous chat input to planted ingested content with a victim trigger to co-authorship of shared corpora (lines 12-16, 50-53).
This notion varies by channel and carries the direct-versus-indirect discriminator.
Common trust assumptions: the model can separate instructions from data, in-band guardrails hold, RAG and memory are not attacker-writable, and model output is safe to render or forward (lines 8, 30, 95-103).
This notion is invariant as the assumption set under test across all variants.
Testing methodology: the seven parent steps S1 to S7 (lines 79-85) are the step-test substrate.
This notion is invariant as parent text and each step states its own completion condition.
Proxy techniques: argument injection into model-reachable SQL, HTTP, and shell tools is reached at S5 (lines 60-64).
This notion invokes sink-skill interpretation at the reached step instead of restating it.
Defence bypass techniques: encoded payloads, delimiter breakout, role-play, multi-turn laundering, and request splitting are the named bypasses (lines 44-46, 72-75).
This notion is an aspect inside the probe steps because no bypass value adds its own non-coverable step.
Techniques anti-patterns: trusting in-band guardrails, testing only the chat box, and claiming chatter without sink proof are the named anti-patterns (lines 95-103).
This notion is invariant across all candidates.
Scripted tests (`references/`): none are shipped with the class skill.
No invariant is stated beyond the inline payload examples.
False positives: unexecuted threats, hallucinated prompts, sanitized output, non-reproducible behavior, and sandboxed tools are the named non-findings (lines 87-93).
This notion is invariant confirmation discipline across all variants.
Chaining: injected content leads to tool calls leads to exfiltration or state change, and indirect plants detonate in a victim's privileged context (lines 60-64; live 117-130).
This notion is invariant plumbing composed across variants rather than a split axis.

## 4. Runtime parametrisation
Each procedure consumes the concrete Service under test and the LLM mechanism System it lies on.
It consumes the Endpoint path and BaseURL where the chat or ingestion feature lives, the Parameter or Header atoms carrying attacker text, and the DataItem records for retrieved documents, memory entries, and tool arguments.
The HTTP history supplies prior prompt-response transcripts, refusal baselines, tool invocation logs, and rendered-sink evidence.
The operator knowledge base supplies test accounts, the victim-action script for triggering retrieval, and seeded corpus notes.
None of these entities defines a variant because swapping one endpoint, parameter, document, or credential for another never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an application exposing an LLM feature where the agent holds direct chat access and, where applicable, the ability to publish content the feature ingests.
S1 Map trust boundaries: enumerate input sources, model capabilities and tools, and output sinks, with completion when every prompt entry, tool, and sink is listed.
S2 Direct probes: send instruction overrides, delimiter breakouts, and encoded payloads in the agent's own turns, with completion when the model follows or resists attacker instructions in chat.
S3 Indirect probes: plant instructions in ingested content and trigger retrieval or summarization through a normal user action, with completion when planted content does or does not execute in the victim's context.
S4 Leakage probes: attempt extraction of the system prompt, tool schemas, and cross-tenant data with verbatim-repeat requests, with completion when hidden text is disclosed or the refusal boundary is mapped.
S5 Tool-abuse probes: steer the model toward privileged tool calls with attacker-chosen arguments and chain injected content to calls, with completion when a tool invocation log shows the call with its arguments.
S6 Output-handling probes: coax HTML, markdown, or SQL bearing output from the model and inspect the sink, with completion when rendering, execution, or exfiltration is proven or proper encoding is confirmed.
S7 Guardrail probes: determine whether moderation is in-band and bypassable and whether the guard inspects the final merged prompt, with completion when guard placement and bypassability are recorded.
S1 is shared setup carried as preamble in every variant, and S7 is confirmation discipline carried as an aspect inside every variant.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Entry channel direct versus indirect (own chat turn versus planted content with victim trigger) | Yes (S2 sends payloads directly while S3 plants content and triggers retrieval, which are different kinds of action) | No (S2 text covers override, breakout, and encoding but never planting, seeding, or victim triggering) | Discriminator (S2 versus S3) | Lines 12-16, 40-53 versus S2 at line 80 and S3 at line 81 |
| Leakage goal (system prompt, schemas, cross-tenant data) | Yes (S4 extracts hidden text while S2 overrides behavior, which are different kinds of action) | No (S2 text covers following attacker instructions but never verbatim-repeat extraction or boilerplate inference) | Discriminator (S4) | Lines 33-36, 55-58 versus S2 at line 80 and S4 at line 82 |
| Tool-abuse goal (privileged calls with attacker arguments) | Yes (S5 produces a tool invocation while S2 produces words, which are different kinds of action) | No (S2 text never steers tool choice, fills arguments, or chains content to calls) | Discriminator (S5) | Lines 60-64 versus S2 at line 80 and S5 at line 83 |
| Output-handling goal (rendered, executed, or forwarded model output) | Yes (S6 proves sink behavior while S2 proves chat behavior, which are different kinds of action) | No (S2 text never emits sink-bearing output nor inspects a renderer) | Discriminator (S6) | Lines 66-70 versus S2 at line 80 and S6 at line 84 |
| Guard placement in-band versus out-of-band | No (probing bypassability and checking the merged prompt is the same kind of action under either placement) | Yes (S7 text names the in-band question and the final-merged-prompt check explicitly) | Aspect inside every variant | Line 85 with lines 30, 72-75; live 112-115 |
| Jailbreak and encoding wrappers (role-play, hypotheticals, laundering, splitting, base64, homoglyphs) | No (wrapping is the same kind of action as the underlying probe) | Yes (the wrapped steps already cover the wrapped values once applied) | Aspect, not a variant axis | Lines 44-46, 72-75 per STATE 3 branch 3b |
| Framework identity (LangChain, OpenAI, Anthropic, LlamaIndex, guardrail products) | No (renaming the framework never changes the kind of testing action) | Not applicable (no parent step is framework-specific) | Non-discriminator | Stability criterion excludes TechnologyStack |
| Payload pattern choice (marker text, delimiter form, encoding) | No (one wrapper versus another is the same kind of action) | Yes (each probe step documents its own instruments) | Non-discriminator | Lines 42-46, 50-52, 68-70 |
| Sink identity (HTML versus SQL versus shell versus redirect) | No (checking the sink is the same kind of action regardless of which sink it is) | Yes (S6 text enumerates HTML, markdown, SQL, command, and redirect sinks) | Aspect inside the output-handling variant | Lines 66-70, 84 |
| Credential, tenant, and document specifics | No (one secret or document versus another is the same kind of action) | Not applicable | Non-discriminator (runtime parameters) | Section 4 |

## 7. Step-coverage falsification
Direct-override value: parent S2 covers it because S2 names instruction override, delimiter breakout, and encoded payloads with a chat-behavior completion condition.
Indirect-plant value: parent S2 fails it because no reading of override, breakout, or encoding text covers authoring third-party content, seeding a retriever, and detonating through a victim's normal action, so S3 is non-coverable from S2.
Leakage value: parent S2 fails it because behavior-following text never covers verbatim-repeat extraction of hidden instructions, schema disclosure, or cross-tenant reads with boilerplate inference, so S4 is non-coverable from S2.
Tool-abuse value: parent S2 fails it because chat-behavior text never covers steering tool choice, filling privileged arguments, or chaining injected content into a logged invocation, so S5 is non-coverable from S2 and from S4.
Output-handling value: parent S2 fails it because chat-behavior text never covers emitting sink-bearing markup and proving rendering, execution, or forwarding at the sink, so S6 is non-coverable from S2 and from S5.
Guard-placement values: parent S7 covers both because S7 names the in-band question and the merged-prompt check with one completion condition.
Encoding and jailbreak values: every parent probe step covers its wrapped values because the wrappers ride inside the existing probe without changing its completion condition.
Framework values: no parent step is left uncovered because no parent step is framework-specific in the first place.
STATE 2 therefore exits through branch 2b with five discriminator-bearing values across two signature features.

## 8. Hypotheses
H1 Single-feature hypothesis on entry channel: if the delivery channel discriminates, then direct-override and indirect-plant deserve variants, and it is falsified if any genuine non-coverable proof step (leakage, tool abuse, output handling) is left without a variant.
H2 Single-feature hypothesis on proof sink: if the proving sink discriminates, then leakage, tool-abuse, and output-handling deserve variants, and it is falsified if indirect delivery (planting plus victim triggering) is left without a variant.
H3 Combined-feature hypothesis on channel by sink: if channel and sink jointly discriminate, then direct-override, indirect-plant, leakage, tool-abuse, and output-handling deserve variants with delivery recorded as an aspect inside the sink variants and membership decided by the terminal proving step, and it is falsified if any proposed variant lacks its own non-coverable step or if two variants admit the same terminal proof.
H4 Framework-split hypothesis: if framework identity discriminates, then LangChain, OpenAI, Anthropic, and LlamaIndex each deserve a variant, and it is falsified by the stability criterion because renaming the framework preserves every testing step.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | direct-override | S2 direct probes (non-coverable from S1 mapping alone) | Override markers, delimiter forms, and encoding wrappers as aspects |
| H1 | indirect-plant | S3 indirect probes (non-coverable from S2) | Hiding places, RAG seeding, and victim triggers as aspects |
| H2 | leakage-proof | S4 leakage probes (non-coverable from S2) | Direct versus indirect delivery as aspects; refusal-boilerplate inference carried inside |
| H2 | tool-abuse-proof | S5 tool-abuse probes (non-coverable from S2 and S4) | Delivery channel and argument-dictionary specifics as aspects |
| H2 | output-proof | S6 output-handling probes (non-coverable from S2 and S5) | Delivery channel and sink identity as aspects |
| H3 | direct-injection-override | S2 direct probes | Encoding and jailbreak wrappers plus guardrail checks as aspects |
| H3 | indirect-injection-plant | S3 indirect probes | Hiding places, RAG seeding, victim triggers, and guardrail checks as aspects |
| H3 | context-leakage | S4 leakage probes | Delivery channel and refusal-boilerplate inference as aspects |
| H3 | tool-abuse | S5 tool-abuse probes | Delivery channel, argument dictionaries, and chaining notes as aspects |
| H3 | output-handling | S6 output-handling probes | Delivery channel, sink identity, and markdown-exfil patterns as aspects |
| H4 | langchain-variant; openai-variant; anthropic-variant; llamaindex-variant | none per variant (no framework adds its own non-coverable step) | Framework API names as runtime notes |

## 10. Well-formedness evaluation
Coverage (critical): H1 fails because S4, S5, and S6 proofs belong to no variant, and H2 fails because S3 planting belongs to no variant, while H3 covers S2 through S6 with S1 as shared setup and S7 as an aspect, and H4 covers nothing with a delta.
Disjointness (critical): H1 passes narrowly but irrelevantly on its uncovered set, and H2 passes on proofs yet collides on delivery because one payload can be delivered either way, while H3 passes because membership is decided by the terminal proving step so a direct-delivered leak lives only in context-leakage and a planted tool-steer lives only in tool-abuse, and H4 is disjoint but empty.
Divergence delta (high): every H3 variant adds a non-coverable step over the parent (S2 chat override, S3 plant-plus-trigger, S4 hidden-text extraction, S5 logged invocation, S6 sink proof), while every H4 variant carries zero delta and is deleted.
Stability (high): H3 survives renaming of frameworks, payload dictionaries, model versions, endpoints, documents, and credentials, while H4 depends entirely on the excluded TechnologyStack axis.
Parsimony (medium): H3 uses two features (channel plus sink) which is the fewest that still covers, because dropping either feature reopens the coverage failure that falsified H1 or H2.
Winner: H3 is well-formed, and the losing reason for H1 and H2 is coverage failure, while the losing reason for H4 is zero divergence delta compounded by stability failure.
No return to STATE 3 was needed because channel and sink never co-vary (every sink is reachable through either channel), so no collapse applied, and only continuous wrapper strength folded to aspect under branch 3b.

## 11. Recommended set
Discrimination function: llm-prompt-injection discriminates by entry channel (direct chat versus planted ingested content with a victim trigger) crossed with proving sink (behavior override versus hidden-text disclosure versus logged tool invocation versus sink rendering or execution).
Recommended variant direct-injection-override: first non-coverable step S2 direct probes, with divergence delta of attacker-instruction following proven in the attacker's own chat turns.
Recommended variant indirect-injection-plant: first non-coverable step S3 indirect probes, with divergence delta of planted instructions detonating through a victim's normal retrieval or summarization action.
Recommended variant context-leakage: first non-coverable step S4 leakage probes, with divergence delta of hidden system text, tool schemas, or cross-tenant data disclosed and matched against ground truth.
Recommended variant tool-abuse: first non-coverable step S5 tool-abuse probes, with divergence delta of a privileged tool invoked with attacker-chosen arguments and captured in the invocation log.
Recommended variant output-handling: first non-coverable step S6 output-handling probes, with divergence delta of model-emitted markup or statements proven rendered, executed, forwarded, or exfiltrated at the sink.
Non-discriminators: all TechnologyStack framework names; guard placement and filter identity; payload patterns and encoding wrappers; jailbreak framings; sink identity within S6; credential, tenant, document, endpoint, parameter, and history specifics; all Artifact proof objects; all ObservableSignal shapes.
STATE 1 completed with seven parent steps S1 to S7 and no malformed-class stop.
STATE 2 tested every ledger value with both halves and exited through branch 2b with discriminators recorded at their failing steps.
STATE 3 fixed the channel-by-sink signature with no collapse and folded only wrapper strength to aspect.
STATE 4 hypothesised two single-feature splits, one combined split, and one framework split, and STATE 5 derived their sets with secondary divergences carried inside.
STATE 6 scored all four sets on the weighted criteria and H3 won while H1 and H2 lost on coverage and H4 lost on delta and stability.
Grey points: a full indirect-to-tool-to-exfiltration chain composes three variants in order (plant, then steer, then sink proof) rather than living in one of them, so each stage keeps its own terminal proof.
Grey points: a direct-delivered verbatim-repeat request lives in context-leakage rather than direct-injection-override because membership follows the terminal proving step, which keeps delivery-delivered proofs disjoint.
Grey points: markdown-image exfiltration steered through a tool call lives in tool-abuse while the same pattern reaching a renderer lives in output-handling, and the proving artifact (invocation log versus rendered request) decides between them.
Open questions: none at FAIL level, and no uncertainty blocks the five-variant recommendation.
