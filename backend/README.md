# 业务后端

使用 Python 3.11+、FastAPI 和 SQLite。一个后端进程拥有一个持久化任务队列，最多一个推理任务执行、五个任务等待。后台独立轮询 SGLang，浏览器关闭后任务继续执行。

## 安装与运行

在 backend 目录执行以下命令，系统需安装包含 ffprobe 的 FFmpeg。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
.venv/bin/pip install --no-deps .
export XYZ_DATA_ROOT=/var/lib/xyzenith
export SGLANG_BASE_URL=http://127.0.0.1:13010
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 --workers 1
```

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `XYZ_DATA_ROOT` | `./runtime` | SQLite、进程锁和媒体缓存目录 |
| `SGLANG_BASE_URL` | `http://127.0.0.1:13010` | 隧道映射后的 SGLang 地址 |
| `CACHE_MAX_BYTES` | `2147483648` | 视频缓存容量上限，包含正在下载的结果 |
| `CACHE_TTL_SECONDS` | `86400` | 已完成视频缓存保留时间 |
| `POLL_SECONDS` | `2` | 后台任务轮询间隔 |
| `H3_MODEL_ID` | `MiniMaxAI/MiniMax-H3` | 上游服务模型名 |
| `H3_GENERATION_PROFILE` | `h3-lightx2v-fl2v-v0.1-4step` | 已部署权重与适配器配置标识 |
| `H3_SHORT_EDGE` | `480` | 输出目标短边，健康接口同步展示 |
| `H3_NUM_INFERENCE_STEPS` | `5` | v0.5.19 的五个调度点对应四次前向，v0.5.23 应设为 `4` |
| `H3_FLOW_SHIFT` / `H3_AUDIO_FLOW_SHIFT` | `12` / `3` | 视频与音频的采样时间偏移 |
| `H3_QUALITY` | `lossless` | 推理质量配置，可设 `exact` |

数据库位于 `XYZ_DATA_ROOT/jobs.sqlite3`，视频位于其 `media` 子目录。缓存删除仅涉及数据库登记的本项目视频。进程锁会拒绝第二个后端进程同时使用同一数据库。

## API

| 接口 | 行为 |
| --- | --- |
| `POST /api/jobs` | 接收 `prompt`、UUID 格式 `client_request_id` 和可选 `seed`，返回 202 与任务对象 |
| `GET /api/jobs/{id}` | 返回状态、视频元数据、URL 与分阶段计时 |
| `GET /api/health` | 返回推理可用性、排队数量及固定模型规格 |
| `GET /media/{id}.mp4` | 播放或下载视频，支持 Range；缓存过期返回 410 |

同一个客户端请求编号对应同一任务，相同编号携带不同提示词或种子返回 409。推理服务离线或被待核对提交阻塞时，新请求返回 503。等待队列已满返回 429。默认采用 MiniMax-H3 FL2VA 加 LightX2V v0.1 四步 LoRA 的 `t2va` 请求，目标短边 480、16:9、5 秒，使用上游实际输出元数据。上游服务须按同一适配器与运行版本配置，业务后端通过上述环境变量固定请求参数。

每个任务在创建时保存生成配置快照，API 的 `generation` 字段返回该快照。数据库升级自动补充快照列，既有记录按原版 768p 配置解释。重复提交仍返回原任务。队列中的任务若与当前运行配置不匹配，会以 `generation_profile_changed` 明确失败并保留原参数，用户可按新配置重新提交。

状态流转为 `queued`、`submitting`、`running`、`transferring`、`succeeded`，异常状态为 `submission_unknown` 与 `failed`。视频完整下载、ffprobe 检查及原子改名完成后才返回播放地址。生成服务耗时按 VPS 观测时间计算，包含轮询误差。

## 中断恢复

已记录上游编号的任务会在后端重启后恢复查询。上游返回 404 时任务标记失败。视频传输失败会重新下载同一上游任务结果。

提交响应丢失或派发中后端退出时，任务进入 `submission_unknown` 并暂停后续派发。维护者核对 SGLang 的任务列表及日志后，在相同后端运行环境执行以下命令。

```bash
# 确认对应的上游任务编号后恢复查询
python -m app.manage JOB_UUID --attach-upstream VIDEO_ID

# 确认上游未接受请求后，结束该任务并恢复队列
python -m app.manage JOB_UUID --confirm-failed
```

这些命令在 SQLite 事务内更新待核对任务，运行中的执行器在下一轮观察变更。确认失败后，用户可以发起新任务。

## 验证

```bash
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```

测试通过模拟 HTTP 上游覆盖原生请求字段、队列容量、并发去重、单执行者、提交响应丢失、数据库写入中断、后端重启、上游任务丢失、下载中断、缓存容量与到期、视频范围请求及播放期间缓存保护。媒体检查在这些故障测试中使用替身，真实 H3 生成与真实媒体检查由部署验收完成。
