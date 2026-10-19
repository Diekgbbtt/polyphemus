---
name: llm-prompt-injection
description: Testing LLM-backed features for prompt injection, jailbreaks, system-prompt leakage, tool/agent abuse, and unsafe output handling
metadata:
  version: 1.0.0
---

# LLM Prompt Injection

Applications that pass untrusted input into a model prompt are vulnerable to prompt injection: attacker-controlled text overrides developer instructions, leaks the system prompt, abuses connected tools, or exfiltrates data. Treat every model-backed feature as a confused deputy: the model holds the application's privileges (tools, retrieved data, credentials) but cannot reliably tell instructions from data. Impact is defined by what the model can do, not just what it can say.

## Attack Surface

**Direct Injection**
- Chat interfaces, assistants, transform features (summarize, translate, rewrite), search, support agents

**Indirect Injection**
- Content the model ingests: pages, documents, messages, retrieved corpus entries, file names, markup metadata, image descriptions, code comments

**Tool and Agent Layer**
- Function calling, plugins, code execution, query and fetch tools, file access, browsing, messaging actions

**Output Sinks**
- Model output rendered as markup, used in a query or command, or followed as a redirect or link

## Reconnaissance

### Identify the Surface

- Where does user input enter a prompt: direct chat, or content the model ingests
- What can the model reach: the retrieved corpus, tools, function schemas, memory, other tenants' data
- Where does output go: rendered markup, a downstream API, another agent
- Is there a moderation or guard layer, and is it in-band (the same model) or out-of-band

### Fingerprint the Rules

- Ask the model to repeat its instructions verbatim, or to output everything above the first user message
- Observe refusal patterns and boilerplate to infer the system prompt and the guardrail boundary

## Detection Channels

- Behaviour change against developer intent, which confirms the model followed attacker instructions.
- Refusal-pattern shift across repeated turns, which signals a guardrail boundary rather than a pass.
- Absence of change after override, breakout, and wrapped attempts, which records a resisted probe.
- Non-reproducible compliance across runs, which marks chatter rather than a finding.
- Disclosed hidden text matching ground truth, which confirms an extraction positive.
- Hallucinated instruction text that matches no ground truth, which marks a negative.
- Tool-schema disclosure in the response, which confirms schema extraction even without a call.
- Behaviour change in the victim's session against developer intent, which confirms planted text executed.
- Retrieved-content citation that surfaces the planted record, which confirms the seeding path works.
- Tool call performed in the victim's context with planted arguments, which confirms cross-domain steering.
- Absence of execution after retrieval, which confirms the plant was treated as data.
- Rendered script execution or a dispatched request at the sink, which confirms a handling positive.
- Sink transcript showing the emitted markup or statements, which confirms the emission reached the sink.
- Properly encoded output at the sink, which confirms a negative even when the model emitted a suspicious shape.
- An outbound request carrying context data to an attacker-observable destination, which confirms an exfiltration channel.
- A tool call with attacker-chosen arguments, which confirms a steering positive.
- An invocation log entry binding one call to its arguments, which confirms the chained path.
- A state change or exfiltration observable downstream, which confirms the call took effect.
- Absence of a call after steering, which confirms the model treated the content as words.

## Adversarial Capabilities

Model testing presupposes prompt control, a victim context the content can reach, and observation of what the model does, and it consumes all three.
- Send arbitrary text through the direct input and through every ingest path the application exposes.
- Plant content the model will later retrieve or read: documents, corpus entries, file names, metadata fields.
- Hold a victim session and trigger the retrieval or summarization action that detonates the plant.
- Observe tool invocations, their arguments, and downstream effects in logs or in state.
- Read the sink for each output class: rendered markup, generated queries, emitted links.
- Send the same probe repeatedly to separate a reproducible effect from run-to-run variance.

## Trust Assumptions

The class rests on one agreement: text the model ingests is data, and the model's output is data for whoever consumes it.
The agreement holds developer instructions and ingested content in separate trust domains, holds the guard layer to a decision independent of the model's own compliance, holds tool arguments to values the application authorizes, and holds output to encoding at the sink.
Sensitive position leaks when a clause fails: the model treats content as instruction, the guard approves what the model was persuaded of, a tool call runs with attacker arguments, or the sink renders the output as live markup.
Each variant breaks one clause: the instruction-domain clause, the guard-independence clause, the tool-authorization clause, the retrieval-trigger clause, or the sink-encoding clause.

## Key Vulnerabilities

### Direct Instruction Override

- Inline override: text claiming to supersede earlier instructions, a fabricated role marker, or a delimiter that closes the application's data block and opens a new instruction block
- Instruction laundering across turns, where a request split across messages passes individually

### Indirect Cross-Domain Injection

- Hide instructions in ingested content the victim later asks about: metadata fields, comments, alternate text, document properties
- Seeding an entry the retriever surfaces for a target query, so retrieval itself becomes the trigger
- Instructions that direct a follow-on action, such as calling a messaging or fetch tool with attacker arguments

### Hidden-Context and Data Leakage

- Extract the system prompt, hidden context, tool schemas, or other users' data present in context
- Verbatim-repeat framing and span-extraction framing are the two reliable shapes
- Treat memory and multi-tenant corpora as attacker-readable until proven otherwise

### Tool and Function-Call Abuse

- Steer the model into calling a privileged tool with attacker-chosen arguments
- Argument injection into query, fetch, or command tools the model can reach
- Chain injected content into a call, then confirm the call in the invocation log

### Insecure Output Handling

- Model output rendered unescaped at a markup sink executes in the viewer's browser
- Output used in a query, a command, or a redirect sink carries injection into that interpreter
- Markup images whose URL carries context data produce a zero-click exfiltration channel at render time

## Bypass Techniques

Guardrails are probed as a control beside the model, so each shape below tests the guard rather than the model.
- Role-play and hypothetical framing, and wrappers that present the request as an authorized test
- Instruction laundering across turns, so each turn looks benign alone
- Encoding and obfuscation: alternate alphabets, homoglyphs, invisible characters, translation into another language, and wrapped forms
- Delimiter breakout combined with a wrapped payload, so one layer clears the filter and the next delivers the instruction
- Split requests across messages or parameters, where the filter sees fragments and the model reassembles them

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Injected content plus a tool call: the model performs the privileged action with attacker arguments
- Injected content plus a retrieved corpus: seeding one entry detonates on every future retrieval for that query
- Injection plus an output sink: the emitted markup fires in another user's browser or reaches a downstream interpreter
- Injection plus memory or cross-tenant context: one tenant's planted text surfaces in another tenant's answer
- Leakage plus a fetch tool: the extracted context is carried out through an outbound request

## Testing Methodology

1. **Map trust boundaries** - Input sources, model capabilities and tools, output sinks
2. **Direct probes** - Instruction override, delimiter breakout, encoded payloads
3. **Indirect probes** - Plant instructions in ingested content and trigger retrieval or summarization
4. **Leakage probes** - Attempt to extract the system prompt, tool schemas, and cross-tenant data
5. **Tool-abuse probes** - Steer the model into privileged calls with attacker arguments
6. **Output-handling probes** - Emit markup, query, and link shapes, then check the sink
7. **Guardrail probes** - Test whether moderation is in-band and bypassable
8. **Confirm reproducibility** - Repeat each positive probe; the step completes when every claim holds across runs and reaches a real sink

## Variants

- direct-injection-override - Override model behaviour through direct chat input, breaking delimiter framing and smuggling instructions past input filters.
- indirect-injection-plant - Plant instructions in ingested content the model later retrieves, then trigger detonation through a victim action.
- context-leakage - Extract hidden system text, tool schemas, and cross-tenant data through verbatim-repeat probes, and map the refusal boundary.
- tool-abuse - Steer the model toward privileged tool calls with attacker-chosen arguments, chaining injected content into invocations.
- output-handling - Coax sink-bearing markup, statements, and links from the model, then prove rendering or execution at the sink.

## False Positives

- The model saying it will do something with no privileged sink or tool to actually do it
- Refusals, or hallucinated instruction text that matches no ground truth
- Output that is properly encoded before reaching a markup, query, or command sink
- Behaviour that does not reproduce across runs, which is variance rather than a bypass
- Sandboxed tools with no access to sensitive data or actions

## Pro Tips

1. Treat in-band guardrails as bypassable and focus on the capability and sink behind the model
2. Indirect injection is the higher-severity, under-tested vector; always test content the model ingests, not only the chat input
3. Chase the sink: an injection is critical only when it reaches a tool, another system, or an unescaped renderer
4. Markup image rendering is a classic zero-click exfiltration channel; test it explicitly
5. Keep a ground-truth pair for every leakage probe so hallucinated text is discarded immediately
6. Encode and obfuscate to probe filter strength, then combine with delimiter breakout
7. Confirm real, reproducible impact; model chatter is not a finding

## Summary

Model-backed features are confused deputies wielding the application's privileges over untrusted text. The severity of prompt injection is set by the model's connected tools, data, and output sinks, not by clever wording. Test direct and indirect vectors, prove impact at a real sink, and never treat in-band guardrails as a control.
