# Address Notation Bypass Families

This note details the address-notation families summarised in the parent body.
Each family is a spelling of one destination that a different reader resolves differently, so the check and the connection disagree.
Concrete payload spellings are runtime knowledge-base facts and stay out of this note.

## Notation families

| Family | Shape | The check it defeats |
|---|---|---|
| Numeric base notation | A decimal, octal, hexadecimal, or short-form spelling of one address | A textual comparison against the canonical dotted form |
| IPv6 and mapped forms | A loopback literal, an IPv4-mapped literal, and a mixed-notation mapped literal | An allowlist written against IPv4 spellings alone |
| Trailing dot and case | A fully qualified form with a trailing dot, or a case variation of a hostname | An equality check on the hostname string |
| Userinfo split | The address carried after the userinfo separator, so the parser reads the permitted name first | A prefix or substring comparison on the authority |
| Fragment before host | A fragment marker placed so the check truncates the value before the host | A check that splits the value on the fragment marker |
| Encoded separator | The userinfo or port separator carried in encoded form | A filter that decodes fewer passes than the fetch side |
| Backslash before host | A backslash ahead of the host so one parser treats it as a path separator | A comparison written for one parser's grammar |
| Wrapped or encoded destination | A blob carried in the path, or a double-encoded host | An inspection point that decodes fewer passes than the fetch side |
| Scheme-less and relative form | A destination the fetcher completes against its own base | A check that only inspects absolute destinations |

## Decode-pass counting

The number of decode passes before the fetch is the bug, so count it deliberately.
Send the value encoded once, then twice, and record which pass the fetch side resolves, because the difference between the inspection point and the fetch is the gap.
Treat a value that reaches the fetch after a pass the check never applied as a finding, and one that is refused at the same pass as a filtered verdict.

## Read-out discipline

Send one notation per probe, with a negative control per family, so a callback or a differential attributes to the notation rather than to the request.
A destination echoed back inside an error, help, or validation string proves formatting rather than a fetch, and it is the most common mis-report.
Uniform errors across every notation and handler read as a closed network rather than a confirmed negative.
Hostname resolution after approval, redirect chains, and the destination parse comparison belong to the `proxy-techniques` family at its rebinding, redirect, and parser steps; record only the reach verdict here.
The encode-depth and decode-count mechanics belong to the `defence-bypass` family at its encoding-differential step, so this note keeps only the address families and their read-out.
