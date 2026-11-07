#!/usr/bin/env python3
"""Run with torchrun using the local GPU count before loading H3."""
import json
import os

import torch
import torch.distributed as dist
import triton
import triton.language as tl


@triton.jit
def add_one(source, destination, count: tl.constexpr, BLOCK: tl.constexpr):
    offset = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    values = tl.load(source + offset, offset < count, other=0)
    tl.store(destination + offset, values + 1, offset < count)


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
torch.cuda.synchronize()
print(json.dumps({"rank": rank, "gpu": torch.cuda.get_device_name(rank), "torch": torch.__version__, "cuda": torch.version.cuda, "bf16": "passed", "triton_jit": "passed", "nccl": "passed"}), flush=True)
dist.destroy_process_group()
