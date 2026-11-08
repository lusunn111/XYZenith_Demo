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
const legacyTarget = {
  short_edge: 768,
  aspect_ratio: "16:9",
  duration_seconds: 5,
};
const promptExamples = [
  {
    label: "海岸建筑",
    prompt:
      "暮色中的荒凉海岸，巨大的混凝土圆环矗立在悬崖上。镜头缓缓掠过深青色海面，穿过薄雾向圆环推进，暖金色夕阳从环中透出，海浪轻拍礁石，电影感航拍。",
  },
  {
    label: "雨夜街景",
    prompt:
      "雨后的城市深夜，暖色霓虹倒映在湿润的街道上。一位撑着透明雨伞的行人走过画面，镜头低角度缓慢跟随。远处传来电车声，近处是雨滴落在伞面的细碎声响，电影感长镜头。",
  },
  {
    label: "微观世界",
    prompt:
      "清晨的森林，一颗晶莹露珠停在苔藓叶尖，映出周围的绿色世界。微距镜头缓慢推近，一只小瓢虫从叶片后走来，露珠轻轻滑落。柔和逆光，浅景深，伴随清脆鸟鸣。",
  },
];

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
  const inputLocked = submitting || Boolean(pending) || Boolean(jobId);
  const model = job
    ? { id: job.model_id, ...(job.generation?.target || legacyTarget) }
    : jobId
      ? null
      : health?.model;
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
    requestAnimationFrame(() => document.getElementById("prompt")?.focus());
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

  function usePrompt(value: string) {
    if (inputLocked) return;
    setPrompt(value);
    setSubmitError(null);
    document.getElementById("prompt")?.focus();
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
      <a className="skip-link" href="#prompt">
        跳到提示词输入
      </a>
      <header className="site-header">
        <div className="header-left">
          <a className="brand" href="/" aria-label="XYZenith 首页">
            <span className="brand-mark" aria-hidden="true">
              <i />
              <i />
            </span>
            <span>
              XYZenith<span className="brand-dot">.</span>
            </span>
          </a>
          <span className="header-divider" aria-hidden="true" />
          <span className="workspace-nav">创作台</span>
        </div>
        <div className="header-right">
          <div
            className={`service-status ${online ? "is-online" : ""}`}
            role="status"
          >
            <i aria-hidden="true" />
            {healthLabel}
          </div>
          <a
            className="repository-link"
            href="https://github.com/lusunn111/XYZenith_Demo"
            target="_blank"
            rel="noreferrer"
          >
            GitHub <span aria-hidden="true">↗</span>
          </a>
        </div>
      </header>
      <main>
        <div className="page-heading">
          <div>
            <h1>
              把想象，<span>变成影像。</span>
            </h1>
            <p>描述画面、镜头与声音，开始创作你的下一幕。</p>
          </div>
          <span className="creation-mode">
            <i aria-hidden="true" />
            文字生成音视频
          </span>
        </div>
        {health?.mock ? (
          <div className="notice mock-notice" role="status">
            开发模拟模式 · 当前结果用于验证交互。
          </div>
        ) : null}
        <div className="workspace">
          <section className="composer" aria-labelledby="compose-heading">
            <div className="section-heading">
              <h2 id="compose-heading">创作设定</h2>
              <span className="composer-symbol" aria-hidden="true">
                ✳
              </span>
            </div>
            <form onSubmit={submit}>
              <div className="field-heading">
                <label className="field-label" htmlFor="prompt">
                  提示词
                </label>
                <span className="muted">你的画面，从这里开始</span>
              </div>
              <div className="prompt-field">
                <textarea
                  id="prompt"
                  name="prompt"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder={
                    "你想看见怎样的世界？\n\n试着描述主体、环境、镜头运动，以及你想听见的声音…"
                  }
                  disabled={inputLocked}
                  required
                  rows={6}
                />
                <div className="prompt-toolbar">
                  <span>画面 · 镜头 · 声音</span>
                  <span className="character-count" aria-hidden="true">
                    {prompt.length} 字
                  </span>
                </div>
              </div>
              <div className="prompt-examples" aria-label="提示词灵感">
                <span className="muted">试一试</span>
                {promptExamples.map((example) => (
                  <button
                    key={example.label}
                    type="button"
                    className="example-button"
                    disabled={inputLocked}
                    aria-pressed={prompt === example.prompt}
                    onClick={() => usePrompt(example.prompt)}
                  >
                    {example.label}
                  </button>
                ))}
              </div>
              <div className="generation-spec">
                <div className="model-card">
                  <span className="model-symbol" aria-hidden="true">
                    M
                  </span>
                  <div>
                    <span className="spec-label">生成模型</span>
                    <strong>
                      {(model?.id || "MiniMaxAI/MiniMax-H3").split("/").pop()}
                    </strong>
                  </div>
                  <span className="model-capability">音视频</span>
                </div>
                <div className="spec-row">
                  <div>
                    <span className="spec-label">分辨率</span>
                    <strong>{model ? `${model.short_edge}p` : "—"}</strong>
                  </div>
                  <div>
                    <span className="spec-label">画面比例</span>
                    <strong>
                      {model?.aspect_ratio.replace(":", "∶") || "—"}
                    </strong>
                  </div>
                  <div>
                    <span className="spec-label">目标时长</span>
                    <strong>
                      {model ? `约 ${model.duration_seconds} 秒` : "—"}
                    </strong>
                  </div>
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
                  disabled={inputLocked}
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
                <span className="button-spark" aria-hidden="true">
                  ✦
                </span>
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
                <span className="button-arrow" aria-hidden="true">
                  ↗
                </span>
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
            inspirationPrompt={promptExamples[0].prompt}
            onUseInspiration={() => usePrompt(promptExamples[0].prompt)}
            canUseInspiration={!inputLocked}
          />
        </div>
      </main>
      <footer className="site-footer">
        <span>
          XYZenith <span className="footer-separator">/</span> 视频生成实验室
        </span>
        <p>结果缓存保留 24 小时，容量达到上限时优先回收较早视频。</p>
      </footer>
    </div>
  );
}
