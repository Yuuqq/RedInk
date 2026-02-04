<div align="center">

<img src="images/2.png" alt="CSS Lab - AI图文生成器" width="600"/>

## CSS Lab - AI图文生成器

<img src="images/showcase-grid.png" alt="生成效果展示" width="700" style="border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.12);"/>

<sub>*AI 驱动，风格统一，文字准确*</sub>

</div>

---

## ✨ 效果展示

### 输入一句话，生成完整图文

<details open>
<summary><b>Step 1: 智能大纲生成</b></summary>

<br>

![大纲示例](./images/example-2.png)

**功能特性：**
- ✏️ 可编辑每页内容
- 🔄 可调整页面顺序（不建议）
- ✨ 自定义每页描述（强烈推荐）

</details>

<details open>
<summary><b>🎨 Step 2: 封面页生成</b></summary>

<br>

![封面示例](./images/example-3.png)

**封面亮点：**
- 🎯 符合个人风格
- 📝 文字准确无误
- 🌈 视觉统一协调

</details>

<details open>
<summary><b>📚 Step 3: 内容页批量生成</b></summary>

<br>

![内容页示例](./images/example-4.png)

**生成说明：**
- ⚡ 并发生成所有页面（默认最多 15 张）
- ⚠️ 如 API 不支持高并发，请在设置中关闭
- 🔧 支持单独重新生成不满意的页面

</details>

---

## 🏗️ 技术架构

<table>
<tr>
<td width="50%" valign="top">

### 🔧 后端技术栈

| 技术 | 说明 |
|------|------|
| **语言** | Python 3.11+ |
| **框架** | Flask |
| **包管理** | uv |
| **文案AI** | Gemini 3 |
| **图片AI** | 🍌 Nano banana Pro |

</td>
<td width="50%" valign="top">

### 🎨 前端技术栈

| 技术 | 说明 |
|------|------|
| **框架** | Vue 3 + TypeScript |
| **构建工具** | Vite |
| **状态管理** | Pinia |
| **样式** | Modern CSS |

</td>
</tr>
</table>

---

## 📦 如何自己部署

### 方式一：Docker 部署（推荐）

使用本仓库自带的 `docker-compose.yml`：

```bash
docker compose up -d --build
```

访问 http://localhost:12398，在 Web 界面的**设置页面**配置你的 API Key 即可使用。

**Docker 部署说明：**
- 容器内不包含任何 API Key，需要在 Web 界面配置
- 使用 `-v ./history:/app/history` 持久化历史记录
- 使用 `-v ./output:/app/output` 持久化生成的图片
- 可选：挂载自定义配置文件 `-v ./text_providers.yaml:/app/text_providers.yaml`

---

### 方式二：本地开发部署

**前置要求：**
- Python 3.11+
- Node.js 18+
- pnpm
- uv

### 1. 克隆项目
```bash
git clone <your-repo-url>
cd <your-repo-dir>
```

### 2. 配置 API 服务

复制配置模板文件：
```bash
cp text_providers.yaml.example text_providers.yaml
cp image_providers.yaml.example image_providers.yaml
```

编辑配置文件，填入你的 API Key 和服务配置。也可以启动后在 Web 界面的**设置页面**进行配置。

### 3. 安装后端依赖
```bash
uv sync
```

### 4. 安装前端依赖
```bash
cd frontend
pnpm install
```

### 5. 启动服务

#### 一键启动（推荐）

双击运行启动脚本，自动安装依赖并启动前后端：

- **macOS**: `start.sh` 或双击 `scripts/start-macos.command`
- **Linux**: `./start.sh`
- **Windows**: 双击 `start.bat`

启动后自动打开浏览器访问 http://localhost:5173

#### 手动启动

**启动后端:**
```bash
uv run python -m backend.app
```
访问: http://localhost:12398

**启动前端:**
```bash
cd frontend
pnpm dev
```
访问: http://localhost:5173

---

## 🔧 配置说明

### 配置方式

项目支持两种配置方式：

1. **Web 界面配置（推荐）**：启动服务后，在设置页面可视化配置
2. **YAML 文件配置**：直接编辑配置文件

### 管理面板（推荐）

除“系统设置”外，新增了管理面板（默认仅允许本机/内网访问，覆盖 Docker bridge 场景）：

- 前端路由：`/admin`
- 功能：健康检查、上游连通性探测、任务状态列表、日志面板（告警/下载/轮转）、history 统计与清理

管理 API 默认仅允许本机访问（127.0.0.1 / ::1）。如需放开限制（不推荐）：
- `REDINK_ADMIN_TRUST_PRIVATE=1`：允许内网访问
- `REDINK_ADMIN_TRUST_XFF=1`：信任 `X-Forwarded-For`（仅在你完全控制反代时）
- `REDINK_ADMIN_ALLOW_REMOTE=1`：允许任意远程访问

### CLIProxyAPI / OpenAI-Compatible 代理快速接入

如果你有本地代理（例如 CLIProxyAPI），可以在 `/admin` 的“快速接入”中一键写入配置，
也可以手动在 `text_providers.yaml` / `image_providers.yaml` 中设置 `base_url` 和 `api_key`。

### 文本生成配置

配置文件: `text_providers.yaml`

```yaml
# 当前激活的服务商
active_provider: openai

providers:
  # OpenAI 官方或兼容接口
  openai:
    type: openai_compatible
    api_key: sk-xxxxxxxxxxxxxxxxxxxx
    base_url: https://api.openai.com/v1
    model: gpt-4o

  # Google Gemini（原生接口）
  gemini:
    type: google_gemini
    api_key: AIzaxxxxxxxxxxxxxxxxxxxxxxxxx
    model: gemini-2.0-flash
```

### 图片生成配置

配置文件: `image_providers.yaml`

```yaml
# 当前激活的服务商
active_provider: gemini

providers:
  # Google Gemini 图片生成
  gemini:
    type: google_genai
    api_key: AIzaxxxxxxxxxxxxxxxxxxxxxxxxx
    model: gemini-3-pro-image-preview
    high_concurrency: false  # 高并发模式

  # OpenAI 兼容接口
  openai_image:
    type: image_api
    api_key: sk-xxxxxxxxxxxxxxxxxxxx
    base_url: https://your-api-endpoint.com
    model: dall-e-3
    high_concurrency: false
```

### 高并发模式说明

- **关闭（默认）**：图片逐张生成，适合 GCP 300$ 试用账号或有速率限制的 API
- **开启**：图片并行生成（最多15张同时），速度更快，但需要 API 支持高并发

⚠️ **GCP 300$ 试用账号不建议启用高并发**，可能会触发速率限制导致生成失败。

---

## ⚠️ 注意事项

1. **API 配额限制**:
   - 注意 Gemini 和图片生成 API 的调用配额
   - GCP 试用账号建议关闭高并发模式

2. **生成时间**:
   - 图片生成需要时间,请耐心等待（不要离开页面）

---

## 🤝 参与贡献

欢迎提交 Issue 和 Pull Request!

如果这个项目对你有帮助,欢迎给个 Star ⭐


---

## 📄 License

本项目使用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) 协议，详见 `LICENSE`。
