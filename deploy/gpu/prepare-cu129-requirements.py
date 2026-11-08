#!/usr/bin/env python3
"""Resolve v0.5.19's CUDA 12 lane using its published dependency metadata."""
import argparse
import json
import os
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
parser.add_argument("--lock", type=Path)
args = parser.parse_args()

# SHA256 values published by the corresponding official GitHub release assets.
wheel_digests = {
    "sglang_kernel-0.4.6.post1+cu129-cp310-abi3-manylinux2014_x86_64.whl":
        "9d400246b3f2512e2c33611e1bb6a2f252c499c5019e9f331f9c9ee215be95ab",
    "sgl_deep_ep-0.1.2+cu129-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl":
        "352389e070d3b38e870db9a3443fb7c7c4c16f4ae79aebfd8cda218cfb2f93c5",
    "sgl_deep_gemm-0.1.7+cu129-py3-none-manylinux2014_x86_64.whl":
        "80e988147f773f4490ac443775480a56d98ec9147b393623c9ce4bf03a0e03c5",
}

if args.lock:
    source_requirements = [
        line.strip() for line in args.lock.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
else:
    with urllib.request.urlopen("https://pypi.org/pypi/sglang/0.5.19/json", timeout=30) as response:
        metadata = json.load(response)
    source_requirements = metadata["info"]["requires_dist"]
requirements = []
for requirement in source_requirements:
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
    if " @ https://github.com/sgl-project/whl/" in requirement:
        package, url = requirement.split(" @ ", 1)
        url, _, fragment = url.partition("#")
        filename = url.rsplit("/", 1)[-1]
        if fragment and fragment != f"sha256={wheel_digests[filename]}":
            raise ValueError(f"Unexpected official wheel digest for {filename}")
        if os.getenv("XYZ_WHEEL_ROOT"):
            wheel = Path(os.environ["XYZ_WHEEL_ROOT"]) / filename
            if wheel.is_file():
                url = wheel.resolve().as_uri()
        requirement = f"{package} @ {url}#sha256={wheel_digests[filename]}"
    requirements.append(requirement)
args.output.write_text("\n".join(requirements) + "\n")
