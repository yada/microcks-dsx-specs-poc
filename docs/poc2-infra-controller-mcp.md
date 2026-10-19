# PoC 2 — infra-controller's OpenAPI spec → Microcks mock → reShapr MCP tool

**Goal:** chain Microcks and reShapr together — mock a real NICo REST
endpoint from [`infra-controller`](https://github.com/dsx-ai-factory/infra-controller)'s
own OpenAPI contract (`rest-api/openapi/spec.yaml`), then expose that mock as
a callable MCP tool, the way an AI agent would consume it.

## Versions used

| Component | Version |
|---|---|
| Microcks (uber) | `quay.io/microcks/microcks-uber:1.15.0` (same stack as PoC 1) |
| reShapr control plane | `registry.reshapr.io/reshapr/reshapr-ctrl:1.1.0` |
| reShapr gateway/proxy | `registry.reshapr.io/reshapr/reshapr-proxy:1.1.0` |
| reShapr CLI | `@reshapr/reshapr-cli@1.1.0` |
| reShapr database | PostgreSQL 17, fresh/empty |

Spec tested: `infra-controller` commit `02b92f18f` (2026-10-17).

> An NPE bug affecting any OpenAPI spec that declares path parameters at the
> path-item level (infra-controller's own convention, used on all 164 of its
> paths) was fixed in
> [reshaprio/reshapr#545](https://github.com/reshaprio/reshapr/issues/545)
> and ships in reShapr 1.1.0 (released 2026-10-15).

## 1. Bring up Microcks

Same stack as [PoC 1](poc1-dsx-exchange-mqtt.md) —
`docker compose -f microcks/docker-compose.yml up -d` (Microcks uber, no Keycloak). The MQTT/Mosquitto pieces aren't needed for this PoC but don't
hurt to leave running.

## 2. Bring up reShapr

```sh
docker compose -f reshapr/docker-compose.yml up -d
npm install -g @reshapr/reshapr-cli@1.1.0
```

**Wait until the gateway reports `healthy`** (`docker ps`, roughly 30 seconds)
before importing: importing earlier prints "No active exposition found" and
the MCP endpoint is not served.

Then log in:

```sh
reshapr login -s http://localhost:5555 -u admin -p password
```

## 3. Import the spec and its examples into Microcks

The spec imports **unmodified**. The request example Microcks needs for the
`org` path parameter comes from an
[APIExamples](https://microcks.io/documentation/references/examples/) file,
imported as a secondary artifact (details in
[`../patches/infra-controller-spec.yaml.patch.md`](../patches/infra-controller-spec.yaml.patch.md)):

```sh
curl -s -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@/path/to/infra-controller/rest-api/openapi/spec.yaml;type=application/x-yaml" \
  -F "mainArtifact=true"

curl -s -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@examples/infra-controller-rest.apiexamples.yaml;type=application/x-yaml" \
  -F "mainArtifact=false"
```

(No token: the default uber stack runs without authentication. On the
secured `microcks/full` stack, add the `Authorization: Bearer` header as shown
in [PoC 1](poc1-dsx-exchange-mqtt.md#2-authentication).)

Sanity-check the mock directly:

```sh
curl -s "http://localhost:8080/rest/NVIDIA+Infra+Controller+REST+API/2.0.0/v2/org/test-org-1/nico/metadata"
# {"version":"0.1.24","buildTime":"2019-08-24T14:15:22Z"}
```

## 4. Import into reShapr, pointing at the Microcks mock

```sh
reshapr import -f /path/to/infra-controller/rest-api/openapi/spec.yaml \
  --be "http://host.docker.internal:8080/rest/NVIDIA+Infra+Controller+REST+API/2.0.0"
```

(`host.docker.internal` lets the reShapr gateway container reach Microcks on
the host; adjust if you've put both stacks on the same Docker network
instead.) This prints an MCP endpoint, typically:

```
localhost:7777/mcp/reshapr/nvidia-infra-controller-rest-api-2-0-0-default
```

## 5. Drive it as an MCP client would

```sh
URL="http://localhost:7777/mcp/reshapr/nvidia-infra-controller-rest-api-2-0-0-default"

# initialize — capture the MCP-Session-Id response header
curl -s -i -X POST "$URL" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"repro","version":"1.0"}}}'

# tools/list (use the session id from above)
curl -s -X POST "$URL" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "MCP-Session-Id: <session>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# tools/call
curl -s -X POST "$URL" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "MCP-Session-Id: <session>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_v2_org_org_nico_metadata","arguments":{"org":"test-org-1"}}}'
```

### Expected output

`tools/list` includes:

```json
{
  "name": "get_v2_org_org_nico_metadata",
  "description": "Retrieve system metadata providing information about the API server",
  "inputSchema": {
    "type": "object",
    "properties": { "org": { "description": "Name of the Org", "type": "string" } },
    "required": ["org"],
    "additionalProperties": false
  }
}
```

`tools/call` returns:

```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"version\":\"0.1.24\",\"buildTime\":\"2019-08-24T14:15:22Z\"}"}],"isError":false}}
```

That text is the Microcks mock's payload, round-tripped through reShapr's
gateway and handed back in MCP's own response envelope.

## What this proves

- Microcks mocks infra-controller's real OpenAPI spec (164 paths, 263
  operations) with no edit to the spec; one APIExamples file provides the
  `org` request example ([notes](../patches/infra-controller-spec.yaml.patch.md)).
- reShapr turns the spec into 263 MCP tools. The one endpoint with an APIExamples entry
  (`get_v2_org_org_nico_metadata`) is backed by a real mock and callable — the full chain
  **spec → Microcks mock → reShapr MCP tool → MCP client call** works
  end-to-end against infra-controller's actual API shape.

## What this doesn't prove (yet)

Microcks' `OpenAPITestRunner` can also run this same contract as a
conformance test against a *live* `rest-api` instance, catching drift
automatically — that run isn't exercised here, only mocking is. It's
proposed as follow-up work in
[dsx-ai-factory/infra-controller#7253](https://github.com/dsx-ai-factory/infra-controller/issues/7253).
