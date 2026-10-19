# PoC 3b (stages 1 and 2) — replaying infra-controller's spec-drift fix as a Microcks REST conformance test

**Question:** [infra-controller#5459](https://github.com/dsx-ai-factory/infra-controller/issues/5459)
fixed 14 places where `rest-api/openapi/spec.yaml` disagreed with what the
REST API actually serves, found by a manual field-by-field audit. Would
Microcks' OpenAPI test runner have caught one of them automatically?

**Answer (stage 1, stub backend):** yes, for the one drift replayed here. One
of the 14 defects: `SkuComponents.tpm` was documented as an **array** while
the server returns a single **object**. Against the spec from before the fix,
Microcks fails the test; against the same spec with that one change applied, it passes. Same
traffic, same runner, no custom validation code in the runner's path.

## Stage 2 — the same runner against a real `rest-api`

Stage 2 starts the real `infra-controller/rest-api` binary locally (Postgres
17, Temporal 1.9.1 dev server, a throw-away RSA key and JWKS server for a
custom JWT issuer; no Kind, no Core, no registered site) and points Microcks'
`OPEN_API_SCHEMA` runner at it with a bearer token.

```sh
poc3b/stage2.sh         # up + test + down, a few minutes; needs Docker, Go, the Microcks stack
```

Result, `infra-controller` at `ee29e315f` (log: `poc3b/evidence/stage2.log`):

- 57 collection `GET` endpoints have only the `org` path parameter. 37 answer
  `200` on the real server with an empty database; 20 answer `400`/`403`
  (required query parameters or a role this token does not have) and are skipped.
- Microcks passes **37 of 37** (status, content type, response schema).
- Without a token the server answers `401`, so the token really is exercised.
- **Negative control:** with `Metadata.version` deliberately documented as an
  integer, Microcks fails exactly `GET /metadata` and nothing else.

What stage 2 does **not** show: the database is empty, so every list is `[]`
and no payload shape (such as `SkuComponents.tpm`) is checked. That needs
registered sites and Core data (the official `make kind-reset` route). So
stage 2 proves the real server's envelope conforms and that the harness works
against it; it does not replay a #5459 drift on the real server.

Harness choices worth knowing (all in `run_stage2.py`): the spec is imported
whole and unmodified apart from `info.title`/`info.version` (so this run does
not collide with other imports of the same spec), and the requests come from a
generated [APIExamples](https://microcks.io/documentation/references/examples/)
secondary artifact (`org: test-org-1` per operation, placeholder response
body) with `filteredOperations` selecting the 37 endpoints. The verdict comes
from validating the live response, not from the placeholder. An earlier
version of this script edited the spec instead (dropped query params, renamed
response examples, removed `401`s); APIExamples made all of that unnecessary.

## Run it (stage 1, stub backend)

```sh
docker compose -f microcks/docker-compose.yml up -d     # wait until healthy
poc3b/run.sh                                            # ~1 minute
```

`run.sh` creates a local virtualenv (`pyyaml`, `jsonschema`) and reads the two
spec revisions straight from your local `infra-controller` checkout with
`git show` (default `../infra-controller`, override with `--infra-controller DIR`).
Nothing in `infra-controller` is modified or vendored.

## What it does

1. Reads `rest-api/openapi/spec.yaml` at `d4cc7e1c2` (on `main`, just before the
   #5459 PR) and derives the post-fix spec by applying only the `tpm` change
   (`apply_tpm_fix()` in `run_poc3b.py`).

   > **Reconstruction, not NVIDIA's commit.** #5459 is still open and its branch
   > has been force-pushed, so its commits cannot be pinned (the original pin,
   > `5eed3849e`, disappeared and broke a fresh clone). The post-fix spec here is
   > our re-application of that one defect's fix. When #5459 merges, this should
   > switch to the merge commit and its parent, and `apply_tpm_fix()` goes away.
2. Keeps only `GET /v2/org/{org}/nico/sku/{skuId}` and sets `info.version`
   to `pre-fix-5459` / `post-fix-5459` so both revisions exist side by side.
   Schemas are untouched. The `org` and `skuId` request values Microcks needs
   come from an APIExamples secondary artifact, not from spec edits.
3. Starts a stub HTTP backend on the host that answers that one request with
   the documented example, except that `components.tpm` is a **single object**,
   which is what #5459 says the server really emits.
4. Runs a Microcks test (`runnerType: OPEN_API_SCHEMA`) against the stub for
   each spec revision and reads the verdict back.
5. Cross-checks both verdicts with an independent offline `jsonschema`
   validation of the same payload, which also names the offending field.

## Results

Microcks 1.15.0, `infra-controller` `d4cc7e1c2` (pre) / reconstructed `tpm` fix (post), run from a fresh blobless clone.
Full output: [`poc3b/evidence/run.log`](../poc3b/evidence/run.log); structured
data: [`poc3b/evidence/results.json`](../poc3b/evidence/results.json).

| Spec | Test | Microcks message | Offline `jsonschema` |
|---|---|---|---|
| pre-fix | ❌ failed | `object found, array expected` | `components/tpm: {...} is not of type 'array'` |
| post-fix | ✅ passed | — | no errors |

All five self-checks pass, including "Microcks verdicts match offline
jsonschema in both". Microcks' own message does not name the field; the
offline check is what pins it to `components/tpm`.

## Limits — read before citing this

- **Stage 1's backend is a stub, not a real `rest-api`.** The payload is the spec's
  own example with `tpm` reshaped to what #5459's description says the server
  returns. This proves the runner catches this class of drift. It does **not**
  show that the real server conforms to today's spec. Stage 2 (above) does
  run against a real `rest-api`, but with an empty database.
- **One drift of the 14, one operation.** The other defects (status enums such
  as `VpcStatus.Configuring`, the unquoted `On` enum value, the shared
  `MachineHealthIssue` schema) are not replayed.
- **Hand-reduced spec.** Only the SKU operation is kept, and its non-200
  responses are dropped, to keep the test focused. The full 164-path spec
  imports as well (PoC 2), but its examples would also need a backend that
  serves each one.
- **Not wired into CI** unless you add it; see the workflow in `.github/`.
