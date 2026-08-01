<div align="center">

# ✨ KiraAI

点亮数字生命灵魂

[English](/README.md) | 简体中文

[🧭 文档](https://docs.kira-ai.top/zh/)

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/) [![Releases](https://img.shields.io/github/v/release/xxynet/KiraAI)](https://github.com/xxynet/KiraAI/releases) [![Commit](https://img.shields.io/github/last-commit/xxynet/KiraAI?color=green)](https://github.com/xxynet/KiraAI/commits) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/xxynet/KiraAI) [![QQ群](https://custom-icon-badges.demolab.com/badge/QQ群-874381335-00BFFF?style=flat&logo=tencent-qq)](https://qm.qq.com/q/eZBJu9wfFC) [![Discord](https://custom-icon-badges.demolab.com/badge/Discord-KiraAI-00BFFF?style=flat&logo=icons8-discord-48)](https://discord.gg/mRNmVmFHn3)

</div>

KiraAI，一个模块化、跨平台的 AI 数字生命项目，以数字生命为中心，连接多种 AI 模型（LLM、TTS、STT、图片/视频生成等）与聊天平台（QQ、Telegram、微信、Discord、Bilibili等）。

## 🚀 功能特性
- 专为拟人场景优化
- 易于使用的 WebUI
- 可自定义的 LLM 提供商与模型
- 灵活的消息发送机制，丰富的消息元素支持
- 插件（Plugin），可自行拓展数字生命能力边界

## 📷 截图

![alt text](/screenshots/webui-light-cn.png)

![alt text](/screenshots/webui-dark-cn.png)

<details>
<summary>📸 聊天截图</summary>

![alt text](/screenshots/image01.jpg)

![alt text](/screenshots/image02.png)

![alt text](/screenshots/image03.png)

![alt text](/screenshots/image04.png)

![alt text](/screenshots/image05.png)

![alt text](/screenshots/image06.png)

</details>

> [!IMPORTANT]
> 本项目在活跃开发期间，可能会有 **破坏性更新**

## 💻 快速开始

> [!NOTE]
> 如需使用其他部署方案，请参考 [部署文档](https://docs.kira-ai.top/zh/deployment/windows.html)

首先，确保你的电脑中安装了 Python 3.10+ 并且添加到了 `PATH` 环境变量

前往 [Releases](https://github.com/xxynet/KiraAI/releases) 下载标记为 `latest` 的 Release 中的 `Source code
(zip)`
解压并执行 `scripts/run.bat` （Windows 用户） 或执行 `scripts/run.sh` （Linux、Mac 用户）

### 🐳 Docker（可选）

更倾向容器部署？请先安装 [Docker](https://docs.docker.com/get-docker/)，然后：

```bash
# 拉取预构建镜像并后台启动
docker compose up -d
```

KiraAI 将运行在 `http://localhost:5267`，运行时数据持久化在 `./data`（容器内挂载至 `/app/data`）。

```bash
docker compose logs -f    # 查看日志
docker compose down       # 停止容器
```

> 默认从 Docker Hub 拉取 `xxynet/kira-ai:latest`，`docker-compose.yml` 中不包含 `build` 段。

## 🧪 开发指南

<details>
<summary>展开开发指南</summary>

## 📦 环境要求
- Python 3.10+ （推荐 3.10-3.12）
- Node.js 18+ 与 npm（用于构建 WebUI 管理面板）
- Windows、macOS 或 Linux

## 🛠️ 安装与初始化
1. 克隆本仓库。
2. 进入 KiraAI 文件夹

## 🎨 构建 WebUI
管理面板是基于 Vue 3 + Vite 的单页应用，首次运行前需要构建一次：

```bash
cd webui/frontend
npm install
npm run build
```

Vite 构建产物会输出到 `webui/static/dist/`。启动时，后端会自动检测 `data/dist/` 下的前端产物——若缺失或版本不匹配，将从 GitHub Releases 自动下载预构建包。若产物不可用，后端访问 `/` 会返回 HTTP 503。

如需前端热重载开发，在同目录下运行 `npm run dev`（Vite 开发服务器监听 `:3000`，会把 `/api` 和 `/sticker` 代理到本地 `:5267` 的 Python 后端）。

本地开发时，可使用 `--webui-dir` 参数指向本地构建产物并跳过版本校验：

```bash
python main.py --webui-dir webui/static/dist --ignore-webui-version-check
```

拉取前端改动后记得重新执行 `npm run build`。

## ▶️ 运行
可通过以下方式启动 KiraAI（venv）：
- Windows 批处理：`scripts\run.bat`
- Linux 脚本：`scripts/run.sh`（先赋予可执行权限）

Linux 赋权并运行：
```bash
chmod +x scripts/run.sh
scripts/run.sh
```

</details>

## ⚙️ 配置项
运行项目后进入WebUI配置
- 提供商
- 适配器
- 人设
...

## 🛠️ CLI 参数

KiraAI 支持通过命令行启动，所有参数均为可选，省略时使用合理的默认值。

| 参数 | 说明 | 默认值 | 示例 |
| --- | --- | --- | --- |
| `--data-dir <path>` | 指定 KiraAI 存放运行时数据的目录（数据库、日志、缓存、会话文件等）。 | `./data` | `kiraai --data-dir /var/lib/kiraai` |
| `--env <dev\|prod>` | 指定运行环境。`dev` 开启调试日志、热重载与详细报错；`prod` 使用优化行为与生产级日志。也可通过环境变量 `KIRA_ENV` 设置。 | `prod` | `kiraai --env dev` |
| `--disable-webui-auth` | 关闭 WebUI 的登录鉴权。仅建议在可信的本地网络中使用。 | 关闭（默认启用鉴权） | `kiraai --disable-webui-auth` |
| `--telemetry-server <url>` | 覆盖遥测数据上报的服务端地址。也可通过环境变量 `KIRA_TELEMETRY_SERVER` 设置。 | 默认的 KiraAI 遥测服务地址 | `kiraai --telemetry-server https://telemetry.example.com` |
| `--webui-dir <path>` | 指定自定义 WebUI 静态文件目录（前端构建产物），用于替代内置的 WebUI。 | 内置 WebUI | `kiraai --webui-dir ./webui/dist` |
| `--ignore-webui-version-check` | 跳过 WebUI 与后端之间的版本兼容性检查。适用于运行自定义构建或版本不匹配的 WebUI 时。 | 关闭（默认检查版本） | `kiraai --ignore-webui-version-check` |

### 环境变量

| 变量 | 说明 |
| --- | --- |
| `KIRA_ENV` | 等价于 `--env`，取值 `dev` / `prod`。 |
| `KIRA_TELEMETRY_SERVER` | 等价于 `--telemetry-server`。 |

## 📡 遥测

KiraAI 会收集匿名遥测数据，用于了解项目使用情况、确定开发优先级并改善稳定性。遥测**默认开启**。

### 收集内容

- **匿名使用数据** —— 汇总统计：各平台消息数、LLM 调用次数与 token 用量、平均响应时间。
- **运行环境信息** —— KiraAI 版本、Python 版本、操作系统平台。
- **客户端标识** —— 随机生成的匿名安装 ID。
- **国家代码** —— 启动时通过第三方服务（`ip-api.com`，明文 HTTP）根据公网 IP 解析一次。

**不会收集**聊天内容、消息记录、个人信息或文件/配置内容。

### 关闭遥测

遥测默认开启，可通过以下任一方式关闭：

**方式一：环境变量（推荐）**

```bash
KIRA_TELEMETRY_ENABLED=0 python main.py
```

**方式二：修改 `system_config.json`**，将 `telemetry.enabled` 设为 `false` 并重启 KiraAI：

```json
{
  "telemetry": {
    "enabled": false
  }
}
```

> 注：目前 WebUI 中没有遥测开关。

## 🗂️ 项目结构

<details>
<summary>展开项目结构</summary>

```
KiraAI/
  core/               # 核心模块
    event_bus.py        # 事件总线：内部与平台事件的异步发布/订阅
    launcher.py         # KiraLauncher：启动 WebUI 与生命周期
    lifecycle.py        # KiraLifecycle：所有模块与后台任务的核心管理器
    llm_client.py       # LLMClient：统一 LLM 客户端（含工具调用）
    logging_manager.py  # 彩色控制台日志 + 滚动文件日志
    temp_monitor.py     # AsyncTempMonitor：异步清理临时/缓存目录
    adapter/           # 适配器（聊天平台接入）
    agent/             # 代理执行器、MCP 管理、技能管理
    chat/              # 会话管理与消息处理
    config/            # 配置加载与字段定义
    db/                # 数据库管理与模型
    persona/           # 人设管理
    plugin/            # 插件系统
    prompts/           # 提示词模板
    provider/          # LLM 提供商管理
    statistics/        # 统计模块
    tag/               # 标签系统
    telemetry/         # 遥测模块
    utils/             # 通用工具
    workflow/          # 工作流系统
  data/               # 记忆、表情包、配置文件、插件数据
  docs/               # 项目文档
  scripts/            # 启动脚本
  screenshots/        # 截图
  webui/              # WebUI 前后端
  main.py             # 主启动入口
```

</details>

## ✨ Star History
[![Star History Chart](https://api.star-history.com/svg?repos=xxynet/KiraAI&type=date&legend=top-left)](https://www.star-history.com/#xxynet/KiraAI&type=date&legend=top-left)