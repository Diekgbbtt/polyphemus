# Bundle structure commands

```text
<prefix> structure <lead_id>
<prefix> structure-items <lead_id> --limit 5
<prefix> structure-items <lead_id> --kind import --limit 5
<prefix> structure-items <lead_id> --kind dependency --limit 5 --cursor <next_cursor>
<prefix> structure-item <item_id>
<prefix> acquire-reference <item_id>
<prefix> note --text 'Structured <lead> index <ID> status <status>; counts <kind=counts>; items <IDs>; child <lead-or-none>; deferred <IDs>; gaps <reasons>'
```

`structure` revalidates the exact acquired Kali file before reuse or parsing.
Its trial limits are 8 MiB input, 20 seconds total/parser deadline, 384 MiB
parser memory, 10,000 items and a 16 MiB private index. Agent-visible responses
are capped at 16 KiB; list pages default to 5 and never exceed 10.

Use kind filters and cursors rather than requesting the complete index. Item
details contain byte spans in the original generated file, safe structural
links and redacted reference state. The private store retains exact literal
specifiers only for broker-side resolution.

`acquire-reference` supports an explicit selected literal ESM item under the
existing project/run/auth scope. It creates a child lead labelled
`code_derived`/`code_reference`, then the CLI uses the existing Kali worker to
verify and confirm bytes. A child can later be selected through inventory, but
this command never starts recursive expansion. Authentication remains subject
to the broker's current context; browser cookies are never inherited by Kali.
