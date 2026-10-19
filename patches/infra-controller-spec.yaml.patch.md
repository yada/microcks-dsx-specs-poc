# Notes — `infra-controller/rest-api/openapi/spec.yaml`

This repo does **not** vendor NVIDIA's `spec.yaml` (1.3 MB, 164 paths). The
file already has a response example on every schema and imports into Microcks
**unmodified**. Verified against `infra-controller` commits `02b92f18f` and
`ee29e315f`.

## No edit needed: use the APIExamples file

For a Microcks mock to answer, a request example must exist for the shared
`org` path parameter. Instead of editing the spec, import
[`../examples/infra-controller-rest.apiexamples.yaml`](../examples/infra-controller-rest.apiexamples.yaml)
as a **secondary** artifact after the spec
([APIExamples reference](https://microcks.io/documentation/references/examples/)).
It maps `org: test-org-1` to the metadata response for
`GET /v2/org/{org}/nico/metadata`.

This replaces two edits this repo used to describe:

1. An `examples:` block on the `org` parameter. Replaced by the APIExamples file.
2. Removing the shared `401` response from that operation. That was a
   workaround for [microcks/microcks#2373](https://github.com/microcks/microcks/issues/2373):
   the `200` and the shared `UnauthorizedError` both named their example
   `example-1`, got the same dispatch key, and the mock flipped between 200
   and 401. With an APIExamples example named differently, 30 of 30 requests
   returned 200 over 3 wipes of Microcks 1.15.0. We did not establish why;
   #2373's flip is non-deterministic, so this is an observation, not a fix of
   the bug.

If you would rather change the spec, adding `examples: {example-1: {value: test-org-1}}`
to the `org` parameter (declared at path-item level, as for all 164 paths)
works too, but then the #2373 collision applies again.

> **Note on path-item-level `parameters:`:** this spec declares path
> parameters as a sibling of the HTTP verb, shared by every verb on the path
> (legal OpenAPI 3.x). A reShapr build older than the fix in
> [reshaprio/reshapr#545](https://github.com/reshaprio/reshapr/issues/545)
> did not read them; this matters if you reproduce PoC 2 on an older build.
