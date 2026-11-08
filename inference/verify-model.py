#!/usr/bin/env python3
"""Check pinned model files against Hugging Face's official Git/LFS manifest."""
import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--metadata-only", action="store_true")
parser.add_argument("--lora-path", type=Path)
args = parser.parse_args()

manifest = json.loads((Path(__file__).parent / "configs/model-manifest.json").read_text())
if os.environ.get("XYZ_H3_MODEL_PATH"):
    root = Path(os.environ["XYZ_H3_MODEL_PATH"])
else:
    root = Path(os.environ["XYZ_MODEL_ROOT"]) / "MiniMax-H3"


def verify(entry, base=root):
    path = base / entry["rfilename"]
    size = path.stat().st_size
    if size != entry["size"]:
        raise ValueError(f"Size mismatch: {path}")
    lfs = entry.get("lfs")
    if lfs and args.metadata_only:
        return entry["rfilename"] + " (size checked, digest pending)"
    digest = hashlib.sha256() if lfs else hashlib.sha1()
    if not lfs:
        digest.update(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    expected = lfs["sha256"] if lfs else entry["blobId"]
    if digest.hexdigest() != expected:
        raise ValueError(f"Digest mismatch: {path}")
    return entry["rfilename"]


with ThreadPoolExecutor(max_workers=int(os.environ.get("XYZ_VERIFY_WORKERS", "4"))) as executor:
    futures = [executor.submit(verify, entry) for entry in manifest["files"]]
    for future in as_completed(futures):
        print(f"VERIFIED {future.result()}", flush=True)
if args.lora_path:
    config = json.loads((Path(__file__).parent / "configs/minimax-h3.json").read_text())
    adapter = config["lora"]
    entry = {
        "rfilename": args.lora_path.name,
        "size": adapter["size"],
        "lfs": {"sha256": adapter["sha256"]},
    }
    print(f"VERIFIED {verify(entry, args.lora_path.parent)}", flush=True)
if args.metadata_only:
    print("MODEL_METADATA_VERIFIED " + manifest["revision"], flush=True)
else:
    (root / "verified-revision.txt").write_text(manifest["revision"] + "\n")
    print("MODEL_VERIFIED " + manifest["revision"], flush=True)
