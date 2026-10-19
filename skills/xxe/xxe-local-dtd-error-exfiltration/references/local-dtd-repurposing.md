# Local Definition Repurposing

This note details the zero-egress recipe the local-definition error variant summarises.
The definition document it repurposes is one the host already installs, so the disclosure rides the parse error and needs no outbound request.
The paths, the entity names, and the error wording are runtime knowledge-base facts: re-run the enumeration per image and per platform version rather than memorising them.

## Preconditions

Four capability verdicts select this recipe, and the variant body carries the probes that produce them.
- Declaration acceptance: the consumer honours a document type declaration at all.
- Local resolution: a caller-named document resolves from the filesystem while remote fetch stays closed.
- Redefinition: an entity the resolved document declares is substituted by a caller-supplied body.
- Error interpolation: a parse failure quotes the reference it failed to resolve.

## Step 1 - Inventory the installed definitions

Enumerate definition documents by the family that ships them, because each family opens a different path space.
- System grammar directories: the markup and conversion grammars installed with the platform's own documentation tooling.
- Application install trees: report, renderer, and export components ship definition documents of their own.
- Converter resources: format converters and editor integrations carry definitions for the formats they read.
- Container image layers: each layer adds its own definitions, so an image change reopens the candidate set.

Test each candidate by naming it as the external subset and reading whether the error class changes, because an unreachable path produces the same silence as a hardened parser.
Keep one candidate per attempt, so an error-class change attributes to exactly one document.

## Step 2 - Find the redefinition hook

The hook is an entity name the installed document declares itself, because the parser substitutes the caller's declaration for that document's own body.
Take the name from the same document version distributed with the platform or the image, since a name the document does not declare fails silently.
Prefer a document whose declared set is small and documented, and expect parameter-entity names to be the usable hook.

## Step 3 - Compose the redefinition

Three parts compose the chain.
- An outer parameter entity that names the installed document as its external subset.
- A redefinition body that declares an inner entity reading the target file, and a second inner entity whose failing destination embeds the first.
- A reference to the outer entity, so the parser expands the chain before it processes the document body.

Escape the reference-opening characters inside the redefinition body in character-reference form, because the parser reads them as data at the outer level and as references at the inner level.
Build the value through two nesting levels rather than one, so a single parse both reads the file and quotes it in the failing destination.

## Step 4 - Read the value in windows

Error text is capped, so read one ordered window per attempt and reassemble locally.
Prefer an error class that quotes the destination it could not resolve over a class that reports only a line number.
Repeat per window until the target value is recovered or a definitive negative is recorded.

## Step 5 - Prove zero egress

Record the absence of outbound traffic across the attempt, because the channel attribution is the finding here.
A callback observed during the attempt places the finding in the callback variant instead.

## Failure modes

- The document resolves but redefinition stays inert: the parser caches the document, or its declared set carries no usable name.
- The error class reports a position without quoting the reference, which discloses nothing.
- The parser stops after the first resolution failure, so one attempt yields one window.
- The target file is unreadable to the parser's account: the error quotes a permission failure instead of content.
- The installed set changed with a build, so a hook that resolved yesterday no longer exists.
