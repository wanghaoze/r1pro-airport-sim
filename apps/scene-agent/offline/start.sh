#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export AIRPORT_PROJECT="${AIRPORT_PROJECT:-/home/michelle/haoze/r1pro-airport-sim}"
export STUDIO_HOST="${STUDIO_HOST:-127.0.0.1}"
export STUDIO_PORT="${STUDIO_PORT:-9080}"
exec "${STUDIO_PYTHON:-/home/michelle/miniconda3/envs/r1pro-tray/bin/python}" offline/supervisor.py
