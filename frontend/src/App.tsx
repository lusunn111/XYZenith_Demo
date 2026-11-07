import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  isFinished,
  request,
  type CreateJob,
  type Health,
  type Job,
} from "./api";
import ResultPanel from "./ResultPanel";

const pendingKey = "xyzenith.pending.v1";

function readPending(): CreateJob | null {
  try {
    const stored = JSON.parse(sessionStorage.getItem(pendingKey) || "null");
    return stored &&
      typeof stored.prompt === "string" &&
      typeof stored.client_request_id === "string"
      ? stored
      : null;
  } catch {
    return null;
  }
}

function savePending(value: CreateJob | null) {
  try {
    if (value) sessionStorage.setItem(pendingKey, JSON.stringify(value));
    else sessionStorage.removeItem(pendingKey);
  } catch {
    // The in-memory request identifier still allows retries when storage is unavailable.
  }
}

function createRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function currentJobId(): string | null {
  return new URL(location.href).searchParams.get("job");
}

function updateJobUrl(id: string | null) {
  const url = new URL(location.href);
  if (id) url.searchParams.set("job", id);
  else url.searchParams.delete("job");
  history.pushState({}, "", url);
}

export default function App() {
  const [pending, setPending] = useState<CreateJob | null>(readPending);
  const [prompt, setPrompt] = useState(() => readPending()?.prompt || "");
  const [seed, setSeed] = useState(() => readPending()?.seed?.toString() || "");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [jobId, setJobId] = useState(currentJobId);
  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState(Date.now);
  const [playableSeconds, setPlayableSeconds] = useState<number | null>(null);
  const firstSubmission = useRef<{
    start: number;
    jobId: string | null;
  } | null>(null);
  const submitLock = useRef(false);
  const postController = useRef<AbortController | null>(null);
  const active = Boolean(job && !isFinished(job));
  const online = health?.inference.status === "online" && !healthError;
  const queueFull = Boolean(
    health && health.queue.waiting >= health.queue.capacity,
  );
  const canSubmit =
    Boolean(prompt.trim()) &&
    !submitting &&
    !active &&
    !jobId?.length &&
    (Boolean(pending) || (online && !queueFull));
  const healthLabel = healthError
    ? "服务连接中断"
    : !health
      ? "正在连接服务"
      : health.inference.status === "online"
        ? "推理服务在线"
        : health.inference.status === "blocked"
          ? "任务待核对"
          : "推理服务离线";

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const next = await request<Health>("/api/health", {
          signal: controller.signal,
        });
        if (!disposed) {
          setHealth(next);
          setHealthError(null);
        }
      } catch {
        if (!disposed) setHealthError("暂时无法连接业务服务，正在自动重连。");
      } finally {
        if (!disposed) timer = setTimeout(poll, 10_000);
      }
    }
    void poll();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!jobId) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      let delay: number | null = 2000;
      try {
        const next = await request<Job>(
          `/api/jobs/${encodeURIComponent(jobId!)}`,
          { signal: controller.signal },
        );
        if (!disposed) {
          setJob(next);
          setJobError(null);
          setPrompt(next.prompt);
          setSeed(next.seed?.toString() || "");
        }
        if (isFinished(next)) delay = 30_000;
      } catch (error) {
        if (!disposed)
          setJobError(
            error instanceof ApiError
              ? error.message
              : "状态连接中断，任务仍可能在执行，正在自动重连。",
          );
        if (error instanceof ApiError && error.status === 404) delay = null;
      } finally {
        if (!disposed && delay !== null) timer = setTimeout(poll, delay);
      }
    }
    void poll();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId]);

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);

  useEffect(() => {
    const onPopState = () => {
      setJobId(currentJobId());
      setJob(null);
      setJobError(null);
      setPlayableSeconds(null);
      firstSubmission.current = null;
    };
    addEventListener("popstate", onPopState);
    return () => {
      removeEventListener("popstate", onPopState);
      postController.current?.abort();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || submitLock.current) return;
    const parsedSeed = seed.trim() ? Number(seed) : undefined;
    if (
      parsedSeed !== undefined &&
      (!Number.isInteger(parsedSeed) ||
        parsedSeed < 0 ||
        parsedSeed > 4_294_967_295)
    ) {
      setSubmitError("随机种子需为 0 到 4294967295 之间的整数。");
      return;
    }
    const payload = pending || {
      prompt: prompt.trim(),
      seed: parsedSeed,
      client_request_id: createRequestId(),
    };
    if (!pending)
      firstSubmission.current = { start: performance.now(), jobId: null };
    setPending(payload);
    savePending(payload);
    submitLock.current = true;
    setSubmitting(true);
    setSubmitError(null);
    const controller = new AbortController();
    postController.current = controller;
    const timeout = setTimeout(() => controller.abort(), 30_000);
    try {
      const created = await request<Job>("/api/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (firstSubmission.current) firstSubmission.current.jobId = created.id;
      setPending(null);
      savePending(null);
      setJob(created);
      setJobId(created.id);
      setJobError(null);
      setPlayableSeconds(null);
      updateJobUrl(created.id);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500
      ) {
        setPending(null);
        savePending(null);
        firstSubmission.current = null;
        setSubmitError(error.message);
      } else {
        setSubmitError(
          "提交结果尚未确认。点击重试会沿用同一请求编号，核对已有任务。",
        );
      }
    } finally {
      clearTimeout(timeout);
      submitLock.current = false;
      setSubmitting(false);
    }
  }

  function newTask() {
    if (submitting) return;
    setJobId(null);
    setJob(null);
    setJobError(null);
    setSubmitError(null);
    setPlayableSeconds(null);
    firstSubmission.current = null;
    updateJobUrl(null);
    document.getElementById("prompt")?.focus();
  }

  function onPlayable() {
    const measurement = firstSubmission.current;
    if (
      !measurement ||
      measurement.jobId !== job?.id ||
      playableSeconds !== null
    )
      return;
    setPlayableSeconds((performance.now() - measurement.start) / 1000);
  }

  const elapsed = job
    ? Math.max(0, (now - new Date(job.created_at).getTime()) / 1000)
    : null;
  const disabledReason =
    healthError ||
    (!health
      ? "正在连接推理服务…"
      : health.inference.status !== "online"
        ? health.inference.detail || "推理服务准备中，请稍后再试。"
        : queueFull
          ? "等待队列已满，请稍后再试。"
          : null);

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="XYZenith 首页">
          <span className="brand-mark" aria-hidden="true">
            X
          </span>
          <span>XYZenith</span>
        </a>
        <div
          className={`service-status ${online ? "is-online" : ""}`}
          role="status"
        >
          <i aria-hidden="true" />
          {healthLabel}
        </div>
      </header>
      <main>
        <div className="page-heading">
          <div>
            <p className="eyebrow">MiniMax-H3</p>
            <h1>视频生成</h1>
          </div>
          <span className="workspace-label">生成工作台</span>
        </div>
        {health?.mock ? (
          <div className="notice mock-notice" role="status">
            开发模拟模式 · 当前结果用于验证交互。
          </div>
        ) : null}
        <div className="workspace">
          <section className="composer" aria-labelledby="compose-heading">
            <div className="section-heading">
              <h2 id="compose-heading">描述你的画面</h2>
              <span className="muted">文字生成视频</span>
            </div>
            <form onSubmit={submit}>
              <label className="field-label" htmlFor="prompt">
                提示词
              </label>
              <div className="prompt-field">
                <textarea
                  id="prompt"
                  name="prompt"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="例如，一只橘猫坐在雨后的窗边。镜头缓缓推近，窗外传来轻柔的雨声，温暖的光线落在它的毛发上。"
                  disabled={submitting || Boolean(pending) || Boolean(jobId)}
                  required
                  rows={8}
                />
                <span className="character-count" aria-hidden="true">
                  {prompt.length} 字
                </span>
              </div>
              <div className="generation-spec">
                <div>
                  <span>模型</span>
                  <strong>MiniMax-H3</strong>
                </div>
                <div className="spec-row">
                  <span>生成规格</span>
                  <strong>
                    768p <b>·</b> 16∶9 <b>·</b> 约 5 秒
                  </strong>
                </div>
              </div>
              <details className="seed-setting">
                <summary>
                  随机种子 <span>可选</span>
                </summary>
                <label className="field-label" htmlFor="seed">
                  固定种子便于复现实验
                </label>
                <input
                  id="seed"
                  type="number"
                  inputMode="numeric"
                  min="0"
                  max="4294967295"
                  step="1"
                  placeholder="留空随机生成"
                  value={seed}
                  onChange={(event) => setSeed(event.target.value)}
                  disabled={submitting || Boolean(pending) || Boolean(jobId)}
                />
              </details>
              {submitError ? (
                <p className="notice notice-error" role="alert">
                  {submitError}
                </p>
              ) : null}
              <button
                className="generate-button"
                type="submit"
                disabled={!canSubmit}
              >
                <span>
                  {submitting
                    ? "正在提交"
                    : pending
                      ? "重试提交"
                      : active
                        ? "任务执行中"
                        : jobId
                          ? "请先新建任务"
                          : "生成视频"}
                </span>
                <span aria-hidden="true">↗</span>
              </button>
              <div className="submission-caption" aria-live="polite">
                {jobId
                  ? "任务已保存，可刷新页面查看进度。"
                  : pending
                    ? "请重试确认上一次提交的结果。"
                    : disabledReason ||
                      `当前等待 ${health?.queue.waiting ?? 0} 个任务，按提交顺序生成。`}
              </div>
            </form>
          </section>
          <ResultPanel
            key={jobId || "empty"}
            job={job}
            loading={Boolean(jobId && !job && !jobError)}
            error={jobError}
            elapsed={elapsed}
            playableSeconds={playableSeconds}
            onPlayable={onPlayable}
            onNewTask={newTask}
          />
        </div>
      </main>
      <footer className="site-footer">
        <span>XYZenith</span>
        <p>视频缓存保留 24 小时，空间达到上限时优先回收较早结果。</p>
        <span>MiniMax-H3 · A100</span>
      </footer>
    </div>
  );
}
