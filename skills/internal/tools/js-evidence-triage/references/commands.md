# Evidence triage commands

After `context` and `notes`, an initial bounded `triage-list` is early
guidance. It resumes planning state without starting the triage-analysis
phase. Actual analysis starts only when `search-code`, `read-code`,
`triage-select` or `triage-update` is executed; all commands still consume the
overall runner budget.

```text
<prefix> triage-list --limit 5
<prefix> triage-list --limit 5 --cursor <next_cursor>
<prefix> search-code <lead_id> --text <exact-case-sensitive-literal> --limit 5
<prefix> search-code <lead_id> --text <literal> --limit 5 --cursor <next_cursor>
<prefix> triage-select --item <item_id> --question '<question>' --priority high
<prefix> triage-select --source <source_id> --question '<question>' --priority normal
<prefix> triage-select --match <match_id> --question '<question>' --priority low
<prefix> read-code --match <match_id> --bytes 4096
<prefix> read-code --source <source_id> --bytes 4096 --cursor <next_cursor>
<prefix> triage-update <span_id> --state inspected --read-id <read_id>
<prefix> triage-update <span_id> --state deferred --reason '<reason>'
<prefix> triage-update <span_id> --state unresolved --reason '<missing evidence>'
```

Read windows default to 4 KiB and never exceed 8 KiB. Search literals are
2–128 UTF-8 bytes, exact and case-sensitive. Search examines at most 64 MiB
per segment and records at most 10,000 matches; list pages default to 5 and
never exceed 10. All operations use the existing opaque project/run/auth
reference and a five-second operation deadline subordinate to the runner.

The CLI transfers bytes only after resolving a verified work file from the
private manifest. Normal stdout contains no work paths, raw URLs or credential
values. Code text appears only in a successful redacted read window. Search
previews and reads remain evidence locators; they are not scanner findings,
browser observations or behavioural conclusions.
