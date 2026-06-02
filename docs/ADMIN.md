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

部署默认值：
- 后端默认拒绝无认证启动；不要依赖 `127.0.0.1` 作为安全边界，因为反向代理部署下公网请求也可能以 loopback 形式到达应用
- Docker Compose 要求设置 `REDINK_AUTH_TOKEN`
- Docker 镜像默认使用 Gunicorn，而不是 Flask 开发服务器
- Docker 默认端口为 `12398`；如需修改，设置 `REDINK_PORT=<port>`，Compose 会同步更新容器监听端口、宿主端口映射和健康检查端口
- Docker 默认 `REDINK_GUNICORN_WORKERS=1`、`REDINK_GUNICORN_THREADS=8`，因为进行中的图片生成任务状态保存在当前进程内；除非已外置任务状态，否则不要提高 worker 数
- Docker Compose 默认挂载 `./config:/app/config` 并把服务商配置路径指向 `/app/config/text_providers.yaml` 与 `/app/config/image_providers.yaml`，容器启动时会在文件缺失时写入默认模板且不会覆盖已有 API Key/模型配置；两个路径必须是不同文件，否则后端会拒绝启动/保存配置，避免互相覆盖
- 未设置 `REDINK_AUTH_TOKEN` 时，启动保护和请求级保护都会拒绝访问
- 启用 `REDINK_AUTH_TOKEN` 后，`/api/images/*` 也需要 Bearer Token 或前端写入的仅限 `/api/images` 路径 SameSite Cookie，避免生成图片匿名可读
- 如确需在受控私有网络中无认证远程访问，可显式设置 `REDINK_ALLOW_UNAUTH_REMOTE=1`，不建议用于公网或共享网络

如需放开限制（不推荐），设置环境变量：
- `REDINK_ADMIN_TRUST_PRIVATE=1`：允许内网地址访问（10.x / 192.168.x / Docker bridge 等）
- `REDINK_ADMIN_TRUST_XFF=1`：信任 `X-Forwarded-For`（仅在你完全控制反向代理时）
- `REDINK_ADMIN_ALLOW_REMOTE=1`：允许任意远程访问

日志文件默认写入 `logs/redink.log`。如需自定义日志路径：
- `REDINK_LOG_FILE=logs/custom.log`（默认仅允许 logs/ 目录下，防止任意文件下载）
- `REDINK_ADMIN_ALLOW_LOG_ANY_PATH=1`（不推荐）：允许下载任意路径的 `REDINK_LOG_FILE`

## 限流与反向代理

默认限流配置：
- `REDINK_RATE_LIMIT=60 per minute`
- `REDINK_RATE_LIMIT_STORAGE_URI=memory://`

默认内存存储只适合单容器、单进程部署。若使用多容器或多个 WSGI worker，请改用 Flask-Limiter 支持的共享存储 URI，并确保镜像内安装对应存储驱动。

反向代理注意事项：
- 默认按直接连接到 Flask/Gunicorn 的客户端 IP 限流。
- 管理接口默认不信任 `X-Forwarded-For`。
- 仅在你完全控制反向代理且代理会覆盖客户端传入的转发头时，才设置 `REDINK_ADMIN_TRUST_XFF=1`。

## 服务商 URL 安全

上游服务商 `base_url` 默认必须解析到公网地址。连接测试、管理面板健康探测、文本生成和图片生成都会拒绝 loopback、内网、link-local、保留地址等非公网目标，避免被配置或上游响应诱导访问内网服务。

如果你的部署确实使用本机或内网代理网关（例如 CLIProxyAPI、OneAPI、Docker bridge 上的网关），可显式设置：

```bash
REDINK_ALLOW_PRIVATE_PROVIDER_URLS=1
```

即使开启该选项，`169.254.0.0/16` 等 link-local/云元数据地址仍会被拒绝。

OpenAI-Compatible / Image API 请求会在发起请求前固定已验证 IP，降低 DNS rebinding 风险。Google GenAI 的自定义 `base_url` 由 Google SDK 管理底层连接，应用无法固定连接 IP，因此默认禁用；留空 `base_url` 会继续使用官方 Gemini API。仅在可信网络中确需 Google GenAI 自定义网关时，再同时设置：

```bash
REDINK_ALLOW_UNPINNED_PROVIDER_URLS=1
```

## 任务状态 TTL（防止内存增长）

后端会对 `_task_states` 做过期清理（默认保留 6 小时）。

可通过环境变量调整：
- `REDINK_TASK_STATE_TTL_SECONDS=21600`（默认值）
