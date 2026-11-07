#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/deploy/gpu/env.sh"
runtime="${XYZ_RUNTIME:-$XYZ_VENV_ROOT/sglang-cu129}"
model_path="${XYZ_H3_MODEL_PATH:-$XYZ_MODEL_ROOT/MiniMax-H3}"
: "${CUDA_VISIBLE_DEVICES:?Set CUDA_VISIBLE_DEVICES to the GPUs assigned to this instance}"
export CUDA_VISIBLE_DEVICES
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
test -f "$model_path/FL2VA/model_index.json"
XYZ_H3_MODEL_PATH="$model_path" "$runtime/bin/python" "$repo_root/inference/verify-model.py" --metadata-only
# Official full-precision TP2/layerwise recipe. This candidate needs A100 validation.
exec "$runtime/bin/sglang" serve \
  --model-path "$model_path" \
  --model-variant fl2va \
  --served-model-name MiniMaxAI/MiniMax-H3 \
  --host 127.0.0.1 --port 30010 \
  --num-gpus "${XYZ_NUM_GPUS:-2}" \
  --tp-size "${XYZ_TP_SIZE:-2}" \
  --ulysses-degree "${XYZ_ULYSSES_DEGREE:-1}" \
  --encoder-parallel auto --performance-mode memory \
  --layerwise-offload-components dit,text_encoder,vae \
  --dit-offload-prefetch-size 1 \
  --dit-layerwise-resident-layers "${XYZ_DIT_RESIDENT_LAYERS:-0}" \
  --enable-torch-compile false \
  --output-path "$XYZ_OUTPUT_ROOT" \
  "$@"
