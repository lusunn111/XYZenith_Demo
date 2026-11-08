# A100 本地缓存与四步部署

用户明确确认采用本地缓存、480p、约5秒、LightX2V四步方案。模型、环境及缓存根目录为 `/home/iflab-zzh-intern/.local/share/xyzenith`，视频原件继续保存在 `/data/Zhihao/XYZenith_Demo/outputs`。

11月8日现场复查，根卷3.9TiB、空闲1.6TiB，由多块SATA SSD组成；共享/data空闲19TiB。双A100-PCIE-40GB均空闲，驱动550.54.14。主机125GiB、可用69GiB，swap31GiB已满，/dev/shm仅剩1.3GiB。共享盘链路仍为100Mbps。sudo非交互认证仍不足。

已建立本地目录并复制Python3.12.12。恢复SGLang0.5.19-cu129隔离安装，官方该版本已支持所选LoRA。v0.5.19请求num_inference_steps=5对应4次去噪，v0.5.23使用4；视频/音频flow_shift为12/3，LoRA scale1、alpha8。安装器调整索引优先级，优先PyPI依赖、CUDA专用Torch回退官方cu129索引，避开此前区域NVIDIA下载入口握手问题。实际GPU验证仍待环境安装完成。

LoRA固定revision30f485ed874aa44c8183348ad361c5eabad318da，文件1383677888字节，已下载到本地models/Minimax-h3-Turbo并通过SHA256校验。基础权重按85文件manifest准备本地实文件，复制时计算官方摘要。为并行利用存储网和公网，NFS负责编码器/VAE，VPS临时固定源代理负责transformer分片；临时代理仅允许A100源地址和manifest固定路径，限量Range请求，完成后关闭。

后端已实现参数配置与逐任务参数快照，历史768p任务保留原参数语义，前端按任务快照显示。本地测试26项通过、1项因缺FFmpeg跳过。4e48095已推送并部署VPS，27项后端测试全部通过，公网桌面/手机页面确认480p、mock=false，当前推理offline。Mac直连和本机7890代理访问VPS超时，浏览器验收使用经A100的临时SOCKS出口访问真实公网网址。

推理脚本已接入固定LoRA与版本对应请求步数，并修复单独指定模型路径时的环境变量读取错误。8e91a73已推送并同步A100，包含本地缓存、共享输出挂载预检、固定端口与关闭自动预热。运行服务清除继承的代理变量。真实加载、HTTP生成及公网生成播放验收仍待完成。
