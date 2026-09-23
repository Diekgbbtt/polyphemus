---
name: two-principal-authz
description: Two-principal authorization testing — A creates state, B acts on A's object (BOLA/IDOR, share/token, nested resources)
metadata:
  version: '1.0'
---

# Two-principal authorization

Use this for any mutating or access-controlled operation. Discover endpoints, methods, and field names at runtime from KB, client/JS, OpenAPI, or traffic. Do not assume path strings.

## Workflow

1. **Create two principals** (register/login/guest or whatever the app exposes). Record tokens with `record_domain_knowledge`.
2. **Principal A creates a resource** (list, document, share grant, child object). Capture A's object ID from the response.
3. **Optional grant** — if the app has share/invite/token flows, A grants access and record the grant token.
4. **Principal B acts on A's object** — read, write, delete, and nested child actions using **B's** credentials (and, separately, grant-token-only if one exists).
5. **Victim object, not attacker-created.** Success on an ID B just created is weak. The chain must target an ID created and owned by A.

## Before each request

Derive **verb + body** from client evidence (JS, OpenAPI, prior HTTP). Retry the inferred method/fields if the first probe fails. A single wrong-verb 404 is not a negative.

## What to file

Call `judge_and_record_finding` as soon as B can read or change A's object (or a grant token exceeds its intended scope). Include both principals' requests and the object ID in the proof.

## False negatives to avoid

- Testing only objects the current session created
- Stopping after one HTTP method
- Using placeholder IDs instead of IDs returned to A
- Exploring new bug classes before filing a confirmed cross-principal success
