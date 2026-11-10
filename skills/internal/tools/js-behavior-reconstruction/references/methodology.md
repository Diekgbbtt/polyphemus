# Behaviour reconstruction methodology

Adapted from Trail of Bits' audit-context-building discipline for grounding
assumptions, callers/callees and open questions in inspected source, and
api-mapper's focused tracing of request values. This repository does not adopt
their subagent-per-function orchestration, exhaustive dossier, direct CDP/curl
replay or automatic target execution.

## Trace one question

1. State the selected question and the concrete clue that produced it.
2. Identify the trigger or entry condition from delivered code.
3. Trace input/state origins and transformations forward to a call, request,
   storage operation, DOM sink or local state effect.
4. Follow a caller or callee only when it changes the answer. Cite its delivered
   read rather than copying code into the record.
5. Keep success, error, conditional and later asynchronous paths distinct.
6. Record what the client code establishes, what remains assumed and what
   cannot be decided without missing source or runtime/server evidence.

## Asynchronous sequences

Treat these as separate events:

1. the code registers a listener;
2. the current function completes and returns;
3. a callback runs on a later event;
4. the callback checks its conditions and mutates local state/DOM.

Do not say the function awaits a future event merely because it registered a
listener. State explicitly whether the return value depends on the listener or
is produced immediately after registration.

For a one-shot listener, `once` describes listener lifetime: it is removed after
the first invoked callback/event, not necessarily after the first event whose ID
matches an inner condition. Nonmatching events can consume the one-shot
registration. Preserve the inner ID checks separately from the listener's
one-shot behavior.

Source code can establish client registration and conditional callback effects.
It does not establish when the server sent the event, when the browser delivered
it, or that a matching event ever occurred. Record those as runtime/server gaps.

## Evidence discipline

- A selected span is authorization and question context, not proof of every
  nearby statement.
- A delivered read proves the referenced bytes/window were delivered. It does
  not make the narrative automatically correct.
- A computed request field needs enough origin/transform evidence to explain its
  value. A function or variable name alone is insufficient.
- Purely local state/DOM behaviour is valid and must not gain an invented HTTP
  step.
- Client code can show construction/use of cookies or tokens; it cannot prove
  server flags, authorization, validation or JWT forgery.
- Redaction markers are visible limitations. Do not infer hidden values.

## Record shape

Prefer a few supported steps and explicit gaps over a complete-looking story.
Use narrative order for explanation, not as proof of unconditional execution.
Save a partial record before the shared closure reserve, then return to the
shortlist for the next prioritization decision.
