import { useState } from "react";
import type { Job, JobStatus } from "./api";

const stateLabels: Record<JobStatus, string> = {
  queued: "等待执行",
  submitting: "正在提交到推理服务",
  submission_unknown: "提交结果待核对",
  running: "正在生成视频",
  transferring: "正在传输视频",
  succeeded: "生成完成",
  failed: "生成失败",
};
const generationStages = ["等待执行", "生成音视频", "传输结果"];
const stageIndex: Record<JobStatus, number> = {
  queued: 0,
  submitting: 0,
  submission_unknown: -1,
  running: 1,
  transferring: 2,
  succeeded: 3,
  failed: -1,
};

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds))
    return "—";
  if (seconds < 60) return `${Math.max(0, seconds).toFixed(1)} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${Math.floor(seconds % 60)} 秒`;
}

interface Props {
  job: Job | null;
  loading: boolean;
  error: string | null;
  elapsed: number | null;
  playableSeconds: number | null;
  onPlayable: () => void;
  onNewTask: () => void;
  inspirationPrompt: string;
  onUseInspiration: () => void;
  canUseInspiration: boolean;
}

export default function ResultPanel({
  job,
  loading,
  error,
  elapsed,
  playableSeconds,
  onPlayable,
  onNewTask,
  inspirationPrompt,
  onUseInspiration,
  canUseInspiration,
}: Props) {
  const [playbackError, setPlaybackError] = useState(false);
  const active = job !== null && !["succeeded", "failed"].includes(job.status);
  const busy = loading || (active && job?.status !== "submission_unknown");
  const hasVideo = Boolean(job?.video_url && !job.media_expired);
  const title = job ? stateLabels[job.status] : "视频预览";
  const progress = job?.progress;
  const showInspiration = !job && !loading && !error;

  return (
    <section className="result-panel" aria-labelledby="result-heading">
      <div className="section-heading">
        <h2 id="result-heading">{showInspiration ? "预览画布" : "生成结果"}</h2>
        {job || error ? (
          <button className="text-button" type="button" onClick={onNewTask}>
            新建任务 <span aria-hidden="true">↗</span>
          </button>
        ) : (
          <span className="muted">从一帧灵感开始</span>
        )}
      </div>
      <div
        className={`preview ${active ? "preview-active" : ""} ${showInspiration ? "preview-inspiration" : ""}`}
      >
        {showInspiration ? (
          <>
            <img
              className="inspiration-image"
              src="/images/coastal-observatory.jpg"
              width={1500}
              height={844}
              alt="暮色海岸上的混凝土圆环建筑，夕阳穿过圆环，远处海雾层叠"
              fetchPriority="high"
            />
            <div className="inspiration-overlay" />
            <span className="image-label">
              <i aria-hidden="true" />
              灵感预览 · 静态图
            </span>
            <div className="inspiration-title">
              <span>海岸建筑 / 电影感航拍</span>
              <h3>潮汐之间</h3>
            </div>
            <span className="image-credit">AI 生成灵感图</span>
          </>
        ) : hasVideo && job ? (
          <>
            <video
              key={job.video_url}
              src={job.video_url!}
              controls
              playsInline
              preload="metadata"
              aria-label="生成的视频"
              onLoadedData={() => {
                setPlaybackError(false);
                onPlayable();
              }}
              onError={() => setPlaybackError(true)}
            />
            {playbackError ? (
              <div className="player-error" role="alert">
                视频暂时无法播放，请刷新页面检查缓存状态。
              </div>
            ) : null}
          </>
        ) : (
          <div className="preview-placeholder">
            <div
              className={`frame-symbol ${busy ? "frame-symbol-working" : ""}`}
              aria-hidden="true"
            >
              <i />
              <i />
              <i />
              <span>{busy ? "✦" : "◇"}</span>
            </div>
            <h3>
              {error && !job
                ? "暂时无法读取任务"
                : loading && !job
                  ? "正在恢复任务"
                  : title}
            </h3>
            <p>
              {job?.status === "queued"
                ? `前方等待 ${Math.max(0, (job.queue_position ?? 1) - 1)} 个任务，轮到后会自动开始。`
                : null}
              {job?.status === "submitting" ? "正在连接 A100 推理实例。" : null}
              {job?.status === "running"
                ? "模型正在生成画面与声音，页面可随时刷新。"
                : null}
              {job?.status === "transferring"
                ? "生成已完成，正在准备可播放的视频。"
                : null}
              {job?.status === "submission_unknown"
                ? "提交结果需维护者核对，队列已暂停。"
                : null}
              {job?.status === "failed"
                ? job.error?.message || "生成过程中出现错误，请重新提交。"
                : null}
              {job?.media_expired
                ? "视频缓存已过期，原始文件保留在实验室数据盘。"
                : null}
              {job?.status === "succeeded" && !job.media_expired
                ? "正在获取视频地址。"
                : null}
            </p>
            {active && elapsed !== null ? (
              <span className="elapsed">
                已等待 <strong>{formatSeconds(elapsed)}</strong>
              </span>
            ) : null}
            {active && progress !== null && progress !== undefined ? (
              <div className="progress-container">
                <progress
                  value={progress}
                  max={100}
                  aria-label="推理服务报告的进度"
                />
                <span>{Math.round(progress)}%</span>
              </div>
            ) : null}
          </div>
        )}
      </div>
      {error ? (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      ) : null}
      {job ? (
        <div className="result-details">
          {active && stageIndex[job.status] >= 0 ? (
            <ol className="generation-stages" aria-label="任务阶段">
              {generationStages.map((stage, index) => (
                <li
                  key={stage}
                  className={
                    index < stageIndex[job.status] ? "stage-complete" : ""
                  }
                  aria-current={
                    index === stageIndex[job.status] ? "step" : undefined
                  }
                >
                  <i aria-hidden="true" />
                  {stage}
                </li>
              ))}
            </ol>
          ) : null}
          <div className="job-reference">
            <span>任务编号</span>
            <code>{job.id}</code>
          </div>
          <div className="result-status-row">
            <span className={`job-state state-${job.status}`} role="status">
              <i aria-hidden="true" />
              {job.media_expired ? "视频缓存已过期" : title}
            </span>
            {hasVideo ? (
              <a
                className="download-button"
                href={job.video_url!}
                download={`${job.id}.mp4`}
              >
                下载视频 <span aria-hidden="true">↓</span>
              </a>
            ) : null}
          </div>
          {job.video ? (
            <div className="video-metadata">
              <span>
                {job.video.width} × {job.video.height}
              </span>
              <span>{formatSeconds(job.video.duration_seconds)}</span>
              <span>{Number(job.video.fps.toFixed(2))} 帧 / 秒</span>
              {job.seed !== null ? <span>种子 {job.seed}</span> : null}
            </div>
          ) : null}
          <dl className="timing-grid">
            <div>
              <dt>排队</dt>
              <dd>{formatSeconds(job.timings.queue_seconds)}</dd>
            </div>
            <div>
              <dt>生成服务</dt>
              <dd>{formatSeconds(job.timings.generation_seconds)}</dd>
            </div>
            <div>
              <dt>结果传输</dt>
              <dd>{formatSeconds(job.timings.transfer_seconds)}</dd>
            </div>
            <div>
              <dt>服务总耗时</dt>
              <dd>{formatSeconds(job.timings.total_seconds)}</dd>
            </div>
          </dl>
          {playableSeconds !== null ? (
            <p className="playable-time">
              本次提交至可播放 <strong>{formatSeconds(playableSeconds)}</strong>
            </p>
          ) : null}
          <details className="task-details">
            <summary>任务详情</summary>
            <dl>
              <div>
                <dt>任务编号</dt>
                <dd>{job.id}</dd>
              </div>
              <div>
                <dt>模型</dt>
                <dd>{job.model_id}</dd>
              </div>
              <div>
                <dt>创建时间</dt>
                <dd>{new Date(job.created_at).toLocaleString("zh-CN")}</dd>
              </div>
              <div>
                <dt>提示词</dt>
                <dd>{job.prompt}</dd>
              </div>
            </dl>
            <p>生成服务耗时包含推理服务处理及约 2 秒状态查询间隔的观测误差。</p>
          </details>
        </div>
      ) : showInspiration ? (
        <div className="inspiration-caption">
          <div className="inspiration-caption-heading">
            <h3>给想象一个起点</h3>
            <button
              className="text-button"
              type="button"
              onClick={onUseInspiration}
              disabled={!canUseInspiration}
            >
              使用这段描述 <span aria-hidden="true">↗</span>
            </button>
          </div>
          <p>{inspirationPrompt}</p>
        </div>
      ) : null}
    </section>
  );
}
