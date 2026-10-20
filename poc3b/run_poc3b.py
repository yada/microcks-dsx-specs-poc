#!/usr/bin/env python3
"""PoC 3b (stage 1): replay infra-controller's spec-drift fix as a Microcks REST conformance test.

PR #5459 ("Resolve differences between REST API models & OpenAPI schema", still open
and force-pushed, so none of its commits can be pinned) fixes spec defects found by a
manual audit. One of them: `SkuComponents.tpm` was documented as an array while the
server returns a single object. The pre-fix spec is the real one on `main` just before
the PR (BASE_COMMIT). The post-fix spec is that same spec with only the tpm change
applied by `apply_tpm_fix()`: a reconstruction of that one defect, not NVIDIA's commit.
This script serves a stub backend that returns the real wire shape (tpm as an object),
then asks Microcks' OpenAPITestRunner (OPEN_API_SCHEMA) to check `GET /sku/{skuId}`
against both specs. Once #5459 merges, use its merge commit and drop apply_tpm_fix().

The backend is a stub, not a real rest-api: it proves the runner catches this class
of drift, not that the real server conforms. Stage 2 (run_stage2.py) runs the same
runner against a real local rest-api.
"""
import argparse
import copy
import json
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import yaml

BASE_COMMIT = "d4cc7e1c2"  # on main, parent of the first #5459 commit
SPEC_PATH = "rest-api/openapi/spec.yaml"
SKU_PATH = "/v2/org/{org}/nico/sku/{skuId}"
OPERATION = "GET " + SKU_PATH
TITLE = "NICo SKU drift replay"
ORG, SKU_ID = "test-org-1", "lenovo.sr650v2.cpu.1"


def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def load_spec(repo, ref):
    return yaml.safe_load(sh(["git", "-C", repo, "show", f"{ref}:{SPEC_PATH}"]))


def apply_tpm_fix(spec):
    """Reconstruction of the #5459 tpm change: array of SkuTpm -> single SkuTpm."""
    spec = copy.deepcopy(spec)
    tpm = spec["components"]["schemas"]["SkuComponents"]["properties"]["tpm"]
    assert tpm["type"] == "array", "base spec no longer has the tpm drift"
    spec["components"]["schemas"]["SkuComponents"]["properties"]["tpm"] = {
        "$ref": "#/components/schemas/SkuTpm", "description": "TPM component"}
    return spec


def prepare(spec, version):
    """Keep only the SKU operation under test (schemas untouched). The request
    examples Microcks needs come from a separate APIExamples file, see api_examples()."""
    spec = copy.deepcopy(spec)
    item = spec["paths"][SKU_PATH]
    spec["paths"] = {SKU_PATH: item}
    for status in [s for s in item["get"]["responses"] if s != "200"]:
        del item["get"]["responses"][status]
    spec["info"]["title"] = TITLE
    spec["info"]["version"] = version
    return spec


def api_examples(version):
    """Microcks APIExamples (secondary artifact): the request the test runner sends."""
    return {"apiVersion": "mocks.microcks.io/v1alpha1", "kind": "APIExamples",
            "metadata": {"name": TITLE, "version": version},
            "operations": {OPERATION: {"poc3b-sku": {
                "request": {"parameters": {"org": ORG, "skuId": SKU_ID}},
                "response": {"status": "200", "mediaType": "application/json", "body": {}}}}}}


def wire_payload(post_spec):
    """What the server really sends: the documented example, with tpm as a single object."""
    resp = post_spec["paths"][SKU_PATH]["get"]["responses"]["200"]
    example = copy.deepcopy(resp["content"]["application/json"]["examples"]["example-1"]["value"])
    example["components"]["tpm"] = {"vendor": "STMicroelectronics", "version": "2.0"}
    return example


class Stub(BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self):
        ok = self.path == f"/v2/org/{ORG}/nico/sku/{SKU_ID}"
        body = self.payload if ok else b'{"error":"not found"}'
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Microcks:
    def __init__(self, api, keycloak=None):
        self.api = api.rstrip("/")
        self.token = None
        if keycloak:
            form = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": "microcks-serviceaccount-test",
                "client_secret": "1b4db7eb-4057-5ddf-91e0-36dec72071f5",
            }).encode()
            req = urllib.request.Request(
                f"{keycloak}/realms/microcks/protocol/openid-connect/token", data=form)
            self.token = json.load(urllib.request.urlopen(req))["access_token"]

    def call(self, method, path, body=None, headers=None):
        h = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        h.update(headers or {})
        req = urllib.request.Request(self.api + path, data=body, method=method, headers=h)
        return json.loads(urllib.request.urlopen(req).read())

    def upload(self, spec_path, main=True):
        boundary = "----poc3b"
        content = Path(spec_path).read_bytes()
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{Path(spec_path).name}"\r\n'
            f"Content-Type: application/x-yaml\r\n\r\n").encode() + content + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="mainArtifact"\r\n\r\n{str(main).lower()}\r\n'
            f"--{boundary}--\r\n").encode()
        h = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.api + "/api/artifact/upload", data=body, method="POST", headers=h)
        return urllib.request.urlopen(req).read().decode()

    def service_id(self, name, version):
        for s in self.call("GET", "/api/services?page=0&size=200"):
            if s["name"] == name and s["version"] == version:
                return s["id"]
        raise RuntimeError(f"service {name}:{version} not found")

    def run_test(self, service_id, endpoint):
        body = json.dumps({
            "serviceId": service_id, "testEndpoint": endpoint, "runnerType": "OPEN_API_SCHEMA",
            "timeout": 20000, "filteredOperations": [OPERATION],
        }).encode()
        test = self.call("POST", "/api/tests", body, {"Content-Type": "application/json"})
        for _ in range(30):
            time.sleep(2)
            test = self.call("GET", f"/api/tests/{test['id']}")
            if not test["inProgress"]:
                return test
        raise RuntimeError("test did not finish in 60s")


def offline_errors(spec, payload):
    """Independent check: validate the payload against the spec's Sku schema with jsonschema."""
    schema = {"$ref": "#/components/schemas/Sku", "components": spec["components"]}
    validator = jsonschema.Draft202012Validator(schema)
    return ["/".join(str(x) for x in e.absolute_path) + ": " + e.message[:80] for e in validator.iter_errors(payload)]


def messages(test):
    out = []
    for case in test.get("testCaseResults", []):
        for step in case.get("testStepResults", []):
            if step.get("message"):
                out.append(step["message"].replace("\n", " "))
    return out


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--infra-controller", default=str(here.parent.parent / "infra-controller"))
    ap.add_argument("--microcks", default="http://localhost:8080")
    ap.add_argument("--keycloak", default=None,
                    help="Keycloak base URL, only for the secured stack (microcks/full)")
    ap.add_argument("--stub-port", type=int, default=8899)
    ap.add_argument("--stub-host", default="host.docker.internal",
                    help="how the Microcks container reaches this machine")
    a = ap.parse_args()

    pre = load_spec(a.infra_controller, BASE_COMMIT)
    post = apply_tpm_fix(pre)
    Stub.payload = json.dumps(wire_payload(post)).encode()
    srv = ThreadingHTTPServer(("0.0.0.0", a.stub_port), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    endpoint = f"http://{a.stub_host}:{a.stub_port}"

    work = here / "work"
    work.mkdir(exist_ok=True)
    mk = Microcks(a.microcks, a.keycloak)
    results = {}
    for label, spec in (("pre-fix", pre), ("post-fix", post)):
        version = f"{label}-5459"
        path = work / f"sku-{label}.yaml"
        path.write_text(yaml.safe_dump(prepare(spec, version), sort_keys=False))
        mk.upload(path)
        ex = work / f"sku-{label}.apiexamples.yaml"
        ex.write_text(yaml.safe_dump(api_examples(version), sort_keys=False))
        mk.upload(ex, main=False)
        test = mk.run_test(mk.service_id(TITLE, version), endpoint)
        offline = offline_errors(spec, json.loads(Stub.payload))
        results[label] = {"success": test["success"], "messages": messages(test), "offline_errors": offline}
        print(f"{label}: test.success={test['success']}  offline jsonschema errors={len(offline)}")
        for m in results[label]["messages"]:
            print("   microcks:", m[:300])
        for m in offline:
            print("   jsonschema:", m)

    checks = [
        ("stub serves the real wire shape (tpm is an object)", isinstance(json.loads(Stub.payload)["components"]["tpm"], dict)),
        ("test fails on the pre-fix spec (tpm documented as array)", not results["pre-fix"]["success"]),
        ("offline jsonschema attributes the pre-fix failure to components/tpm",
         any(m.startswith("components/tpm") for m in results["pre-fix"]["offline_errors"])),
        ("test passes on the post-fix spec", results["post-fix"]["success"]),
        ("Microcks verdicts match offline jsonschema in both",
         all(r["success"] == (not r["offline_errors"]) for r in results.values())),
    ]
    print("\n=== Checks")
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    evidence = here / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "results.json").write_text(json.dumps(
        {"base_commit": BASE_COMMIT, "post_fix": "reconstructed tpm change (see run_poc3b.py)", "operation": OPERATION, "results": results,
         "checks": {n: ok for n, ok in checks}}, indent=2) + "\n")
    srv.shutdown()
    sys.exit(0 if all(ok for _, ok in checks) else 1)


if __name__ == "__main__":
    main()
