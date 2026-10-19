# Note: Microcks vs `mock-core` for mocking NICo Core (gRPC)

**Status:** manual spike, 2026-10-19. Not scripted, so the results below are a
record of a one-off session, not a reproducible PoC. Versions: Microcks 1.15.0,
`infra-controller` commit `02b92f18f`.

## What `mock-core` is

`rest-api/site-agent/cmd/mock-core` in `infra-controller` is a hand-written,
in-memory gRPC mock of NICo **Core**, the layer below the REST API. It exists
so the REST stack can run in Kind or CI without a real Core. It is not
generated from a spec, and it is a different layer from the REST/MQTT contracts
used in PoCs 1–3.

## What was tried

1. Imported the real Core proto (`proto/core/src/v1/nico_nico.proto`, about
   12k lines plus 14 imported protos) into Microcks as a gRPC service.
2. Added `APIExamples` for `Version`, `CreateVpc` and `FindVpcIds`.
3. Called Microcks (`:9090`) and a locally built `mock-core` (`:11079`) with
   `grpcurl`.

## Measured results

| Check | Result |
|---|---|
| Proto import | OK: `forge.Forge:forge`, 535 operations |
| `Version` on Microcks, with an example | Full `BuildInfo` returned |
| `Version` on `mock-core` | Only `{"buildVersion":"1.0.0"}` |
| RPCs implemented | `mock-core` 60 of 534. Microcks imports all 534 and needs examples to answer. |
| `mock-core`: `CreateVpc` then `FindVpcIds` | Stateful: the created VPC is listed |
| Microcks, no example for the RPC | `NotFound: No response found for the GRPC input request` |
| Microcks with examples: `FindVpcIds` before and after `CreateVpc` | Identical fixed answer |
| Microcks: `CreateVpc` with a different name and org | Returns the `poc-vpc` example (no dispatching on complex request messages) |

## Practical finding: proto import layout

Microcks resolves proto imports by package depth. With `package forge` it
expects the main file at `<base>/forge/nico_nico.proto` and its imports one
level up (`<base>/common_nico.proto`, ...). The flat `src/v1/` layout fails
with a generic "Protobuf schema file parsing error". Serving a copy of the
files in that shape and importing via `POST /api/artifact/download` worked.

## Conclusion

- Microcks is **complementary**, not a replacement. It is cheap to produce from
  the proto and covers far more RPCs, but its answers are fixed by examples.
- `mock-core` stays the right tool for stateful end-to-end flows (create then
  read, multi-step Temporal workflows).
- Microcks is a plausible mock for static, read-only Core RPCs and for
  contract-testing Core against its proto.

## Statefulness spike (measured, Microcks 1.15.0)

First measured on the full stack, then repeated on the default uber JVM stack. The scripted behaviour (first four rows) is identical on both; storage-related behaviour (last three rows) differs and is shown per stack.

Setup: the real Core proto imported as a gRPC service, one example for
`CreateVpc` (`created`), two for `FindVpcIds` (`empty`, `one`), and an
`APIMetadata` setting `dispatcher: JS` on both operations. Scripts must define
`function process() { ... }` (no automatic wrapping on the gRPC path).
`CreateVpc` runs `store.putWithTtl("vpc_created","true",N); return "created";`
and `FindVpcIds` returns `"one"` if `store.get("vpc_created")` is `"true"`,
else `"empty"`.

| Step | Result |
|---|---|
| `FindVpcIds` before create | `{}` (empty) |
| `CreateVpc` poc-vpc / org1 | canned `poc-vpc` response |
| `FindVpcIds` after create | lists the canned VPC id (state works) |
| `CreateVpc` other-vpc / org2 | **same canned id, name `poc-vpc`**: bodies are not generated |
| TTL set to 5 s | **Full stack:** still visible at +10 s and +30 s, gone at +70 s (Mongo TTL sweep is about 60 s, so expiry is not precise). **Default uber:** still visible at +330 s, the TTL was never enforced by the embedded store |
| App container restart | **Full stack:** state survived (stored in MongoDB), imported services kept. **Default uber:** everything lost, including the imported services (in-memory store) |
| `down -v` | state is lost on both (the full stack's Mongo has no volume) |

Conclusion: Microcks supports limited state. A JS/Groovy dispatch script plus
a TTL key-value store (MongoDB) chooses between prepared responses. It cannot
generate new data (IDs, echoed fields, lists that grow). We therefore stay
complementary to `mock-core` rather than reinventing it: `mock-core` for
stateful flows, Microcks for contract-driven, example-based mocks and tests.

## Not tested

- Pointing the REST API at Microcks instead of `mock-core`. That requires the
  whole chain (REST, Temporal, site-agent, a registered site, Kind) and was not
  attempted, so "the REST layer behaves correctly on a Microcks-backed Core" is
  unproven.
- Microcks gRPC contract tests (`GRPC_PROTOBUF` runner) against a real Core.
- The coverage count (60 of 534) comes from matching RPC names in the proto
  against `NICoServerImpl` methods in `nico_test_server.go`; it is approximate.
