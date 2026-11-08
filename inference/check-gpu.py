#!/usr/bin/env python3
"""Run with torchrun using the local GPU count before loading H3."""
import json
import os
from pathlib import Path

import cudnn
import torch
import torch.distributed as dist
import triton
import triton.language as tl


@triton.jit
def add_one(source, destination, count: tl.constexpr, BLOCK: tl.constexpr):
    offset = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    values = tl.load(source + offset, offset < count, other=0)
    tl.store(destination + offset, values + 1, offset < count)


def check_cudnn_convolutions():
    errors = {}
    generator = torch.Generator().manual_seed(20261108)
    for dtype, tolerance in (
        (torch.float32, 0.00001),
        (torch.float16, 0.001),
        (torch.bfloat16, 0.01),
    ):
        for kernel in (1, 3):
            inputs = torch.randn(1, 24, 4, 12, 16, generator=generator).to(dtype)
            weights = torch.randn(
                24, 24, kernel, kernel, kernel, generator=generator
            ).to(dtype)
            bias = torch.randn(24, generator=generator).to(dtype)
            with torch.inference_mode(), torch.backends.cudnn.flags(
                enabled=True, benchmark=False, allow_tf32=False
            ):
                result = torch.nn.functional.conv3d(
                    inputs.cuda(), weights.cuda(), bias.cuda(), padding=kernel // 2
                )
                reference = torch.nn.functional.conv3d(
                    inputs.float(), weights.float(), bias.float(), padding=kernel // 2
                )
            error = (result.float().cpu() - reference).norm() / reference.norm()
            assert torch.isfinite(result).all()
            assert error.item() < tolerance, (dtype, kernel, error.item())
            errors[f"{dtype}_kernel{kernel}"] = error.item()

    loaded = sorted({
        line.split()[-1]
        for line in Path("/proc/self/maps").read_text().splitlines()
        if "libcudnn" in line
    })
    expected = Path(torch.__file__).resolve().parent.parent / "nvidia/cudnn/lib"
    assert loaded and all(Path(path).is_relative_to(expected) for path in loaded), loaded
    return {"relative_errors": errors, "libraries": loaded}


rank = int(os.environ["LOCAL_RANK"])
torch.cuda.set_device(rank)
dist.init_process_group("nccl")
left = torch.ones((128, 128), dtype=torch.bfloat16, device="cuda")
product = left @ left
assert torch.equal(product, torch.full_like(product, 128))
source = torch.arange(1024, dtype=torch.float32, device="cuda")
output = torch.empty_like(source)
add_one[(4,)](source, output, 1024, BLOCK=256)
assert torch.equal(output, source + 1)
value = torch.tensor([rank + 1.0], device="cuda")
dist.all_reduce(value)
world_size = dist.get_world_size()
assert value.item() == world_size * (world_size + 1) / 2
cudnn_result = check_cudnn_convolutions()
torch.cuda.synchronize()
print(json.dumps({
    "rank": rank,
    "gpu": torch.cuda.get_device_name(rank),
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "bf16": "passed",
    "triton_jit": "passed",
    "nccl": "passed",
    "cudnn": torch.backends.cudnn.version(),
    "cudnn_frontend": cudnn.__version__,
    "conv3d": cudnn_result,
}), flush=True)
dist.destroy_process_group()
