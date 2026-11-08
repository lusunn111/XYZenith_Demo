from contextlib import asynccontextmanager
from uuid import UUID
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .service import Service
from .store import QueueFull, RequestConflict


class LeasedFileResponse(FileResponse):
    def __init__(self, instance, job_id, path):
        super().__init__(path, media_type="video/mp4", filename=f"{job_id}.mp4",
                         content_disposition_type="inline", headers={"Cache-Control": "no-cache"})
        self.instance = instance
        self.job_id = job_id
        instance.media_leases[job_id] = instance.media_leases.get(job_id, 0) + 1

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            remaining = self.instance.media_leases[self.job_id] - 1
            if remaining:
                self.instance.media_leases[self.job_id] = remaining
            else:
                self.instance.media_leases.pop(self.job_id)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=10000)
    client_request_id: UUID
    seed: int | None = Field(default=None, ge=0, le=4294967295)

    @field_validator("prompt")
    @classmethod
    def trim_prompt(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入提示词。")
        return value


def error(status, code, message):
    return HTTPException(status, detail={"code": code, "message": message})


def create_app(settings=None, service=None):
    @asynccontextmanager
    async def lifespan(application):
        instance = service or Service(settings or Settings.from_env())
        application.state.service = instance
        await instance.start()
        try:
            yield
        finally:
            await instance.stop()

    application = FastAPI(title="XYZenith Demo", lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exception):
        return JSONResponse(status_code=422, content={"detail": {
            "code": "invalid_request", "message": "请求参数无效，请检查提示词、请求编号和随机种子。"}})

    @application.get("/api/health")
    async def health(request: Request):
        instance = request.app.state.service
        await instance.refresh_health()
        return instance.health_response()

    @application.post("/api/jobs", status_code=202)
    async def create_job(body: JobRequest, request: Request):
        instance = request.app.state.service
        client_id = str(body.client_request_id)
        existing = instance.store.by_client_id(client_id)
        if existing:
            if existing["prompt"] != body.prompt or existing["seed"] != body.seed:
                raise error(409, "request_conflict", "该请求编号已用于另一组生成参数。")
            return instance.store.public(existing)
        await instance.refresh_health()
        if instance.health_response()["inference"]["status"] != "online":
            raise error(503, "inference_unavailable", "推理服务暂不可用，请稍后重试。")
        try:
            job = instance.store.submit(client_id, body.prompt, body.seed,
                                        instance.settings.model_id, instance.settings.queue_capacity,
                                        generation=instance.settings.generation)
        except QueueFull:
            raise error(429, "queue_full", "等待队列已满，请稍后重试。")
        except RequestConflict:
            raise error(409, "request_conflict", "该请求编号已用于另一组生成参数。")
        return instance.store.public(job)

    @application.get("/api/jobs/{job_id}")
    async def get_job(job_id: UUID, request: Request):
        instance = request.app.state.service
        job = instance.store.get(str(job_id))
        if job is None:
            raise error(404, "job_not_found", "未找到该生成任务。")
        if job["status"] == "succeeded" and not (instance.settings.media_dir / f"{job_id}.mp4").exists():
            instance.store.update(str(job_id), media_expired=1)
            job["media_expired"] = 1
        if job["status"] == "succeeded" and time.time() - job["completed_at"] >= instance.settings.cache_ttl_seconds:
            job["media_expired"] = 1
        return instance.store.public(job)

    @application.api_route("/media/{job_id}.mp4", methods=["GET", "HEAD"])
    async def media(job_id: UUID, request: Request):
        instance = request.app.state.service
        job = instance.store.get(str(job_id))
        if job is None or job["status"] != "succeeded":
            raise error(404, "media_not_found", "视频尚未生成或任务不存在。")
        path = instance.settings.media_dir / f"{job_id}.mp4"
        expired = time.time() - job["completed_at"] >= instance.settings.cache_ttl_seconds
        if job["media_expired"] or expired or not path.exists():
            raise error(410, "media_expired", "视频缓存已过期。")
        return LeasedFileResponse(instance, str(job_id), path)

    return application


app = create_app()
