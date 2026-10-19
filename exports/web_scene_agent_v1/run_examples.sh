#!/usr/bin/env bash
set -euo pipefail
# Choose the existing project non-base Conda Python. Does not start Isaac or BC.
: "${AGENT_PYTHON:?Set AGENT_PYTHON to a non-base Conda Python executable}"
agent_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
agent_project="$(cd -- "$agent_dir/../.." && pwd)"
for example in describe edit_room list_datasets plan_training; do
  "$AGENT_PYTHON" "$agent_dir/executor.py" --project "$agent_project" --command "$agent_dir/examples/$example.json"
done
