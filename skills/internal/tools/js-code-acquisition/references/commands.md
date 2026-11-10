# Context-bound acquisition

```text
<supplied-prefix> skill js-code-acquisition
<supplied-prefix> reference js-code-acquisition commands
<supplied-prefix> lead <selected_lead_id>
<supplied-prefix> acquire <selected_lead_id>
<supplied-prefix> scan <selected_lead_id>
<supplied-prefix> scan-results <selected_lead_id> --mode urls --limit 5
<supplied-prefix> scan-results <selected_lead_id> --mode urls --limit 5 --cursor <next_cursor>
<supplied-prefix> scan-results <selected_lead_id> --mode secrets --limit 5
<supplied-prefix> recover <selected_lead_id>
<supplied-prefix> recovered-sources <selected_lead_id> --limit 5
<supplied-prefix> note --text 'Acquired <ID/hash/size>; scan <key> urls=<status/count> secrets=<status/count>; pending <IDs>; deferred <IDs/reasons>; next_cursor <cursor or none>; gaps <reasons>'
```

The installed CLI delegates streaming to the repository worker. It writes a `.part`, verifies exact size/hash, atomically renames to `/work/js-analysis/<run_id>/<sha256>.js`, confirms the app-owned manifest and rechecks the file. Ordinary stdout contains only bounded metadata; exact URLs, response bodies and credentials stay private. Both skills and their focused references resolve through the app's shared SkillStore, project first, without mounting the app data root in Kali.

`scan` resolves only the manifest-bound work file for that lead. It rechecks file presence/size/hash, runs local jsluice `urls` and `secrets` sequentially with a 15-second and 1 MiB bound per mode, and persists the modes independently. Reuse occurs only for a complete scan with the same source hash, binary identity, options and pattern fingerprint. Partial scans may be retried; they never count as complete coverage.

Candidate reads return redacted endpoint metadata or secret type/fingerprint only. Preserve relative/dynamic URLs as output by the scanner; do not resolve them against the acquisition URL in this slice. Scanner candidates are internal evidence for later analysis, not proof of execution and not graph publications.

After a verified acquisition, recovery is attempted even if `scan` fails,
times out or is partial. Record the two outcomes separately, continue through
the remaining selected leads, and keep `map_not_found` as a gap for that lead.

An expired reference fails explicitly. The model cannot renew or widen it; the trusted dispatcher supplies a valid reference covering its finite runtime. On interruption request the same project/run/context again through the dispatcher and recover pending work from notes. Missing Steel captures and `multiple_capture_versions` require a named gap, not choosing a body or retrying with stored/anonymous cookies.
