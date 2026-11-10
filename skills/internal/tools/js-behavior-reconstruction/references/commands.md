# Behaviour reconstruction commands

```text
<prefix> behavior-list --limit 5
<prefix> behavior-list --limit 5 --cursor <next_cursor>
<prefix> behavior-save --record '<compact-json>'
<prefix> behavior-save --record '<compact-json>' \
  --dependency '{"selector_type":"source","target":"src_...","rationale":"Required caller of the cited request path."}'
```

The submitted JSON contains exactly:

```json
{
  "question_ref": "span_...",
  "steps": [
    {
      "kind": "transform",
      "text": "Concise evidence-linked explanation.",
      "read_ids": ["read_..."]
    }
  ],
  "assumptions": [
    {
      "text": "Condition not established by the cited client code.",
      "status": "unverified",
      "read_ids": []
    }
  ],
  "gaps": ["Unread callee or runtime/server condition remains unknown."]
}
```

Allowed step kinds: `trigger`, `input`, `transform`, `call`, `request`, `sink`,
`response`, `error`, `effect`. Every factual step needs delivered read IDs.
Supported assumptions also need delivered reads. Unknown fields, empty steps,
invalid types, undelivered/foreign read IDs and records over 4,096 canonical JSON
bytes are rejected.

The CLI and service count the same compact JSON encoding (sorted keys, no
formatting spaces, ASCII escapes for non-ASCII characters), including all keys
and repeated read IDs. Pretty printing does not increase the semantic allowance.
The CLI also bounds the raw JSON argument to 8 KiB before parsing; Exec allows
32,768 characters only for `behavior-save` to accommodate worst-case apostrophe
escaping plus the scoped prefix. This is a transport bound, not extra record
space: the 4 KiB record and 8 KiB raw-JSON bounds still apply. Other
commands keep their existing limit. This does not increase the attempt budget.

For `behavior_record_too_large`, inspect `actual_bytes`, `max_bytes` and
`size_basis`. Shorten duplicate prose/metadata, preserving important branches,
or narrow the question and record what is still missing. For
`behavior_read_not_delivered`, `invalid_fields` gives zero-based field positions
such as `steps[2].read_ids[0]`, with `invalid_count` for the full count. Copy the
exact ID from the relevant delivered read; never invent or pad a shortened ID.
Prepared, unknown and foreign receipts all remain rejected. Error feedback does
not reveal foreign state, include source text or make an unsupported step valid.

After an explicit rejection, correct the indicated problem before retrying.
After an uncertain outcome, check `behavior-list` first. Every retry still
consumes the shared analysis budget; closure is not extra save time.

Same context/question has a stable `behavior_id`. Identical saves are
idempotent; changed content appends a revision. Saved records are current run
notes, not final YAML or runtime observations.

`behavior-save` automatically nominates the complete files behind every cited
delivered read. An additional dependency is optional, limited to eight bounded
nominations, and must name an authorized `item`, `source` or `match` plus a
short reason it is indispensable. Do not submit paths or URLs.

The returned `record_saved` and `retention` outcomes are separate. Retention
states are `complete`, `pending`, `partial` or `gap`; only `complete` means all
nominated files were archived and verified. `pending` work can be retried by
the same idempotent save after checking `behavior-list`.

## Optional graph-candidate notes

One analysis can support the final asset proposal and the future behavioural
summary. All saved scan candidates are collected by trusted finalization code;
there is no need to retype the inventory or issue a command per candidate.
For a specific supported exclusion/correction or an explicit behaviour link,
inspect only the relevant candidate page:

```text
<prefix> graph-candidates <lead_id> --limit 5 [--cursor <next_cursor>]
<prefix> graph-note --record '{"candidate_ref":"occ_<64-hex>","action":"exclude","reason":"documented_false_positive","evidence_refs":["read_..."]}'
<prefix> graph-note --record '{"candidate_ref":"occ_<64-hex>","action":"include","reason":"review_corrected_exclusion","evidence_refs":["read_..."]}'
<prefix> graph-note --record '{"candidate_ref":"occ_<64-hex>","action":"link_behavior","reason":"request_in_flow","evidence_refs":["read_..."],"behavior_id":"behavior_...","behavior_revision":1,"fact_id":"<exact-returned-fact-id>"}'
```

Use the exact scoped occurrence and `fact_id` returned by the reader. Notes
require delivered read evidence from that lead/content version. For a behaviour
link, the read must also be cited in that behaviour's current revision. These
checks establish structural agreement of URL/method/context facts; they do not
verify the meaning of the explanation. A new behaviour revision needs a new
explicit link. Do not link items merely because they mention the same file.

`include` corrects a prior exclusion and reruns the original deterministic
validation; it cannot invent a missing URL component, method or resolution base.
The latest evidenced include/exclude applies, while notes remain append-only.
Reason values are short snake_case codes; no URLs, source text or credentials.
Unknown bases, virtual source paths, obscured/truncated identities and obsolete
secret projections remain named gaps. Repeating `scan <lead_id>` uses the
existing bounded verified-file scanner to refresh an obsolete projection when
those bytes are still available; it does not refetch missing code.

These optional operations consume the existing analysis budget and cannot run
in protected closure slots. They record notes only. No Exec operation submits
the graph proposal; trusted orchestration freezes and submits it once per
analysis version through the unchanged curator. Native job finalization and
final YAML publication are application-owned, not specialist commands.
