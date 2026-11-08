# Root cause: the `RESTApi:api` unit model difference

*Status: diagnosis complete. Fix plan: `ROOT-CAUSE-AND-FIX-PLAN.md`.*
*Old project: `7eb71c29-f28b-4f5f-ad51-7db543ce466b`, run `bfeee1b4-f35f-40f8-8c03-f8e1971d472d`, commit `5789ad3f`.*
*New project: `dda347be-abea-48e4-94e5-4a4039f41858`, run `12d15890-47b2-43c2-bbe3-14c9626a2fdb`, commit `81522a71`.*

## The red loop

The differential loop asserts the `EXPOSED_VIA` clients of `RESTApi:api`.
The old project passes.
The new project fails.

```text
old: 7 clients: article-management, jotter-reading, library-catalog,
     navigation-menu, register, sign-in, user-administration
old: complete

new: 4 clients: article-management, navigation-menu, register, sign-in
new: MISSING jotter-reading, library-catalog, user-administration
```

The minimal repro is the three missing edges and the isolated `Service:user-administration`.
The new graph gives `user-administration` zero live edges.
The old graph gives it four.

## The upstream trigger: the recon auth context

The recon jobs are the same five jobs in both runs.
The job counts and the L0 endpoint inventory are the same.
The commands are not.

| Job | Old command | New command |
|---|---|---|
| `httpx` | no request headers | `-H 'Cookie: <JSESSIONID>' -H 'Content-Type: application/json'` |
| `katana` | no request headers | same Cookie header |
| `httpx_reprofile` | no request headers | same Cookie header |

The new recon ran authenticated.
The old recon ran anonymous.
The Cookie value is 43 characters, consistent with `JSESSIONID=` plus a 32-hex identifier.

The four endpoint property differences are the fingerprint:

| Path | Old, anonymous | New, authenticated |
|---|---|---|
| `/api/admin` | 200, 0 bytes | 404, 662-byte SPA shell |
| `/api/admin/dashboard` | 200, 0 bytes | 404, 662-byte SPA shell |
| `/api/authentication` | 404, 662-byte SPA shell | 200, 18 bytes |
| `/api/menu` | 404, 662-byte SPA shell | 200, 43 bytes JSON |

The old anonymous pass produced the Shiro denial shape: HTTP 200 with a zero-byte body.
The new authenticated pass replaced that denial shape with the 404 SPA fallback.
The new typist then treated the authenticated L0 as a positive route set.

The exact privilege of the new session is not recorded.
The L0 responses show a session that passes `/api/menu` but does not produce the admin denial shape.
The auth store contains an `admin` account and a `wjbootstrap4821` account.
The recon Cookie is not attributed to either account in the trace.

## The decision point: the A1 typist extraction

The Langfuse traces contain both `typist-systems-and-edges` writes.
The A1 write is the first extraction, not the final `jsluice:0` extraction.

| A1 `EXPOSED_VIA RESTApi:api` | Old `091bc86a` | New `7c3b92bc` |
|---|---|---|
| Clients written at A1 | sign-in, register, user-administration, library-catalog, jotter-reading, article-management | sign-in, navigation-menu, article-management |
| Added by final extraction | navigation-menu | register |
| Final graph | 7 | 4 |
| Lost | - | user-administration, library-catalog, jotter-reading |

The Neo4j edge properties confirm the write times:

- Old: all six A1 edges have `first_seen` 2026-10-23T15:40:28 and `prov_job: analyser:091bc86a-02a4-4574-94be-2335c6c0ce22`.
- Old: navigation-menu has `first_seen` 2026-10-23T15:48:13.
- New: sign-in, navigation-menu, and article-management have `first_seen` 2026-10-25T22:02:18.
- New: register has `first_seen` 2026-10-25T22:10:29.
- The three lost edges are absent. There is no later delete.

The new typist's ORIENT says it withheld "every auth/authz edge not backed by a witnessed refusal."
It probed `/api/admin/content/editor`, not `/api/admin/user`.
The old typist probed `/api/admin/user`, saw the 200/zero-byte denial, and linked `user-administration`.
The old typist also started from the full service list.
The new typist started from the `library-catalog` aggregate.
The new typist followed the `exposed_admin` observation to the content editor route.
It did not follow the user-administration contract to the account route.

The old typist's first tool output listed every service with its endpoint count.
The new typist's first tool output was `{"service": "library-catalog", "l0_label": ["Endpoint"], "n": 1}`.
That first query set a narrower scope.

## What is falsified

| Hypothesis | Verdict |
|---|---|
| Assigner or typist system message changed | Falsified. The system prompt is identical, 24,217 characters. |
| Thinking effort changed | No trace-visible evidence. The model is `opencode-go/deepseek-v4.1-flash`; the parameters are identical: `temperature 0`, `max_completion_tokens 131072`. The hidden provider effort is not recorded. |
| L0 chunk formatting changed | Not supported. The initial chunk prompt is 15,598 vs 15,830 characters, same schema. The extra input is the typist's own tool output: 235,588 vs 255,055 characters at the A1 write. |
| Analysis code or prompt regression | Falsified. `git diff 5789ad3f 81522a71 -- src/polymerhus/analysis` is empty. `recon/control/jobs.py` and `auth_feed.py` are unchanged. |
| Curator or auditor deleted the edges | Falsified. The new A1 typist never wrote the three edges. |
| Assigner wrote the edges | Falsified. The assigner wrote only an aggregate (`GET /` to `library-catalog`). It wrote no `system_edges` in either run. |

## Root-cause statement

The L1 divergence is a run-to-run typist nondeterminism, triggered by the authenticated recon context.
The authenticated pass replaced the denial shape with a 404 fallback.
The typist then applied a witnessed-refusal rule and withheld the three services it could not see.
The old anonymous pass forced the typist to infer the API transport from the SPA bundle and the service contracts, and to probe the admin route.
The 4000-character projection cap then amplified the edge loss into a different modeller input.

The renderer is an amplifier, not the primary cause.
It hid the business service contracts in the new run because the new graph had fewer of them.
It also hid the old run's aggregated endpoint list entirely.
A coherent renderer would have shown the old model the full business surface even with the cap.

## What is inferred, not proven

- The exact privilege of the new recon session is inferred from the L0 response shapes. It is not recorded.
- The old auth-feed resolution is inferred from the absence of a Cookie header. The old container logs are gone.
- The hidden provider thinking effort is not recorded. The recorded parameters are identical.
- Both graphs contain zero `Parameter` nodes. The parameter render path can only be tested with fixtures until recon emits them.
- The old run stopped after one unit and produced no specs or pods. The new run was a full pipeline with three units. The per-unit modeller budget is not comparable.

## Fix direction

1. Replace the 4000-character JSON cap with a coherent Markdown renderer.
2. Render each cooperating service with its endpoints and parameters underneath it.
3. Render one separate, deduplicated structure per baseURL for the linked headers.
4. Never cut an endpoint, a parameter, or a header from the analysis unit.
5. Respecify the threat modeller's spatial axis toward data contracts and application contexts.
6. Teach the typist to read status codes with their canonical meaning, and to recover the correct request shape from HTTP history before concluding absence.
7. Keep the L1 edge set deterministic through the typist prompt and a coverage check, not through the renderer.
