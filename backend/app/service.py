import asyncio
from contextlib import suppress
import fcntl
import json
import logging
from pathlib import Path
from fractions import Fraction
import shutil
import time
from urllib.parse import quote

import httpx

from .config import Settings
from .store import Store

logger = logging.getLogger(__name__)


async def inspect_video(path: Path):
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except BaseException:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("生成文件未通过媒体格式检查")
    metadata = json.loads(stdout)
    stream = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "video"), None)
    if stream is None:
        raise ValueError("生成文件缺少视频轨道")
    video = {
        "width": int(stream["width"]), "height": int(stream["height"]),
        "duration_seconds": float(stream.get("duration") or metadata.get("format", {}).get("duration", 0)),
        "fps": float(Fraction(stream.get("avg_frame_rate") or stream["r_frame_rate"])),
    }
    if min(video.values()) <= 0:
        raise ValueError("生成文件包含无效的视频尺寸或时长")
    return video


class Service:
    def __init__(self, settings: Settings, client=None, probe=inspect_video):
        self.settings = settings
        self.store = Store(settings.database)
        settings.media_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.AsyncClient(
            base_url=settings.upstream_url,
            timeout=httpx.Timeout(300, connect=10),
            follow_redirects=False,
        )
        self.owns_client = client is None
        self.probe = probe
        self.health = {"status": "offline", "detail": "正在连接推理服务。"}
        self.checked_at = 0.0
        self.health_lock = asyncio.Lock()
        self.lock_file = None
        self.worker_task = None
        self.media_leases = {}

    async def start(self):
        self.lock_file = (self.settings.data_root / "worker.lock").open("a")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise RuntimeError("Only one backend process may use this data directory")
        self.store.recover()
        for path in self.settings.media_dir.glob("*.part"):
            path.unlink(missing_ok=True)
        self.maintain_cache()
        self.worker_task = asyncio.create_task(self.run(), name="generation-worker")

    async def stop(self):
        if self.worker_task:
            self.worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker_task
        if self.owns_client:
            await self.client.aclose()
        if self.lock_file:
            self.lock_file.close()

    async def refresh_health(self):
        async with self.health_lock:
            if time.monotonic() - self.checked_at < 5:
                return
            try:
                response = await self.client.get("/health", timeout=5)
                response.raise_for_status()
                self.health = {"status": "online", "detail": None}
            except httpx.HTTPError:
                self.health = {"status": "offline", "detail": "暂时无法连接 A100 推理服务。"}
            self.checked_at = time.monotonic()

    def health_response(self):
        inference = self.health
        active = self.store.active()
        if active and active["status"] == "submission_unknown":
            inference = {"status": "blocked", "detail": "有一项提交结果待维护者核对，队列暂时暂停。"}
        return {"status": "ok", "inference": inference,
                "queue": {"waiting": self.store.waiting(), "capacity": self.settings.queue_capacity},
                "model": self.settings.model, "mock": False}

    def fail(self, job_id, code, message):
        self.store.update(job_id, status="failed", completed_at=time.time(),
                          error_code=code, error_message=message)
        logger.warning("job=%s failed code=%s", job_id, code)

    async def tick(self):
        self.maintain_cache()
        await self.refresh_health()
        job = self.store.active()
        if job is None and self.health["status"] == "online":
            claimed = self.store.claim()
            if claimed:
                await self.submit(claimed)
            return
        if job is None or job["status"] == "submission_unknown":
            return
        if job["status"] == "submitting":
            # A previous dispatch raised after claiming. Its upstream outcome is unknown.
            self.unknown(job["id"])
        elif job["status"] == "running":
            await self.poll(job)
        elif job["status"] == "transferring":
            await self.transfer(job)

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Generation worker cycle failed")
            await asyncio.sleep(self.settings.poll_seconds)

    async def submit(self, job):
        generation = self.store.generation(job)
        if generation != self.settings.generation or job["model_id"] != self.settings.model_id:
            self.fail(job["id"], "generation_profile_changed",
                      "任务创建后的推理配置已变更，原参数已保留。请按当前配置新建任务。")
            return
        body = {
            "model": job["model_id"], "prompt": job["prompt"],
            **{key: value for key, value in generation.items() if key != "profile"},
        }
        if job["seed"] is not None:
            body["seed"] = job["seed"]
        try:
            response = await self.client.post("/v1/videos", json=body)
        except httpx.RequestError:
            self.unknown(job["id"])
            return
        # Server errors and malformed success responses can occur after enqueueing.
        if response.status_code >= 500:
            self.unknown(job["id"])
            return
        if response.is_error:
            self.fail(job["id"], "upstream_rejected", f"推理服务拒绝请求（HTTP {response.status_code}），请联系维护者检查生成配置。")
            return
        try:
            payload = response.json()
            upstream_id = payload["id"]
            if not isinstance(upstream_id, str) or not upstream_id:
                raise ValueError("Missing upstream ID")
        except (ValueError, KeyError, TypeError):
            self.unknown(job["id"])
            return
        self.store.update(job["id"], status="running", upstream_id=upstream_id)
        logger.info("job=%s submitted upstream=%s", job["id"], upstream_id)

    def unknown(self, job_id):
        self.store.update(job_id, status="submission_unknown", error_code="submission_unknown",
                          error_message="提交响应中断，生成结果待维护者核对。")
        logger.warning("job=%s submission outcome unknown", job_id)

    async def poll(self, job):
        try:
            response = await self.client.get(f'/v1/videos/{quote(job["upstream_id"], safe="")}')
            if response.status_code == 404:
                self.fail(job["id"], "upstream_job_lost", "推理服务中的任务记录已丢失，请重新提交。")
                return
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid upstream status response")
            status = result.get("status")
            if status in ("failed", "cancelled", "canceled"):
                error = result.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                self.fail(job["id"], "generation_failed", (message or "推理服务报告生成失败。")[:1000])
            elif status in ("completed", "succeeded"):
                self.store.update(job["id"], status="transferring", inference_completed_at=time.time(),
                                  error_code=None, error_message=None, progress=100)
            else:
                progress = result.get("progress")
                # SGLang 0.5.19 keeps its initial zero throughout generation.
                if type(progress) in (int, float) and 0 < progress <= 100:
                    progress = float(progress)
                else:
                    progress = None
                self.store.update(job["id"], progress=progress, error_code=None, error_message=None)
        except (httpx.HTTPError, ValueError, TypeError):
            self.store.update(job["id"], error_code="connection_interrupted",
                              error_message="正在恢复与推理服务的连接。")

    def maintain_cache(self, incoming_bytes=0):
        records = self.store.cached()
        cached = []
        now = time.time()
        for job in records:
            path = self.settings.media_dir / f'{job["id"]}.mp4'
            if self.media_leases.get(job["id"], 0) and path.exists():
                cached.append((job["id"], path, path.stat().st_size))
                continue
            if not path.exists() or now - job["completed_at"] >= self.settings.cache_ttl_seconds:
                path.unlink(missing_ok=True)
                self.store.update(job["id"], media_expired=1)
            else:
                cached.append((job["id"], path, path.stat().st_size))
        total = sum(item[2] for item in cached)
        for job_id, path, size in cached:
            if total + incoming_bytes <= self.settings.cache_max_bytes:
                break
            if self.media_leases.get(job_id, 0):
                continue
            path.unlink(missing_ok=True)
            self.store.update(job_id, media_expired=1)
            total -= size
        return total + incoming_bytes <= self.settings.cache_max_bytes

    async def transfer(self, job):
        destination = self.settings.media_dir / f'{job["id"]}.mp4'
        temporary = destination.with_suffix(".part")
        try:
            # Recover a crash between the atomic rename and the SQLite update.
            if not destination.exists():
                path = f'/v1/videos/{quote(job["upstream_id"], safe="")}/content'
                async with self.client.stream("GET", path) as response:
                    if response.status_code == 404:
                        self.fail(job["id"], "upstream_result_lost", "推理服务中的视频结果已不可访问，请重新提交。")
                        return
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > self.settings.cache_max_bytes:
                                raise ValueError("生成文件超过本项目视频缓存容量。")
                            if not self.maintain_cache(incoming_bytes=size):
                                raise OSError("视频播放占用缓存，等待释放容量。")
                            if shutil.disk_usage(self.settings.data_root).free < len(chunk) + 64 * 1024**2:
                                raise OSError("视频缓存磁盘空间不足。")
                            output.write(chunk)
                video = await self.probe(temporary)
                temporary.replace(destination)
            else:
                video = await self.probe(destination)
            self.store.update(job["id"], status="succeeded", completed_at=time.time(),
                              video_json=json.dumps(video), error_code=None, error_message=None)
            logger.info("job=%s completed bytes=%s", job["id"], destination.stat().st_size)
        except httpx.HTTPError:
            self.store.update(job["id"], error_code="transfer_interrupted",
                              error_message="视频传输中断，正在重试下载。")
        except FileNotFoundError:
            self.store.update(job["id"], error_code="media_probe_unavailable",
                              error_message="视频检查程序不可用，正在等待维护者修复。")
        except (ValueError, KeyError, StopIteration, ZeroDivisionError, asyncio.TimeoutError):
            destination.unlink(missing_ok=True)
            self.fail(job["id"], "invalid_video", "生成结果未通过视频完整性检查，请联系维护者。")
        except OSError:
            self.store.update(job["id"], error_code="storage_unavailable",
                              error_message="视频缓存存储暂不可用，正在等待恢复。")
        finally:
            temporary.unlink(missing_ok=True)
