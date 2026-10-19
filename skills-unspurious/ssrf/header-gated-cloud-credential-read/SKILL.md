---
name: header-gated-cloud-credential-read
description: Read gated cloud credentials through SSRF by sequencing a token fetch before the authenticated metadata read, pairing the required method with gate-passing headers, and confirming each step under a direct response oracle.
metadata:
  version: 1.0.0
---

# Header-Gated Cloud Credential Read

Platform credential stores gate their reads behind a token header plus a method pair that plain fetches never send.
This variant reads through the gate by sequencing a token fetch first and replaying the token in an authenticated metadata read.
The read goal is short-lived credential disclosure plus platform API access, all confirmed through a direct response oracle.

## Attack Surface

- **Applicability**: centers on a server-side fetch sink that can influence request headers or the request method.
- **Destination sink**: the sink accepts attacker-influenced destination input reaching a platform credential store that is gated behind a token plus header plus method check.
- **Fetcher sequencing**: the fetcher permits at least a two-step sequence, namely one fetch that mints the gate token plus one fetch that presents it.
- **Response oracle**: stays direct, meaning each gated outcome returns visibly as credential content or as a gate denial.
- **User-data target**: a second metadata target beside the credential path is the instance user-data path, because startup scripts plus provisioning material often carry secrets of their own.
- **Blind gated replay**: adds no step beyond sequencing plus the inference oracle, so it rides as a secondary inside the inference variant.

## Detection Channels

- **Channel scope**: gated reads listen to token plus credential objects rather than side channels, so only the entries below are live here.
- **Token-fetch response**: carries a short-lived gate token that proves the sequencing first half succeeded.
- **Authenticated metadata read**: returns a credential object that proves the gate opened.
- **Gate-denied versus gate-passed response contrast**: separates a missing header or method from a satisfied gate.
- **Single-fetch denial**: confirms the gate demands the full sequence rather than one plain read.

## Adversarial Capabilities

- **Prerequisites**: gated reads presuppose destination supply plus header and method influence plus two-step sequencing, and they consume all three.
- **Destination supply**: supply destination input that reaches the token endpoint and then the gated credential path.
- **Header and method influence**: influence request headers or the request method far enough to satisfy the gate check.
- **Two-step sequencing**: sequence the token fetch before the authenticated read and carry the token between the two fetches.
- **Direct-oracle confirmation**: confirm each half through the direct response oracle rather than through statistical differencing.
- **Callback infrastructure**: hold callback infrastructure only as a secondary confirmation for token delivery.

## Trust Assumptions

- **The agreement**: the fetcher trusts a user-supplied destination to select only locations the server is permitted to reach.
- **The agreement**: holds the destination stable from allowlist check through fetch, keeps the response observable to the caller, keeps the request in plain-fetch shape with no translated protocol grammar, and keeps the request in plain-fetch shape with no gate-passing header or method pair.
- **The exposure**: stored platform credentials leak only when the server exposes them through such a fetch.
- **The failing clause**: this variant breaks the plain-header clause because the gated target demands a token header plus method pair that a plain fetch cannot supply, so a single fetch never reaches the credential.

## Key Vulnerabilities

### Token-Then-Read Sequencing

- **Token-first fetch**: fetch the gate token first with the method the gate demands, then present that token in the header of the authenticated metadata read.
- **Role-name sequencing**: the token request carries the lifetime header the gate demands, and the credential read follows a role-name listing, so the sequence reads token, then role name, then credentials.
- **Token carry**: carry the token value between the two fetches without alteration, because any mutation re-arms the gate.
- **Procedure ownership**: the parent header step covers only a single-fetch influence question and cannot describe ordered token-then-read sequencing, so this variant owns the sequencing procedure.

### Method Plus Header Pairing

- **Method-plus-header pairing**: pair the exact method the gate demands with the exact gate-passing header, because the gate checks the combination rather than either half alone.
- **Independent half testing**: test each half independently first so a denial attributes cleanly to the method or to the header.
- **Direct confirmation**: confirm the satisfied pair through the direct credential body rather than through timing.

### Flavour-Gated Flow Traversal

- **Flavour traversal**: traverse the platform flavour that matches the sink, since each flavour gates on its own token plus header plus method combination.
- **Per-flavour separation**: keep each flavour flow separate with its own token, because a token minted for one flavour never opens another.
- **Blind replay placement**: carry blind gated replay as a secondary inside the inference variant, since blind sequencing adds no step beyond the sequence above plus that oracle.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no encoding difference changes the token-then-read step itself.
- **Address encoding families**: address encoding families such as decimal plus hex plus octal plus mapped forms steer the gated destination past a naive textual allowlist.
- **Parser differentials**: parser differentials, redirect chains, and short-lived resolution carry the gated destination to the fetch side, and the proxy-techniques family owns those mechanics; record only the gated verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: gated reads chain forward into platform access because a credential without use is only a string.
- **Credential replay**: replay the disclosed credential against the platform API for minimal listing, then stop there.
- **Secret-store pivot**: pivot from the credential to secret stores reachable with the same identity, reading narrowly.
- **Orchestration pivot**: pivot from orchestration endpoints visible to the same identity toward lateral movement.
- **Blind-read handoff**: hand a gated read that stays blind to the inference variant for oracle confirmation.

## Testing Methodology

gated reads run the direct oracle first and the sequence second, because an unconfirmed token cannot authenticate anything.
1. **Inventory sinks** - list every attacker-influenced destination sink with its carrier plus its header and method influence, and the step completes when no unlisted sink or influence remains.
2. **Establish the direct oracle** - confirm gated outcomes return visibly as content or as denial, and the step completes when a benign gated path shows a recorded denial and a benign open path shows a recorded body.
3. **Test header and method influence** - vary the method plus one header at a time, and the step completes when the influence over each is recorded as present or absent.
4. **Fetch the gate token** - call the token endpoint with the demanded method, and the step completes when the token value is recorded or its refusal is recorded.
5. **Replay the authenticated read** - present the recorded token in the gated read, and the step completes when the credential object or a fresh denial is recorded.
6. **Traverse remaining flavours** - repeat the token-then-read pair per platform flavour with a fresh token each, and the step completes when every reachable flavour carries a credential verdict or a recorded negative.

## False Positives

- **Gate-closed stop**: stop when the gate never opens or no fetch leaves the server, because a denial without influence is not this variant.
- **Client-side fetch only**: client-side fetch only, where no request ever leaves the server.
- **Header and method influence absent**: header and method influence absent, confirmed by uniform denials across every pairing attempt.
- **Canned simulator responses**: canned simulator responses that return fixed bodies without real gate evaluation.
- **Strict allowlist**: strict allowlist with resolution pinning plus no redirect following, confirmed by uniform negatives across all gated paths.
- **Callback-source mismatch**: callback hits whose source matches the tester machine rather than the server, which indicate a client-side fetch made the request.
- **Plain-read sink**: a sink that can issue nothing but a plain read cannot open the gate, confirmed by uniform denials across every method and header attempt.

## Pro Tips

- **Pairing discipline**: gated reads reward exact pairing plus fresh tokens plus minimal follow-up.
- **Independent influence testing**: test method plus header influence independently before attempting the full sequence.
- **Fresh token per flavour**: mint one fresh token per flavour and never reuse a token across flavours.
- **Visible token confirmation**: confirm the token value visibly before spending it in the authenticated read.
- **Narrow reads**: read credentials narrowly and chain quickly to minimal platform listing, then stop there.
- **Token expiry discipline**: treat short-lived tokens as expiring evidence and re-mint rather than debugging a stale value.

## Summary

A credential store that demands a token header plus method pair still falls to an ordered fetch.
The gated read mints the token first, replays it in the authenticated read, and verifies each half through the direct oracle.
