from dataclasses import dataclass
import math
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_root: Path
    upstream_url: str = "http://127.0.0.1:13010"
    cache_max_bytes: int = 2 * 1024**3
    cache_ttl_seconds: int = 86400
    poll_seconds: float = 2.0
    queue_capacity: int = 5
    model_id: str = "MiniMaxAI/MiniMax-H3"
    generation_profile: str = "h3-lightx2v-fl2v-v0.1-4step"
    short_edge: int = 480
    num_inference_steps: int = 5
    flow_shift: float = 12.0
    audio_flow_shift: float = 3.0
    quality: str = "lossless"

    def __post_init__(self):
        if min(self.cache_max_bytes, self.cache_ttl_seconds, self.poll_seconds) <= 0:
            raise ValueError("Cache and polling settings must be positive")
        if self.short_edge <= 0 or self.short_edge % 32:
            raise ValueError("H3 short edge must be a positive multiple of 32")
        if self.num_inference_steps not in (4, 5):
            raise ValueError("H3 four-step profile requires 4 or 5 according to the SGLang version")
        if not all(math.isfinite(value) and value > 0 for value in (self.flow_shift, self.audio_flow_shift)):
            raise ValueError("H3 flow shifts must be finite and positive")
        if self.quality not in ("lossless", "exact"):
            raise ValueError("H3 distilled profile supports lossless or exact quality")
        if not self.model_id.strip() or not self.generation_profile.strip():
            raise ValueError("H3 model and generation profile must be nonempty")

    @classmethod
    def from_env(cls):
        settings = cls(
            data_root=Path(os.getenv("XYZ_DATA_ROOT", "./runtime")).resolve(),
            upstream_url=os.getenv("SGLANG_BASE_URL", "http://127.0.0.1:13010").rstrip("/"),
            cache_max_bytes=int(os.getenv("CACHE_MAX_BYTES", str(2 * 1024**3))),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "86400")),
            poll_seconds=float(os.getenv("POLL_SECONDS", "2")),
            model_id=os.getenv("H3_MODEL_ID", "MiniMaxAI/MiniMax-H3"),
            generation_profile=os.getenv("H3_GENERATION_PROFILE", "h3-lightx2v-fl2v-v0.1-4step"),
            short_edge=int(os.getenv("H3_SHORT_EDGE", "480")),
            num_inference_steps=int(os.getenv("H3_NUM_INFERENCE_STEPS", "5")),
            flow_shift=float(os.getenv("H3_FLOW_SHIFT", "12")),
            audio_flow_shift=float(os.getenv("H3_AUDIO_FLOW_SHIFT", "3")),
            quality=os.getenv("H3_QUALITY", "lossless"),
        )
        return settings

    @property
    def database(self):
        return self.data_root / "jobs.sqlite3"

    @property
    def media_dir(self):
        return self.data_root / "media"

    @property
    def model(self):
        return {"id": self.model_id, **self.generation["target"]}

    @property
    def generation(self):
        return {
            "profile": self.generation_profile,
            "task": "t2va",
            "target": {"short_edge": self.short_edge, "aspect_ratio": "16:9", "duration_seconds": 5},
            "num_inference_steps": self.num_inference_steps,
            "flow_shift": self.flow_shift,
            "audio_flow_shift": self.audio_flow_shift,
            "quality": self.quality,
        }
