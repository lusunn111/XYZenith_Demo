# Demo 实现与部署

用户批准实施完整计划。页面按组内分享链接直接访问，单任务执行、最多五个等待位。用户选择 VPS 缓存保留 24 小时、上限 2 GiB，允许自动回收本项目缓存，A100 原始输出保留。

已实现 React/TypeScript/Vite 中文深色工作台和 FastAPI/SQLite 后端。包含任务去重、持久状态、上游任务映射、提交结果不明时暂停队列及人工核对、视频检查与原子保存、浏览器范围请求、缓存回收及发送中媒体保护。依赖分别由 package-lock.json 和 requirements.lock.txt 锁定。

前端提交 dac809f，后端提交 ab7d9a8，VPS 与隧道部署脚本提交 cde8d9e。VPS 当前发布 cde8d9e976e02f9ef26651da6c410369f162ee82，网址 http://23.159.248.224:18080/。Nginx 代理本机 18000 业务后端，数据目录 /var/lib/xyzenith，服务账号 xyzenith。发布采用独立虚拟环境、current 链接和失败恢复。安装 FFmpeg 与 Python venv 后 VPS 空余约 9.1 GiB。

A100 的 xyzenith-tunnel 用户服务已启用，用户 Linger=yes。专用密钥在 A100 生成，VPS xyzenith-tunnel 账号仅允许远程转发本机 13010，目标为 A100 本机 30010。终止该隧道主进程后，服务自动重启，NRestarts 变为 1，新进程与 VPS 端口恢复，验证通过。密钥与实际环境文件仅位于部署机器。

验证结果为本地18项后端测试通过、1项因缺FFmpeg跳过，VPS上19项全部通过。真实媒体测试使用合成MP4及受控上游，覆盖下载、ffprobe、原子保存和Range206。浏览器受控接口测试通过提交、排队、运行、完成播放、刷新恢复、视频过期、离线和手机无横向溢出。公网网页另经桌面1440和手机390宽度访问验证，业务API mock=false，推理当时显示offline。

A100 推理环境仍在部署。共享盘发现已有 /data/models/MiniMaxAI/MiniMax-H3，85个文件尺寸与固定官方revision 42ed227ee7df40d41602854ae760620d6eb651fe 清单一致，正在完整校验。真实H3端到端生成尚待验收。
