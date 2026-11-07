# Demo 实现与部署

2026-11-07，用户明确要求将仓库改为公开。已修改 GitHub 可见性，并通过 API 核实 `visibility=public`、`private=false`。README 与接入说明已同步更新。

用户批准实施完整计划。页面按组内分享链接直接访问，单任务执行、最多五个等待位。用户选择 VPS 缓存保留 24 小时、上限 2 GiB，允许自动回收本项目缓存，A100 原始输出保留。

已实现 React/TypeScript/Vite 中文深色工作台和 FastAPI/SQLite 后端。包含任务去重、持久状态、上游任务映射、提交结果不明时暂停队列及人工核对、视频检查与原子保存、浏览器范围请求、缓存回收及发送中媒体保护。依赖分别由 package-lock.json 和 requirements.lock.txt 锁定。

前端提交 dac809f，后端提交 ab7d9a8，VPS 与隧道部署脚本提交 cde8d9e。VPS 当前发布 cde8d9e976e02f9ef26651da6c410369f162ee82，网址 http://23.159.248.224:18080/。Nginx 代理本机 18000 业务后端，数据目录 /var/lib/xyzenith，服务账号 xyzenith。发布采用独立虚拟环境、current 链接和失败恢复。安装 FFmpeg 与 Python venv 后 VPS 空余约 9.1 GiB。

A100 的 xyzenith-tunnel 用户服务已启用，用户 Linger=yes。专用密钥在 A100 生成，VPS xyzenith-tunnel 账号仅允许远程转发本机 13010，目标为 A100 本机 30010。终止该隧道主进程后，服务自动重启，NRestarts 变为 1，新进程与 VPS 端口恢复，验证通过。密钥与实际环境文件仅位于部署机器。

验证结果为本地18项后端测试通过、1项因缺FFmpeg跳过，VPS上19项全部通过。真实媒体测试使用合成MP4及受控上游，覆盖下载、ffprobe、原子保存和Range206。浏览器受控接口测试通过提交、排队、运行、完成播放、刷新恢复、视频过期、离线和手机无横向溢出。公网网页另经桌面1440和手机390宽度访问验证，业务API mock=false，推理当时显示offline。

A100 推理环境在安装完成前暂停。共享盘发现已有 /data/models/MiniMaxAI/MiniMax-H3，85个文件尺寸与固定官方revision 42ed227ee7df40d41602854ae760620d6eb651fe 清单一致，完整权重校验尚未完成。真实H3端到端生成尚待验收。

## 可行性调研与交接调整

后续补查确认四步蒸馏发布。SGLang v0.5.23 官方 LoRA 配方包含 LightX2V FL2VA/T2VA v0.1，scale1、alpha8、四次去噪，训练544p且shift12/3；发布者分辨率源码支持864×480。FastVideo Preview v1也有四步Dense及VSA权重，PTD发布针对Ref2VA。480p四步存在Sogni单5090量化图生视频实测。来源、接口步数差异及适用范围已补入 docs/h3-feasibility-and-handoff.md。双A100的480p四步加载、生成质量及耗时仍待实测，部署选型待确认。

用户质疑双 A100 容量，要求先调研可行性，受限时构建好链路交给另一位同学在20张L20资源上部署。模型加载与GPU生成暂停，独立环境仍为未完成安装的候选。

补查官方证据发现原版H3低显存运行存在路径。双5090配方采用377GiB主机内存，1344×768/约5秒/50步耗时559.67秒；v0.5.23官方配置源码另有单5090+60GB物理内存+PCIe5 NVMe的480p案例。377GiB仅为特定已验证配方条件。当前双A100、79GiB可用主机内存和百兆NFS的组合缺少匹配成功记录，不能承诺768p可运行或低延迟。资料及L20接入契约见 docs/h3-feasibility-and-handoff.md。

网络只读核查确认eno8403存储口100Mbps/full/autoneg，本机通告千兆，对端仅通告10/100Mbps。eno8303公网口1000Mbps但处于另一子网，绑定该口访问NAS的ping及TCP2049均失败。所有本地盘并入根卷，剩余7.8GB。NFS读取约11.5MiB/s，完整144GB顺序读约3.3小时为带宽估算。

为验证交接链路，在A100临时运行CPU HTTP fixture的/chain-test前缀，VPS独立18001后端调用同一真实13010反向隧道，完成提交、状态、合成MP4回传、ffprobe检查和Range206。测试视频320×180、1秒，SHA256为57033089547ca98403d9a1b9a243aa9f1b71dbc82aa23126770718166ae50a49。公开业务服务始终返回真实推理offline，临时服务已停止，测试不涉及H3生成。

收尾核验确认本项目安装、重复下载及哈希进程均已退出，包含暂停的hash PID3394304。推理服务inactive，两GPU显存0MiB、无计算进程。cu129安装遇到nvidia-cuda-runtime-cu12下载TLS握手失败，独立环境仅完成bootstrap，torch和sglang未安装。85文件尺寸匹配，24文件摘要通过（23个元数据文件与音频VAE），完整摘要未完成。候选脚本支持可配置同机GPU拓扑，烟测脚本持久化任务编号并支持恢复。脚本语法与Python编译检查通过，运行能力待接手节点验证。
