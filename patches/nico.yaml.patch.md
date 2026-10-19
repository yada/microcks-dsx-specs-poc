# Patch notes — `dsx-exchange/schemas/asyncapi/nico/nico.yaml`

Same reasoning as `bms.yaml.patch.md`: import the APIExamples file and apply
the one binding edit below to your own checkout.

> **Suggested upstream change.** Same as for `bms.yaml`. Only needed for
> mocking (PoC 1), not for the PoC 3a conformance test.

> **Verified current:** [dsx-ai-factory/dsx-exchange#117](https://github.com/dsx-ai-factory/dsx-exchange/pull/117)
> (the schema restructuring) has merged. This patch was re-verified against
> `dsx-exchange` commit `484162a` (2026-10-15) and applies as written.

## 1. Examples: no edit needed, use the APIExamples file

This spec's only message has no `examples:`. Import
[`../examples/nico.apiexamples.yaml`](../examples/nico.apiexamples.yaml) as a
**secondary** artifact after the spec (see [`APIExamples`](https://microcks.io/documentation/references/examples/)). It
holds one example for `RECEIVE subscribeManagedHostStateChange`. Adding an
`examples:` block under `components.messages.ManagedHostStateChangeMessage`
upstream remains the more tool-neutral option.

## 2. Declare the MQTT binding on the subscribe operation

Add the binding to `subscribeManagedHostStateChange` under `operations:`:

```yaml
  subscribeManagedHostStateChange:
    action: receive
    channel:
      $ref: "#/channels/managedHostState"
    messages:
      - $ref: "#/channels/managedHostState/messages/stateChangeMessage"
    description: >
      Subscribe to managed host state change events for monitoring,
      orchestration, and automation purposes.
    bindings:                         # <-- add this block
      mqtt: {}
```
