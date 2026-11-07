#!/usr/bin/env python3
"""Download only the pinned official H3 FL2VA partition."""
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download

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
