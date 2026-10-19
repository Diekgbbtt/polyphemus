---
name: llm-prompt-injection
description: Testing LLM-backed features for prompt injection, jailbreaks, system-prompt leakage, tool/agent abuse, direct tool-server and retrieval-layer testing, and unsafe output handling
metadata:
  version: 1.0.0
---

# LLM Prompt Injection

Applications that pass untrusted input into a model prompt are vulnerable to prompt injection: attacker-controlled text overrides developer instructions, leaks the system prompt, abuses connected tools, or exfiltrates data. Treat every model-backed feature as a confused deputy: the model holds the application's privileges (tools, retrieved data, credentials) but cannot reliably tell instructions from data. Impact is defined by what the model can do, not just what it can say.

## Attack Surface

**Direct Injection**
- **Direct surfaces**: chat interfaces, assistants, transform features (summarize, translate, rewrite), search, support agents.

**Indirect Injection**
- **Ingested content**: pages, documents, messages, retrieved corpus entries, file names, markup metadata, image descriptions, code comments.

**Tool and Agent Layer**
- **Tool surfaces**: function calling, plugins, code execution, query and fetch tools, file access, browsing, messaging actions.
- **Tool-server endpoints**: a tool layer reachable as its own endpoint, where tools are listed and called directly and the model is bypassed.

**Retrieval Layer**
- **Corpus store**: the corpus store behind retrieval, reachable on its own beside the chat path, with its own scoping and identifier space.

**Output Sinks**
- **Output sinks**: model output rendered as markup, used in a query or command, or followed as a redirect or link.

## Reconnaissance

### Identify the Surface

- **Prompt entry points**: where does user input enter a prompt: direct chat, or content the model ingests.
- **Model reach**: what can the model reach: the retrieved corpus, tools, function schemas, memory, other tenants' data.
- **Tool-layer enumeration**: enumerate the tool layer as its own endpoint where it is reachable: a listing operation that returns every tool with its input schema, and a call path per tool.
- **Retrieval-layer enumeration**: enumerate the retrieval layer: which corpus, namespace, and record identifiers the store exposes beside the chat path.
- **Output destinations**: where does output go: rendered markup, a downstream API, another agent.
- **Guard layer**: is there a moderation or guard layer, and is it in-band (the same model) or out-of-band.

### Fingerprint the Rules

- **Verbatim-repeat requests**: ask the model to repeat its instructions verbatim, or to output everything above the first user message.
- **Refusal observation**: observe refusal patterns and boilerplate to infer the system prompt and the guardrail boundary.

## Detection Channels

- **Behaviour change**: behaviour change against developer intent, which confirms the model followed attacker instructions.
- **Refusal-pattern shift**: refusal-pattern shift across repeated turns, which signals a guardrail boundary rather than a pass.
- **Absence of change**: absence of change after override, breakout, and wrapped attempts, which records a resisted probe.
- **Non-reproducible compliance**: non-reproducible compliance across runs, which marks chatter rather than a finding.
- **Disclosed hidden text**: disclosed hidden text matching ground truth, which confirms an extraction positive.
- **Hallucinated instruction text**: hallucinated instruction text that matches no ground truth, which marks a negative.
- **Tool-schema disclosure**: tool-schema disclosure in the response, which confirms schema extraction even without a call.
- **Victim-session behaviour change**: behaviour change in the victim's session against developer intent, which confirms planted text executed.
- **Retrieved-content citation**: retrieved-content citation that surfaces the planted record, which confirms the seeding path works.
- **Victim-context tool call**: tool call performed in the victim's context with planted arguments, which confirms cross-domain steering.
- **Absence of execution**: absence of execution after retrieval, which confirms the plant was treated as data.
- **Sink execution**: rendered script execution or a dispatched request at the sink, which confirms a handling positive.
- **Sink transcript**: sink transcript showing the emitted markup or statements, which confirms the emission reached the sink.
- **Proper encoding**: properly encoded output at the sink, which confirms a negative even when the model emitted a suspicious shape.
- **Outbound context request**: an outbound request carrying context data to an attacker-observable destination, which confirms an exfiltration channel.
- **Attacker-argument tool call**: a tool call with attacker-chosen arguments, which confirms a steering positive.
- **Invocation-log entry**: an invocation log entry binding one call to its arguments, which confirms the chained path.
- **Downstream state change**: a state change or exfiltration observable downstream, which confirms the call took effect.
- **Absence of a call**: absence of a call after steering, which confirms the model treated the content as words.
- **Unattributed tool call**: a tool call the invocation log cannot bind to a model turn, which proves the tool endpoint is reachable directly.
- **Retrieval-layer read**: corpus content or record metadata returned to a caller the retrieval layer does not scope, which proves the isolation gap.
- **Lifecycle-state acceptance**: a call accepted in a state the interface agreement forbids, which proves the state-transition trust gap.

## Adversarial Capabilities

- **Prerequisites**: model testing presupposes prompt control, a victim context the content can reach, and observation of what the model does, and it consumes all three.
- **Text submission**: send arbitrary text through the direct input and through every ingest path the application exposes.
- **Content planting**: plant content the model will later retrieve or read: documents, corpus entries, file names, metadata fields.
- **Victim trigger**: hold a victim session and trigger the retrieval or summarization action that detonates the plant.
- **Invocation observation**: observe tool invocations, their arguments, and downstream effects in logs or in state.
- **Sink reading**: read the sink for each output class: rendered markup, generated queries, emitted links.
- **Repetition**: send the same probe repeatedly to separate a reproducible effect from run-to-run variance.
- **Direct layer calling**: call the tool endpoint and the retrieval store directly, without a model turn, where either interface is reachable.
- **Second clean session**: hold a second clean session to prove a persistent plant survived the first conversation.

## Trust Assumptions

- **The agreement**: the class rests on one agreement: text the model ingests is data, and the model's output is data for whoever consumes it. The agreement holds developer instructions and ingested content in separate trust domains, holds the guard layer to a decision independent of the model's own compliance, holds tool arguments to values the application authorizes, and holds output to encoding at the sink. Sensitive position leaks when a clause fails: the model treats content as instruction, the guard approves what the model was persuaded of, a tool call runs with attacker arguments, or the sink renders the output as live markup.
- **The failing clause**: each variant breaks one clause: the instruction-domain clause, the guard-independence clause, the tool-authorization clause, the retrieval-trigger clause, or the sink-encoding clause.
- **Direct-layer agreement**: the agreement also covers the tool and retrieval layers when they are reachable on their own: each lifecycle transition keeps the identity and permission decisions the previous one established, and the declared tool interface is the interface the server enforces.

## Key Vulnerabilities

### Direct Instruction Override

- **Inline override**: text claiming to supersede earlier instructions, a fabricated role marker, or a delimiter that closes the application's data block and opens a new instruction block.
- **Instruction laundering**: instruction laundering across turns, where a request split across messages passes individually.
- **Payload reference**: see `references/llm-injection-payloads.md` for the phrase families behind override, breakout, extraction, and exfiltration shapes.

### Indirect Cross-Domain Injection

- **Content hiding**: hide instructions in ingested content the victim later asks about: metadata fields, comments, alternate text, document properties.
- **Retrieval seeding**: seeding an entry the retriever surfaces for a target query, so retrieval itself becomes the trigger.
- **Follow-on action**: instructions that direct a follow-on action, such as calling a messaging or fetch tool with attacker arguments.

### Hidden-Context and Data Leakage

- **Hidden-text extraction**: extract the system prompt, hidden context, tool schemas, or other users' data present in context.
- **Framing shapes**: verbatim-repeat framing and span-extraction framing are the two reliable shapes.
- **Memory and corpora**: treat memory and multi-tenant corpora as attacker-readable until proven otherwise.

### Tool and Function-Call Abuse

- **Call steering**: steer the model into calling a privileged tool with attacker-chosen arguments.
- **Argument injection**: argument injection into query, fetch, or command tools the model can reach.
- **Call chaining**: chain injected content into a call, then confirm the call in the invocation log.

### Tool-Server Lifecycle and Interface Agreement

- **Direct reachability**: where the tool server is reachable on its own, tool listing, permission checks, and parameter validation are server-side duties, so a call can arrive with no model turn behind it.
- **Interface agreement**: the declared input schema is assumed to be what the server accepts, so a parameter the schema does not declare but a handler consumes is a server-side validation gap.
- **Lifecycle trust**: each transition carries forward the identity and permission decisions of the previous one, so a state that skips a check opens the call path.
- **Tool-permission gap**: the server trusts the model to respect permissions, so a direct call reaches a tool the model would refuse.
- **Cross-tool chains**: an execution-capable tool beside a fetch or file tool turns one accepted call into a chain; name the ssrf and rce skills at those steps.

### Insecure Output Handling

- **Unescaped markup**: model output rendered unescaped at a markup sink executes in the viewer's browser.
- **Downstream interpreters**: output used in a query, a command, or a redirect sink carries injection into that interpreter.
- **Markup images**: markup images whose URL carries context data produce a zero-click exfiltration channel at render time.
- **Adopted code**: where the output is code a developer adopts, steering the emission toward an insecure shape is the same sink problem with a human in the loop.

## Bypass Techniques

- **Bypass scope**: guardrails are probed as a control beside the model, so each shape below tests the guard rather than the model.
- **Framing**: role-play and hypothetical framing, and wrappers that present the request as an authorized test.
- **Instruction laundering**: instruction laundering across turns, so each turn looks benign alone.
- **Encoding and obfuscation**: alternate alphabets, homoglyphs, invisible characters, translation into another language, and wrapped forms.
- **Invisible codepoints**: invisible tag-plane codepoints, zero-width characters, and bidirectional controls carry an instruction past a text filter while the model still consumes them.
- **Matcher probing**: encoded, transposed, or substituted-alphabet forms of a blocked phrase pass a keyword matcher, so probe the matcher beside the model.
- **Delimiter breakout**: delimiter breakout combined with a wrapped payload, so one layer clears the filter and the next delivers the instruction.
- **Split requests**: split requests across messages or parameters, where the filter sees fragments and the model reassembles them.
- **Encoder reference**: see `scripts/tag-plane-smuggle.py` for the tag-plane encoder and decoder behind the invisible-codepoint shape.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Tool-call chain**: injected content plus a tool call: the model performs the privileged action with attacker arguments.
- **Retrieval chain**: injected content plus a retrieved corpus: seeding one entry detonates on every future retrieval for that query.
- **Sink chain**: injection plus an output sink: the emitted markup fires in another user's browser or reaches a downstream interpreter.
- **Cross-tenant chain**: injection plus memory or cross-tenant context: one tenant's planted text surfaces in another tenant's answer.
- **Exfiltration chain**: leakage plus a fetch tool: the extracted context is carried out through an outbound request.
- **Capability ordering**: capability classes chain in order: content ingestion, memory or corpus persistence, tool invocation, privilege escalation, and outbound exfiltration.
- **Direct tool-server chain**: a direct tool-server call plus a privileged tool: the chain needs no model turn, so name the tool-server block at the entry step.

## Testing Methodology

1. **Map trust boundaries** - Input sources, model capabilities and tools, output sinks
2. **Direct probes** - Instruction override, delimiter breakout, encoded payloads
3. **Indirect probes** - Plant instructions in ingested content and trigger retrieval or summarization
4. **Leakage probes** - Attempt to extract the system prompt, tool schemas, and cross-tenant data
5. **Tool-abuse probes** - Steer the model into privileged calls with attacker arguments
6. **Output-handling probes** - Emit markup, query, and link shapes, then check the sink
7. **Guardrail probes** - Test whether moderation is in-band and bypassable
8. **Confirm reproducibility** - Repeat each positive probe; the step completes when every claim holds across runs and reaches a real sink
9. **Direct-layer probes** - Call the tool endpoint and the retrieval store directly, without a model turn; the step completes when each direct interface carries a reachability and permission verdict

## Variants

- direct-injection-override - Override model behaviour through direct chat input, breaking delimiter framing and smuggling instructions past input filters.
- indirect-injection-plant - Plant instructions in ingested content the model later retrieves, including retrieval-ranked corpus records and second-order sources, then trigger detonation through a victim action.
- context-leakage - Extract hidden system text, tool schemas, and cross-tenant data through verbatim-repeat probes, and map the refusal boundary.
- tool-abuse - Steer the model toward privileged tool calls with attacker-chosen arguments, chaining injected content into invocations, including direct calls to a reachable tool server where the model is bypassed.
- output-handling - Coax sink-bearing markup, statements, and links from the model, then prove rendering or execution at the sink.

## False Positives

- **Words without a sink**: the model saying it will do something with no privileged sink or tool to actually do it.
- **Refusals and hallucinations**: refusals, or hallucinated instruction text that matches no ground truth.
- **Properly encoded output**: output that is properly encoded before reaching a markup, query, or command sink.
- **Non-reproducing behaviour**: behaviour that does not reproduce across runs, which is variance rather than a bypass.
- **Sandboxed tools**: sandboxed tools with no access to sensitive data or actions.
- **Model-mediated-only endpoint**: a tool endpoint that refuses direct calls and requires a model-mediated invocation, confirmed by uniform refusals without a turn.

## Pro Tips

- **Guardrail posture**: treat in-band guardrails as bypassable and focus on the capability and sink behind the model.
- **Indirect first**: indirect injection is the higher-severity, under-tested vector; always test content the model ingests, not only the chat input.
- **Sink chasing**: chase the sink: an injection is critical only when it reaches a tool, another system, or an unescaped renderer.
- **Markup rendering**: markup image rendering is a classic zero-click exfiltration channel; test it explicitly.
- **Ground-truth pairing**: keep a ground-truth pair for every leakage probe so hallucinated text is discarded immediately.
- **Obfuscation probing**: encode and obfuscate to probe filter strength, then combine with delimiter breakout.
- **Reproducible impact**: confirm real, reproducible impact; model chatter is not a finding.
- **Direct-layer probing**: probe the tool and retrieval layers directly where they are reachable, because the model is optional there and the server owns the checks.

## Summary

Model-backed features are confused deputies wielding the application's privileges over untrusted text. The severity of prompt injection is set by the model's connected tools, data, and output sinks, not by clever wording. Test direct and indirect vectors, prove impact at a real sink, and never treat in-band guardrails as a control. Where the tool server or the retrieval store is reachable on its own, test it directly: the model is bypassed there and the server owns identity, validation, and per-message authorization.
