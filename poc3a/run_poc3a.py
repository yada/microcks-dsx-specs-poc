#!/usr/bin/env python3
"""PoC 3a: replay dsx-exchange PR #117 as a Microcks AsyncAPI conformance test.

Publishes one retained MQTT message per NICo managed-host state, then asks
Microcks (ASYNC_API_SCHEMA runner) to validate the live broker traffic against
nico.yaml as it was before and after #117. Also cross-checks every Microcks
verdict with an offline jsonschema validation.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import jsonschema

import gen_payloads as gp

OPERATION = "SEND publishManagedHostStateChange"
TOPIC_FMT = "NICO/v1/machine/{}/state"
TOPIC_FILTER = "NICO/v1/machine/+/state"


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def git_show(repo, ref, path):
    return sh(["git", "-C", repo, "show", f"{ref}:{path}"])


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

    def call(self, method, path, body=None, headers=None, raw=False):
        h = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        h.update(headers or {})
        req = urllib.request.Request(self.api + path, data=body, method=method, headers=h)
        data = urllib.request.urlopen(req).read()
        return data if raw else json.loads(data)

    def upload(self, spec_path, main=True):
        boundary = "----poc3a"
        content = Path(spec_path).read_bytes()
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{Path(spec_path).name}"\r\n'
            f"Content-Type: application/x-yaml\r\n\r\n").encode() + content + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="mainArtifact"\r\n\r\n{str(main).lower()}\r\n'
            f"--{boundary}--\r\n").encode()
        return self.call("POST", "/api/artifact/upload", body,
                         {"Content-Type": f"multipart/form-data; boundary={boundary}"}, raw=True).decode()

    def run_test(self, service_id, endpoint, timeout_ms):
        body = json.dumps({
            "serviceId": service_id, "testEndpoint": endpoint,
            "runnerType": "ASYNC_API_SCHEMA", "timeout": timeout_ms,
            "filteredOperations": [OPERATION],
        }).encode()
        test = self.call("POST", "/api/tests", body, {"Content-Type": "application/json"})
        for _ in range(60):
            time.sleep(2)
            test = self.call("GET", f"/api/tests/{test['id']}")
            if not test["inProgress"]:
                return test
        raise RuntimeError("test did not finish in 120s")

    def events(self, test):
        case = urllib.parse.quote(f"{test['id']}-{test['testNumber']}-{OPERATION}")
        return self.call("GET", f"/api/tests/{test['id']}/events/{case}")


class Broker:
    def __init__(self, container):
        self.c = container

    def pub(self, topic, payload=None):
        cmd = ["docker", "exec", self.c, "mosquitto_pub", "-r", "-t", topic]
        cmd += ["-m", json.dumps(payload, separators=(",", ":"))] if payload is not None else ["-n"]
        sh(cmd)

    def clear_retained(self):
        out = subprocess.run(
            ["docker", "exec", self.c, "mosquitto_sub", "-t", TOPIC_FILTER, "-v",
             "--retained-only", "-W", "3"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            self.pub(line.split(" ", 1)[0])

    def publish_all(self, messages):
        self.clear_retained()
        for label, payload in messages.items():
            self.pub(TOPIC_FMT.format(label), payload)


def offline_validator(spec):
    schema = {"$ref": "#/components/messages/ManagedHostStateChangeMessage/payload",
              "components": spec["components"]}
    return jsonschema.Draft7Validator(schema)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def scenario(mk, broker, name, spec_path, spec, service_id, messages, timeout_ms):
    print(f"\n=== {name}")
    print(f"  upload {Path(spec_path).name}: {mk.upload(spec_path).strip()}")
    broker.publish_all(messages)
    time.sleep(1)
    test = mk.run_test(service_id, f"mqtt://mosquitto:1883/{TOPIC_FILTER}", timeout_ms)
    by_content = {canon(p): label for label, p in messages.items()}
    steps = {s["eventMessageName"]: s for s in test["testCaseResults"][0]["testStepResults"]}
    validator = offline_validator(spec)
    rows = []
    for ev in mk.events(test):
        msg = ev["eventMessage"]
        label = by_content.get(canon(json.loads(msg["content"])), "?")
        step = steps[msg["name"]]
        offline = not list(validator.iter_errors(json.loads(msg["content"])))
        rows.append({"message": label, "microcks_pass": step["success"],
                     "offline_pass": offline,
                     "error": step.get("message", "").replace("\\n", " | ")})
    rows.sort(key=lambda r: r["message"])
    passed = sum(r["microcks_pass"] for r in rows)
    agree = all(r["microcks_pass"] == r["offline_pass"] for r in rows)
    print(f"  received={len(rows)}/{len(messages)}  pass={passed}  fail={len(rows) - passed}"
          f"  test.success={test['success']}  offline-agreement={agree}")
    for r in rows:
        if not r["microcks_pass"]:
            print(f"    FAIL {r['message']:<28} {r['error'][:110]}")
    return {"name": name, "test_id": test["id"], "success": test["success"],
            "received": len(rows), "sent": len(messages), "rows": rows, "agree": agree}


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent
    ap.add_argument("--dsx-exchange", default=str(root.parent.parent / "dsx-exchange"))
    ap.add_argument("--merge-commit", default="4e8b71f", help="dsx-exchange commit of PR #117")
    ap.add_argument("--microcks", default="http://localhost:8080")
    ap.add_argument("--keycloak", default=None,
                    help="Keycloak base URL, only for the secured stack (microcks/full), e.g. http://localhost:18080")
    ap.add_argument("--mosquitto", default="microcks-poc-mosquitto")
    ap.add_argument("--timeout-ms", type=int, default=10000)
    ap.add_argument("--out", default=str(root / "evidence"))
    a = ap.parse_args()

    work = root / "work"
    work.mkdir(exist_ok=True)
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    path = "schemas/asyncapi/nico/nico.yaml"
    full = sh(["git", "-C", a.dsx_exchange, "rev-parse", a.merge_commit]).strip()
    before = sh(["git", "-C", a.dsx_exchange, "rev-parse", f"{full}^"]).strip()
    specs = {}
    for tag, ref in (("pre-117", before), ("post-117", full)):
        text = git_show(a.dsx_exchange, ref, path)
        # Only info.version changes, so both revisions can coexist as distinct Microcks services.
        text = text.replace("\n  version: 1.0.0", f"\n  version: {tag}", 1)
        p = work / f"nico-{tag}.yaml"
        p.write_text(text)
        specs[tag] = (p, gp.load_spec(p), ref)
        print(f"{tag}: dsx-exchange {ref[:9]}  states={len(gp.state_list(specs[tag][1]))}")

    pre_states, post_states = (gp.state_list(specs[t][1]) for t in ("pre-117", "post-117"))
    added = [s for s in post_states if s not in pre_states]
    print(f"states added by #117 ({len(added)}): {', '.join(added)}")

    valid = gp.valid_payloads(specs["post-117"][1])
    invalid = gp.invalid_payloads(valid)
    title = specs["post-117"][1]["info"]["title"]
    mk, broker = Microcks(a.microcks, a.keycloak), Broker(a.mosquitto)

    results = [
        scenario(mk, broker, "A. pre-#117 spec vs valid NICo traffic (drift)", *specs["pre-117"][:2],
                 f"{title}:pre-117", valid, a.timeout_ms),
        scenario(mk, broker, "B. post-#117 spec vs the same traffic", *specs["post-117"][:2],
                 f"{title}:post-117", valid, a.timeout_ms),
        scenario(mk, broker, "C. post-#117 spec vs valid + 3 deliberately broken messages",
                 *specs["post-117"][:2], f"{title}:post-117", {**valid, **invalid}, a.timeout_ms),
    ]
    broker.clear_retained()

    A, B, C = results
    failed_a = {r["message"] for r in A["rows"] if not r["microcks_pass"]}
    failed_c = {r["message"] for r in C["rows"] if not r["microcks_pass"]}
    checks = [
        ("A: every message was received by the runner", A["received"] == A["sent"]),
        ("A: test fails on pre-#117 spec", not A["success"]),
        ("A: all 11 states added by #117 are rejected", set(added) <= failed_a),
        ("B: test passes on post-#117 spec, all messages valid", B["success"] and B["received"] == B["sent"]),
        ("C: exactly the 3 broken messages fail", failed_c == set(invalid)),
        ("Microcks verdicts match offline jsonschema in A, B, C", all(r["agree"] for r in results)),
    ]
    print("\n=== Checks")
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    evidence = {"dsx_exchange_before": before, "dsx_exchange_after": full,
                "states_pre": len(pre_states), "states_post": len(post_states),
                "states_added": added, "scenarios": results,
                "checks": {label: ok for label, ok in checks}}
    (out / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"\nevidence written to {out.relative_to(Path.cwd()) / 'results.json' if out.is_relative_to(Path.cwd()) else out / 'results.json'}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
