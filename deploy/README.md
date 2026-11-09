# 部署

| 目录 | 内容 |
| --- | --- |
| `vps/` | 网页、业务接口、Nginx 及进程管理配置 |
| `gpu/` | A100 数据目录、隔离环境安装、CUDA 库绑定和推理常驻服务配置 |
| `tunnel/` | A100 主动连接 VPS 的反向 SSH 隧道配置 |

真实主机地址、密钥及账号信息通过部署环境提供。首版隧道将推理接口映射到 VPS 的本地回环地址，业务后端调用该地址。

GPU 环境准备命令如下，执行前检查数据盘挂载和空间。

完整推理安装还需要 GPU 节点的 `uv`、FFmpeg 和兼容的 NVIDIA 驱动。前置检查、权重下载及启动步骤见 [推理说明](../inference/README.md)。

```bash
bash deploy/gpu/prepare-directories.sh
source deploy/gpu/env.sh
```

脚本支持通过 `XYZ_DATA_ROOT` 指定数据根目录。GPU 选择在具体任务启动命令中设置。
