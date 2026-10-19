---
name: rce
description: RCE testing covering command injection, deserialization, template injection, and code evaluation
metadata:
  version: 1.0.0
---

# RCE

Remote code execution leads to full server control when input reaches code execution primitives: OS command wrappers, dynamic evaluators, template engines, decoders, media pipelines, and internal control services. Focus on quiet, portable oracles and chain to stable shells only when needed.

## Attack Surface

**Command Execution**
- OS command execution through wrappers, shells, and CLI delegates

**Dynamic Evaluation**
- Template engines, expression languages, and evaluation runtimes

**Decoders**
- Native unmarshalling and encoded container formats that resolve types at decode time

**Media and Document Pipelines**
- Image converters, document renderers, metadata tools, typesetting engines, and transcoders

**Internal Service Sinks**
- Services reached through a fetch that execute on request (script consoles, key-value stores, process managers)

**Container and Cluster Control**
- Application execution escalating to the node and the cluster through mounts, sockets, and tokens

## Reconnaissance

### Sink Inventory

- Enumerate every delegate that receives user-influenced content: command wrappers, template rendering, decoder entry points, file converters, report generators, plugin hooks
- Treat utility-style surfaces as applicability signals: network diagnostics, file conversion, archive utilities, and report generators that build a shell string for the caller
- For each sink, note whether input arrives as data, as an argument, or as file content
- Trace stored inputs that a batch job or pipeline later evaluates

### Baseline and Oracle Setup

- Mint a unique callback marker per probe and confirm listener infrastructure receives DNS and HTTP arrivals before any effect payload
- Where only name-resolution egress survives, carry the result in an encoded label of the callback name so the arrival returns data rather than mere liveness
- Measure a response-time baseline so a gated delay is attributable
- Record output length and digest for plain-control requests so a reflected-output differential is calibrated

### Environment Inventory

- Identify the runtime, shell, and delegate set behind each sink where errors or version markers reveal them
- For white-box scope, enumerate the dependency inventory and match it to known chain families
- Note whether the sink runs in-process, out-of-process, or in a sandbox

## Detection Channels

- Delay oracle separates execution from noise when a short gated delay shifts response timing past its baseline.
- Callback oracle binds one minted unique marker per probe to one inbound arrival on operated listener infrastructure.
- Reflected-output oracle separates execution from noise when response length or digest shifts with the probe result.
- Quoting-break error class separates a live wrapper from inert handling when delimiter acceptance changes status text or timing class.
- Flag-acceptance signal separates a live CLI sink from a plain string sink when option-shaped input alters behavior without executing.
- Job-trigger signal separates a live delegate from inert storage when an upload fires a conversion or parse job.
- Derived-artifact difference separates execution from rendering when converted outputs or error state carry operator results.
- Job-duration delta separates operator evaluation from clean conversion when processing time shifts past its baseline.
- Planted-marker surfacing proves file-read operators when unique out-of-scope content appears in derived outputs.
- Policy-gate signal separates an enforcing build from a permissive one when operator families succeed or fail as a group.
- Context-confirmation read discloses the execution user, working directory, shell, and confinement markers once execution is proven.

## Adversarial Capabilities

RCE testing presupposes a reachable execution sink, a no-effect oracle, and a boundary map, and it consumes all three.
- Reach a sink: an OS wrapper, an evaluator, a decoder, a converter, or an internal control service.
- Operate listener infrastructure and mint a unique marker per probe for DNS and HTTP arrivals.
- Read timing, output, and error-class differences against a calibrated baseline.
- Craft files that survive the front door and reach the delegate unchanged in meaning.
- Send the gated probe repeatedly within the target's tolerance so a delay verdict is stable.
- Enumerate the confinement boundary (user, working directory, shell, sandbox markers) once execution is proven.

## Trust Assumptions

The class rests on one agreement: no data string becomes instructions at any delegate the input reaches.
The agreement holds each sink to a fixed argument list with no caller-supplied option or path, holds evaluators to constant templates, holds decoders to non-executing formats, and holds the execution environment to a confinement that limits what a granted instruction could do.
Full host position leaks when any clause fails: a delimiter breaks quoting, an option reaches the argument list, a template evaluates caller-supplied content, a decoder instantiates a caller-named type, or a delegate evaluates file content.
Each variant reaches the same failure at a different delegate: an OS wrapper, or a converter and renderer pipeline.

## Key Vulnerabilities

### Command Execution

- Delimiter and operator classes across Unix-style and Windows-style shells, including substitution and environment expansion
- Argument injection: flags, output paths, and configuration options accepted in place of the expected value
- Quoting breaks: alternate quotes and escapes that end the quoted segment early
- Path and builtin confusion: absolute paths, alternative tools, and wrapper invocations that reach the shell anyway
- Evasion: whitespace alternatives, token splitting, variable building, and encoded stagers
- Body-to-parser matching: match the body encoding to the parser the endpoint reads, because a structured body against a form parser yields a silent false negative with a plausible success status, and the probe must be re-encoded before any conclusion is drawn

### Evaluation and Template Sinks

- Template rendering that evaluates caller-supplied expressions reaches the host language and process interfaces
- A header-delivered expression evaluated during routing runs before the authorization filter, so the sink executes on a path the caller never authenticated for
- Minimal probes reveal engine identity; the engine family decides the path from expression to execution
- Template selection from user input converts a name into file selection; combine with the traversal class where it does

### Decoder Sinks

- Any byte stream reaching a native decoder with attacker-influenced types is an execution candidate
- Self-executing encodings run code during decode by design
- Treat this as an entry point and hand off to the deserialization class for chain assembly

### Media and Document Pipelines

- Converters and renderers evaluate file content during processing, often out-of-process with powerful delegates
- Metadata, typesetting, and transcoding tools invoke external programs and honour embedded directives
- Directives and pipeline shapes must reach the delegate intact; test the exact file shapes each stage accepts

### Internal Service Sinks

- Fetch translation reaches internal control interfaces that execute on request
- Script consoles, key-value stores, and process managers are the high-value internal targets
- Reachability is the gate: confirm the internal destination before assembling the request

### Container and Cluster Escalation

- From application execution, enumerate container markers, mounts, capabilities, and exposed sockets
- Cluster agent credentials and metadata services extend execution to the node and the platform
- Escalation paths: privileged pods, mounted host paths, and control interfaces; document the shortest durable chain

## Advanced Techniques

**Quiet Oracle Discipline**
- Run a no-effect oracle first (callback, gated delay, or output digest) before sending any effect payload
- Confirm the sink is live, then choose the smallest effect that proves control

**Deferred and Second-Order Triggers**
- Plant a file or record that a batch job, converter, or pipeline executes later
- Attribute the effect by timing correlation between the plant and the trigger

**Confinement and Escalation**
- Enumerate the confinement boundary before claiming impact: user, directory, shell, sandbox markers, capabilities
- Escalate through the control interfaces the environment exposes, and stop at the narrowest durable control

**Filtered Paths**
- When one delimiter class or keyword is filtered, switch the oracle channel and the delegate
- Keep payloads portable across the shell and toolset the target exposes

## Bypass Techniques

**Encoding Differentials**
- URL encoding, Unicode normalization, comment insertion, and mixed case to slip past string filters
- Reach alternate parsers through front-end and backend disagreement

**Binary Alternatives**
- Absolute paths and alternative binaries for the same operation
- Alternate shell and interpreter selections where one family is filtered

**Delegate Substitution**
- Where the primary delegate is filtered, reach the same operation through a converter, pipeline, or internal service

**Indirection and Token Shaping**
- Reach the same operation through a language-level indirection when its name is filtered, because a send or call primitive resolves the name at runtime
- Shape whitespace alternatives past a token filter: field separators, brace expansion, redirection in place of a space, wildcard expansion, and quote splitting
- Decode a staged token at execution time so the filter never reads the plain operation string

Filter and encoding shapes are the defence-bypass family's steps; name it there rather than restating the mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Execution to durable control: file write, scheduled execution, and service restart hooks
- Fetch translation to an internal execution interface, which converts SSRF into execution
- Execution to credential and token stores, then movement to other systems
- Upload pipelines to conversion delegates, where the front door accepts the file the delegate evaluates
- Treat an execution primitive as two halves: one that puts bytes on the host and one that interprets them, so name the `sql-injection`, `insecure-file-uploads`, `prototype-pollution`, and `xxe` classes at the steps that supply each half rather than restating their mechanics here

## Testing Methodology

1. **Identify sinks** - Command wrappers, template rendering, decoder paths, file converters, report generators, plugin hooks
2. **Establish the oracle** - Timing, callbacks, or deterministic output differentials
3. **Confirm context** - User, working directory, path, shell, sandbox, and container markers
4. **Map boundaries** - Read and write locations, outbound egress, and internal reach
5. **Progress to control** - File write, scheduled execution, and service hooks; stop at the narrowest durable effect
6. **Confirm the effect** - Keep the probe set minimal and repeatable, with each step carrying a verdict

## Variants

- rce-command-injection - Break shell quoting and CLI flag parsing so command strings reach OS execution.
- rce-pipeline-execution - Trigger converter and renderer delegates with crafted files so the pipeline evaluates content.

## False Positives

- Crashes or timeouts without controlled behavior
- Filtered execution of a limited command subset with no attacker-controlled arguments
- Sandboxed interpreters running in a restricted environment with no IO and no process spawn
- Simulated outputs not derived from executed commands
- Delays explained by general load rather than the gated probe; repeat the probe to separate the two
- Callbacks that arrive from a different source than the target's egress path

## Pro Tips

1. Prefer callback oracles; when using delays, keep them short and gated to reduce noise
2. When command execution is weak, pivot to file write, decoding, or template paths
3. Treat converters and renderers as first-class sinks; many run out-of-process with powerful delegates
4. Enumerate the dependency inventory before assembling chains, and prove each link with a no-effect oracle
5. Confirm the environment early: path, shell, sandbox, and container capabilities
6. Keep payloads portable across the toolset and minimize dependencies
7. Document the smallest exploit chain that proves durable impact; avoid unnecessary shells

## Summary

RCE is a property of the execution boundary. Find the sink, establish a quiet oracle, and escalate to durable control only as far as necessary. Validate across transports and environments; defences often differ per code path.
