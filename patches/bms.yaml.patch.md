# Patch notes — `dsx-exchange/schemas/asyncapi/bms/bms.yaml`

This repo does **not** vendor NVIDIA's `bms.yaml` (it's large and belongs to
the `dsx-exchange` repo). To reproduce PoC 1, import the APIExamples file (step 1) and apply the
one edit in step 2 to your own checkout of `bms.yaml`.

> **Suggested upstream change.** Standard AsyncAPI `examples:` and `bindings:`
> fields would let any tool (not only Microcks) mock these channels. The
> binding has no APIExamples equivalent, so it stays a spec edit.
> They are only needed for *mocking* (PoC 1); the conformance test in PoC 3a
> runs on the unmodified specs.

## 1. Examples: no edit needed, use the APIExamples file

Microcks needs a message example to publish. Instead of editing `ValueMessage`,
import [`../examples/bms.apiexamples.yaml`](../examples/bms.apiexamples.yaml) as a
**secondary** artifact after the spec (see [`APIExamples`](https://microcks.io/documentation/references/examples/)).
It holds one example for `RECEIVE receiveRackValue`. Trade-off: an example in
the spec's `ValueMessage` would serve every Value channel at once; an
APIExamples file is per operation, so each further channel needs its own entry.
Adding an `examples:` block to `ValueMessage` upstream remains the more
tool-neutral option.

## 2. Declare the MQTT binding on at least one operation

`bms.yaml` has zero `bindings:` nodes anywhere, so Microcks' importer
defaults every operation to its generic KAFKA binding. Add an explicit MQTT
binding to the `receiveRackValue` operation under `operations:`:

```yaml
  receiveRackValue:
    action: receive
    channel:
      $ref: '#/channels/rackBmsValue'
    messages:
      - $ref: '#/channels/rackBmsValue/messages/valueMessage'
    description: Subscribe to real-time BMS-published values for all Rack points.
    bindings:                         # <-- add this block
      mqtt: {}
```

Repeat step 2 for any other operation you want Microcks to mock over MQTT
(in production, this would be a mechanical pass applying `bindings: mqtt: {}`
to every operation in the file — a few dozen lines, not a redesign).
