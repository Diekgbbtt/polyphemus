---
name: upload-server-execution
description: Server placement proving uploaded files execute in the server interpreter. Triggers on stored executable uploads, handler-mapping placement, execution-URL confirmation.
metadata:
  version: 1.0.0
---

# Upload Server Execution

Place uploaded content where the server interpreter evaluates it and confirm execution through interpreter output.
This variant owns handler mapping discovery with language placement plus execution-URL invocation.

## Attack Surface

- **Server-evaluated flows**: files whose stored objects stay reachable under a server-evaluated path apply.
- **Staged pipelines**: apply where ingress validation and storage placement precede a server-side evaluation point.
- **Handler mapping**: applies where a directory honors configuration files that bind a stored extension to an interpreter.

## Reconnaissance

- **Pipeline map**: map from submission through ingress and storage to the serving path and record each validation point.
- **Placement probe**: probe with benign files of each claimed type and record where each object lands and under which serving party it returns.
- **Handler-mapping discovery**: place benign configuration-shaped content and observe whether the directory changes its evaluation behavior.
- **Execution-path inventory**: record candidate execution paths for every reachable stored object before attempting live content.

## Detection Channels

- **Interpreter output**: output returning from a requested stored object proves server execution.
- **Handler activation**: evaluation behavior change after configuration-shaped placement proves handler activation.
- **Header adjudication**: serving headers that confirm server-set type adjudication separate executable placement from serving-context effects.

## Adversarial Capabilities

- **Name-and-type submission**: submit crafted files through the application submission path and steer their stored names and types.
- **Handler rebinding**: place configuration-shaped content that rebinds a stored extension to the server interpreter.
- **Direct request**: request stored objects directly and read interpreter output from the response.

## Trust Assumptions

- **The agreement**: a file accepted at ingress keeps its validated type through storage and processing and serving, serving reflects only server-set type with sniffing disabled, extraction and conversion stay confined, and no late control point re-opens the gate.
- **The failing clause**: server-interpreter confinement fails because placed content reaches a handler that evaluates it as code.

## Key Vulnerabilities

- **Executable placement**: accepts script-shaped content whose stored extension the interpreter evaluates on request.
- **Handler-directive placement**: accepts configuration-shaped content that binds an otherwise inert extension to the interpreter.
- **Encoding acceptance**: double extensions with mixed casing plus trailing marks plus magic-prefix spoofs survive validation and land executable.

## Advanced Techniques

- **Rebinding-first placement**: place configuration-shaped content first and follow with script-shaped content so the rebinding precedes the payload.
- **Acceptance search**: vary extension casing with extra marks plus magic-prefix framing to find the narrow acceptance that still evaluates.
- **Placement confirmation**: match interpreter output shape to the submitted script logic rather than to serving headers.

## Bypass Techniques

- **Allowlist defeat**: submit casing and mark variants that normalize to an evaluated extension after the check.
- **Name-check defeat**: defeat name checks with double and truncated extension spellings where the storing layer normalizes after the validation point.
- **Inspection defeat**: prefix script content with a benign magic framing that the gate accepts and the interpreter ignores.
- **Part-header defeat**: send submission metadata whose declared type passes ingress while the stored object keeps its executable shape.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Command-execution chain**: chain interpreter execution into command execution by invoking processor primitives through the evaluated script context.
- **Persistence chain**: chain configuration overwrite into persistent execution by rebinding a directory that later uploads inherit.

## Testing Methodology

- Map the pipeline and record submission, validation, storage, and serving points for every file-bearing field.
- Complete when every stage with its validation owner is recorded and no file-bearing field stays unmapped.
- Place benign script-shaped and configuration-shaped probes and discover each candidate execution path.
- Complete when every reachable stored object has a recorded request path and handler behavior is adjudicated.
- Place webshell-shaped content then discover the execution URL and confirm interpreter output.
- Complete when interpreter output matches submitted logic for every placed candidate or when placement is proven confined under the false-positive predicates.

## False Positives

- **Unreachable objects**: stored objects remain unreachable through any server-evaluated path.
- **Confined converters**: converters confined in sandboxes with no external IO and no script engines.
- **Quarantined objects**: access before verdict is impossible by design.

## Pro Tips

- **Minimal placement probes**: keep placement probes minimal so interpreter output stays unambiguous.
- **Serving-header capture**: capture serving headers on every execution attempt so placement effects separate from rendering effects.
- **Safe-rendering guidance**: prefer transforming risky formats to safe renderings over complex sanitization when advising the fix.

## Summary

Server execution holds when placed content reaches an evaluating handler and interpreter output confirms it.
Treat every reachable stored path as an evaluation point until placement confinement is proven.
