#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/deploy/gpu/env.sh"
runtime="${XYZ_RUNTIME:-$XYZ_VENV_ROOT/sglang-cu129}"
source "$repo_root/deploy/gpu/runtime-env.sh" "$runtime"
model_path="${XYZ_H3_MODEL_PATH:-$XYZ_MODEL_ROOT/MiniMax-H3}"
lora_path="${XYZ_H3_LORA_PATH:-$XYZ_MODEL_ROOT/Minimax-h3-Turbo/minimax_h3_fl2v_turbo_4step_v0.1.safetensors}"
: "${CUDA_VISIBLE_DEVICES:?Set CUDA_VISIBLE_DEVICES to the GPUs assigned to this instance}"
export CUDA_VISIBLE_DEVICES
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
test -f "$model_path/FL2VA/model_index.json"
test -f "$lora_path"
mkdir -p "$XYZ_OUTPUT_ROOT"
XYZ_H3_MODEL_PATH="$model_path" "$runtime/bin/python" "$repo_root/inference/verify-model.py" \
  --metadata-only --lora-path "$lora_path"
# The selected LightX2V FL2VA adapter needs scale 1 and training alpha 8.
# The first A100 validation uses the official single-GPU mapped-weight path.
exec "$runtime/bin/sglang" serve \
  --model-path "$model_path" \
  --model-variant fl2va \
  --served-model-name MiniMaxAI/MiniMax-H3 \
  --host 127.0.0.1 --port 30010 --strict-ports \
  --num-gpus "${XYZ_NUM_GPUS:-1}" \
  --tp-size "${XYZ_TP_SIZE:-1}" \
  --ulysses-degree "${XYZ_ULYSSES_DEGREE:-1}" \
  --encoder-parallel auto --performance-mode memory \
  --pin-cpu-memory false \
  --attention-backend torch_sdpa \
  --layerwise-offload-components dit,text_encoder,vae \
  --dit-offload-prefetch-size 1 \
  --dit-layerwise-resident-layers "${XYZ_DIT_RESIDENT_LAYERS:-0}" \
  --lora-path "$lora_path" \
  --lora-nickname h3-lightx2v-4step \
  --lora-scale 1.0 --lora-alpha 8 --lora-merge-mode auto \
  --enable-torch-compile false --warmup-mode off \
  --output-path "$XYZ_OUTPUT_ROOT" \
  "$@"
