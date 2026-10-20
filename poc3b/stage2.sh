#!/usr/bin/env bash
# PoC 3b (stage 2): run Microcks against a REAL infra-controller rest-api started locally.
# Light route: Postgres + Temporal (dev server) + the rest-api binary. No Kind, no Core, no site.
# Needs: Docker, Go (see rest-api/go.mod), a checkout of infra-controller, the Microcks stack on :8080.
#   ./stage2.sh up      start Postgres, Temporal, JWKS server and the API
#   ./stage2.sh test    run the conformance test (needs `up`)
#   ./stage2.sh down    stop everything and remove poc3b/work/s2
#   ./stage2.sh         up + test + down
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD
IC=${INFRA_CONTROLLER:-$HERE/../../infra-controller}
WORK=$HERE/work/s2
PIDS=$WORK/pids

check_ports() {
  for port in 8766 8388 35432 7233; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      echo "port $port is already in use (leftover from an earlier run?): free it and retry" >&2; exit 1
    fi
  done
}

up() {
  mkdir -p "$WORK"
  [ -d .venv ] || { python3 -m venv .venv; .venv/bin/python -m pip install -q pyyaml jsonschema; }
  [ -d "$WORK/v" ] || { python3 -m venv "$WORK/v"; "$WORK/v/bin/python" -m pip install -q pyjwt cryptography; }
  "$WORK/v/bin/python" make_token.py "$WORK"
  printf nico > "$WORK/dbpass"
  printf 'poc-temporal-encryption-key-0123' > "$WORK/tkey"
  sed "s#@WORK@#$WORK#g" stage2-config.yaml > "$WORK/config.yaml"

  [ -x "$WORK/api" ] || (cd "$IC/rest-api" && go build -o "$WORK/api" ./api/cmd/api && go build -o "$WORK/migrate" ./db/cmd/migrations)

  docker rm -f s2-pg s2-temporal >/dev/null 2>&1 || true
  docker run -d --name s2-pg -e POSTGRES_USER=nico -e POSTGRES_PASSWORD=nico -e POSTGRES_DB=nico \
    -p 35432:5432 postgres:17-alpine >/dev/null
  docker run -d --name s2-temporal -p 7233:7233 temporalio/temporal:1.9.1 server start-dev --ip 0.0.0.0 >/dev/null
  # TCP only: the image's temporary init server listens on the unix socket and then restarts
  for _ in $(seq 30); do docker exec s2-pg pg_isready -h 127.0.0.1 -U nico >/dev/null 2>&1 && break; sleep 1; done
  docker exec s2-pg psql -U nico -d nico -qc 'CREATE EXTENSION IF NOT EXISTS pg_trgm'
  export PGHOST=localhost PGPORT=35432 PGDATABASE=nico PGUSER=nico PGPASSWORD=nico PGSSLMODE=disable
  "$WORK/migrate" db init >/dev/null && "$WORK/migrate" db migrate >/dev/null

  (cd "$WORK" && python3 -m http.server 8766 >jwks.log 2>&1 & echo $! >> "$PIDS")
  sleep 5   # let Temporal accept connections: the API health-checks it at startup
  (CONFIG_FILE_PATH="$WORK/config.yaml" "$WORK/api" >"$WORK/api.log" 2>&1 & echo $! >> "$PIDS")
  for _ in $(seq 30); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8388/v2/org/test-org-1/nico/metadata)" = 401 ] && return 0
    sleep 1
  done
  echo "rest-api did not come up, see $WORK/api.log" >&2; exit 1
}

test_() {
  for _ in $(seq 60); do curl -sf http://localhost:8080/api/keycloak/config >/dev/null && break; sleep 1; done
  curl -sf http://localhost:8080/api/keycloak/config >/dev/null \
    || { echo "Microcks is not reachable on :8080 - start the stack first" >&2; exit 2; }
  .venv/bin/python run_stage2.py --infra-controller "$IC" --token-file "$WORK/token.txt" "$@"
}

down() {
  [ -f "$PIDS" ] && while read -r p; do kill "$p" 2>/dev/null || true; done < "$PIDS"
  # on macOS the recorded PID can be a launcher, so also stop whatever still listens on our ports
  if command -v lsof >/dev/null; then
    for port in 8766 8388; do
      { lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true; } | while read -r p; do kill "$p" 2>/dev/null || true; done
    done
  fi
  docker rm -f s2-pg s2-temporal >/dev/null 2>&1 || true
  rm -rf "$WORK"
}

case "${1:-all}" in
  up) check_ports; up ;;
  test) shift; test_ "$@" ;;
  down) down ;;
  all) check_ports; trap down EXIT; up; test_ ;;
  *) echo "usage: $0 [up|test|down]" >&2; exit 2 ;;
esac
