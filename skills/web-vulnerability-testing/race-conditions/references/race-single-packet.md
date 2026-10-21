# Single-Packet Synchronisation

This note details the precision-synchronisation procedure the parent body summarises in one line.
The staging-and-flush template is tool-agnostic: any client that can multiplex, withhold a terminator, and flush one final write implements it.
Concrete client names and engine flags are runtime knowledge-base facts and stay out of this note.

## Why the window collapses

A concurrent burst fails for two different reasons that look alike: network jitter spreads the arrivals, and the server's dispatch order may serialise them anyway.
Single-packet synchronisation removes the jitter by making every request's final frame leave in one write, so the kernel hands the whole batch to the parser in one scheduler tick.
What remains is the application's own atomicity gap, which is the window the technique exposes rather than creates.
Blocking back-ends that serialise their workers still help less: the technique beats transport sequencing but cannot beat a genuine queue.

## Last-byte-sync procedure

1. Open one multiplexed connection and complete the transport handshake.
2. For each prepared request, send its header block and all but the last body byte, and withhold the stream-end flag so the server holds the request one byte short.
3. Repeat step two for every request in the batch, so each one is buffered at the server and parsed up to almost complete.
4. Release every final byte with the stream-end flag in one write, so the transport coalesces them into one segment.
5. Read one response per request and attribute one verdict per request, because a batch total cannot show which member won.

## Gate-sync template

```
prepare  N requests, each carrying its own intent (identical for one intent, varied for a partial-construction burst)
stage    for each request: send headers, then all but the last body byte, withhold the stream-end flag
gate     wait until every request is staged, so the server holds each one one byte short
flush    write every final byte with the stream-end flag in one write
collect  read all N responses, then re-read authoritative state to separate a durable effect from a transient reply
```

The client must expose four capabilities for the template to hold: multiplexing several requests over one connection, staging without the terminator, one flush carrying every final byte, and per-request response attribution.
Where the needed batch exceeds what one segment carries, widen with the first-sequence-sync extension below instead of repeating the flush.

## First-sequence-sync widening

The single-segment bound caps the batch size, so above that bound synchronise the first sequence numbers across several connections.
Align the handshakes in lockstep, fragment each request so the final frames still arrive together, and let the fragments land inside one processing window.
This widens the batch by an order of magnitude, which matters when the guard is a counting window rather than an atomic write.

## Window estimation

Time the operation single, then sequential, then concurrent, and read the verdict before choosing a primitive.
- Concurrent timings close to the single-request time mean the back-end handles the batch in parallel, so the window is real and single-packet helps most.
- A second concurrent timing that adds roughly one single-request time means the back-end serialises, so the window is whatever happens between workers and single-packet helps less.
- A body that exceeds one segment widens the arrival spread, so estimate again after the request size changes.
- Start with a small batch and raise it when the single-request time is very short, because a fast endpoint needs a larger staged batch to overflow the worker pool.

## Wire-capture validation

Capture the flush and confirm it landed as one segment carrying every final frame, in one transport record.
A merely pipelined burst reads as a race attempt without the tightness, and a reviewer downgrades it for that reason.
Record the capture beside the responses that should have been mutually exclusive, because the proof is the pair of them.

## Anti-patterns

A parallel-send mode that pipelines over the older protocol with millisecond spread is not a single-packet burst, however simultaneous it looks in a client.
A timing delta with no duplicated effect is parser or load noise, not a race.
Racing an endpoint that holds a real lock or transaction spends the budget without a window, which is what window estimation exists to filter out.
