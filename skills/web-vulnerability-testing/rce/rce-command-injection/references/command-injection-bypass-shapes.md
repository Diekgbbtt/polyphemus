# Command Injection Bypass Shapes

This note details the bypass families summarised in the variant body.
Each family names the filter it defeats and the read-out that confirms the shape survived.
Concrete payload spellings are runtime knowledge-base facts and stay out of this note.

## Bypass families

| Family | Shape | The filter it defeats |
|---|---|---|
| Separator substitution | A variable-held field separator, brace expansion, or redirection in place of a space | A filter that blocks the space character |
| Token splitting | Quote insertion or an empty-variable insertion inside the operation name | A filter that matches operation names literally |
| Wildcard execution | A glob that resolves to the target path | A filter that blocks the operation name and the separator characters |
| Encoded stager | An encoded blob decoded on the fly, which restores the shape after inspection | An inspection point that decodes fewer passes than the interpreter |
| Path-component substitution | One character extracted from an existing variable | A filter that blocks the path separator |
| Shell-flavour switching | An alternate binary, an absolute tool path, or a wrapper invocation | A filter that blocks the primary family |
| Caret-style escape | A character escape recognised by the Windows-style family | A filter written against the Unix-style family |
| Reflection indirection | A language-level send or call that reaches the same operation | A filter that blocks the operation's own name |
| Argument-file expansion | A prefix that makes a CLI read further arguments from a file | A filter on the argument value, where the error text then echoes the file |
| Array-argument delivery | The operation plus its arguments as separate list members | Quoting rules, because the wrapper never builds a shell string |

## Out-of-band confirmation

Mint one fresh callback marker per probe, so each inbound arrival binds to exactly one request.
Carry the result in an encoded label of the callback name where only name-resolution egress survives, so the arrival returns data rather than mere liveness.
Fall back to a gated delay oracle when no egress exists, measured against a response-time baseline recorded before the probe.
Read an argument-derived file line in the error text, and a probe output redirected to a fetchable path, as the two shapes that turn argument injection into a read.

## Discipline

Match the body encoding to the parser the endpoint reads before drawing any conclusion, because a structured body against a form parser yields a silent false negative with a plausible success status.
Try one family per probe against one sink, and record a filtered verdict as a result rather than a reason to skip the sink.
Probe delimiter acceptance with a portable gated shape first, then choose the family the filter leaves open.
Hand layered combinations to the `defence-bypass` family at the filter step rather than restating relay mechanics here.
