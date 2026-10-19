---
name: upload-client-execution
description: Client rendering proving stored uploads fire scripts in the browser. Triggers on inline-served uploads, sniffable serving headers, stored script rendering.
metadata:
  version: 1.0.0
---

# Upload Client Execution

Prove stored content fires scripts under the served context through header capture plus render confirmation.
This variant owns serving-header adjudication with reflection and sniffing analysis plus script-fire proof.

## Attack Surface

- **Inline-serving flows**: file submission flows whose stored objects return under an inline serving context apply here.
- **Staged pipelines**: apply where the serving stage decides type and disposition independently of ingress validation.
- **Previewer contexts**: apply where a derived rendering serves stored properties as active content.

## Reconnaissance

- **Pipeline map**: map the pipeline from submission through storage to each serving path and record the serving party for every path.
- **Serving-header probe**: probe with benign markup and document-shaped files and record the served type with disposition and sniffing-guard state.
- **Type-source comparison**: compare server-set type against reflected submission type to find reflection-driven serving decisions.
- **Disposition baseline**: record inline against attachment behavior for every serving path before attempting live content.

## Detection Channels

- **Script fire**: script fire in the browser under the served context proves client execution.
- **Header adjudication**: served type with disposition and sniffing-guard state adjudicates whether inline rendering was server-set or reflected.
- **Origin authority**: same-origin serving beside a sandboxed or separate-domain rendering context adjudicates whether the served object carries the application's origin authority or only a display context.
- **Previewer delivery**: previewer rendering of stored properties proves document-property script delivery.

## Adversarial Capabilities

- **Shaped-file submission**: submit markup-shaped and document-shaped files through the application submission path.
- **Hint steering**: steer submission-declared type and disposition hints where the serving stage reflects them.
- **Controlled observation**: observe served objects in a controlled browser context and read script-fire signals.

## Trust Assumptions

- **The agreement**: the pipeline agrees that a file accepted at ingress keeps its validated type through storage and processing and serving, that serving reflects only server-set type with sniffing disabled, that extraction and conversion stay confined, and that no late control point re-opens the gate.
- **The failing clause**: serving-context confinement: stored content renders inline as active script.

## Key Vulnerabilities

- **Inline serving**: returns stored markup as active content under a script-capable served type.
- **Reflection serving**: derives the served type from submission-declared values instead of server-set policy.
- **Sniffing acceptance**: serves ambiguous content without a sniffing guard so the browser upgrades it to script.

## Advanced Techniques

- **Header-capture proof**: capture serving headers then prove inline script fire under reflection with sniffing and disposition analysis.
- **Reflection search**: vary submission-declared type and disposition hints to find the reflection that flips attachment to inline.
- **Previewer confirmation**: confirm previewer delivery by placing script logic in document properties and observing derived renderings.

## Bypass Techniques

- **Type-gate defeat**: defeat type gates by submitting polyglot shapes that read as inert at ingress and as markup at serving time.
- **Disposition-policy defeat**: defeat disposition policy by steering reflected hints so the served object returns inline instead of as attachment.
- **Sniffing-guard defeat**: defeat sniffing guards by targeting serving paths that omit the guard and let the browser upgrade the content.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Session-theft chain**: chain stored script fire into session theft by reading ambient credentials in the served origin.
- **Distribution-amplification chain**: chain broad distribution into wide impact by placing script content on serving paths shared across recipients.

## Testing Methodology

1. **Pipeline mapping** - map the pipeline and record submission, storage, and every serving path with its serving party, and the step completes when every serving path has captured baseline headers for legitimate uploads.
2. **Header adjudication** - capture serving headers for each probe and adjudicate server-set against reflected type with disposition and sniffing state, and the step completes when every probe has a recorded header verdict covering type source plus disposition plus guard state.
3. **Script-fire proof** - capture serving headers then prove inline script fire under reflection with sniffing and disposition analysis, and the step completes when script fire is demonstrated for every inline path or when all paths are proven attachment with strict sniffing guards.

## False Positives

- **Unserved objects**: exclude stored objects that never return to any client under any serving path.
- **Attachment-served objects**: exclude objects always served as attachment with strict sniffing guards enforced by the server.
- **Inert-rendering previewers**: exclude previewer paths that transform risky formats into inert renderings before serving.

## Pro Tips

- **Minimal script probes**: keep script probes minimal so script fire stays unambiguous.
- **Served-header verdict**: treat final served headers as the verdict and ignore submission-time declarations.
- **Shared-path verification**: verify shared serving paths honor attachment with sniffing guards before closing the finding.

## Summary

Client execution holds when served headers permit inline rendering and script fire confirms it.
Treat every serving path as a rendering decision until attachment with strict guards is proven.
