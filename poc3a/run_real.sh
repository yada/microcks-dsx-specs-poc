#!/usr/bin/env bash
# PoC 3a (real fixtures): import nico.yaml and the NICo-serialised APIExamples
# (examples/nico-real.apiexamples.yaml) into Microcks; its minion publishes them and an
# ASYNC_API_SCHEMA test validates them against the current dsx-exchange nico.yaml. Needs the default stack and a ../dsx-exchange checkout.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv; .venv/bin/python -m pip install --quiet pyyaml jsonschema; }
curl -sf http://localhost:8080/api/keycloak/config >/dev/null \
  || { echo "Microcks is not reachable on :8080 - start the stack first" >&2; exit 2; }
exec .venv/bin/python run_real.py "$@"
