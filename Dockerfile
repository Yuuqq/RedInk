# ============================================
# CSS Lab AI图文生成器 - Docker 镜像
# ============================================

# 阶段1: 构建前端
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# 安装与 lockfile 匹配的 pnpm 版本，避免 Docker 构建随 latest 漂移
RUN npm install -g pnpm@10.29.2

# 复制前端依赖文件
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# 安装依赖
RUN pnpm install --frozen-lockfile

# 复制前端源码
COPY frontend/ ./

# 构建前端
RUN pnpm build

# ============================================
# 阶段2: 最终镜像
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install --no-cache-dir uv

# 复制 Python 项目配置
COPY pyproject.toml uv.lock* ./

# 安装 Python 依赖。此层尚未复制 backend/，因此不要安装本地项目本身。
RUN uv sync --no-dev --no-install-project

# 复制后端代码
COPY backend/ ./backend/

# 复制空白配置文件模板（不包含任何 API Key），容器启动时只在缺失时写入持久化 config/
COPY docker/text_providers.yaml ./default-config/text_providers.yaml
COPY docker/image_providers.yaml ./default-config/image_providers.yaml
COPY docker/docker-entrypoint.sh ./docker-entrypoint.sh

# 从构建阶段复制前端产物
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 创建数据目录。生成图片和历史记录都存放在 history/ 下。
RUN mkdir -p history config && chmod +x /app/docker-entrypoint.sh

# 设置环境变量
ENV REDINK_DEBUG=false
ENV REDINK_HOST=0.0.0.0
ENV REDINK_PORT=12398
ENV REDINK_TEXT_PROVIDERS_PATH=/app/config/text_providers.yaml
ENV REDINK_IMAGE_PROVIDERS_PATH=/app/config/image_providers.yaml

# 暴露端口
EXPOSE 12398

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('REDINK_PORT', '12398'); urllib.request.urlopen(f'http://localhost:{port}/api/health')" || exit 1

# 启动命令
# Keep one worker by default because active generation task state is in-process.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec /app/.venv/bin/gunicorn --bind ${REDINK_HOST:-0.0.0.0}:${REDINK_PORT:-12398} --workers ${REDINK_GUNICORN_WORKERS:-1} --threads ${REDINK_GUNICORN_THREADS:-8} --timeout ${REDINK_GUNICORN_TIMEOUT:-300} 'backend.app:create_app()'"]
