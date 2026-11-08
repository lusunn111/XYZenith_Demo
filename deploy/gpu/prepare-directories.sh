#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/env.sh"

for project_directory in "$XYZ_DATA_ROOT" "$XYZ_MODEL_ROOT" "$XYZ_OUTPUT_ROOT" "$XYZ_VENV_ROOT"; do
  case "$project_directory" in
    /data|/data/*)
      if ! mountpoint -q /data; then
        printf 'Expected /data to be mounted before creating project directories.\n' >&2
        exit 1
      fi
      ;;
  esac
done

mkdir -p -- \
  "$XYZ_MODEL_ROOT" \
  "$XYZ_OUTPUT_ROOT" \
  "$XYZ_VENV_ROOT" \
  "$HF_HOME" \
  "$HF_HUB_CACHE" \
  "$HF_ASSETS_CACHE" \
  "$TORCH_HOME" \
  "$PIP_CACHE_DIR" \
  "$UV_CACHE_DIR" \
  "$TRITON_CACHE_DIR" \
  "$TORCHINDUCTOR_CACHE_DIR" \
  "$TMPDIR"

printf 'Prepared data directories under %s\n' "$XYZ_DATA_ROOT"
