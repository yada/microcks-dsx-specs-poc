#!/usr/bin/env bash
# PoC 3b (stage 1): replay infra-controller's spec-drift fix as a Microcks REST conformance test.
# Needs the Microcks stack running (docker compose -f microcks/docker-compose.yml up -d)
# and a local checkout of infra-controller (default: ../../infra-controller, override with --infra-controller).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet pyyaml jsonschema
fi

curl -sf http://localhost:8080/api/keycloak/config >/dev/null \
  || { echo "Microcks is not reachable on :8080 - start the stack first" >&2; exit 2; }

exec .venv/bin/python run_poc3b.py "$@"
