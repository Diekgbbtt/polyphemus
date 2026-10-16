# Streamed-chunk inventory - arm J trials (F3)

Date: 2026-10-16.
Plan: `docs/design/plans/2026-10-16-failure-modes-diagnosis.md` (F3, operator item 1 part 3).
Scope: enumerate ALL chunks streamed in both arm J trials (comfyui `2df3ad9d`, white-jotter `bf0d9408`) with per-chunk asset types, observations, and a Langfuse URL to a trace whose first HumanMessage holds the chunk content.

Langfuse base: `https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/<traceId>`.

## Method

- Source: Langfuse observations pulled per project window (`GET /api/public/v2/observations`, fields `core,basic,io,metadata`).
- A chunk is one distinct `STREAMED SURFACE` block; blocks are grouped by content hash at their first occurrence.
- The trace link per chunk is a mechanism_typist trace whose first HumanMessage (message index 1) renders that block.
- Chunk delivery is per-job gated: each chunk carries the assets of one job when its consumption gate opens.
- The assigner does NOT carry the block; its structured input is `{"chunk": "<job>:<i>"}` (confirmed on all 12 assigner turns of both trials).
- Asset type counts are the streamed asset lines per chunk; observations are the minted adversarial insights.

## comfyui (project `2df3ad9d`, recon `9ae295dc`)

| # | chunk | t0 (UTC) | job | assets | types | observations | typist calls carrying block | typist trace |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `04f33dcc941f` | 22:03:49.675 | httpx | 13 | BaseURL 1, Header 10, Technology 1, Endpoint 1 | 12 | 17 | [de453d0c6d23e53366fa71e0350888a9](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/de453d0c6d23e53366fa71e0350888a9) |
| 2 | `2494f99cee4f` | 22:08:26.600 | katana | 15 | BaseURL 1, Header 11, Technology 1, Endpoint 2 | 14 | 8 | [bcae6a2348c6f59c80bacec63c26b2cd](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/bcae6a2348c6f59c80bacec63c26b2cd) |
| 3 | `839f2a9eae5b` | 22:10:23.494 | ffuf | 11 | BaseURL 1, Endpoint 10 | 11 | 9 | [6443b8a74baccd62dd35d86d51654d56](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/6443b8a74baccd62dd35d86d51654d56) |
| 4 | `406eb9631c54` | 22:12:51.400 | steel_crawl | 4 | BaseURL 2, Endpoint 2 | 0 | 4 | [a9554698af47c40c3ae43506e0676975](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/a9554698af47c40c3ae43506e0676975) |
| 5 | `877ff08e6104` | 22:17:56.163 | jsluice | 101 | BaseURL 1, Secret 4, Endpoint 92, Parameter 4 | 97 | 6 | [6698c178874a557e40106f7179bf0b10](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/6698c178874a557e40106f7179bf0b10) |

Totals: 5 chunks, 144 assets, 134 observations.

First insight per chunk (truncated):

- `04f33dcc941f`: "adversarial insight: The root origin serves a ComfyUI instance - a node-based diffusion/AI workflow UI whose default deployment ships without authentication and whose HTTP API exposes workflow execution plus fi..."
- `2494f99cee4f`: "adversarial insight: ComfyUI is a node-graph workflow engine whose web UI fronts a privileged backend that queues and executes arbitrary workflow graphs. The landing request reaches the control UI with no authe..."
- `839f2a9eae5b`: "adversarial insight: A distinct JSON/REST API surface is served on the same origin as the HTML frontend with no authentication wall. The resource-noun scheme (users, models, queue, settings, extensions, feature..."
- `406eb9631c54`: none (0 observations; the steel chunk re-presented already-seen roots and redirects).
- `877ff08e6104`: "adversarial insight: The frontend origin also carries the backend API routes of a ComfyUI server, including operational end..."

## white-jotter (project `bf0d9408`, recon `131ba77d`)

| # | chunk | t0 (UTC) | assets | types | observations | typist calls carrying block | typist trace |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `c1f38182697e` | 23:09:30.173 | 10 | BaseURL 1, Header 7, Technology 1, Endpoint 1 | 9 | 9 | [02603ec0e41b721050724e62c66904fb](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/02603ec0e41b721050724e62c66904fb) |
| 2 | `253486d10288` | 23:11:57.289 | 12 | BaseURL 1, Header 9, Technology 1, Endpoint 1 | 11 | 12 | [7792a95bcb6c988a8ffce4bc943df4bd](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/7792a95bcb6c988a8ffce4bc943df4bd) |
| 3 | `52d39b9790d6` | 23:14:38.927 | 2 | BaseURL 1, Endpoint 1 | 0 | 5 | [40f02d29beab742f1877e95977355bbf](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/40f02d29beab742f1877e95977355bbf) |
| 4 | `30b0d8274193` | 23:17:33.147 | 4 | BaseURL 2, Endpoint 2 | 2 | 9 | [5d330c9fc722b6c0e240269f1b76eaa7](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/5d330c9fc722b6c0e240269f1b76eaa7) |
| 5 | `9b3e6e3e70b8` | 23:20:03.557 | 1 | BaseURL 1 | 1 | 8 | [4241f67434d6779bc79f8c3d6103edca](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/4241f67434d6779bc79f8c3d6103edca) |

Totals: 5 chunks, 29 assets, 23 observations.

First insight per chunk (truncated):

- `c1f38182697e`: "adversarial insight: The origin advertises its exact web-server product and version on every response rather than suppressing the banner. This is a hygiene signal..."
- `253486d10288`: "adversarial insight: Absence of the standard defence-in-depth header set is a hygiene signal directly evidenced in the response, not a parsing artifact: the app relies solely on nginx defaults..."
- `52d39b9790d6`: none (0 observations).
- `30b0d8274193`: "adversarial insight: Both the plaintext and TLS roots delegate via a temporary redirect instead of serving content, and the fact that HTTPS itself still 307s (rather than terminating the chain) indica..."
- `9b3e6e3e70b8`: "adversarial insight: The whole client application logic is delivered to anonymous visitors as static assets. Unlike a single entry bundle, the numbered chunk map enumerates the app's feature modules..."

## Notes

- Cross-chunk duplication is expected: comfyui chunk 2 re-streams chunk 1 headers with a fresh `date` value; Endpoint lines duplicate across chunks 3 and 5 (9 duplicate lines overall in comfyui).
- The white-jotter chunk hash `52d39b9790d6` also occurs in the aborted attempt window (22:59:42) because the re-run re-streamed identical content; the trace listed above is the `bf0d9408` occurrence at 23:14:38.
- Aborted attempt (`b0353d51` / run `96262aa1`), recorded for completeness: 4 blocks - `0e3189feb34f` (11 typist calls, trace [91822ab09816607d74748a52ec5043c2](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/91822ab09816607d74748a52ec5043c2)), `28354e2e36de` (16, trace [609e53de045fc6d996b1ad3e9b536780](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/609e53de045fc6d996b1ad3e9b536780)), `29ad9d943a5a` (6, trace [045c3d9f08f67c2841a08d0c08fa44a1](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/045c3d9f08f67c2841a08d0c08fa44a1)), `9b3a7580d554` (1, trace [634d9d3ec42f60fdcbb06f7bede3fa68](https://cloud.langfuse.com/project/cmv6cdk12000sad0nbechto7t/traces/634d9d3ec42f60fdcbb06f7bede3fa68)).
- The white-jotter assigner turns name chunks `httpx:0`, `katana:0`, and `jsluice:0`; the corresponding streamed blocks are identifiable by shape but are not re-derived as a job map here (the comfyui map above is the confirmed one).
- White-jotter chunks 3-5 are small (2, 4, 1 assets); the trial's endpoint volume lands almost entirely in chunks 1-2 (headers/technology) and in the post-stream assigner turn at 23:26:53.
