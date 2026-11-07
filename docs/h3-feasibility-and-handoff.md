# H3 可行性调研与 L20 接入交接

## 当前结论

双 A100 40 GiB 存在通过分阶段加载、流式读取和 CPU 卸载运行原版 H3 的技术路径。本机的 768p、约 5 秒请求尚未完成真实生成，当前缺少与其主机内存及存储条件相匹配的官方成功配置。工程状态记为“候选配置，未验证”。

2026-11-07 用户要求先完成可行性调研，双 A100 路线受限时交付链路，由另一位同学在 L20 资源上验证推理。A100 的模型加载与真实生成已暂停，环境安装状态及停止记录见项目记忆。

## 权重与本机资源

表 1 固定官方版本的 FL2VA 文件体积

| 组件 | 文件大小 GB | 文件大小 GiB |
| --- | ---: | ---: |
| 33B 音视频生成主干 | 66.28 | 61.73 |
| Qwen3-VL-32B 文本编码器 | 66.73 | 62.14 |
| 视频 VAE | 10.42 | 9.70 |
| 音频 VAE | 0.61 | 0.56 |
| 合计，含少量配置和分词文件 | 144.05 | 134.16 |

以上按仓库中的官方版本清单求和。推理还需要激活张量、通信缓冲和工作空间。分阶段加载能够降低峰值显存，同时增加权重搬运和内存管理开销。

模型卡说明生成主干约 13B 参数属于可预计算的 AdaLN 分支。公开权重包含原始分支，SGLang 默认采用标准路径，预计算缓存需要额外显式配置及验证。容量预算应包含默认实际加载的组件。[MiniMax 官方模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3) · [SGLang AdaLN 缓存说明](https://github.com/sgl-project/sglang/blob/v0.5.23/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx#advanced-precomputed-adaln-cache)

本机实测为双 A100-PCIE-40GB、NV8 互联，主机内存 125 GiB、当时可用约 79 GiB。根卷仅余约 7.8 GB，共享 `/data` 剩余约 19 TB。共享盘经 `eno8403` 连接 NAS，该口本机支持千兆，对端仅通告 10/100baseT，实际协商 100 Mbps，全双工。读取约 11.5 MiB/s。公网千兆口属于另一子网，绑定该口访问 NAS 的短连接测试失败。

完整顺序读取 144 GB 文件约需 3.3 小时，这是带宽估算。首次加载和低内存条件下的再次读取均可能受影响。已暂停额外全量哈希读取，保留文件尺寸及已通过的小文件摘要检查，完整权重校验状态仍待完成。

## 官方及社区证据

表 2 已找到的实际运行记录

| 来源 | 条件与结果 | 适用范围 |
| --- | --- | --- |
| SGLang 双 5090 卸载配方 | 每卡 32 GB、主机 377 GiB，完整精度，1344×768、约 5 秒、50 步，耗时 559.67 秒 | 证明小显存双卡有运行路径，377 GiB 是该配方验证条件 |
| SGLang v0.5.23 官方配置源码 | 单 5090、60 GB 物理内存、PCIe 5.0 NVMe，864×480、124 帧、20 步，约 112 秒，每次请求读取约 96 GiB | 证明较低主机内存可以运行，示例同时依赖较低分辨率与高速本地存储 |
| 官方文档低内存预算测试 | 12 GB GPU、32 GB 主机预算，实际宿主机 2 TB 内存，映射权重由系统页缓存承载 | 吞吐测量需要连同物理宿主机条件理解 |
| 社区一手报告 | 2×5090、116 GB 内存控制组、0.5.17 加四处代码补丁，CPU 峰值 114.7 GB，完成 Ref2VA 请求 | 提供进一步研究线索，本机尚未复现 |

前两项来自 [SGLang H3 部署文档](https://github.com/sgl-project/sglang/blob/v0.5.23/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx) 和 [官方部署配置源码](https://github.com/sgl-project/sglang/blob/v0.5.23/docs/src/snippets/configs/MiniMaxAI/minimax-h3.jsx)。社区记录来自 [Discussion #34426](https://github.com/sgl-project/sglang/discussions/34426)。这些结果保留原有硬件和生成规格，本项目尚无 A100 或 L20 实测生成耗时。

## 给 L20 部署同学的接口与步骤

L20 的完整显存规格为 48 GB。部署前收集每台机器卡数、主机可用内存、本地存储容量，以及 `nvidia-smi topo -m` 和跨节点网络信息。优先在一台具备足够资源的机器建立一个推理实例。同机八张 L20 可作为容量更充足的候选，四张配置仍需验证峰值显存。实际参数依据该机器拓扑确定。[NVIDIA L20 显存规格](https://docs.nvidia.com/ai-enterprise/release-8/latest/infra-software/vgpu/reference/ada-lovelace.html)

20 张卡分布在不同服务器时，先按同机实例完成验证。SGLang 具备跨节点并行能力，官方 H3 跨节点记录采用两台各八张 H200；L20 的跨节点配置需独立测量通信与生成表现。当前 VPS 适配一个推理实例，后续多实例任务分发另行扩展。[SGLang 并行能力记录](https://github.com/sgl-project/sglang/blob/v0.5.23/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx)

接入按以下顺序执行。

1. 克隆公开仓库，检出约定提交，按推理说明准备隔离环境。指定 GPU，并验证 BF16 运算、即时编译与卡间通信。
2. 复用已确认版本的共享权重，配置模型路径及输出目录。使用合适的同机多卡配置启动 SGLang，监听本机 30010，服务模型名设置为 `MiniMaxAI/MiniMax-H3`。
3. 本机验证三个原生接口，创建任务、查询任务和下载视频。保存生成参数、任务编号、显存峰值、实际视频规格和耗时。
4. 在 L20 节点生成独立隧道密钥，由 VPS 管理者安装公钥。现有 A100 隧道占用 VPS 的 13010，切换前停止 A100 的 `xyzenith-tunnel` 服务，再启动 L20 隧道。每次由一个节点拥有该端口。
5. VPS 后端通过本机 13010 调用新实例。检查网页健康状态，再从公网提交一条真实请求，完成播放和耗时验收。

原生接口契约如下。

| 接口 | 约定 |
| --- | --- |
| `GET /health` | 模型服务准备完成后返回成功状态 |
| `POST /v1/videos` | 接受下列请求，返回含 `id` 的任务对象 |
| `GET /v1/videos/{id}` | 返回任务状态，成功为 `completed`，失败为 `failed` |
| `GET /v1/videos/{id}/content` | 返回可播放的 MP4 字节 |

```json
{
  "model": "MiniMaxAI/MiniMax-H3",
  "prompt": "A small orange cat walks across a sunlit wooden floor.",
  "task": "t2va",
  "target": {"short_edge": 768, "aspect_ratio": "16:9", "duration_seconds": 5},
  "seed": 42
}
```

VPS 网页接口、任务队列和媒体保存已实现。卡数、卸载或量化策略由推理实例负责，VPS 接收统一的任务状态和视频结果。

## 已完成的链路验收

网页和后端已部署，19 项后端测试通过。浏览器受控测试覆盖提交、状态、播放、刷新、缓存过期和手机布局。

另在真实 A100 到 VPS 反向隧道上执行隔离 CPU 测试。A100 的 `backend/tests/chain_inference_fixture.py` 提供带 `/chain-test` 前缀的测试接口，VPS 独立临时后端调用该前缀，完成任务提交、查询、视频回传、真实 ffprobe 检查和 Range 206 下载。回传视频 SHA256 与原始测试文件一致。

测试素材为 320×180、1 秒的合成 MP4。测试期间公开服务始终显示真实推理离线，结束后两个临时进程已停止。真实 H3 视频生成仍由部署同学完成验收。
