# MiniMax-H3 推理服务

首版使用官方 MiniMax-H3 FL2VA 权重，目标为短边 768、16:9、约 5 秒的文本生成音视频。服务监听 A100 本机 `127.0.0.1:30010`，VPS 通过反向 SSH 隧道访问。

模型版本和请求规格记录在 `configs/minimax-h3.json`。`configs/model-manifest.json` 来自 Hugging Face 官方 API 的固定提交，列出 85 个文件、总计 144,051,244,506 字节。大文件使用官方 LFS SHA256 校验，小文件使用 Git blob SHA1 校验。

## 环境与权重准备

在 A100 的 `~/XYZenith_Demo` 执行。大文件和隔离环境均进入共享数据盘。

```bash
bash deploy/gpu/prepare-directories.sh
source deploy/gpu/env.sh
bash deploy/gpu/install-runtime.sh cu129
source "$XYZ_VENV_ROOT/sglang-cu129/bin/activate"
export XYZ_H3_MODEL_PATH="$XYZ_MODEL_ROOT/MiniMax-H3-shared"
python inference/verify-model.py --metadata-only
```

`install-runtime.sh cu130` 对应优先版本 SGLang 0.5.23，要求驱动与 CUDA 13 环境匹配。`cu129` 对应回退版本 0.5.19，安装器依据上游该版本 Dockerfile 的 CUDA 12 依赖修改，并固定 CUDA 12.9 的 Torch 和扩展 wheel。两者均需完成 GPU 验证。

当前 A100 已建立共享权重链接目录，可直接复用。新部署确实缺少权重时再运行下载脚本，默认下载目录为 `$XYZ_MODEL_ROOT/MiniMax-H3`。服务器无法直接访问 Hugging Face 时，可在当前项目命令中显式设置镜像入口，下载后使用官方清单验证文件。

```bash
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
  python inference/download-model.py
XYZ_H3_MODEL_PATH="$XYZ_MODEL_ROOT/MiniMax-H3" python inference/verify-model.py
```

下载支持复用已完成文件，默认 8 个并发，可通过 `XYZ_DOWNLOAD_WORKERS` 调整。权重仅下载 FL2VA 分支和根目录元数据。

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

启动脚本检查权重尺寸和小文件 Git 摘要，完整 SHA256 校验作为单独验证执行，成功后在项目模型目录写入版本标记。`XYZ_H3_MODEL_PATH` 可指向项目内的共享权重链接目录。输出视频保存在 `$XYZ_OUTPUT_ROOT`。

## 真实接口验收

```bash
python inference/smoke-test.py --output "$XYZ_OUTPUT_ROOT/smoke-test.mp4"
ffprobe -v error -show_streams -show_format "$XYZ_OUTPUT_ROOT/smoke-test.mp4"
```

脚本创建真实任务后立即保存任务编号和请求到输出同名 JSON，查询至完成再下载 MP4。再次使用同一输出路径会恢复已有任务，也可使用 `--resume JOB_ID` 指定恢复。提交响应丢失时保留待核对记录，查明任务编号后再恢复。

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

用户将本轮工作转为可行性评估与交接。项目自己的依赖安装、重复权重下载和摘要校验任务已停止，下载缓存、部分文件和日志保留。推理用户服务模板已安装但未启动。恢复部署时由接手同学核实资源和环境，再按上述步骤验证。

脚本已通过 Bash 语法检查和 Python 编译检查。候选安装脚本仍需继续解决依赖下载与实际 GPU 兼容性，性能数据以未来的真实任务测量为准。
