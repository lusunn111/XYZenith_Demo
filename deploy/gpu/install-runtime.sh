#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/env.sh"
bash "$script_dir/prepare-directories.sh"
mkdir -p "$XYZ_DATA_ROOT/logs" "$XYZ_DATA_ROOT/tools" "$XYZ_DATA_ROOT/src"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-30}"
export UV_HTTP_RETRIES="${UV_HTTP_RETRIES:-1}"
export UV_PYTHON_INSTALL_DIR="$XYZ_DATA_ROOT/tools/python"
uv_bin="${UV_BIN:-$HOME/.local/bin/uv}"
profile="${1:-cu129}"
if [[ "$profile" == cu129 ]]; then
  runtime="$XYZ_VENV_ROOT/sglang-cu129"
  version=0.5.19
elif [[ "$profile" == cu130 ]]; then
  runtime="$XYZ_VENV_ROOT/sglang-cu130"
  version=0.5.23
else
  printf 'Usage: %s [cu129|cu130]\n' "$0" >&2
  exit 2
fi
if [[ ! -x "$runtime/bin/python" ]]; then
  "$uv_bin" venv --python 3.12 "$runtime"
fi
if [[ "$profile" == cu130 ]]; then
  "$uv_bin" pip install --python "$runtime/bin/python" --prerelease=allow "sglang[diffusion]==$version"
else
  # Match the CUDA 12 dependency substitutions used by the v0.5.19 Dockerfile.
  "$runtime/bin/python" "$script_dir/prepare-cu129-requirements.py" "$XYZ_DATA_ROOT/src/requirements-cu129.txt"
  "$uv_bin" --verbose pip install --python "$runtime/bin/python" --prerelease=allow \
    --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cu129 \
    -r "$XYZ_DATA_ROOT/src/requirements-cu129.txt"
  "$uv_bin" pip install --python "$runtime/bin/python" --no-deps "sglang==$version"
fi
"$uv_bin" pip freeze --python "$runtime/bin/python" > "$XYZ_DATA_ROOT/logs/runtime-$profile.freeze.txt"
"$runtime/bin/python" -c 'import torch; print("Torch", torch.__version__, "CUDA", torch.version.cuda); print("GPUs", torch.cuda.device_count()); assert torch.cuda.is_available()'
