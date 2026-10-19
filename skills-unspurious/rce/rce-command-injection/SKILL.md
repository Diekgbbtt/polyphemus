---
name: rce-command-injection
description: Command strings breaking shell quoting and CLI flag parsing into OS execution. Use when user input reaches OS wrappers, when CLI flags accept attacker filenames, when quoting error classes gate delimiter probing.
metadata:
  version: 1.0.0
---

# Command Injection

Direct input strings reach an OS command wrapper or CLI and break out of their quoting or argument role into execution.
This variant owns wrapper and CLI discovery plus shell-context probing with gated portable oracles.
The goal is confirmed execution context that later escalates to durable control.

## Attack Surface

- **Applicability**: a user-influenced string reaches an OS command wrapper or CLI parser.
- **Carrier inventory**: the carrier may be a path segment, a query value, a body field, or a header value; inventory every carrier the endpoint accepts rather than assuming the obvious parameter.
- **Wrapper parsing**: the wrapper applies quoting, concatenation, or flag parsing before the string reaches the execution primitive.
- **Oracle availability**: the server exposes at least one oracle per submission, such as timing, a callback arrival, or a reflected output difference.
- **Surface aspects**: metacharacter break-out, argument and flag injection, and builtin and path confusion all ride this same surface as aspects.
- **Out-of-scope sinks**: file-mediated delegate construction belongs to pipeline execution, and template, deserialization, chained-service, and container-boundary sinks belong to their owning skills.

## Detection Channels

- **Channel scope**: command probing listens to the channels below.
- **Delay oracle**: separates execution from noise when a short gated delay probe shifts response timing past its baseline.
- **Callback oracle**: binds one minted unique marker per probe to one inbound arrival on operated listener infrastructure.
- **Reflected-output oracle**: separates execution from noise when response length or digest shifts with the probe result.
- **Quoting-break error class**: separates a live wrapper from inert handling when delimiter acceptance changes status text or timing class.
- **Flag-acceptance signal**: separates a live CLI sink from a plain string sink when option-shaped input alters behavior without executing.
- **Argument-derived file echo**: error text carries a line from a file the argument list named, which proves an argument-driven read.
- **Redirected-output surfacing**: the operation's output appears at a fetchable path, which proves execution plus a write primitive.
- **Context-confirmation read**: discloses the execution user plus working directory plus shell plus confinement markers once execution is proven.

## Adversarial Capabilities

- **Prerequisites**: command probing presupposes string submission plus oracle operation plus repeated measurement, and it consumes all three.
- **Crafted strings**: supply crafted strings that test delimiter, quoting, flag, and expansion handling one shape at a time.
- **Callback operation**: operate callback infrastructure that mints one fresh unique marker per probe and records each inbound arrival.
- **Measurement**: measure per-submission timing plus response length plus error class across repeated probes against a stable baseline.
- **Context reading**: read reflected outputs plus error text plus confinement markers to confirm the execution context.
- **Starting position**: hold no file-upload or prior-execution position, because this variant starts from direct strings alone.

## Trust Assumptions

- **The agreement**: every input string stays inside its shell quoting or CLI argument role through concatenation and parsing and execution, every template stays inert data, every blob stays sender-faithful, every uploaded file stays rendition-only, and every internal service stays unreachable, and sensitive server control leaks only when an execution primitive consumes input outside its agreed role.
- **The failing clause**: the variant breaks the quoting-role clause because a crafted string escapes its shell quoting or CLI argument role and reaches OS execution.

## Key Vulnerabilities

### Delimiter Break-Out

- **Break-out surface**: live wrappers concatenate input inside shell quoting that attacker delimiters can close.
- **Delimiter probing**: probe delimiter acceptance with gated portable delay and callback shapes before asserting execution.
- **Abstract payload shapes**: payload shapes stay abstract with placeholders denoting the break token, the probe command, the delay value, and the callback marker.
- **Break shape**: concatenates a break token plus a probe command plus a comment or closing token.
- **Quoted-segment shape**: alternates quoting characters with escape characters to exit the confined segment.
- **Expansion shape**: nests variable or substitution syntax that the shell resolves before execution.

### Argument and Flag Injection

- **Injection surface**: live CLIs parse attacker strings as options or filenames rather than inert values.
- **Option probing**: probe option acceptance by submitting option-shaped and path-shaped values and watching the flag-acceptance signal.
- **Option shape**: carries an option prefix plus an attacker-chosen value into the argument vector.
- **Filename shape**: carries a path separator plus an attacker-chosen destination into a file-writing flag.
- **Environment shape**: carries an expansion reference that the runtime resolves before the command runs.
- **Argument-file shape**: an argument-file shape carries a prefix that makes the CLI read further arguments from a file, which turns argument injection into an arbitrary file read when the error text echoes the arguments.
- **Array-argument shape**: an array-argument shape carries the operation plus its arguments as separate list members, which avoids shell quoting altogether where the wrapper accepts a list.

### Path and Builtin Confusion

- **Filtered-environment surface**: filtered environments still expose execution through absolute paths, builtin helpers, or alternate binaries.
- **Absolute-path preference**: prefer absolute tool paths over bare names when path filtering is suspected.
- **Builtin fallback**: prefer builtin helpers or alternate binaries when the primary probe command is blocked.
- **Shell-wrapper preference**: prefer explicit shell-wrapper invocation when the sink needs a shell to interpret the break token.
- **Handoff rule**: cross-referenced sinks stay out of this variant by naming their owning skill at the step that owns them.
- **Template-evaluation handoff**: template and expression evaluation hands off to the template-injection skill at the evaluator step.
- **Deserializer handoff**: deserializer blobs hand off to the deserialization skill at the unmarshal step.
- **Chained-service handoff**: chained internal-service construction hands off to the server-side-fetch skill at the chained-sink step.
- **Container-expansion handoff**: container and cluster expansion hands off to post-exploitation at the durable-control step.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no encoding difference changes the wrapper-discovery step itself.
- **Encoding differentials**: reach alternate parsers through case, comment, and normalization differences that the wrapper resolves.
- **Whitespace and token tricks**: reach the shell past naive filters through separator substitutes plus quote-split tokens plus staged variable building plus brace expansion plus redirection in place of a space plus wildcard execution plus a caret-style escape on the Windows-style family.
- **Path-component substitution**: path-component substitution extracts one character from an existing variable when the separator itself is filtered, so the operation path is assembled from environment material.
- **Encoded stagers**: reach execution through transport decoding that restores the probe shape after the filter.
- **Binary alternatives**: reach execution through absolute paths plus alternate binaries plus shell-flavour switching when one family is blocked.
- **Layered combinations**: hand off to the defence-bypass family at the filter step rather than restating relay mechanics here.

- **Bypass-shape table**: see `references/command-injection-bypass-shapes.md` for the per-family bypass table and the out-of-band confirmation procedure.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: command execution chains forward into durable control because a bare probe is only proof of context.
- **File-write chaining**: chain confirmed execution into file writes by aiming the probe command at a writable location.
- **Scheduled-execution chaining**: chain file writes into scheduled execution or service restart hooks once a writable path is proven.
- **Lateral-movement chaining**: chain stolen outputs into lateral movement by aiming reads at credential material.
- **Container-expansion handoff**: hand container or cluster expansion to post-exploitation at the durable-control step rather than extending this variant.

## Testing Methodology

Command probing runs wrapper discovery first and everything else follows, because no oracle is meaningful without a mapped sink.
The first bent step is P1 wrapper and CLI discovery plus shell-context probing over direct strings.
The delta over the parent is the wrapper-specific discovery plus shell-oracle discipline that generic find-it plus oracle-it language never names.
1. **Sink mapping locates** every wrapper and CLI sink with its injection locus plus its quoting and flag semantics.
The step is done when every candidate sink carries a code or configuration reference tied to an injection locus.
2. **Baseline capture records** timing plus response length plus error class for benign input at each sink.
The step is done when every sink shows a stable baseline across repeated benign submissions.
3. **Wrapper probing submits** delimiter plus quoting plus flag plus expansion shapes one at a time through gated portable oracles.
The step is done when every shape at every sink shows acceptance or filtering with its oracle verdict.
4. **Context confirmation reads** execution user plus working directory plus shell plus confinement markers from proven sinks.
The step is done when the context record explains which commands and writes are plausible at each proven sink.
5. **Boundary mapping records** writable paths plus callback egress plus read locations at each proven sink.
The step is done when every writable path and every egress path is confirmed or ruled out.
6. **Durable-control proof demonstrates** the smallest file write or scheduled effect that proves persistence without an unnecessary shell.
The step is done when every claimed durable effect shows its artifact or is recorded as absent.

## False Positives

- **No-control stop**: stop when the evidence shows no attacker-driven execution, because noise without control is only a negative.
- **Crash-only behavior**: crash-only or timeout-only behavior rejects the claim while no oracle separates execution from failure.
- **Filtered subsets**: reject the claim when a limited command set runs with no attacker-controlled argument reaching it.
- **Sandboxed interpreters**: reject the claim when execution stays inside a restricted runtime with no process spawn and no external IO.
- **Simulated outputs**: reject the claim when reflected text never derives from an executed command.

## Pro Tips

- **Discipline**: command probing rewards quiet oracles plus portable shapes plus small claims.
- **Oracle preference**: prefer the callback oracle first, then promote only stable positives to timing and output differencing.
- **Gated delays**: gate every delay probe short so execution separates cleanly from network jitter.
- **Portable shapes**: keep probe shapes portable across shell families and minimize dependencies on any single binary.
- **Context confirmation**: confirm environment facts before asserting impact so the context record gates every follow-up.
- **Minimal chain**: document the smallest chain that proves durable effect and stop before an unnecessary persistent shell.

## Summary

A wrapper that concatenates input inside quoting or parses it as flags is a command-injection candidate.
Map the wrapper, probe with gated portable oracles, confirm the context, and escalate to durable control only as far as proof requires.
