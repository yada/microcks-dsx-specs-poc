# PoC 3a — replaying dsx-exchange PR #117 as a Microcks conformance test

**Question:** [dsx-exchange#117](https://github.com/dsx-ai-factory/dsx-exchange/pull/117)
fixed `nico.yaml` after the real NICo message serializer turned out to publish
11 managed-host states the spec did not describe. It was found by running a
generator script by hand once. Would Microcks' AsyncAPI test runner have caught
the same drift automatically, on live MQTT traffic, with no custom code?

**Answer:** yes. Run against the `nico.yaml` from before #117, Microcks rejects
12 of 26 messages and fails the test; against the `nico.yaml` from after #117
it accepts all 26 and passes. This works on the **unmodified** upstream specs:
no `bindings:` or `examples:` patch is needed for testing (those patches are
only needed for PoC 1's *mocking*).

## Run it

```sh
docker compose -f microcks/docker-compose.yml up -d     # wait until healthy (secured stack: add `--keycloak http://localhost:18080` to run.sh)
poc3a/run.sh                                            # ~2 minutes
```

`run.sh` creates a local virtualenv (`pyyaml`, `jsonschema`), reads the two spec
revisions straight from your local `dsx-exchange` checkout with `git show`
(default `../dsx-exchange`, override with `--dsx-exchange DIR`), and exits
non-zero if any expected outcome does not hold. Nothing in `dsx-exchange` is
modified or vendored.

## What it does

1. Extracts `schemas/asyncapi/nico/nico.yaml` at `4e8b71f` (#117) and its
   parent `16867bd`. The only edit is `info.version`, set to `post-117` /
   `pre-117`, so both revisions exist side by side in Microcks as separate services.
2. Builds one example message per managed-host state from the **post-#117**
   schema (required properties, first enum value, first `oneOf` branch): 26
   messages. Three deliberately broken messages are added for scenario C.
3. Publishes them as **retained** MQTT messages on
   `NICO/v1/machine/<id>/state` (Mosquitto, from the PoC 1 stack). Retained
   messages are replayed on subscribe, so the run is deterministic.
4. Starts a Microcks test (`runnerType: ASYNC_API_SCHEMA`, endpoint
   `mqtt://mosquitto:1883/NICO/v1/machine/+/state`, operation
   `SEND publishManagedHostStateChange`) per scenario, reads each message's
   verdict back through the Microcks API and maps it to its payload.
5. Cross-checks every Microcks verdict with an independent offline `jsonschema`
   validation of the same payload.

## Results

Microcks 1.15.0, `dsx-exchange` `16867bd` (pre) / `4e8b71f` (post). Full output:
[`poc3a/evidence/run.log`](../poc3a/evidence/run.log); per-message data:
[`poc3a/evidence/results.json`](../poc3a/evidence/results.json).

| Scenario | Spec | Traffic | Received | Pass | Fail | Test |
|---|---|---|---|---|---|---|
| A | pre-#117 | 26 valid | 26/26 | 14 | **12** | ❌ failed |
| B | post-#117 | same 26 | 26/26 | **26** | 0 | ✅ passed |
| C | post-#117 | 26 valid + 3 broken | 29/29 | 26 | **3** | ❌ failed |

**A — the drift.** The 12 rejected messages are the 11 states #117 added
(`decommissioning`, `reset`, `bootconfiguring`, `maintenance`, `configureastra`,
`rotatingbmc`, `rotatinghostuefi`, `rotatingdpuuefi`, `rotatingniclockdown`,
`preassignedmeasuring`, `startassignmentcycle`) plus `postassignedmeasuring`,
whose payload schema #117 also changed. Typical Microcks message:

```
must be valid to one and only one schema, but 0 are valid
does not have a value in the enumeration ["dpudiscoveringstate", "dpuinit", ...]
```

The pre-#117 count of 14 passing messages matches the "14 validate against the
current schema" figure quoted in #117's own validation notes. This is a
coincidence worth noting, not a claim: #117 used 27 payloads from NICo's real
serializer, this PoC uses 26 schema-derived ones.

**C — it still catches real errors.** Only the broken messages fail, each with a
precise reason:

| Message | Microcks error |
|---|---|
| `bad-missing-machine-id` | `required property 'machine_id' not found` |
| `bad-unknown-state` | `must be valid to one and only one schema, but 0 are valid` |
| `bad-wrong-timestamp-type` | `integer found, string expected` |

The script's six self-checks all pass, including "Microcks verdicts match the
offline jsonschema verdicts in A, B and C" (every message, every scenario).

## Reproducibility evidence

- Run from a fully wiped stack (`docker compose down -v`, fresh `up -d`):
  exit 0, identical results.
- Re-run on the same stack: exit 0 (retained topics are cleared before each
  scenario).
- Both specs imported as-is; the async-minion had 0 restarts.

## Real fixtures: messages serialized by NICo's own types

The scenarios above use schema-derived payloads. `poc3a/run_real.sh` replays
messages that come from `infra-controller`'s real `ManagedHostState` serde
types instead, stored as a Microcks
[APIExamples](https://microcks.io/documentation/references/examples/) file
(`examples/nico-real.apiexamples.yaml`, 49 unique messages).

How they are made (`poc3a/real/regenerate.sh`, needs Rust and `protoc`):
`extract_samples.py` harvests the `ManagedHostState` JSON snippets that
NVIDIA's own tests and docs contain (71 candidates); a small Rust example
(`dump_states.rs`, run in a throw-away git worktree so the checkout is not
modified) deserializes each with the real types, which rejects the 18 that are
stale or deliberately bogus, and re-serializes the 53 accepted ones inside a
copy of the `ManagedHostStateMessage` struct from
`api-core/src/mqtt_state_change_hook/message.rs`. `machine_id` is a zero test
id and `timestamp` is fixed.

The replay is Microcks-native: the script imports `nico.yaml` (with the MQTT
binding edit applied automatically to a work copy) and then the APIExamples
file as a secondary artifact. Microcks' async minion publishes the 49 examples
to Mosquitto, an `ASYNC_API_SCHEMA` test subscribes and validates, and events
are deduplicated by content since the minion republishes periodically.

Result against `dsx-exchange` `28c66bf5b` (log: `poc3a/evidence/real.log`):
**45 of 49 conform, 4 do not**, and Microcks agrees with offline `jsonschema`
on every message:

- `dpuinit` with `dpustate: waitingforplatformpoweroff`
- `dpureprovision` with a `configurehostboot` substate
- `dpureprovision` with an `unlockhostforbootrepair` substate
- `hostinit` / `spdmmeasuring`

None of those four state names appears in `nico.yaml`, while the code defines
them. This is a finding about spec coverage, not yet a confirmed bug: the
fixture shows the serializer can emit them, not that production NICo emits them
today. It is the kind of gap #118 proposes to catch automatically, and it is
worth asking the maintainers whether `nico.yaml` is meant to be exhaustive.

Limits of the real fixtures: they cover the states NVIDIA's tests happen to
contain (not every reachable state, so 45/49 is not a conformance rate for
NICo), `ManagedHostStateMessage` is copied rather than imported, and no live
NICo or broker is involved.

## Limits — read before citing this

- **In scenarios A-C the payloads are schema-derived (see the real fixtures above for the other set).** Scenario B
  passing is therefore expected by construction. What the PoC demonstrates is
  scenario A: a spec revision that is out of date relative to what the
  publisher emits is detected automatically and loudly. #117 is the evidence
  that NICo does emit the 11 extra states; this PoC does not independently
  confirm it.
- **Not run against a real broker or a real NICo.** The broker is the local
  Mosquitto from PoC 1. Pointing the same test at a staging NATS/MQTT endpoint
  is the next step and is untested.
- **CI.** `.github/workflows/poc-conformance.yml` runs the A-C scenarios and the
  real-fixture replay (`run_real.sh`, against dsx-exchange pinned to `28c66bf5b`)
  on GitHub (`ubuntu-latest`). Fixture regeneration (`real/regenerate.sh`, needs
  Rust) is not in CI.
- **The Microcks runner validates a window of traffic, not all of it.** It
  subscribes for the timeout (10 s here) and validates what arrives. States that
  are never published in the window are never checked, which is why retained
  messages are used to make this PoC deterministic.
- The upstream proposal for this idea,
  [dsx-exchange#118](https://github.com/dsx-ai-factory/dsx-exchange/issues/118),
  was closed as "not planned" on 2026-10-19 without comment, then reopened by
  the maintainer the same day (open, no comments). This PoC is a
  self-contained demonstration, not something NVIDIA asked for.
