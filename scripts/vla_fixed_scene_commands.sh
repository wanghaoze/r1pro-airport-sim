#!/usr/bin/env bash
# Run on the server after copying the standalone diagnostic files into project.
set -euo pipefail
PROJECT="${VLA_PROJECT:-/home/michelle/haoze/r1pro-airport-sim}"
CONDA_ROOT="${VLA_CONDA_ROOT:-/home/michelle/miniconda3}"
export VLA_CODE_ROOT="${VLA_CODE_ROOT:-$PROJECT/releases/three_table_single_tray_v34_eval_audit_20261006}"
SIM_PY="${VLA_SIM_PYTHON:-$CONDA_ROOT/envs/r1pro-tray/bin/python}"
MODEL_PY="${VLA_MODEL_PYTHON:-$CONDA_ROOT/envs/r1pro-vla/bin/python}"
TRAINING_ROOT="$PROJECT/runs/three_table_single_tray_20261006/overnight_hardened_v29_v1/training_batch_v1"
MILESTONE="${VLA_MILESTONE:-$TRAINING_ROOT/milestone_001000.json}"
SOURCE_CASE="${VLA_SOURCE_CASE:-$PROJECT/runs/three_table_single_tray_20261006/overnight_20261006_v1/campaign_v1/case_0000/observed_source}"
CONFIG="${VLA_CONFIG:-$VLA_CODE_ROOT/resources/single_tray_three_table_v1/source_registry/v64_actual_config.json}"
DEMO_ROOT="${VLA_DEMO_ROOT:-$PROJECT/runs/vla_free_fixed_scene_20261007_step999}"
PORT="${VLA_PORT:-8027}"
export PYTHONPATH="$VLA_CODE_ROOT:$PROJECT/third_party/openpi/src:$PROJECT/third_party/openpi/packages/openpi-client/src${PYTHONPATH:+:$PYTHONPATH}"
export OPENPI_DATA_HOME="$PROJECT/resources/openpi_cache"
export HF_HOME="$PROJECT/resources/hf_cache"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$PROJECT"
case "${1:-}" in
  prepare)
    # An existing root is rejected; never overwrite checkpoint identity evidence.
    mkdir "$DEMO_ROOT"
    "$MODEL_PY" "$VLA_CODE_ROOT/scripts/serve_pi05_airport.py" --training-status "$MILESTONE" --identity-only > "$DEMO_ROOT/checkpoint_identity.json"
    cp "$MILESTONE" "$DEMO_ROOT/milestone.json"
    printf 'Prepared %s\n' "$DEMO_ROOT"
    ;;
  serve)
    test -s "$DEMO_ROOT/checkpoint_identity.json"
    export CUDA_VISIBLE_DEVICES="${VLA_GPU:-0}"
    exec "$MODEL_PY" "$VLA_CODE_ROOT/scripts/serve_pi05_airport.py" --training-status "$DEMO_ROOT/milestone.json" --host 127.0.0.1 --port "$PORT"
    ;;
  pick|place|push)
    test -s "$DEMO_ROOT/checkpoint_identity.json"
    export MUJOCO_GL=egl MUJOCO_EGL_DEVICE_ID="${VLA_EGL_DEVICE:-0}"
    output="$DEMO_ROOT/${1}_$(date -u +%Y%m%dT%H%M%S)_$$"
    exec "$SIM_PY" scripts/run_vla_fixed_scene.py --source-case "$SOURCE_CASE" --config "$CONFIG" \
      --identity-file "$DEMO_ROOT/checkpoint_identity.json" --host 127.0.0.1 --port "$PORT" \
      --command "$1" --seconds "${VLA_SECONDS:-300}" --execute-steps "${VLA_EXECUTE_STEPS:-5}" --output "$output"
    ;;
  all)
    for command in pick place push; do bash "$0" "$command"; done
    ;;
  *)
    printf 'Usage: bash %s prepare|serve|pick|place|push|all\n' "$0" >&2
    exit 2
    ;;
esac
