# Contributing / 贡献指南

欢迎贡献安装体验、句段边界、模型适配器、费用/任务恢复、可读文档和可脱敏的真实任务。
优先把一次局部修改做可靠，再增加自由度。讨论过的能力不等于已经实现。

## Setup

```bash
uv sync --project app/backend --locked --extra dev
npm --prefix app/frontend ci --ignore-scripts --no-audit --no-fund
app/backend/.venv/bin/python -m pytest app/backend/tests -q
npm --prefix app/frontend test
npm --prefix app/frontend run build
```

Apple Silicon ASR 开发可另加 `--extra transcription` 并显式下载权重。一般测试不得调用收费服务。
独立 HTTP/Worker/FFmpeg 验证：`app/backend/.venv/bin/python scripts/verify_local_flow.py`，先确认 8878 空闲。
不要使用生产数据目录做回归；不要重置真实预算来让测试通过。

## 提交什么

Issue 写明实际目标、操作步骤、期望与实际行为、环境和脱敏日志。PR 写清问题、改后的行为、
验证方式及尚未验证的边界。文档和界面说“已实现”必须有对应代码或运行证据。

新模型请提供精确 API ID、账户/地区前提、支持输入/输出、时长/规格、价格来源和验证日期。
用无凭据的契约测试检验请求和结果；真实调用需要使用者另行明确授权。Unknown submission、
下载恢复、预算预留、候选采用和旧任务完成不得回归。

内置 Skill 改动先检查方法、允许工具与结果回写。不要给 Skill 任意终端、文件、网络或无限收费权限。
外部插件和多人协作属于范围扩展，请先开 Issue 说明需求与边界。

## Protect data

不要提交 `.env`、API Key、cookies、签名 URL、数据库、`.vault-key`、客户素材、访谈内容或原始账本。
项目 ZIP 不是可公开分享的脱敏样例。示例必须由你原创或具有明确可再分发权利。
参考其他开源项目时保留其许可和归属，不把“可在 GitHub 看见”当作可以直接复制。

请阅读 [MIT](LICENSE)、[Security](SECURITY.md) 与 [third-party notices](THIRD_PARTY_NOTICES.md)。
