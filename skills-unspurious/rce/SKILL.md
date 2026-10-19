---
name: rce
description: Remote code execution testing covering OS command injection, template and expression evaluation, decoder exploits, media pipelines, and internal service sinks
metadata:
  version: 1.0.0
---

# RCE

Remote code execution leads to full server control when input reaches code execution primitives: OS command wrappers, dynamic evaluators, template engines, decoders, media pipelines, and internal control services. Focus on quiet, portable oracles and chain to stable shells only when needed.

## Attack Surface

**Command Execution**
- **OS command execution**: through wrappers, shells, and CLI delegates

**Dynamic Evaluation**
- **Template engines and evaluators**: template engines, expression languages, and evaluation runtimes

**Decoders**
- **Native unmarshalling**: native unmarshalling and encoded container formats that resolve types at decode time

**Media and Document Pipelines**
- **Media and document tools**: image converters, document renderers, metadata tools, typesetting engines, and transcoders

**Internal Service Sinks**
- **Fetch-reached services**: services reached through a fetch that execute on request (script consoles, key-value stores, process managers)

**Container and Cluster Control**
- **Cluster escalation**: application execution escalating to the node and the cluster through mounts, sockets, and tokens

## Reconnaissance

### Sink Inventory

- **Delegate enumeration**: enumerate every delegate that receives user-influenced content - command wrappers, template rendering, decoder entry points, file converters, report generators, plugin hooks
- **Utility-surface signals**: treat utility-style surfaces as applicability signals - network diagnostics, file conversion, archive utilities, and report generators that build a shell string for the caller
- **Input arrival mode**: for each sink, note whether input arrives as data, as an argument, or as file content
- **Stored-input tracing**: trace stored inputs that a batch job or pipeline later evaluates

### Baseline and Oracle Setup

- **Callback marker minting**: mint a unique callback marker per probe and confirm listener infrastructure receives DNS and HTTP arrivals before any effect payload
- **Encoded-label egress**: where only name-resolution egress survives, carry the result in an encoded label of the callback name so the arrival returns data rather than mere liveness
- **Response-time baseline**: measure a response-time baseline so a gated delay is attributable
- **Output-digest calibration**: record output length and digest for plain-control requests so a reflected-output differential is calibrated

### Environment Inventory

- **Runtime identification**: identify the runtime, shell, and delegate set behind each sink where errors or version markers reveal them
- **Dependency inventory**: for white-box scope, enumerate the dependency inventory and match it to known chain families
- **Process placement**: note whether the sink runs in-process, out-of-process, or in a sandbox

## Detection Channels

- **Delay oracle**: separates execution from noise when a short gated delay shifts response timing past its baseline.
- **Callback oracle**: binds one minted unique marker per probe to one inbound arrival on operated listener infrastructure.
- **Reflected-output oracle**: separates execution from noise when response length or digest shifts with the probe result.
- **Quoting-break error class**: separates a live wrapper from inert handling when delimiter acceptance changes status text or timing class.
- **Flag-acceptance signal**: separates a live CLI sink from a plain string sink when option-shaped input alters behavior without executing.
- **Job-trigger signal**: separates a live delegate from inert storage when an upload fires a conversion or parse job.
- **Derived-artifact difference**: separates execution from rendering when converted outputs or error state carry operator results.
- **Job-duration delta**: separates operator evaluation from clean conversion when processing time shifts past its baseline.
- **Planted-marker surfacing**: proves file-read operators when unique out-of-scope content appears in derived outputs.
- **Policy-gate signal**: separates an enforcing build from a permissive one when operator families succeed or fail as a group.
- **Context-confirmation read**: discloses the execution user, working directory, shell, and confinement markers once execution is proven.

## Adversarial Capabilities

- **Testing prerequisites**: a reachable execution sink, a no-effect oracle, and a boundary map, which the class consumes.
- **Sink reach**: reach a sink - an OS wrapper, an evaluator, a decoder, a converter, or an internal control service.
- **Listener operation**: operate listener infrastructure and mint a unique marker per probe for DNS and HTTP arrivals.
- **Differential reading**: read timing, output, and error-class differences against a calibrated baseline.
- **File crafting**: craft files that survive the front door and reach the delegate unchanged in meaning.
- **Repeated gated probes**: send the gated probe repeatedly within the target's tolerance so a delay verdict is stable.
- **Confinement enumeration**: enumerate the confinement boundary (user, working directory, shell, sandbox markers) once execution is proven.

## Trust Assumptions

- **The agreement**: no data string becomes instructions at any delegate the input reaches.
- **Held conditions**: the agreement holds each sink to a fixed argument list with no caller-supplied option or path, holds evaluators to constant templates, holds decoders to non-executing formats, and holds the execution environment to a confinement that limits what a granted instruction could do.
- **The failing clause**: full host position leaks when any clause fails - a delimiter breaks quoting, an option reaches the argument list, a template evaluates caller-supplied content, a decoder instantiates a caller-named type, or a delegate evaluates file content.
- **Variant delegates**: each variant reaches the same failure at a different delegate - an OS wrapper, or a converter and renderer pipeline.

## Key Vulnerabilities

### Command Execution

- **Delimiter and operator classes**: across Unix-style and Windows-style shells, including substitution and environment expansion
- **Argument injection**: flags, output paths, and configuration options accepted in place of the expected value
- **Quoting breaks**: alternate quotes and escapes that end the quoted segment early
- **Path and builtin confusion**: absolute paths, alternative tools, and wrapper invocations that reach the shell anyway
- **Evasion**: whitespace alternatives, token splitting, variable building, and encoded stagers
- **Body-to-parser matching**: match the body encoding to the parser the endpoint reads, because a structured body against a form parser yields a silent false negative with a plausible success status, and the probe must be re-encoded before any conclusion is drawn

### Evaluation and Template Sinks

- **Template rendering**: template rendering that evaluates caller-supplied expressions reaches the host language and process interfaces
- **Routing-time evaluation**: a header-delivered expression evaluated during routing runs before the authorization filter, so the sink executes on a path the caller never authenticated for
- **Engine identity**: minimal probes reveal engine identity; the engine family decides the path from expression to execution
- **Template selection**: template selection from user input converts a name into file selection; combine with the traversal class where it does

### Decoder Sinks

- **Decoder reach**: any byte stream reaching a native decoder with attacker-influenced types is an execution candidate
- **Self-executing encodings**: self-executing encodings run code during decode by design
- **Deserialization handoff**: treat this as an entry point and hand off to the deserialization class for chain assembly

### Media and Document Pipelines

- **Converter and renderer evaluation**: converters and renderers evaluate file content during processing, often out-of-process with powerful delegates
- **Metadata and typesetting tools**: metadata, typesetting, and transcoding tools invoke external programs and honour embedded directives
- **Directive integrity**: directives and pipeline shapes must reach the delegate intact; test the exact file shapes each stage accepts

### Internal Service Sinks

- **Fetch translation**: fetch translation reaches internal control interfaces that execute on request
- **High-value internal targets**: script consoles, key-value stores, and process managers are the high-value internal targets
- **Reachability gate**: reachability is the gate - confirm the internal destination before assembling the request

### Container and Cluster Escalation

- **Container markers**: from application execution, enumerate container markers, mounts, capabilities, and exposed sockets
- **Cluster credentials**: cluster agent credentials and metadata services extend execution to the node and the platform
- **Escalation paths**: privileged pods, mounted host paths, and control interfaces; document the shortest durable chain

## Advanced Techniques

**Quiet Oracle Discipline**
- **No-effect oracle first**: run a no-effect oracle first (callback, gated delay, or output digest) before sending any effect payload
- **Smallest proving effect**: confirm the sink is live, then choose the smallest effect that proves control

**Deferred and Second-Order Triggers**
- **Deferred plant**: plant a file or record that a batch job, converter, or pipeline executes later
- **Timing attribution**: attribute the effect by timing correlation between the plant and the trigger

**Confinement and Escalation**
- **Boundary enumeration**: enumerate the confinement boundary before claiming impact - user, directory, shell, sandbox markers, capabilities
- **Narrowest durable control**: escalate through the control interfaces the environment exposes, and stop at the narrowest durable control

**Filtered Paths**
- **Channel and delegate switching**: when one delimiter class or keyword is filtered, switch the oracle channel and the delegate
- **Payload portability**: keep payloads portable across the shell and toolset the target exposes

## Bypass Techniques

**Encoding Differentials**
- **Encoding and case variants**: URL encoding, Unicode normalization, comment insertion, and mixed case to slip past string filters
- **Parser disagreement**: reach alternate parsers through front-end and backend disagreement

**Binary Alternatives**
- **Absolute paths**: absolute paths and alternative binaries for the same operation
- **Shell and interpreter selection**: alternate shell and interpreter selections where one family is filtered

**Delegate Substitution**
- **Delegate substitution**: where the primary delegate is filtered, reach the same operation through a converter, pipeline, or internal service

**Indirection and Token Shaping**
- **Language-level indirection**: reach the same operation through a language-level indirection when its name is filtered, because a send or call primitive resolves the name at runtime
- **Whitespace alternatives**: shape whitespace alternatives past a token filter - field separators, brace expansion, redirection in place of a space, wildcard expansion, and quote splitting
- **Staged token decoding**: decode a staged token at execution time so the filter never reads the plain operation string
- **Defence-bypass pointer**: filter and encoding shapes are the defence-bypass family's steps; name it there rather than restating the mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Execution to durable control**: file write, scheduled execution, and service restart hooks
- **Fetch translation to execution**: fetch translation to an internal execution interface, which converts SSRF into execution
- **Execution to credential stores**: execution to credential and token stores, then movement to other systems
- **Upload pipelines**: upload pipelines to conversion delegates, where the front door accepts the file the delegate evaluates
- **Two-half primitives**: treat an execution primitive as two halves - one that puts bytes on the host and one that interprets them, so name the `sql-injection`, `insecure-file-uploads`, `prototype-pollution`, and `xxe` classes at the steps that supply each half rather than restating their mechanics here

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

- **Crashes or timeouts**: without controlled behavior
- **Filtered execution**: filtered execution of a limited command subset with no attacker-controlled arguments
- **Sandboxed interpreters**: sandboxed interpreters running in a restricted environment with no IO and no process spawn
- **Simulated outputs**: simulated outputs not derived from executed commands
- **Load-explained delays**: delays explained by general load rather than the gated probe; repeat the probe to separate the two
- **Foreign callbacks**: callbacks that arrive from a different source than the target's egress path

## Pro Tips

- **Callback oracles first**: prefer callback oracles; when using delays, keep them short and gated to reduce noise
- **Weak-execution pivots**: when command execution is weak, pivot to file write, decoding, or template paths
- **Converters as sinks**: treat converters and renderers as first-class sinks; many run out-of-process with powerful delegates
- **Dependency inventory**: enumerate the dependency inventory before assembling chains, and prove each link with a no-effect oracle
- **Environment confirmation**: confirm the environment early - path, shell, sandbox, and container capabilities
- **Portable payloads**: keep payloads portable across the toolset and minimize dependencies
- **Smallest chain**: document the smallest exploit chain that proves durable impact; avoid unnecessary shells

## Summary

RCE is a property of the execution boundary. Find the sink, establish a quiet oracle, and escalate to durable control only as far as necessary. Validate across transports and environments; defences often differ per code path.
