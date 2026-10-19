#!/usr/bin/env bash
# PoC 3a: replay dsx-exchange PR #117 as a Microcks AsyncAPI conformance test.
# Needs the Microcks stack running (docker compose -f microcks/docker-compose.yml up -d)
# and a local checkout of dsx-exchange (default: ../../dsx-exchange, override with --dsx-exchange).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet pyyaml jsonschema
fi

curl -sf http://localhost:8080/api/keycloak/config >/dev/null \
  || { echo "Microcks is not reachable on :8080 - start the stack first" >&2; exit 2; }

exec .venv/bin/python run_poc3a.py "$@"
