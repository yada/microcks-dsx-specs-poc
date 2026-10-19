#!/usr/bin/env python3
"""PoC 3a (real fixtures): replay messages serialised by infra-controller's real
ManagedHostState types (examples/nico-real.apiexamples.yaml) through Microcks'
AsyncAPI test runner against the current dsx-exchange nico.yaml.

Unlike run_poc3a.py, the payloads are not derived from the schema: they come from
NICo's own serialiser (regenerate with poc3a/real/regenerate.sh). Limits: the set
is the states NVIDIA's tests happen to contain, not every reachable state; machine
ids and timestamps are fixed test values; no live NICo is involved.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import yaml

import gen_payloads as gp
import run_poc3a as p3a


def main():
    root = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsx-exchange", default=str(root.parent.parent / "dsx-exchange"))
    ap.add_argument("--fixture", default=str(root.parent / "examples" / "nico-real.apiexamples.yaml"))
    ap.add_argument("--microcks", default="http://localhost:8080")
    ap.add_argument("--keycloak", default=None)
    ap.add_argument("--timeout-ms", type=int, default=10000)
    ap.add_argument("--out", default=str(root / "evidence" / "real.json"))
    a = ap.parse_args()

    fixture = yaml.safe_load(Path(a.fixture).read_text())
    messages = {name: ex["eventMessage"]["payload"]
                for name, ex in fixture["operations"]["RECEIVE subscribeManagedHostStateChange"].items()}

    path = "schemas/asyncapi/nico/nico.yaml"
    ref = p3a.sh(["git", "-C", a.dsx_exchange, "rev-parse", "HEAD"]).strip()
    ver = "real-fixtures"
    text = p3a.git_show(a.dsx_exchange, ref, path).replace("\n  version: 1.0.0", f"\n  version: {ver}", 1)
    # Microcks' importer defaults to a KAFKA binding; MQTT needs this one-line spec edit (patches/nico.yaml.patch.md).
    marker = "      orchestration, and automation purposes.\n"
    assert text.count(marker) == 1, "nico.yaml changed: update the binding edit"
    text = text.replace(marker, marker + "    bindings:\n      mqtt: {}\n")
    work = root / "work"
    work.mkdir(exist_ok=True)
    spec_path = work / "nico-real-fixtures.yaml"
    spec_path.write_text(text)
    spec = gp.load_spec(spec_path)
    title = spec["info"]["title"]
    ex_path = work / "nico-real-fixtures.apiexamples.yaml"
    fixture["metadata"]["version"] = ver
    ex_path.write_text(yaml.safe_dump(fixture, sort_keys=False, width=200))

    mk = p3a.Microcks(a.microcks, a.keycloak)
    print(f"upload spec: {mk.upload(spec_path).strip()}")
    print(f"upload APIExamples (secondary): {mk.upload(ex_path, main=False).strip()}")
    # Microcks' own minion now publishes every example to the MQTT topic; nothing is published by this script.
    topic = f"{title.replace(' ', '')}-{ver}-NICO/v1/machine/{{machineId}}/state"
    time.sleep(5)
    test = mk.run_test(f"{title}:{ver}", f"mqtt://mosquitto:1883/{topic}", a.timeout_ms)
    by_content = {p3a.canon(pl): name for name, pl in messages.items()}
    steps = {s["eventMessageName"]: s for s in test["testCaseResults"][0]["testStepResults"]}
    validator = p3a.offline_validator(spec)
    seen = {}
    for ev in mk.events(test):
        msg = ev["eventMessage"]
        payload = json.loads(msg["content"])
        name = by_content.get(p3a.canon(payload), "?")
        step = steps[msg["name"]]
        row = {"message": name, "microcks_pass": step["success"],
               "offline_pass": not list(validator.iter_errors(payload)),
               "error": step.get("message", "").replace("\\n", " | ")}
        seen.setdefault(name, row)
    rows = sorted(seen.values(), key=lambda x: x["message"])
    r = {"name": f"nico.yaml @ dsx-exchange {ref[:9]} vs {len(messages)} examples published by Microcks",
         "test_id": test["id"], "success": test["success"], "received": len(rows), "sent": len(messages),
         "rows": rows, "agree": all(x["microcks_pass"] == x["offline_pass"] for x in rows)}
    print(f"\n=== {r['name']}\n  distinct messages seen={len(rows)}/{len(messages)}  "
          f"pass={sum(x['microcks_pass'] for x in rows)}  test.success={test['success']}  offline-agreement={r['agree']}")
    for x in rows:
        if not x["microcks_pass"]:
            print(f"    FAIL {x['message']:<28} {x['error'][:110]}")
    failed = sorted(x["message"] for x in r["rows"] if not x["microcks_pass"])
    checks = [
        ("the runner saw every example Microcks published", r["received"] == r["sent"]),
        ("Microcks verdicts match offline jsonschema", r["agree"]),
    ]
    print("\n=== Checks")
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nresult: {len(messages) - len(failed)} of {len(messages)} real messages conform; "
          f"{len(failed)} do not: {', '.join(failed) or '-'}")
    Path(a.out).write_text(json.dumps({"dsx_exchange": ref, "fixture": Path(a.fixture).name,
                                       "failed": failed, "scenario": r,
                                       "checks": {l: ok for l, ok in checks}}, indent=2) + "\n")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
