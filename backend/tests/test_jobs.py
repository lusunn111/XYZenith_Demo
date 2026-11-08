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
        self.progress = 42
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
        return httpx.Response(200, json={"status": self.status, "progress": self.progress})


async def fake_probe(path):
    assert path.read_bytes() == b"test-video-content"
    return {"width": 864, "height": 480, "fps": 24, "duration_seconds": 124 / 24}


@pytest.fixture
async def setup(tmp_path):
    upstream = Upstream()
    client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(upstream))
    settings = Settings(data_root=tmp_path, poll_seconds=0.01)
    service = Service(settings, client=client, probe=fake_probe)
    yield service, upstream
    await client.aclose()


def enqueue(service, prompt="一只鸟飞过湖面", client_id=None):
    return service.store.submit(client_id or str(uuid4()), prompt, None, service.settings.model_id, 5,
                                generation=service.settings.generation)


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
    assert body["target"] == {"short_edge": 480, "aspect_ratio": "16:9", "duration_seconds": 5}
    assert body["num_inference_steps"] == 5
    assert body["flow_shift"] == 12 and body["audio_flow_shift"] == 3
    assert body["quality"] == "lossless"
    assert "profile" not in body
    assert result["generation"] == service.settings.generation
    assert "num_frames" not in body and "fps" not in body


async def test_health_and_submission_share_configured_profile(api):
    client, service, upstream = api
    service.settings = replace(service.settings, short_edge=768, num_inference_steps=4)
    health = (await client.get("/api/health")).json()
    response = await client.post("/api/jobs", json={
        "prompt": "海岸", "seed": 0, "client_request_id": str(uuid4()),
    })
    assert response.status_code == 202
    assert response.json()["generation"] == service.settings.generation
    await service.tick()
    body = json.loads(next(r for r in upstream.requests if r.method == "POST").content)
    assert body["target"] == {key: value for key, value in health["model"].items() if key != "id"}
    assert body["num_inference_steps"] == 4 and body["seed"] == 0


@pytest.mark.parametrize("progress, expected", [
    (0, None), (0.0, None), (None, None), (True, None), (False, None),
    (-1, None), (101, None), ("42", None), (1, 1.0), (42.5, 42.5), (100, 100.0),
])
async def test_poll_exposes_only_reported_positive_percentages(api, progress, expected):
    client, service, upstream = api
    upstream.status = "queued"
    upstream.progress = progress
    job = enqueue(service)
    await service.tick()
    # Clear a previously persisted placeholder on the next successful poll.
    service.store.update(job["id"], progress=0)
    await service.tick()
    response = await client.get(f'/api/jobs/{job["id"]}')
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "running"
    assert result["progress"] == expected
    assert result["created_at"] and result["started_at"]
    assert result["timings"]["queue_seconds"] >= 0
    assert result["timings"]["total_seconds"] is None
    assert result["error"] is None


async def test_completion_sets_progress_without_upstream_incremental_updates(api):
    client, service, upstream = api
    upstream.status = "queued"
    upstream.progress = 0
    job = enqueue(service)
    await service.tick()
    await service.tick()
    upstream.status = "completed"
    await service.tick()
    result = (await client.get(f'/api/jobs/{job["id"]}')).json()
    assert result["status"] == "transferring"
    assert result["progress"] == 100


@pytest.mark.parametrize("legacy", [False, True])
async def test_api_keeps_saved_generation_when_current_profile_changes(api, legacy):
    client, service, upstream = api
    body = {"prompt": "历史任务", "client_request_id": str(uuid4())}
    if legacy:
        job = service.store.submit(body["client_request_id"], body["prompt"], None,
                                   service.settings.model_id, 5)
        original = service.store.public(job)
    else:
        original = (await client.post("/api/jobs", json=body)).json()
    original_target = original["generation"]["target"]
    service.settings = replace(service.settings,
                               short_edge=480 if legacy else 768,
                               num_inference_steps=4)
    health = (await client.get("/api/health")).json()
    assert health["model"]["short_edge"] != original_target["short_edge"]
    restored = await client.get(f'/api/jobs/{original["id"]}')
    retried = await client.post("/api/jobs", json=body)
    assert restored.status_code == 200 and retried.status_code == 202
    for response in (restored, retried):
        assert response.json()["generation"] == original["generation"]
        assert response.json()["id"] == original["id"]
    assert service.store.waiting() == 1 and upstream.posts == 0


async def test_queued_profile_survives_restart_and_changed_config_fails_explicitly(setup):
    service, upstream = setup
    job = enqueue(service)
    changed = replace(service.settings, num_inference_steps=4)
    restarted = Service(changed, client=service.client, probe=fake_probe)
    await restarted.tick()
    result = restarted.store.public(restarted.store.get(job["id"]))
    assert result["generation"]["num_inference_steps"] == 5
    assert result["error"]["code"] == "generation_profile_changed"
    assert result["status"] == "failed" and upstream.posts == 0


async def test_old_queued_job_preserves_original_profile_without_dispatch(setup):
    service, upstream = setup
    job = service.store.submit(str(uuid4()), "旧任务", None, service.settings.model_id, 5)
    await service.tick()
    result = service.store.public(service.store.get(job["id"]))
    assert result["generation"]["target"]["short_edge"] == 768
    assert result["generation"]["profile"] == "h3-original-fl2va"
    assert result["error"]["code"] == "generation_profile_changed"
    assert upstream.posts == 0


async def test_running_job_recovers_with_original_snapshot_after_profile_change(setup):
    service, upstream = setup
    job = enqueue(service)
    await service.tick()
    changed = replace(service.settings, num_inference_steps=4)
    restarted = Service(changed, client=service.client, probe=fake_probe)
    restarted.store.recover()
    await restarted.tick()
    await restarted.tick()
    result = restarted.store.public(restarted.store.get(job["id"]))
    assert result["status"] == "succeeded"
    assert result["generation"]["num_inference_steps"] == 5
    assert upstream.posts == 1


def test_existing_database_adds_snapshot_column_without_rewriting_old_jobs(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    store = Store(database)
    job = store.submit(str(uuid4()), "历史任务", None, "MiniMaxAI/MiniMax-H3", 5)
    with store.connection() as db:
        db.execute("ALTER TABLE jobs DROP COLUMN generation_json")
    migrated = Store(database)
    result = migrated.public(migrated.get(job["id"]))
    assert result["prompt"] == "历史任务"
    assert result["generation"]["target"]["short_edge"] == 768
    assert result["status"] == "queued"


def test_generation_settings_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("XYZ_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("H3_SHORT_EDGE", "480")
    monkeypatch.setenv("H3_NUM_INFERENCE_STEPS", "4")
    monkeypatch.setenv("H3_FLOW_SHIFT", "12")
    monkeypatch.setenv("H3_AUDIO_FLOW_SHIFT", "3")
    settings = Settings.from_env()
    assert settings.generation["target"]["short_edge"] == 480
    assert settings.generation["num_inference_steps"] == 4
    monkeypatch.setenv("H3_AUDIO_FLOW_SHIFT", "nan")
    with pytest.raises(ValueError, match="finite"):
        Settings.from_env()


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
