# MiniMax-H3 推理服务

当前采用官方 MiniMax-H3 FL2VA 权重与 LightX2V v0.1 四步 LoRA，目标为短边 480、16:9、约 5 秒的文本生成音视频。服务监听 A100 本机 `127.0.0.1:30010`，VPS 通过反向 SSH 隧道访问。

模型版本和请求规格记录在 `configs/minimax-h3.json`。`configs/model-manifest.json` 来自 Hugging Face 官方 API 的固定提交，列出 85 个文件、总计 144,051,244,506 字节。大文件使用官方 LFS SHA256 校验，小文件使用 Git blob SHA1 校验。

## 环境与权重准备

在 A100 的 `~/XYZenith_Demo` 执行。经用户确认，模型、隔离环境与缓存使用本地项目数据目录，视频输出保留在共享数据盘。实际位置由 `deploy/gpu/env.sh` 和部署环境指定。

```bash
bash deploy/gpu/prepare-directories.sh
source deploy/gpu/env.sh
bash deploy/gpu/install-runtime.sh cu129
source "$XYZ_VENV_ROOT/sglang-cu129/bin/activate"
export XYZ_H3_MODEL_PATH="$XYZ_MODEL_ROOT/MiniMax-H3"
export XYZ_H3_LORA_PATH="$XYZ_MODEL_ROOT/Minimax-h3-Turbo/minimax_h3_fl2v_turbo_4step_v0.1.safetensors"
python inference/verify-model.py --metadata-only --lora-path "$XYZ_H3_LORA_PATH"
```

`install-runtime.sh cu130` 对应优先版本 SGLang 0.5.23，要求驱动与 CUDA 13 环境匹配。`cu129` 对应回退版本 0.5.19，安装器依据上游该版本 Dockerfile 的 CUDA 12 依赖修改，并固定 CUDA 12.9 的 Torch 和扩展 wheel。两者均需完成 GPU 验证。

已有共享权重可复制到本地项目模型目录，再按固定清单验证。新部署缺少权重时运行下载脚本，基础权重目录为 `$XYZ_MODEL_ROOT/MiniMax-H3`，LoRA 目录为 `$XYZ_MODEL_ROOT/Minimax-h3-Turbo`。服务器无法直接访问 Hugging Face 时，可在当前项目命令中显式设置镜像入口，下载后使用官方清单验证文件。

```bash
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
  python inference/download-model.py
XYZ_H3_MODEL_PATH="$XYZ_MODEL_ROOT/MiniMax-H3" \
  python inference/verify-model.py --lora-path "$XYZ_H3_LORA_PATH"
```

下载支持复用已完成文件，默认 8 个并发，可通过 `XYZ_DOWNLOAD_WORKERS` 调整。基础权重下载 FL2VA 分支和根目录元数据。LoRA 固定为 `lightx2v/Minimax-h3-Turbo` 的提交 `30f485ed874aa44c8183348ad361c5eabad318da`，文件为 `minimax_h3_fl2v_turbo_4step_v0.1.safetensors`，大小为 1,383,677,888 字节。配置保存其 SHA256，完整验证会同时检查 LoRA 摘要。

## 四步请求约定

LoRA 使用 `scale=1.0`、训练 `alpha=8` 和自动合并，视频与音频时间偏移分别为 12 和 3，质量字段为 `lossless`。这组参数对应 v0.1 适配器。上游两个版本的步数字段定义不同，同样四次去噪分别需要以下请求值。[v0.5.19 官方配方](https://github.com/sgl-project/sglang/blob/v0.5.19/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx)、[v0.5.23 官方配方](https://github.com/sgl-project/sglang/blob/v0.5.23/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx)

| SGLang 版本 | `num_inference_steps` | 实际去噪次数 |
| --- | --- | --- |
| 0.5.19 | 5 | 4 |
| 0.5.23 | 4 | 4 |

`configs/minimax-h3.json` 保存版本映射与固定请求规格。5 秒目标由模型对齐帧数，播放时长以输出视频元数据为准。480p 配置和双 A100 容量需要通过真实生成验证。

## GPU 验证与启动

先检查 GPU 占用，然后运行 BF16 矩阵运算、Triton 即时编译和双卡 NCCL 通信检查。

```bash
nvidia-smi
export CUDA_VISIBLE_DEVICES=0,1
torchrun --standalone --nproc-per-node=2 inference/check-gpu.py
bash inference/serve.sh
```

`serve.sh` 使用完整精度、张量并行和逐层卸载候选配置，默认 DiT 常驻层数为 0。`XYZ_NUM_GPUS`、`XYZ_TP_SIZE`、`XYZ_ULYSSES_DEGREE` 分别指定同一服务实例的 GPU 数、张量并行度和序列并行度，默认值为 2、2、1。运行者须显式设置 `CUDA_VISIBLE_DEVICES`，并根据实际同机拓扑选择参数。多机资源需要另行设计实例划分与网络方案。

A100 和 L20 上的真实生成均待验证，`profile_status` 保持 `pending_gpu_validation`。`XYZ_DIT_RESIDENT_LAYERS` 可调整常驻层数，`XYZ_RUNTIME` 可指定经过验证的环境目录。

启动脚本检查基础权重与 LoRA 尺寸和小文件 Git 摘要，完整 SHA256 校验作为单独验证执行，成功后在项目模型目录写入版本标记。`XYZ_H3_MODEL_PATH` 与 `XYZ_H3_LORA_PATH` 可分别指定基础权重和 LoRA 文件。输出视频保存在 `$XYZ_OUTPUT_ROOT`。

## 真实接口验收

```bash
python inference/smoke-test.py --output "$XYZ_OUTPUT_ROOT/smoke-test.mp4"
ffprobe -v error -show_streams -show_format "$XYZ_OUTPUT_ROOT/smoke-test.mp4"
```

脚本根据当前环境安装的 SGLang 版本选择四步请求值。跨主机调用时显式传入服务端版本，例如 `--sglang-version 0.5.19`。脚本创建真实任务后立即保存任务编号和请求到输出同名 JSON，查询至完成再下载 MP4。再次使用同一输出路径会恢复已有任务，也可使用 `--resume JOB_ID` 指定恢复。提交响应丢失时保留待核对记录，查明任务编号后再恢复。

## 常驻服务

GPU 检查和真实生成通过后安装并启动用户服务。

```bash
bash deploy/gpu/install-user-service.sh
systemctl --user enable --now xyzenith-inference
systemctl --user status xyzenith-inference
journalctl --user -u xyzenith-inference -f
```

可选环境文件为 `~/.config/xyzenith/inference.env`。服务失败重启间隔为 30 秒，五分钟内最多尝试三次。

## 当前验证记录

2026-11-07 已复查双 A100 40 GB、驱动 550.54.14，项目数据目录与 Python 3.12 独立环境已创建。CUDA 12.9 回退依赖安装在 NVIDIA wheel 下载时遇到 TLS 握手失败，安装未完成，尚无通过验收的运行时冻结清单。GPU 运算、即时编译、双卡通信、H3 加载及真实生成均未执行。

共享目录 `/data/models/MiniMaxAI/MiniMax-H3` 的 85 个文件尺寸全部与官方固定提交清单匹配。项目目录 `models/MiniMax-H3-shared` 通过逐文件软链接只读复用这些权重。已完成 24 个文件摘要检查，包含 23 个元数据文件和音频 VAE 权重 SHA256，完整文件摘要校验未完成。启动预检会重新检查全部文件尺寸和小文件摘要。

NFS 路由使用 `eno8403`，该接口协商速率为 100 Mbps。四线程文件读取实测约 11.46 MiB/s，模型加载及逐层读取存在实际带宽约束。完整精度候选配方需要结合主机内存和存储带宽实测。

2026-11-07 转为可行性评估与交接时，项目依赖安装、重复权重下载和摘要校验任务已停止，下载缓存、部分文件和日志保留。2026-11-08 用户确认恢复部署，采用本地模型与缓存、480p 四步生成，原始视频保留在共享目录。当前部署进度以项目待办和记忆记录为准。

脚本已通过 Bash 语法检查和 Python 编译检查。候选安装脚本仍需继续解决依赖下载与实际 GPU 兼容性，性能数据以未来的真实任务测量为准。
