#!/usr/bin/env sh

# Source this file in the shell used for model downloads and inference.
export XYZ_DATA_ROOT="${XYZ_DATA_ROOT:-/data/Zhihao/XYZenith_Demo}"
export XYZ_MODEL_ROOT="${XYZ_MODEL_ROOT:-$XYZ_DATA_ROOT/models}"
export XYZ_OUTPUT_ROOT="${XYZ_OUTPUT_ROOT:-$XYZ_DATA_ROOT/outputs}"
export XYZ_VENV_ROOT="${XYZ_VENV_ROOT:-$XYZ_DATA_ROOT/.venvs}"
export HF_HOME="$XYZ_DATA_ROOT/cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_ASSETS_CACHE="$HF_HOME/assets"
export TORCH_HOME="$XYZ_DATA_ROOT/cache/torch"
export XDG_CACHE_HOME="$XYZ_DATA_ROOT/cache"
export PIP_CACHE_DIR="$XYZ_DATA_ROOT/cache/pip"
export UV_CACHE_DIR="$XYZ_DATA_ROOT/cache/uv"
export TRITON_CACHE_DIR="$XYZ_DATA_ROOT/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$XYZ_DATA_ROOT/cache/torchinductor"
export TMPDIR="$XYZ_DATA_ROOT/tmp"
