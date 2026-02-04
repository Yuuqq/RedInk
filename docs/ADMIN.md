# 管理面板（Admin）

访问：前端页面侧边栏 `管理面板`（路由：`/admin`）

后端管理 API（默认仅允许本机 loopback 访问）：
- `GET /api/admin/health`：后端信息 + 当前激活服务商 + 上游连通性探测（OpenAI-compatible 的 `/v1/models`）
- `GET /api/admin/tasks`：列出内存中仍保留的任务状态（用于重试/排障）
- `DELETE /api/admin/tasks/<task_id>?delete_files=true|false`：清理任务内存状态；可选删除 `history/<task_id>` 文件夹
- `GET /api/admin/logs`：增量读取后端日志（offset/max_bytes），包含 `warnings`（例如日志文件过大告警）
- `GET /api/admin/logs/download`：下载后端日志文件
- `POST /api/admin/logs/rotate`：主动轮转日志（`redink.log` -> `redink.log.1`）
- `GET /api/admin/history/stats`：history 目录统计（总大小、孤儿目录等）
- `POST /api/admin/history/cleanup`：history 目录清理（建议先 dry-run）
  - `scope`: `orphan|all`（默认 `orphan`）
  - `delete_orphan_tasks`: `true|false`（为 `true` 时会强制只作用于孤儿目录，即使 `scope=all`）
  - `older_than_days`: 仅删除超过 N 天的任务目录
  - `keep_last_n`: 只保留最近 N 个任务目录（按 mtime）
  - `larger_than_mb`: 仅删除超过阈值大小（MB）的任务目录
  - `dry_run`: `true|false`
  - 高危确认：
    - `confirm_delete_orphans='YES_DELETE_ORPHAN_TASKS'`（当 `dry_run=false` 且作用范围包含孤儿目录）
    - `confirm_delete_any='YES_DELETE_ANY_TASKS'`（当 `dry_run=false` 且 `scope=all`）

## 安全策略

默认只允许 loopback（127.0.0.1 / ::1）访问管理 API。

如需放开限制（不推荐），设置环境变量：
- `REDINK_ADMIN_TRUST_PRIVATE=1`：允许内网地址访问（10.x / 192.168.x / Docker bridge 等）
- `REDINK_ADMIN_TRUST_XFF=1`：信任 `X-Forwarded-For`（仅在你完全控制反向代理时）
- `REDINK_ADMIN_ALLOW_REMOTE=1`：允许任意远程访问

日志文件默认写入 `logs/redink.log`。如需自定义日志路径：
- `REDINK_LOG_FILE=logs/custom.log`（默认仅允许 logs/ 目录下，防止任意文件下载）
- `REDINK_ADMIN_ALLOW_LOG_ANY_PATH=1`（不推荐）：允许下载任意路径的 `REDINK_LOG_FILE`

## 任务状态 TTL（防止内存增长）

后端会对 `_task_states` 做过期清理（默认保留 6 小时）。

可通过环境变量调整：
- `REDINK_TASK_STATE_TTL_SECONDS=21600`（默认值）
