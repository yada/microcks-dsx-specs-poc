#!/usr/bin/env python3
"""PoC 3b (stage 2): run Microcks' OPEN_API_SCHEMA conformance test against a REAL rest-api.

Target: infra-controller/rest-api started locally (see docs), empty database, no Core,
JWT issuer pointing at a local JWKS. Every `GET /v2/org/{org}/nico/...` collection
endpoint that has only the `org` path parameter is replayed with a bearer token.
Each operation is also called directly and its body validated with jsonschema, so
Microcks' verdict is cross-checked independently.

Limit: an empty database returns empty lists, so this checks envelope/status/headers
conformance, not payload shapes such as SKU `components.tpm`.
"""
import argparse
import copy
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_poc3b import Microcks, SPEC_PATH, sh  # noqa: E402

TITLE = "NICo REST real-server conformance"


def collection_paths(spec):
    return [p for p, i in spec["paths"].items()
            if "get" in i and p.replace("{org}", "") .count("{") == 0]


def prepare(spec, version):
    """The spec is used as-is (all 164 paths); only title/version change, so this run
    does not collide with other imports of the same spec in a shared Microcks."""
    spec = copy.deepcopy(spec)
    spec["info"]["title"] = TITLE
    spec["info"]["version"] = version
    return spec


def api_examples(version, paths):
    """APIExamples (secondary artifact): one request per operation, `org` only.
    The response body is a placeholder; the verdict comes from the live response."""
    ops = {f"GET {p}": {"poc3b-org": {
        "request": {"parameters": {"org": "test-org-1"}},
        "response": {"status": "200", "mediaType": "application/json", "body": {}}}} for p in paths}
    return {"apiVersion": "mocks.microcks.io/v1alpha1", "kind": "APIExamples",
            "metadata": {"name": TITLE, "version": version}, "operations": ops}


def direct(base, path, token):
    req = urllib.request.Request(base + path.replace("{org}", "test-org-1"),
                                 headers={"Authorization": "Bearer " + token})
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--infra-controller", default=str(here.parent.parent / "infra-controller"))
    ap.add_argument("--microcks", default="http://localhost:8080")
    ap.add_argument("--api", default="http://localhost:8388", help="rest-api as seen from this machine")
    ap.add_argument("--api-from-microcks", default="http://host.docker.internal:8388")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--keycloak", default=None)
    ap.add_argument("--out", default=str(here / "evidence" / "stage2.json"))
    a = ap.parse_args()
    token = Path(a.token_file).read_text().strip()

    spec = yaml.safe_load(sh(["git", "-C", a.infra_controller, "show", f"HEAD:{SPEC_PATH}"]))
    commit = sh(["git", "-C", a.infra_controller, "rev-parse", "--short", "HEAD"]).strip()

    ok_paths, skipped = [], {}
    for p in collection_paths(spec):
        status, body = direct(a.api, p, token)
        if status == 200:
            ok_paths.append(p)
        else:
            skipped[p] = status
    print(f"{len(ok_paths)} endpoints answer 200 on the real API; {len(skipped)} skipped "
          f"(HTTP {sorted(set(skipped.values()))}: required query params / not allowed for this token)")

    work = here / "work"
    work.mkdir(exist_ok=True)
    mk = Microcks(a.microcks, a.keycloak)

    def run(prepared, version):
        f = work / f"{version}.yaml"
        f.write_text(yaml.safe_dump(prepared, sort_keys=False))
        mk.upload(f)
        ex = work / f"{version}.apiexamples.yaml"
        ex.write_text(yaml.safe_dump(api_examples(version, ok_paths), sort_keys=False))
        mk.upload(ex, main=False)
        body = json.dumps({
            "serviceId": mk.service_id(TITLE, version), "testEndpoint": a.api_from_microcks,
            "runnerType": "OPEN_API_SCHEMA", "timeout": 20000,
            "filteredOperations": [f"GET {p}" for p in ok_paths],
            "operationsHeaders": {"globals": [{"name": "Authorization", "values": "Bearer " + token}]},
        }).encode()
        test = mk.call("POST", "/api/tests", body, {"Content-Type": "application/json"})
        for _ in range(120):
            time.sleep(2)
            test = mk.call("GET", f"/api/tests/{test['id']}")
            if not test["inProgress"]:
                break
        per_op = {}
        for c in test.get("testCaseResults", []):
            steps = c.get("testStepResults", [])
            per_op[c["operationName"]] = {"success": c["success"], "messages": [
                s["message"].replace("\n", " ")[:200] for s in steps if s.get("message")]}
        return test, per_op

    test, per_op = run(prepare(spec, f"real-{commit}"), f"real-{commit}")
    failed = {k: v for k, v in per_op.items() if not v["success"]}
    # negative control: document /metadata `version` as an integer while the server returns a string
    drifted = prepare(spec, f"drifted-{commit}")
    drifted["components"]["schemas"]["Metadata"]["properties"]["version"]["type"] = "integer"
    _, drift_ops = run(drifted, f"drifted-{commit}")
    drift_failed = sorted(k for k, v in drift_ops.items() if not v["success"])
    print("negative control (Metadata.version documented as integer): failed operations =", drift_failed)
    print(f"Microcks: success={test['success']}  operations={len(per_op)}  failed={len(failed)}")
    for k, v in failed.items():
        print("  FAIL", k, v["messages"][:1])

    checks = [
        ("real rest-api rejects unauthenticated calls (401)",
         urllib.request.urlopen is not None and _status(a.api + "/v2/org/test-org-1/nico/metadata") == 401),
        ("Microcks exercised every endpoint that answers 200", len(ok_paths) > 0 and len(per_op) == len(ok_paths)),
        ("Microcks passes all operations against the real server", test["success"] and not failed),
        ("negative control: Microcks fails exactly /metadata on a deliberately drifted spec",
         drift_failed == ["GET /v2/org/{org}/nico/metadata"]),
    ]
    print("\n=== Checks")
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    Path(a.out).write_text(json.dumps({
        "infra_controller_commit": commit, "endpoints_tested": len(per_op),
        "endpoints_skipped": skipped, "failed": failed,
        "checks": {n: ok for n, ok in checks}}, indent=2) + "\n")
    sys.exit(0 if all(ok for _, ok in checks) else 1)


def _status(url):
    try:
        return urllib.request.urlopen(url, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code


if __name__ == "__main__":
    main()
