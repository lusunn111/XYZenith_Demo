# 部署与维护

## 本地开发

后端需要 Python 3.11+。从仓库根目录执行下列命令，系统安装 FFmpeg 后可检查真实视频。

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
backend/.venv/bin/pip install --no-deps ./backend
cd backend
XYZ_DATA_ROOT=./runtime .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
```

另一个终端启动前端，Vite 将业务请求代理到本机 18000 端口。

```bash
cd frontend
npm ci
npm run dev
```

页面默认查询真实后端。推理服务尚未启动时显示离线状态。前端的开发模拟标记由测试拦截响应中的 `mock` 字段触发。

## VPS 发布

VPS 需要 Nginx、Python 3 的 venv 支持和 FFmpeg。网页使用 18080，业务接口使用本机 18000，反向隧道使用本机 13010。先确认这些端口可用。

本地构建前端，记录 Git 提交，将该提交的源码及 `frontend/dist` 一起上传到 `/opt/xyzenith/releases/完整提交号`。每个发布目录建立独立 Python 环境。

```bash
npm --prefix frontend ci
npm --prefix frontend run build
git rev-parse HEAD
```

在 VPS 中执行发布脚本，参数为上传后的完整目录。

```bash
bash /opt/xyzenith/releases/完整提交号/deploy/vps/install.sh /opt/xyzenith/releases/完整提交号
```

脚本安装锁定依赖、创建 `xyzenith` 服务账号，检查 Nginx 配置并切换 `current` 链接。后端健康检查通过后重载 Nginx。失败时恢复先前版本链接与配置。环境文件位于 `/etc/xyzenith/backend.env`，数据库和缓存位于 `/var/lib/xyzenith`。

部署后检查网页、后端健康和运行版本。

```bash
curl --fail http://127.0.0.1:18080/api/health
systemctl status xyzenith.service --no-pager
journalctl -u xyzenith.service -n 80 --no-pager
readlink /opt/xyzenith/current
```

`inference.status=online` 表示推理服务健康检查通过。真实生成还需要通过提交、查询和下载完成验收。

恢复到已有版本时，对旧发布目录再次运行其 `deploy/vps/install.sh`。任务数据库保存在发布目录之外。

## 反向隧道

A100 使用专用 SSH 密钥连接 VPS 的 `xyzenith-tunnel` 账号。密钥在 A100 生成，公钥交给 VPS 管理账号安装。

```bash
ssh-keygen -t ed25519 -N '' -f ~/.ssh/xyzenith_tunnel -C xyzenith-a100-tunnel
```

在 VPS 上执行 `deploy/tunnel/setup-vps.sh 公钥文件路径`。该账号仅允许远程转发到 VPS 的 `127.0.0.1:13010`。通过已认证的 VPS 管理连接取得主机公钥，写入 A100 的独立 `known_hosts` 文件。

按 `deploy/tunnel/tunnel.env.example` 设置 A100 的 `~/.config/xyzenith/tunnel.env`，然后安装用户服务。

```bash
bash deploy/tunnel/install-user.sh
systemctl --user status xyzenith-tunnel.service --no-pager
journalctl --user -u xyzenith-tunnel.service -n 50 --no-pager
loginctl show-user "$USER" -p Linger
```

当前 A100 的用户驻留已启用。隧道退出后等待 10 秒重连，SSH 每 20 秒检测连接，连续 3 次无响应时退出。

## 任务核对与缓存

任务进入 `submission_unknown` 后，维护者先查询 SGLang 任务列表和日志，确定是否已接受请求。在 VPS 后端工作目录中加载实际环境，再执行任务核对命令。

```bash
cd /opt/xyzenith/current/backend
set -a
. /etc/xyzenith/backend.env
set +a
sudo -u xyzenith --preserve-env=XYZ_DATA_ROOT .venv/bin/python -m app.manage 任务编号 --attach-upstream 上游编号
```

确认提交失败时将最后一个参数组改为 `--confirm-failed`。执行器在下一轮读取更新，恢复队列。

VPS 视频缓存保留 24 小时，上限 2 GiB。回收时跳过正在传输给浏览器的文件，保留任务记录。缓存过期后视频接口返回 410，原始视频保留在 A100 项目输出目录。

## 验证命令

```bash
cd backend
.venv/bin/pip install '.[test]'
.venv/bin/python -m pytest -q
```

测试涵盖去重、容量、任务与传输恢复、人工核对、缓存回收和视频范围请求。安装 FFmpeg 时额外执行真实 MP4 解析测试。该测试的上游为受控替身，真实 H3 验收使用推理目录中的实际生成脚本。
