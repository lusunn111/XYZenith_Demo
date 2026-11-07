"""CPU-only HTTP fixture for testing the real SSH tunnel with a synthetic MP4.

The /chain-test prefix keeps the production /health endpoint unavailable.
Run only while the real inference server is stopped, then stop this process.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--port", type=int, default=30010)
    args = parser.parse_args()
    video = args.video.read_bytes()
    jobs = {}

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, body):
            content = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            if self.path != "/chain-test/v1/videos":
                self.send_json(404, {"error": "test fixture requires /chain-test"})
                return
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            job_id = "chain-test-" + str(uuid4())
            jobs[job_id] = {"id": job_id, "created": time.monotonic(), "prompt": request["prompt"]}
            self.send_json(200, {"id": job_id, "status": "queued"})

        def do_GET(self):
            if self.path == "/chain-test/health":
                self.send_json(200, {"fixture": True})
                return
            prefix = "/chain-test/v1/videos/"
            job_id = self.path.removeprefix(prefix).split("/")[0]
            if not self.path.startswith(prefix) or job_id not in jobs:
                self.send_json(503, {"error": "real inference is offline; CPU test fixture only"})
                return
            if self.path.endswith("/content"):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(video)))
                self.end_headers()
                self.wfile.write(video)
                return
            status = "completed" if time.monotonic() - jobs[job_id]["created"] >= 1 else "in_progress"
            self.send_json(200, {"id": job_id, "status": status})

    print("CPU TEST FIXTURE: synthetic video, no model inference", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
