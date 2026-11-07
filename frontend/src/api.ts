export type JobStatus =
  | "queued"
  | "submitting"
  | "submission_unknown"
  | "running"
  | "transferring"
  | "succeeded"
  | "failed";

export interface Job {
  id: string;
  status: JobStatus;
  prompt: string;
  model_id: string;
  seed: number | null;
  created_at: string;
  started_at: string | null;
  inference_completed_at: string | null;
  completed_at: string | null;
  queue_position: number | null;
  video_url: string | null;
  media_expired: boolean;
  error: { code: string; message: string } | null;
  timings: {
    queue_seconds: number | null;
    generation_seconds: number | null;
    transfer_seconds: number | null;
    total_seconds: number | null;
  };
  video: {
    width: number;
    height: number;
    duration_seconds: number;
    fps: number;
  } | null;
  progress: number | null;
}

export interface Health {
  status: string;
  inference: {
    status: "online" | "offline" | "blocked";
    detail: string | null;
  };
  queue: { waiting: number; capacity: number };
  model: {
    id: string;
    short_edge: number;
    aspect_ratio: string;
    duration_seconds: number;
  };
  mock: boolean;
}

export interface CreateJob {
  prompt: string;
  client_request_id: string;
  seed?: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init.signal?.aborted) abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(abort, init.method === "POST" ? 30_000 : 10_000);
  try {
    const response = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      let message = "请求失败，请稍后重试。";
      if (typeof body?.detail === "string") message = body.detail;
      if (typeof body?.detail?.message === "string")
        message = body.detail.message;
      if (Array.isArray(body?.detail))
        message = "请检查提示词和随机种子的格式。";
      if (response.status === 404)
        message = "找不到这个任务，请检查链接或创建新任务。";
      throw new ApiError(message, response.status, body?.detail?.code);
    }
    if (body === null)
      throw new ApiError("服务返回了无法识别的响应。", response.status);
    return body as T;
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

export function isFinished(job: Job | null): boolean {
  return job?.status === "succeeded" || job?.status === "failed";
}
