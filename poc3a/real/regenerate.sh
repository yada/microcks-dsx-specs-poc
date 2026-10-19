#!/usr/bin/env bash
# Regenerate examples/nico-real.apiexamples.yaml with infra-controller's real serde types.
# Needs: Rust (rustup, toolchain from infra-controller/rust-toolchain.toml), protoc, git, and a
# local infra-controller checkout (default ../../../infra-controller). Uses a throw-away git
# worktree in /tmp, so the checkout is not modified. First build takes a few minutes.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD
IC=${INFRA_CONTROLLER:-$HERE/../../../infra-controller}
WT=$(mktemp -d /tmp/ic-wt.XXXXXX)
trap 'git -C "$IC" worktree remove --force "$WT" >/dev/null 2>&1 || true' EXIT
git -C "$IC" worktree add -q --detach "$WT" HEAD
python3 extract_samples.py "$IC" "$WT/crates/api-model/samples.json"
mkdir -p "$WT/crates/api-model/examples"
cp dump_states.rs "$WT/crates/api-model/examples/"
(cd "$WT/crates/api-model" && cargo run -q --example dump_states > "$WT/messages.jsonl")
python3 -m venv "$HERE/.venv-fixture" >/dev/null && "$HERE/.venv-fixture/bin/python" -m pip install -q pyyaml
"$HERE/.venv-fixture/bin/python" build_fixture.py "$WT/messages.jsonl" "$HERE/../../examples/nico-real.apiexamples.yaml"
echo "infra-controller commit: $(git -C "$IC" rev-parse --short HEAD)"
