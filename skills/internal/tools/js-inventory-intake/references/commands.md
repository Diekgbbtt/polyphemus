# Exec recipes

Use the supplied prefix `python3 /opt/polymerhus-js/cli.py --agent-url <agent> --reference <ref>` before each operation. The runner checks that prefix; shell pipelines, direct HTTP and arbitrary commands are unavailable in this acquisition slice.

```text
<prefix> context
<prefix> skill js-inventory-intake
<prefix> reference js-inventory-intake commands
<prefix> notes
<prefix> inventory --limit 5
<prefix> inventory --limit 5 --cursor <next_cursor>
<prefix> lead <lead_id>
<prefix> note --text 'Selected <IDs> with reasons; deferred <IDs> with reasons; pending <IDs>; next_cursor <cursor or none>; gaps <reasons>'
```

`context` binds this invocation. `inventory` returns redacted metadata, pod completeness and `next_cursor`; null cursor means no remaining inventory page, not complete application coverage. The opaque reference expires: a 403 is an access gap. Do not remove the reference or change context. A new dispatcher invocation validates its supplied reference and issues a fresh reference for its finite deadline; an already-expired input must be reissued by the trusted pipeline owner. Notes survive a fresh model context.

Read just enough pages to rank a bounded batch. The batch limit is a maximum,
not a requirement to select that many leads. Record the remaining cursor and
returned but unselected IDs with reasons. Reasons can be tentative; later code
inspection must establish actual relationships. CLI errors have explicit
`error`/`failure_reason` fields and nonzero exit status.

After recording the selection, load `js-code-acquisition` and continue in the
same specialist through acquisition, baseline scan and source-map recovery.
Selection does not end the workflow.
