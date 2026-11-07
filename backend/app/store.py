from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

ACTIVE = ("submitting", "submission_unknown", "running", "transferring")


class QueueFull(Exception):
    pass


class RequestConflict(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    client_request_id TEXT NOT NULL UNIQUE,
                    prompt TEXT NOT NULL,
                    seed INTEGER,
                    model_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    upstream_id TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    inference_completed_at REAL,
                    completed_at REAL,
                    error_code TEXT,
                    error_message TEXT,
                    video_json TEXT,
                    media_expired INTEGER NOT NULL DEFAULT 0,
                    progress REAL
                );
                CREATE INDEX IF NOT EXISTS jobs_status_created
                ON jobs(status, created_at);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def by_client_id(self, client_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE client_request_id=?", (client_id,)).fetchone()
            return dict(row) if row else None

    def submit(self, client_id, prompt, seed, model_id, capacity):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM jobs WHERE client_request_id=?", (client_id,)).fetchone()
            if existing:
                if existing["prompt"] != prompt or existing["seed"] != seed:
                    raise RequestConflict()
                return dict(existing)
            waiting = db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0]
            if waiting >= capacity:
                raise QueueFull()
            job_id = str(uuid4())
            db.execute(
                "INSERT INTO jobs(id,client_request_id,prompt,seed,model_id,status,created_at) VALUES(?,?,?,?,?,'queued',?)",
                (job_id, client_id, prompt, seed, model_id, time.time()),
            )
        return self.get(job_id)

    def update(self, job_id, **fields):
        allowed = {"status", "upstream_id", "started_at", "inference_completed_at", "completed_at",
                   "error_code", "error_message", "video_json", "media_expired", "progress"}
        if not fields.keys() <= allowed:
            raise ValueError("Invalid job update fields")
        with self.connection() as db:
            columns = ", ".join(f"{key}=?" for key in fields)
            db.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*fields.values(), job_id))

    def recover(self):
        # A crash after upstream accepted POST can leave the local state at submitting.
        with self.connection() as db:
            db.execute("""UPDATE jobs SET status='submission_unknown',
                error_code='submission_unknown', error_message='提交结果待核对，请联系维护者。'
                WHERE status='submitting'""")

    def active(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE status IN (?,?,?,?) ORDER BY created_at LIMIT 1", ACTIVE).fetchone()
            return dict(row) if row else None

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE status IN (?,?,?,?) LIMIT 1", ACTIVE).fetchone():
                return None
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at, id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='submitting',started_at=? WHERE id=?", (time.time(), row["id"]))
        return self.get(row["id"])

    def waiting(self):
        with self.connection() as db:
            return db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0]

    def cached(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM jobs WHERE status='succeeded' AND media_expired=0 ORDER BY completed_at,id")]

    def resolve(self, job_id, upstream_id=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["status"] != "submission_unknown":
                raise ValueError("Only a submission_unknown job can be resolved")
            if upstream_id:
                db.execute("""UPDATE jobs SET status='running',upstream_id=?,error_code=NULL,
                    error_message=NULL WHERE id=?""", (upstream_id, job_id))
            else:
                db.execute("""UPDATE jobs SET status='failed',completed_at=?,error_code='submission_failed',
                    error_message='维护者已确认提交失败，可以重新提交。' WHERE id=?""", (time.time(), job_id))

    def public(self, job):
        def timestamp(value):
            return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None

        def elapsed(start, end):
            return max(0, end - start) if start is not None and end is not None else None

        queue_position = None
        if job["status"] == "queued":
            with self.connection() as db:
                queue_position = db.execute("""SELECT count(*) FROM jobs WHERE status='queued'
                    AND (created_at < ? OR (created_at=? AND id<=?))""",
                    (job["created_at"], job["created_at"], job["id"])).fetchone()[0]
        error = None
        if job["error_code"]:
            error = {"code": job["error_code"], "message": job["error_message"]}
        available = job["status"] == "succeeded" and not job["media_expired"]
        return {
            "id": job["id"], "status": job["status"], "prompt": job["prompt"],
            "model_id": job["model_id"], "seed": job["seed"],
            **{key: timestamp(job[key]) for key in ("created_at", "started_at", "inference_completed_at", "completed_at")},
            "queue_position": queue_position,
            "video_url": f'/media/{job["id"]}.mp4' if available else None,
            "media_expired": bool(job["media_expired"]), "error": error,
            "timings": {
                "queue_seconds": elapsed(job["created_at"], job["started_at"]),
                "generation_seconds": elapsed(job["started_at"], job["inference_completed_at"]),
                "transfer_seconds": elapsed(job["inference_completed_at"], job["completed_at"]) if job["status"] == "succeeded" else None,
                "total_seconds": elapsed(job["created_at"], job["completed_at"]),
            },
            "video": json.loads(job["video_json"]) if job["video_json"] else None,
            "progress": job["progress"],
        }
