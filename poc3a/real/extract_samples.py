#!/usr/bin/env python3
"""Harvest candidate ManagedHostState JSON snippets that NVIDIA's own tests and docs
contain in the infra-controller checkout. Not all are valid for the current code
(some are deliberately bogus or stale); dump_states.rs keeps only those the real
serde types accept. Usage: extract_samples.py <infra-controller-dir> <out.json>
"""
import json
import re
import subprocess
import sys

TOP = {"dpudiscoveringstate", "dpuinit", "hostinit", "validation", "ready", "decommissioning", "reset",
       "bootconfiguring", "maintenance", "assigned", "waitingforcleanup", "forcedeletion", "created",
       "configureastra", "failed", "dpureprovision", "hostreprovision"}
DPU = "fm100ds7blqjsadm2uuh3qqbf1h7k8pmf47um6v9uckrg7l03po8mhqgvng"  # a DPU id used in NVIDIA's own tests

repo, out = sys.argv[1], sys.argv[2]
files = subprocess.run(["git", "-C", repo, "ls-files", "*.rs", "*.sql", "*.json", "*.md"],
                       capture_output=True, text=True, check=True).stdout.split()
found = set()
for f in files:
    try:
        s = open(f"{repo}/{f}").read()
    except (OSError, UnicodeDecodeError):
        continue
    for m in re.finditer(r'\{\s*\\?"state\\?"\s*:\s*\\?"([a-z]+)\\?"', s):
        if m.group(1) not in TOP:
            continue
        depth, j = 0, m.start()
        while j < len(s):
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                break
            j += 1
        t = s[m.start():j + 1].replace('\\"', '"').replace("&dpu_machine_id_string", f'"{DPU}"')
        t = re.sub(r'"?\{\s*dpu_machine_id_string\s*\}"?', f'"{DPU}"', t)
        try:
            found.add(json.dumps(json.loads(t)))
        except ValueError:
            pass
json.dump(sorted(found), open(out, "w"))
print(f"{len(found)} candidate snippets -> {out}")
