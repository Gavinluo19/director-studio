# 安装与启动 / Installation

## 已验证范围

首发目标是 Apple Silicon Mac。本地自动转写依赖 MLX，要求 macOS / arm64。
Linux CI 验证核心回归与合成流程，不代表 Windows、Intel Mac 或 Linux 的完整产品体验已验收。
没有原生安装包；你需要使用终端安装依赖。最低内存与所有硬件组合尚未正式测量。

## 前置软件

准备 Git、uv、Node.js 22+（含 npm）、FFmpeg 和 Python 3.12。项目使用 `.python-version`
固定开发解释器；uv 可在环境需要时管理 Python。若已安装 Homebrew，可使用：

```bash
brew install git uv node ffmpeg
git --version
uv --version
node --version
ffmpeg -version
```

安装来源：[Homebrew](https://brew.sh/)、[uv](https://docs.astral.sh/uv/getting-started/installation/)、
[Node.js](https://nodejs.org/)、[FFmpeg](https://ffmpeg.org/download.html)。首次安装的网络下载可能较慢。

## 启动一套工作台

```bash
git clone https://github.com/Gavinluo19/director-studio.git
cd director-studio
bash scripts/start.sh
```

脚本检查依赖、建立 Python 环境；首次构建 React 页面；同时启动 API 和独立 Worker，
打开 http://127.0.0.1:8768/。保持终端运行，`Control+C` 停止两个进程。
在 Finder 中双击 `启动片场.command` 也会调用同一入口。可执行权限缺失时使用上述 `bash` 命令。
如果 macOS 阻止打开文件，请阅读系统提示并确认来源；终端命令不需要双击文件。

更新代码后停止旧服务，再运行：

```bash
git pull --ff-only
STUDIO_REBUILD=1 bash scripts/start.sh
```

提交过本地修改时先保留自己的变更，不要强行覆盖。脚本不会添加登录自启、后台常驻代理或修改防火墙。

## 数据、端口和日志

默认数据：`~/Library/Application Support/DirectorStudio`。内容包括项目数据库、媒体、任务和运行日志。
源码与业务数据分开；重新下载源码不等于恢复项目。原始文件、数据库及凭据都不要提交到 GitHub。

使用隔离数据和另一端口：

```bash
bash scripts/start.sh --port 8889 --data-dir "$PWD/runtime/my-studio"
```

同一个数据目录只允许一套主进程；同一端口只能由一个服务监听。不要绕过这些保护来重复启动 Worker。
日志在数据目录的 `logs/api.log` 与 `logs/worker.log`。日志可能包含文件名、任务信息或私有内容，分享前先脱敏。

## 本地转写权重

Apple Silicon 启动脚本安装 `mlx-whisper==0.4.3`，但不自动下载权重。手动准备：

```bash
app/backend/.venv/bin/python scripts/download_asr.py --yes
```

准备的是 [`mlx-community/whisper-large-v3-turbo`](https://huggingface.co/mlx-community/whisper-large-v3-turbo)。
权重缓存位于 `~/.cache/huggingface/hub`，不在 Git 仓库内；首次下载占用网络与磁盘。
命令只下载配置、权重和说明，不上传音视频。用户须自行阅读模型卡及许可证。
下载后进入“能力与方法”，点击刷新。准备失败时可继续用含时间戳的 SRT 导入。

## 零收费调用的安装验收

```bash
uv sync --project app/backend --locked --extra dev
app/backend/.venv/bin/python scripts/verify_local_flow.py
```

脚本自动建立合成色卡、音调和独立测试库，启动 8878 端口的 API/Worker，完成字幕、声音、
合成、审片阻断、MP4/SRT/ZIP、重启与恢复检查，结束后关闭测试服务。
没有供应商账号，没有真实 AI 生成调用，没有付费请求。
确保 8878 空闲；结果和日志在 `app/verification/`，不写默认业务库。

## 常见故障

| 现象 | 检查与处理 |
|---|---|
| 页面仍在，但创建作品失败 | 可能是旧页面而 API 已退出。启动脚本后刷新或重新连接，弹窗保留已输入内容 |
| 8768 已占用 | 检查现有服务，或选另一端口；不要结束不明进程 |
| API 能打开，任务一直等待 | `/api/health` 的 `workers` 为空；查看 `worker.log`，停止旧启动终端后统一重启 |
| 本地会话失效 | 刷新页面重新建立会话；这里是单机访问会话，不是多人账号登录 |
| 转写未就绪 | 检查 Apple Silicon、可选依赖、缓存权重，再刷新能力；不自动切云端 |
| 模型无法执行 | 填真实 ID、启用模型、确认连接/规格/报价；不要只看预设名字 |
| 结果不明 / 供应商超时 | 先查原任务或对账，不重复提交收费生成 |
| 配音超时长 | 调整台词或声音时段，保留原件；视频不会因此被清空 |
| 导出被拒绝 | 重新合成当前内容、处理审片问题，再确认当前版本 |

安装失败可提交 Issue，包含系统、芯片、版本、步骤及脱敏日志，禁止上传 Key、签名 URL 和业务库。
