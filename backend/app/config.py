from dataclasses import dataclass
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

    @classmethod
    def from_env(cls):
        settings = cls(
            data_root=Path(os.getenv("XYZ_DATA_ROOT", "./runtime")).resolve(),
            upstream_url=os.getenv("SGLANG_BASE_URL", "http://127.0.0.1:13010").rstrip("/"),
            cache_max_bytes=int(os.getenv("CACHE_MAX_BYTES", str(2 * 1024**3))),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "86400")),
            poll_seconds=float(os.getenv("POLL_SECONDS", "2")),
        )
        if min(settings.cache_max_bytes, settings.cache_ttl_seconds, settings.poll_seconds) <= 0:
            raise ValueError("Cache and polling settings must be positive")
        return settings

    @property
    def database(self):
        return self.data_root / "jobs.sqlite3"

    @property
    def media_dir(self):
        return self.data_root / "media"

    @property
    def model(self):
        return {"id": self.model_id, "short_edge": 768,
                "aspect_ratio": "16:9", "duration_seconds": 5}
