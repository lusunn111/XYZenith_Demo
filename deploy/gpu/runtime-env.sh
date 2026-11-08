#!/usr/bin/env bash
# Source after selecting the project virtual environment.
if [[ "$#" -ne 1 || ! -x "$1/bin/python" ]]; then
  printf 'Usage: source runtime-env.sh /path/to/project/venv\n' >&2
  return 2
fi

xyzenith_runtime_library_path="$("$1/bin/python" - <<'PY'
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import sys
import sysconfig

site = Path(sysconfig.get_path("purelib"))
cudnn_dir = site / "nvidia/cudnn/lib"
versions = []
for package in ("nvidia-cudnn-cu12", "nvidia-cudnn-cu13"):
    try:
        versions.append(version(package))
    except PackageNotFoundError:
        pass
if len(versions) != 1:
    raise SystemExit("Expected one CUDA-specific cuDNN package in the selected runtime")

package_version = versions[0]
library_version = ".".join(package_version.split(".")[:3])
major = package_version.split(".")[0]
libraries = sorted(cudnn_dir.glob(f"libcudnn*.so.{major}"))
if not libraries or not (site / "torch/lib").is_dir():
    raise SystemExit("The selected runtime is missing cuDNN or PyTorch libraries")

# cuDNN tries full-version names before the major-only names in its wheel.
# Supply those aliases outside site-packages to keep system CUDA builds out.
alias_dir = Path(sys.prefix) / "lib/xyzenith-cudnn" / package_version
alias_dir.mkdir(parents=True, exist_ok=True)
for library in libraries:
    alias = alias_dir / (library.name.split(".so.")[0] + ".so." + library_version)
    target = os.path.relpath(library, alias_dir)
    try:
        alias.symlink_to(target)
    except FileExistsError:
        if not alias.is_symlink() or os.readlink(alias) != target:
            raise SystemExit(f"Unexpected existing cuDNN alias: {alias}")

paths = [alias_dir, cudnn_dir, site / "torch/lib"]
paths.extend(sorted((site / "nvidia").glob("*/lib")))
paths.extend(path for path in os.environ.get("LD_LIBRARY_PATH", "").split(":") if path)
print(":".join(dict.fromkeys(str(path) for path in paths)))
PY
)" || return "$?"
export LD_LIBRARY_PATH="$xyzenith_runtime_library_path"
unset xyzenith_runtime_library_path
