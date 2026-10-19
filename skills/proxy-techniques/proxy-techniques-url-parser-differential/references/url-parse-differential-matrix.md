# URL Parse Differential Matrix

This note holds the notation family across readers of one destination value: the element, the reader that folds it, the reader that does not, and the observable that localises the split.

## The Notation Family

| Element | One reader folds it | The other reader keeps it | Observable |
|---|---|---|---|
| Authority boundary | The host before a userinfo or separator shape | A second host after the shape | The two readers deriving different authorities |
| Duplicate destination member | One occurrence by its precedence | The other occurrence by its precedence | Each reader acting on a different occurrence |
| Trailing dot or case variant | A look-alike of the approved host | A distinct host | The connection reaching the distinct host |
| Numeric or address notation | One resolved address | A different resolved address | The consumer connecting where the approver did not |
| Encoded separator | A separator after its decode | Data until the decode | The path or authority splitting on one side only |
| Dot segments | A normalised path | The original path | The router resolving a path the approver never named |
| Relative or scheme-relative value | The consumer's own base | The approver's base | The derived target differing between the two readers |
| Fragment terminator | A value ending at the terminator | A value carrying the remainder | A constructed destination ending where the approver did not read |

## Reader Kinds

The reader kinds are: the approver that validates the destination, the connector that resolves it, a server-side URL builder that interpolates it into a backend destination, the cache that keys on it, and the origin that routes it.
List each reader with the target it derives, because the gap is between two derived targets rather than inside one value.
A server-side builder is a second reader: a terminator inside the value ends the path the builder meant to append, and traversal segments move within the backend destination.
An API-definition error, a route-not-found error, or an unexpected backend path in a response is the observable that the value reached a server-side URL router rather than a text validator.

## Probe Order

Shape one structural element per attempt: the authority boundary, the userinfo, the fragment, the case, the encoding, then the duplicate occurrence.
Keep the approved host visible to the approver, because the check reads the value it derives rather than the value's text.
Establish the refusal baseline with a plainly external destination, so a later arrival is attributable to the second parse.
Treat a decode-count disagreement on one value as the encoding differential's step rather than this one, and keep this family on the destination's structure.

## Proof

Reach the derived target with a listener, because the shaped value's own response names only the approver's parse.
Pair the approver's derived target with the consumer's derived target, so the element that split the parse is named from the pair.
Where the response reflects nothing, confirm the derived destination out of band, because the builder's own answer names only the builder.
A refusal from a second check behind the first reads as a stacked control rather than a parse gap.
