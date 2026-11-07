import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import time
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.service import Service
from app.store import QueueFull, RequestConflict, Store


class BrokenDownload(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial-video"
        raise httpx.ReadError("tunnel disconnected")


class Upstream:
    def __init__(self):
        self.posts = 0
        self.downloads = 0
        self.status = "completed"
        self.post_error = False
        self.missing = False
        self.offline = False
        self.break_download = False
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "POST":
            self.posts += 1
            if self.post_error:
                raise httpx.ReadTimeout("response lost", request=request)
            return httpx.Response(200, json={"id": f"upstream-{self.posts}", "status": "queued"})
        if self.missing:
            return httpx.Response(404)
        if request.url.path.endswith("/content"):
            self.downloads += 1
            if self.break_download:
                self.break_download = False
                return httpx.Response(200, stream=BrokenDownload())
            return httpx.Response(200, content=b"test-video-content", headers={"Content-Type": "video/mp4"})
        return httpx.Response(200, json={"status": self.status, "progress": 42})


async def fake_probe(path):
    assert path.read_bytes() == b"test-video-content"
    return {"width": 1344, "height": 768, "fps": 24, "duration_seconds": 124 / 24}


@pytest.fixture
async def setup(tmp_path):
    upstream = Upstream()
    client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(upstream))
    settings = Settings(data_root=tmp_path, poll_seconds=0.01)
    service = Service(settings, client=client, probe=fake_probe)
    yield service, upstream
    await client.aclose()


def enqueue(service, prompt="一只鸟飞过湖面", client_id=None):
    return service.store.submit(client_id or str(uuid4()), prompt, None, service.settings.model_id, 5)


@pytest.fixture
async def api(setup):
    service, upstream = setup

    async def idle():
        await asyncio.Event().wait()

    service.run = idle
    app = create_app(service=service)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client, service, upstream


async def test_end_to_end_job_uses_native_h3_fields_and_atomic_result(setup):
    service, upstream = setup
    job = enqueue(service)
    await service.tick()
    assert service.store.get(job["id"])["status"] == "running"
    await service.tick()
    assert service.store.get(job["id"])["status"] == "transferring"
    assert not (service.settings.media_dir / f'{job["id"]}.mp4').exists()
    await service.tick()
    result = service.store.public(service.store.get(job["id"]))
    assert result["status"] == "succeeded"
    assert result["video"]["duration_seconds"] == 124 / 24
    assert result["timings"]["total_seconds"] >= 0
    assert result["video_url"].endswith(".mp4")
    assert not list(service.settings.media_dir.glob("*.part"))
    body = json.loads(next(r for r in upstream.requests if r.method == "POST").content)
    assert body["task"] == "t2va"
    assert body["target"] == {"short_edge": 768, "aspect_ratio": "16:9", "duration_seconds": 5}
    assert "num_frames" not in body and "fps" not in body


async def test_idempotent_submission_and_conflicting_input(api):
    client, service, upstream = api
    body = {"prompt": "雪山", "client_request_id": str(uuid4())}
    first = await client.post("/api/jobs", json=body)
    second = await client.post("/api/jobs", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    conflict = await client.post("/api/jobs", json={**body, "prompt": "森林"})
    assert conflict.status_code == 409
    assert service.store.waiting() == 1
    # Retrieving an accepted retry remains possible even if inference goes offline.
    upstream.offline = True
    service.checked_at = 0
    assert (await client.post("/api/jobs", json=body)).status_code == 202


async def test_one_active_five_waiting_and_queue_full(api):
    client, service, upstream = api
    enqueue(service)
    await service.tick()
    for _ in range(5):
        result = await client.post("/api/jobs", json={"prompt": "云", "client_request_id": str(uuid4())})
        assert result.status_code == 202
    response = await client.post("/api/jobs", json={"prompt": "雨", "client_request_id": str(uuid4())})
    assert response.status_code == 429
    assert upstream.posts == 1
    assert service.store.waiting() == 5


async def test_offline_rejects_new_tasks_and_health_reports_it(api):
    client, service, upstream = api
    upstream.offline = True
    response = await client.post("/api/jobs", json={"prompt": "雨", "client_request_id": str(uuid4())})
    assert response.status_code == 503
    assert (await client.get("/api/health")).json()["inference"]["status"] == "offline"
    assert service.store.waiting() == 0


async def test_lost_submission_response_blocks_dispatch_and_can_be_attached(setup):
    service, upstream = setup
    first = enqueue(service)
    second = enqueue(service)
    upstream.post_error = True
    await service.tick()
    await service.tick()
    assert service.store.get(first["id"])["status"] == "submission_unknown"
    assert service.store.get(second["id"])["status"] == "queued"
    assert upstream.posts == 1
    assert service.health_response()["inference"]["status"] == "blocked"
    service.store.resolve(first["id"], "upstream-1")
    await service.tick()
    await service.tick()
    assert service.store.get(first["id"])["status"] == "succeeded"
    assert upstream.posts == 1


async def test_restart_recovers_running_without_resubmission(setup):
    service, upstream = setup
    job = enqueue(service)
    await service.tick()
    restarted = Service(service.settings, client=service.client, probe=fake_probe)
    restarted.store.recover()
    await restarted.tick()
    await restarted.tick()
    assert restarted.store.get(job["id"])["status"] == "succeeded"
    assert upstream.posts == 1


async def test_restart_of_submitting_is_unknown_and_operator_can_fail(setup):
    service, upstream = setup
    job = enqueue(service)
    service.store.claim()
    service.store.recover()
    await service.tick()
    assert service.store.get(job["id"])["status"] == "submission_unknown"
    assert upstream.posts == 0
    service.store.resolve(job["id"])
    assert service.store.get(job["id"])["status"] == "failed"
    with pytest.raises(ValueError):
        service.store.resolve(job["id"], "another-id")


async def test_lost_upstream_job_becomes_failed(setup):
    service, upstream = setup
    job = enqueue(service)
    await service.tick()
    upstream.missing = True
    await service.tick()
    result = service.store.get(job["id"])
    assert result["status"] == "failed"
    assert result["error_code"] == "upstream_job_lost"
    assert upstream.posts == 1


async def test_download_interruption_retries_only_content(setup):
    service, upstream = setup
    job = enqueue(service)
    await service.tick()
    await service.tick()
    upstream.break_download = True
    await service.tick()
    assert service.store.get(job["id"])["status"] == "transferring"
    assert not list(service.settings.media_dir.glob("*.part"))
    await service.tick()
    assert service.store.get(job["id"])["status"] == "succeeded"
    assert upstream.posts == 1 and upstream.downloads == 2


async def test_invalid_video_does_not_publish_result(setup):
    service, upstream = setup

    async def bad_probe(path):
        raise ValueError("bad video")

    service.probe = bad_probe
    job = enqueue(service)
    for _ in range(3):
        await service.tick()
    assert service.store.get(job["id"])["status"] == "failed"
    assert not list(service.settings.media_dir.iterdir())


async def test_crash_after_atomic_rename_recovers_local_result(setup):
    service, upstream = setup
    job = enqueue(service)
    await service.tick()
    await service.tick()
    (service.settings.media_dir / f'{job["id"]}.mp4').write_bytes(b"test-video-content")
    upstream.offline = True
    await service.tick()
    assert service.store.get(job["id"])["status"] == "succeeded"
    assert upstream.downloads == 0


async def test_video_range_and_expired_response(api):
    client, service, upstream = api
    job = enqueue(service)
    for _ in range(3):
        await service.tick()
    response = await client.get(f'/media/{job["id"]}.mp4', headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"test"
    service.store.update(job["id"], completed_at=time.time() - 86401)
    service.maintain_cache()
    assert (await client.get(f'/media/{job["id"]}.mp4')).status_code == 410
    result = (await client.get(f'/api/jobs/{job["id"]}')).json()
    assert result["media_expired"] is True and result["video_url"] is None


async def test_capacity_evicts_oldest_completed_and_preserves_records(setup):
    service, upstream = setup
    service.settings = replace(service.settings, cache_max_bytes=25)
    old = enqueue(service)
    for _ in range(3):
        await service.tick()
    new = enqueue(service)
    for _ in range(3):
        await service.tick()
    assert service.store.get(old["id"])["media_expired"] == 1
    assert service.store.get(new["id"])["media_expired"] == 0
    assert service.store.get(old["id"])["status"] == "succeeded"
    assert sum(p.stat().st_size for p in service.settings.media_dir.glob("*.mp4")) <= 25


async def test_two_backend_processes_cannot_own_one_queue(setup):
    service, upstream = setup
    second = Service(service.settings, client=service.client)
    await service.start()
    try:
        with pytest.raises(RuntimeError, match="Only one"):
            await second.start()
    finally:
        await service.stop()


def test_concurrent_claim_has_single_winner(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    for _ in range(3):
        store.submit(str(uuid4()), "天空", None, "H3", 5)
    with ThreadPoolExecutor(max_workers=4) as executor:
        winners = list(executor.map(lambda _: store.claim(), range(4)))
    assert sum(item is not None for item in winners) == 1
    assert store.waiting() == 2


def test_concurrent_idempotency_has_one_record(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    client_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = list(executor.map(lambda _: store.submit(client_id, "天空", None, "H3", 5), range(4)))
    assert len({job["id"] for job in jobs}) == 1
    assert store.waiting() == 1


async def test_database_failure_after_upstream_acceptance_never_resubmits(setup):
    service, upstream = setup
    job = enqueue(service)
    original = service.store.update

    def interrupted_update(job_id, **fields):
        if fields.get("upstream_id"):
            raise RuntimeError("database write interrupted")
        return original(job_id, **fields)

    service.store.update = interrupted_update
    with pytest.raises(RuntimeError):
        await service.tick()
    service.store.update = original
    await service.tick()
    assert service.store.get(job["id"])["status"] == "submission_unknown"
    assert upstream.posts == 1


async def test_active_media_lease_prevents_deletion_and_defers_capacity(setup):
    service, upstream = setup
    job = enqueue(service)
    for _ in range(3):
        await service.tick()
    path = service.settings.media_dir / f'{job["id"]}.mp4'
    service.media_leases[job["id"]] = 1
    service.settings = replace(service.settings, cache_max_bytes=25)
    assert service.maintain_cache(incoming_bytes=20) is False
    assert path.exists()
    service.store.update(job["id"], completed_at=time.time() - 86401)
    service.maintain_cache()
    assert path.exists()
    service.media_leases.pop(job["id"])
    service.maintain_cache()
    assert not path.exists()
    assert service.store.get(job["id"])["media_expired"] == 1


async def test_real_ffmpeg_media_probe_download_and_range(api, tmp_path):
    import shutil
    import subprocess

    from app.service import inspect_video

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe are required for real-media verification")
    client, service, upstream = api
    fixture = tmp_path / "synthetic-media-fixture.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=blue:s=320x180:r=24", "-t", "0.5", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(fixture)],
        check=True, capture_output=True, timeout=30,
    )
    video_bytes = fixture.read_bytes()

    async def with_real_media(request):
        if request.url.path.endswith("/content"):
            upstream.downloads += 1
            return httpx.Response(200, content=video_bytes, headers={"Content-Type": "video/mp4"})
        return await upstream(request)

    async with httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(with_real_media)) as upstream_client:
        service.client = upstream_client
        service.probe = inspect_video
        submitted = await client.post("/api/jobs", json={"prompt": "媒体路径测试", "client_request_id": str(uuid4())})
        assert submitted.status_code == 202
        job_id = submitted.json()["id"]
        for _ in range(3):
            await service.tick()
        completed = (await client.get(f"/api/jobs/{job_id}")).json()
        assert completed["status"] == "succeeded"
        assert completed["video"] == {"width": 320, "height": 180, "fps": 24.0, "duration_seconds": 0.5}
        result = service.settings.media_dir / f"{job_id}.mp4"
        assert result.read_bytes() == video_bytes
        assert not list(service.settings.media_dir.glob("*.part"))
        ranged = await client.get(completed["video_url"], headers={"Range": "bytes=0-31"})
        assert ranged.status_code == 206
        assert ranged.content == video_bytes[:32]
        assert upstream.posts == 1 and upstream.downloads == 1
