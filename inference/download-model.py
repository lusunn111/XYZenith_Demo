#!/usr/bin/env python3
"""Download the pinned H3 FL2VA partition and its four-step adapter."""
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

config = json.loads((Path(__file__).parent / "configs/minimax-h3.json").read_text())
model_root = Path(os.environ["XYZ_MODEL_ROOT"]) / "MiniMax-H3"
print(f"Downloading {config['model_id']} at {config['revision']} to {model_root}", flush=True)
snapshot_download(
    repo_id=config["model_id"],
    revision=config["revision"],
    local_dir=model_root,
    allow_patterns=["FL2VA/*", "model_index.json", "modular_model_index.json", "README.md", "LICENSE"],
    max_workers=int(os.environ.get("XYZ_DOWNLOAD_WORKERS", "8")),
)
print("MODEL_DOWNLOAD_COMPLETE", flush=True)
adapter = config["lora"]
adapter_root = Path(os.environ["XYZ_MODEL_ROOT"]) / "Minimax-h3-Turbo"
hf_hub_download(
    repo_id=adapter["repo_id"],
    revision=adapter["revision"],
    filename=adapter["filename"],
    local_dir=adapter_root,
)
print(f"LORA_DOWNLOAD_COMPLETE {adapter_root / adapter['filename']}", flush=True)
