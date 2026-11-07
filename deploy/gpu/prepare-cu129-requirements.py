#!/usr/bin/env python3
"""Resolve v0.5.19's CUDA 12 lane using its published dependency metadata."""
import json
import sys
import urllib.request
from pathlib import Path

with urllib.request.urlopen("https://pypi.org/pypi/sglang/0.5.19/json", timeout=30) as response:
    metadata = json.load(response)
requirements = []
for requirement in metadata["info"]["requires_dist"]:
    if "extra ==" in requirement:
        if 'extra == "diffusion"' not in requirement:
            continue
        requirement = requirement.replace(' and extra == "diffusion"', '').replace('; extra == "diffusion"', '')
    requirement = requirement.replace("cuda-python>=13.0", "cuda-python>=12,<13")
    requirement = requirement.replace("flashinfer_python[cu13]", "flashinfer_python[cu12]")
    requirement = requirement.replace("nvidia-cutlass-dsl[cu13]", "nvidia-cutlass-dsl")
    requirement = requirement.replace("humming-kernels[cu13]", "humming-kernels[cu12]")
    if requirement.startswith("torch=="):
        requirement = "torch==2.13.0+cu129"
    elif requirement == "torchvision":
        requirement = "torchvision==0.28.0+cu129"
    elif requirement.startswith("torchaudio=="):
        requirement = "torchaudio==2.11.0+cu129"
    elif requirement.startswith("sglang-kernel=="):
        requirement = "sglang-kernel @ https://github.com/sgl-project/whl/releases/download/v0.4.6.post1/sglang_kernel-0.4.6.post1+cu129-cp310-abi3-manylinux2014_x86_64.whl"
    elif requirement.startswith("sgl-deep-ep=="):
        requirement = "sgl-deep-ep @ https://github.com/sgl-project/whl/releases/download/v0.1.2/sgl_deep_ep-0.1.2+cu129-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    elif requirement.startswith("sgl-deep-gemm=="):
        requirement = "sgl-deep-gemm @ https://github.com/sgl-project/whl/releases/download/v0.1.7/sgl_deep_gemm-0.1.7+cu129-py3-none-manylinux2014_x86_64.whl"
    requirements.append(requirement)
Path(sys.argv[1]).write_text("\n".join(requirements) + "\n")
