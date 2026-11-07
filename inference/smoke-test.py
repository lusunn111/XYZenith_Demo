#!/usr/bin/env python3
"""Submit or resume one real H3 task and persist its recovery information."""
import argparse
import json
import time
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:30010")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--resume", metavar="JOB_ID")
parser.add_argument("--timeout", type=int, default=7200)
parser.add_argument("--prompt", default="A small orange cat walks slowly across a sunlit wooden floor. The camera remains steady, with soft natural light and quiet room ambience.")
args = parser.parse_args()
config = json.loads((Path(__file__).parent / "configs/minimax-h3.json").read_text())
args.output.parent.mkdir(parents=True, exist_ok=True)
record_path = args.output.with_suffix(".json")
record = json.loads(record_path.read_text()) if record_path.exists() else {}


def save_record():
    temporary = record_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2))
    temporary.replace(record_path)


body = record.get("request") or {"model": config["model_id"], "prompt": args.prompt, "task": config["task"], "target": config["target"], "seed": 42}
job_id = args.resume or record.get("job_id")
if record.get("status") in {"submitting", "submission_unknown"} and not job_id:
    raise RuntimeError("Previous submission has no confirmed job ID. Reconcile it, then use --resume JOB_ID.")
started = time.monotonic()
if job_id:
    record.update({"job_id": job_id, "request": body, "status": "resuming"})
    save_record()
    with urllib.request.urlopen(args.base_url + "/v1/videos/" + job_id, timeout=30) as response:
        job = json.load(response)
else:
    record.update({"request": body, "status": "submitting", "submitted_at": time.time()})
    save_record()
    request = urllib.request.Request(args.base_url + "/v1/videos", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            job = json.load(response)
        job_id = job["id"]
    except Exception:
        record["status"] = "submission_unknown"
        save_record()
        raise
record.update({"job_id": job_id, "status": job["status"], "result": job})
save_record()
print(json.dumps(job), flush=True)
while job["status"] not in {"completed", "failed"}:
    if time.monotonic() - started > args.timeout:
        raise TimeoutError(f"Task {job_id} is still pending; resume it with --resume {job_id}")
    time.sleep(2)
    with urllib.request.urlopen(args.base_url + "/v1/videos/" + job_id, timeout=30) as response:
        job = json.load(response)
    record.update({"status": job["status"], "result": job})
    save_record()
    print(json.dumps({"id": job_id, "status": job["status"], "progress": job.get("progress"), "elapsed_seconds": round(time.monotonic() - started, 2)}), flush=True)
if job["status"] == "failed":
    raise RuntimeError(json.dumps(job))
temporary_video = args.output.with_suffix(".mp4.part")
with urllib.request.urlopen(args.base_url + "/v1/videos/" + job_id + "/content", timeout=300) as response, temporary_video.open("wb") as destination:
    while chunk := response.read(1024 * 1024):
        destination.write(chunk)
temporary_video.replace(args.output)
record.update({"status": "downloaded", "downloaded_at": time.time(), "session_elapsed_seconds": time.monotonic() - started})
save_record()
print(f"VIDEO_SAVED {args.output}", flush=True)
