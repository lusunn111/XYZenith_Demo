#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/env.sh"
bash "$script_dir/prepare-directories.sh"
mkdir -p "$XYZ_DATA_ROOT/logs" "$XYZ_DATA_ROOT/tools" "$XYZ_DATA_ROOT/src"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-30}"
export UV_HTTP_RETRIES="${UV_HTTP_RETRIES:-1}"
export UV_PYTHON_INSTALL_DIR="$XYZ_DATA_ROOT/tools/python"
export XYZ_WHEEL_ROOT="${XYZ_WHEEL_ROOT:-$XYZ_DATA_ROOT/cache/wheels}"
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
  requirements_file="$XYZ_DATA_ROOT/src/requirements-cu129.txt"
  lock_file="$script_dir/../../inference/requirements-cu129.lock.txt"
  dependency_flags=()
  if [[ -f "$lock_file" ]]; then
    "$runtime/bin/python" "$script_dir/prepare-cu129-requirements.py" "$requirements_file" --lock "$lock_file"
    # The complete CUDA 12 freeze intentionally overrides the CUDA 13 metadata
    # published in the upstream SGLang wheel.
    dependency_flags=(--no-deps)
  else
    "$runtime/bin/python" "$script_dir/prepare-cu129-requirements.py" "$requirements_file"
  fi
  # Prefer PyPI for CUDA dependencies, whose PyTorch-index links can redirect
  # to a regional NVIDIA host. Only CUDA-specific Torch builds need fallback.
  "$uv_bin" pip install --python "$runtime/bin/python" --prerelease=allow \
    --index-strategy unsafe-first-match \
    --index https://pypi.org/simple \
    --default-index https://download.pytorch.org/whl/cu129 \
    "${dependency_flags[@]}" -r "$requirements_file"
  # The upstream CUDA 12 Dockerfile removes optional CUDA 13 library packages
  # pulled in by transitive dependencies after resolving the full package set.
  "$runtime/bin/python" - "$uv_bin" <<'PY'
from importlib.metadata import distributions
import subprocess
import sys

cuda13_packages = [
    package.metadata["Name"]
    for package in distributions()
    if package.metadata["Name"].lower().replace("_", "-").endswith("-cu13")
]
if cuda13_packages:
    subprocess.run(
        [sys.argv[1], "pip", "uninstall", "--python", sys.executable, *cuda13_packages],
        check=True,
    )
PY
  "$uv_bin" pip install --python "$runtime/bin/python" --no-deps "sglang==$version"
fi
"$uv_bin" pip freeze --python "$runtime/bin/python" > "$XYZ_DATA_ROOT/logs/runtime-$profile.freeze.txt"
"$runtime/bin/python" -c 'import torch; print("Torch", torch.__version__, "CUDA", torch.version.cuda); print("GPUs", torch.cuda.device_count()); assert torch.cuda.is_available()'
