# A100 本地缓存与四步部署

用户明确确认采用本地缓存、480p、约5秒、LightX2V四步方案。模型、环境及缓存根目录为 `/home/iflab-zzh-intern/.local/share/xyzenith`，视频原件继续保存在 `/data/Zhihao/XYZenith_Demo/outputs`。

11月8日现场复查，根卷3.9TiB、空闲1.6TiB，由多块SATA SSD组成；共享/data空闲19TiB。双A100-PCIE-40GB均空闲，驱动550.54.14。主机125GiB、可用69GiB，swap31GiB已满，/dev/shm仅剩1.3GiB。共享盘链路仍为100Mbps。sudo非交互认证仍不足。

已完成本地Python3.12.12与SGLang0.5.19-cu129隔离安装。Torch2.13.0+cu129、CUDA12.9、Triton3.7.1，双卡BF16、Triton即时编译、NCCL通信全部通过。v0.5.19请求num_inference_steps=5对应4次去噪，v0.5.23使用4；视频/音频flow_shift为12/3，LoRA scale1、alpha8。

安装器优先PyPI依赖、CUDA专用Torch回退官方cu129索引，三份GitHub扩展wheel由VPS下载并按官方SHA256验证后缓存到A100。229包冻结到inference/requirements-cu129.lock.txt，锁文件重放成功。按官方CUDA12路线覆盖依赖，pip check仍报告官方wheel声明cuda-python>=13与实际12.9.10的元数据差异。VPS临时wheel服务28444已停、临时中转文件已回收。

实际默认torch_sdpa变长注意力通过BF16与FP32数学参考对照，最大绝对误差0.00402045、平均0.000482252。显式FA4 SM80路径在CuTe编译遇到nvvm.fmax签名错误，因此首轮固定torch_sdpa。视频API、H3 pipeline与适配模块均成功导入，完整模型加载和生成仍待验收。运行时与注意力修正提交0cb8cb9，A100代码目录已建立完整Git仓库并同步至该提交，工作树干净。

LoRA固定revision30f485ed874aa44c8183348ad361c5eabad318da，文件1383677888字节，已下载到本地models/Minimax-h3-Turbo并通过SHA256校验。基础权重按85文件manifest准备本地实文件，复制时计算官方摘要。为并行利用存储网和公网，NFS负责编码器/VAE，VPS临时固定源代理负责transformer分片；临时代理仅允许A100源地址和manifest固定路径，限量Range请求，完成后关闭。

后端已实现参数配置与逐任务参数快照，历史768p任务保留原参数语义，前端按任务快照显示。本地测试26项通过、1项因缺FFmpeg跳过。4e48095已推送并部署VPS，27项后端测试全部通过，公网桌面/手机页面确认480p、mock=false，当前推理offline。Mac直连和本机7890代理访问VPS超时，浏览器验收使用经A100的临时SOCKS出口访问真实公网网址。

推理脚本已接入固定LoRA与版本对应请求步数，并修复单独指定模型路径时的环境变量读取错误。8e91a73已推送并同步A100，包含本地缓存、共享输出挂载预检、固定端口与关闭自动预热。运行服务清除继承的代理变量。真实加载、HTTP生成及公网生成播放验收仍待完成。

加载前的CPU小夹具复现了v0.5.19 LoRA与逐层卸载的重复存储。TP2权重为匿名CPU分片，LoRA wrapper保存底权alias，卸载器另建buffer后alias仍保留旧storage。dynamic消除首次clone仍无法消除后续双份，且默认包装所有Linear。当前主机约78GiB可用内存无法按原预算容纳该组合。未启动完整模型，未把预检记为真实OOM。

官方world1路径可使用文件映射，auto合并缓存已通过CPU夹具验证；H3自定义QKV重排仍会产生约11.2GiB匿名底权。双卡局部修复通过21组CPU回归及独立复核，保留在.cache候选，未修改安装包。

用户进一步明确确认先验证单A100官方省内存方案。采用GPU0、num_gpus/tp/ulysses=1、全组件逐层卸载、auto LoRA文件缓存、torch_sdpa。用户服务设置MemoryMax=60G，CPU-only实测SGLang读取cgroup预算为59.30GiB，并触发文本编码器checkpoint映射。实际模型加载及生成继续待验收。

13时31分基础模型及LoRA完整校验结束，85个基础文件144,051,244,506字节全部为本地文件，86项摘要通过，完整复核149.8秒。日志与审计JSON保存在本地数据目录logs及Mac .cache/deploy。临时模型代理28443已停止并清理，所有下载及校验任务已退出。

单卡服务13时31分47秒启动、13时35分47秒就绪，首次冷加载240秒，包含208层LoRA文件缓存生成（约38GiB）。健康接口200，空闲GPU0占7465MiB，GPU1为0。安装包保持官方版本。

原生首条任务302df026-094b-4acc-a818-7d5f7a72a51c于13时44分26秒失败。文本编码与四步去噪已完成，去噪阶段381.57秒，随后视频VAE的FP16 Conv3d报CUDNN_STATUS_NOT_INITIALIZED。记录保存在共享outputs/smoke-single-a100.json，无对应MP4。动态库审计确认项目CUDA12主库误载系统CUDA13的完整版本名子库，PyPI包只提供主版本名是触发原因。

项目runtime-env.sh为所选环境创建完整版本名别名并绑定全部CUDA库，已接入安装和启动脚本。六组小Conv3d通过，覆盖FP32/FP16/BF16及1/3卷积核，实际加载的cuDNN子库全部来自项目CUDA12环境。软件版本和系统包保持原状，GPU预检新增上述回归。完整生成使用新任务与输出名重新验证，保留首次失败记录。
