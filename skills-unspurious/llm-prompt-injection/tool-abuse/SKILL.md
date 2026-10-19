---
name: tool-abuse
description: Steer the model toward privileged tool calls with attacker-chosen arguments, chain injected content into invocations, confirm each call in the log, and probe a reachable tool server directly.
metadata:
  version: 1.0.0
---

# Tool Abuse

An LLM feature wired to privileged tools becomes an actuator when injected content steers tool choice and arguments.
This variant proves steering by directing the model toward chosen tools plus filling attacker arguments plus chaining content into calls.
The abuse goal is a logged invocation with attacker-controlled effect rather than words in a transcript.

## Attack Surface

Applicability centers on an LLM-backed feature with a reachable tool or agent layer.
The layer exposes capabilities such as data access plus messaging plus retrieval plus state-changing actions.
A tool server reachable as its own endpoint is part of the surface: tools are listed and called there without a model turn.
Delivery may arrive through direct turns or planted content, since delivery is an aspect carried inside this variant.
An invocation log or otherwise observable call record is required for this variant.

## Reconnaissance

Abuse work starts by mapping the tool layer before sending any steering probe.
- Enumerate every model-reachable tool with its capability plus its argument shape.
- Enumerate the tool-listing operation where the server is reachable directly: it returns every tool with its input schema, which maps destructive capabilities before any call.
- Record the connection lifecycle and which identity and permission decisions each transition carries forward.
- Record which tools touch sensitive data or actions versus sandboxed no-effect stubs.
- Note argument validation placement and whether checks run server-side or model-side.
- List the invocation log source that will confirm each steered call.

## Detection Channels

Abuse listens to invocation evidence, so only the entries below are live here.
- Tool call performed with attacker-chosen arguments confirms a steering positive.
- Invocation log entry binding one call to its arguments confirms the chained path.
- State change or exfiltration observable downstream confirms the call took effect.
- Absence of a call after steering confirms the model treated the content as words.
- **Direct tool call**: a call the invocation log cannot bind to a model turn, which proves the server is reachable without the model.
- **Lifecycle-state acceptance**: a call accepted in a state the interface agreement forbids, which proves the state-transition trust gap.

## Adversarial Capabilities

Abuse presupposes prompt influence plus tool reachability, and it consumes both.
- Submit steering text through direct turns or through planted ingested content.
- Name or describe a target tool so the model selects it over alternatives.
- Fill privileged arguments with attacker-chosen values through the same steering text.
- Chain injected content into a call sequence that moves from read toward effect.
- Call the tool endpoint directly, without a model turn, where the interface is reachable.
- Place a scheduled task or a key through an execution-capable tool where the capability exists, so access outlives the session.
- Read the invocation log to confirm each call with its arguments.

## Trust Assumptions

The feature executes under an agreement that the model separates instructions from data, treats ingested content as untrusted data, holds tool choice plus arguments to developer intent, keeps hidden system text undisclosed, and emits only sink-safe output.
Sensitive application behavior changes only when developer instructions direct them.
This variant breaks the tool-choice-and-arguments clause because a privileged tool is selected and parameterised by attacker-steered content.
Where the tool server is reachable directly, this variant also breaks the interface-agreement clause: the declared interface is assumed to be the enforced interface, and each lifecycle transition is assumed to keep the identity and permission decisions of the previous one.

## Key Vulnerabilities

### Tool Steering

Direct the model toward one chosen tool by describing the task so that tool is the natural selection.
Vary the steering framing across attempts because one description never covers every tool set.
The parent tool-abuse step names only generic steering and cannot describe log-confirmed selection, so this variant owns the steering procedure.

### Argument Injection

Fill the chosen tool's arguments with attacker-selected values carried in the steering text.
Shape each argument through placeholders that match the tool's expected value shape.
Treat a logged call carrying the attacker's values as a positive and treat defaulted or refused arguments as a resisted probe.

### Content-to-Call Chaining

Chain injected content through the model into a call sequence that progresses from read toward state change or exfiltration.
Confirm each link in the invocation log rather than in chat text, because transcript claims without a logged call prove nothing.
Treat a markdown-exfiltration pattern that fires through a tool call as abuse here, since the proving artifact is the log rather than a render.

### Tool-Server Lifecycle and Interface Agreement

Direct reachability makes tool listing, permission checks, and parameter validation server-side duties rather than prompt-steering outcomes, so probe the endpoint with no model turn behind the call.
The declared input schema is assumed to be what the server accepts, so a parameter the schema does not declare but a handler consumes is a server-side validation gap.
Each lifecycle transition is assumed to carry forward the identity and permission decisions of the previous one, so a state that skips a check opens the call path.
The server trusts the model to respect permissions, so a direct call reaches a tool the model would refuse; chain an execution-capable tool with a fetch or file tool and name the ssrf and rce skills at those steps.

## Advanced Techniques

- **Progressive escalation**: begin with a read-capable tool call and progress toward effect, since each accepted call establishes the capability the next one needs.
- **Capability boundary testing**: probe each tool's declared capability against what the server actually permits, and record the gap as a permission-enforcement finding.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no wrapper changes the invocation step itself.
- Paraphrase reframing redescribes the tool task when a direct steering phrase is refused.
- Multi-turn laundering spreads tool selection and argument filling across several turns.
- Encoding wrappers disguise argument values past input-side filters.
- Split-request framing separates the tool choice from the argument values across messages.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Abuse chains forward into effect because a logged call without consequence is only partial proof.
- Hand a read-capable call to output-handling where the sink renders or forwards the returned data.
- Hand a messaging-capable call to indirect-injection-plant for victim-context propagation.
- Hand schema detail learned here back to context-leakage for deeper hidden-text extraction.
- A tool-use fetch to a cloud metadata address names the ssrf skill at the fetch step, since the tool holds an elevated network position.
- A scheduled task or key placed through an execution-capable tool keeps access after the session, so file the persistence path as its own finding.
- Treat argument validation findings here as the guardrail intelligence sink variants reuse.

## Testing Methodology

Abuse runs steering first and everything else follows, because no argument claim stands without a logged call.
1. **Inventory tools** - list every reachable tool with its argument shape plus its log source, including the tool-listing operation and the lifecycle states where the server is reachable directly, and the step completes when no unlisted tool remains.
2. **Steer selection** - direct the model toward one chosen tool per framing, and the step completes when every steering probe shows a selected or refused verdict.
3. **Inject arguments** - fill privileged arguments with placeholder-shaped values, and the step completes when every argument probe shows an attacker-valued or defaulted verdict.
4. **Chain content to calls** - progress injected content from read toward effect through logged sequences, and the step completes when every chain shows a log-confirmed or words-only verdict.
5. **Probe the direct interface** - call the tool endpoint with no model turn and vary the lifecycle state, and the step completes when every direct call shows a permitted or refused verdict with its state recorded.
6. **Confirm effect** - check the downstream state or exfiltration channel, and the step completes when every logged call shows an effected or inert verdict.

## False Positives

Stop when the evidence shows talk of tools without invocation, because transcript promises without a logged call are not findings.
- The model describing a call it never makes in the invocation log.
- Calls into sandboxed stubs with no sensitive data or action behind them.
- Argument values the server-side validation neutralises before effect.
- Single-run calls that never reproduce across repeated steering.
- Hallucinated tool names matching no inventoried capability.
- A tool server that refuses direct calls and requires a model-mediated invocation, confirmed by uniform refusals without a turn.

## Pro Tips

Abuse rewards log discipline plus argument shaping plus chain patience.
1. Confirm every claim in the invocation log because chat text alone never proves a call.
2. Shape arguments to the tool's expected value form so rejections reflect policy rather than malformation.
3. Progress chains from read toward effect so each link earns the next privilege.
4. Log each call behind its steering text plus arguments so attribution survives review.
5. Treat server-side argument validation as the real boundary and probe it explicitly.
6. Probe the tool server directly where it is reachable; the model is optional there and the server owns the checks.

## Summary

A model with tool access that obeys injected content lends its privileges to whoever shapes the prompt.
Abuse proves that loan with steered selection plus attacker arguments plus chained sequences, confirmed call by call in the invocation log until effect is shown. Where the tool server is reachable on its own, the same procedure runs with no model turn, and the server's own identity, interface, and lifecycle checks become the boundary.
