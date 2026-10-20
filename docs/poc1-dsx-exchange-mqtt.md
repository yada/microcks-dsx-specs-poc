# PoC 1 — Microcks mocking dsx-exchange's AsyncAPI specs over MQTT

**Goal:** replace [`dsx-exchange`](https://github.com/dsx-ai-factory/dsx-exchange)'s
hand-built, CSV-driven telemetry simulator (`local/mqtt-client/cmd/dummy-bms`)
with mocks generated directly from the AsyncAPI contracts the team already
maintains (`schemas/asyncapi/bms/bms.yaml`, `schemas/asyncapi/nico/nico.yaml`).

## Versions used

| Component | Version |
|---|---|
| Microcks (uber, all-in-one: app + embedded store, auth disabled) | `quay.io/microcks/microcks-uber:nightly-native` (pinned by digest in the compose file) |
| Microcks async minion (uber) | `quay.io/microcks/microcks-uber-async-minion:nightly-native` (pinned by digest) |
| MQTT broker | `eclipse-mosquitto:2` |

Specs tested: `dsx-exchange` commit `484162a` (2026-10-15).

The multi-component, Keycloak-secured stack used earlier is kept as an option
(see the "Stacks" section of the [README](../README.md#stacks-default-and-full));
the commands below work on both except where noted.

## 1. Bring up the stack

```sh
docker compose -f microcks/docker-compose.yml up -d
```

This starts three containers: Microcks (uber distribution, which embeds its
own MongoDB-compatible store and runs without Keycloak), its async minion
(configured for MQTT through `ASYNC_PROTOCOLS=,MQTT`), and a standalone
Mosquitto broker standing in for the MQTT side of dsx-exchange's NATS
deployment. State is in memory: restarting the app container resets it.

Wait for the app to answer (the async minion starts after it; the native image
has no container healthcheck):

```sh
until curl -sf http://localhost:8080/api/keycloak/config >/dev/null; do sleep 1; done
docker compose -f microcks/docker-compose.yml ps
```

To use the released JVM images (1.15.0) instead, add
`-f microcks/docker-compose.jvm.yml` to the compose command.

## 2. Authentication

None needed: the uber distribution runs with `keycloak.enabled=false`, so the
upload calls below carry no token. This is fine for a local demo and not
something to expose. On the secured stack (`microcks/full`), get a token first
and add `-H "Authorization: Bearer $TOKEN"` to the `curl` calls:

```sh
TOKEN=$(curl -s -X POST http://localhost:18080/realms/microcks/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=microcks-serviceaccount-test" \
  -d "client_secret=1b4db7eb-4057-5ddf-91e0-36dec72071f5" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

## 3. Patch, import the specs and the examples

Apply the one edit (the MQTT binding) in [`../patches/bms.yaml.patch.md`](../patches/bms.yaml.patch.md)
and [`../patches/nico.yaml.patch.md`](../patches/nico.yaml.patch.md) to your
own checkout of `dsx-exchange`, upload both specs, then upload the message
examples from [`../examples/`](../examples/) as **secondary** artifacts
([Microcks APIExamples](https://microcks.io/documentation/references/examples/)):

```sh
curl -s -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@/path/to/dsx-exchange/schemas/asyncapi/bms/bms.yaml;type=application/x-yaml" \
  -F "mainArtifact=true"

curl -s -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@/path/to/dsx-exchange/schemas/asyncapi/nico/nico.yaml;type=application/x-yaml" \
  -F "mainArtifact=true"

# examples: secondary artifacts, imported after the spec they belong to
curl -s -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@examples/bms.apiexamples.yaml;type=application/x-yaml" -F "mainArtifact=false"
curl -s -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@examples/nico.apiexamples.yaml;type=application/x-yaml" -F "mainArtifact=false"
```

Expect `201` responses echoing `BMS Event Bus:1.0.0` and
`NICo Managed Host State Event Bus:1.0.0`.

## 4. Watch Microcks publish real mock traffic

```sh
docker run --rm --network microcks-poc_default eclipse-mosquitto:2 \
  mosquitto_sub -h mosquitto -p 1883 -t '#' -v -W 15
```

(Adjust the `--network` name to match whatever Docker Compose project name
it generated — check with `docker network ls`.)

### Expected output

```
NICoManagedHostStateEventBus-1.0.0-NICO/v1/machine/{machineId}/state {"machine_id":"dpu-gb200-rack42-node07","timestamp":"2026-10-05T18:00:00Z","managed_host_state":{"state":"ready"}}
BMSEventBus-1.0.0-BMS/v1/PUB/Value/Rack/{pointType}/{tagPath} {"value":22.96215,"timestamp":1743620423000,"quality":1}
```

Repeating every ~3 seconds, generated entirely from the spec — no custom
simulator code.

## What this proves

- Microcks can parse dsx-exchange's real, production AsyncAPI specs as-is.
- Once the one mechanical spec edit (MQTT binding) and the APIExamples files
  are applied, Microcks produces live, schema-conformant MQTT traffic on dsx-exchange's actual
  documented topic conventions.

## What this doesn't prove (yet)

Microcks' `AsyncAPITestRunner` can also validate *real* traffic against
these same contracts — something `dummy-bms` cannot do — but that run
against a live broker isn't exercised in this PoC, only mocking is. It's
proposed as follow-up work in
[dsx-ai-factory/dsx-exchange#118](https://github.com/dsx-ai-factory/dsx-exchange/issues/118).
