#!/usr/bin/env python3
"""Turn dump_states output (one JSON message per line) into a Microcks APIExamples file.
Usage: build_fixture.py <messages.jsonl> <out.apiexamples.yaml>
"""
import json
import re
import sys

import yaml

rows = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
seen, examples = set(), {}
for p in rows:
    key = json.dumps(p, sort_keys=True)
    if key in seen:
        continue
    seen.add(key)
    st = p["managed_host_state"]
    parts = [st["state"]] + [str(v["state"]) if isinstance(v, dict) and "state" in v else str(v)
                             for k, v in st.items() if k != "state" and isinstance(v, (str, dict)) and k.endswith("_state")]
    slug = re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-")[:48]
    examples[f"{len(examples) + 1:02d}-{slug}"] = {"eventMessage": {"payload": p}}
doc = {"apiVersion": "mocks.microcks.io/v1alpha1", "kind": "APIExamples",
       "metadata": {"name": "NICo Managed Host State Event Bus", "version": "1.0.0"},
       "operations": {"RECEIVE subscribeManagedHostStateChange": examples}}
header = ("# Messages serialized by infra-controller's real ManagedHostState serde types (see poc3a/real/).\n"
          "# machine_id is a zero test id and timestamp is fixed; the state bodies are what NICo emits.\n"
          "# DPU ids are the placeholder id from NVIDIA's own tests (see poc3a/real/extract_samples.py), not a real machine.\n")
open(sys.argv[2], "w").write(header + yaml.safe_dump(doc, sort_keys=False, width=200))
print(f"{len(examples)} unique messages -> {sys.argv[2]}")
