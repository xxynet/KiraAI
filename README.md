<div align="center">

# ✨ KiraAI

Light up the digital soul

English | [简体中文](docs/README.zh.md)

[🧭 Documentation](https://docs.kira-ai.top)

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/) [![Releases](https://img.shields.io/github/v/release/xxynet/KiraAI)](https://github.com/xxynet/KiraAI/releases) [![Commit](https://img.shields.io/github/last-commit/xxynet/KiraAI?color=green)](https://github.com/xxynet/KiraAI/commits) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/xxynet/KiraAI) [![QQ群](https://custom-icon-badges.demolab.com/badge/QQ群-874381335-00BFFF?style=flat&logo=tencent-qq)](https://qm.qq.com/q/eZBJu9wfFC) [![Discord](https://custom-icon-badges.demolab.com/badge/Discord-KiraAI-00BFFF?style=flat&logo=icons8-discord-48)](https://discord.gg/mRNmVmFHn3)

</div>

KiraAI, a modular, multi-platform AI digital life that connects various AI models (LLM, TTS, STT, image/video generation, etc.) and chat platforms (QQ, Telegram, WeChat, Discord, Bilibili, etc.) with a digital life centered architecture.

## 🚀 Features
- Optimized for anthropomorphic scenarios
- Easy-to-use WebUI
- Customizable LLM providers and models
- Flexible message sending mechanism, various message elements
- Add-ons, expand the boundarieds of AI digital life

## 📷 ScreenShots

![alt text](screenshots/webui-light-en.png)

![alt text](screenshots/webui-dark-en.png)

<details>
<summary>📸 CHat screenshots</summary>

![alt text](screenshots/image01.jpg)

![alt text](screenshots/image02.png)

![alt text](screenshots/image03.png)

![alt text](screenshots/image04.png)

![alt text](screenshots/image05.png)

![alt text](screenshots/image06.png)

</details>

> [!IMPORTANT]
> This project is in active development, and **breaking changes** may occur.

## 💻 Quick Start

> [!NOTE]
> For other deployment options, see the [Deployment Guide](https://docs.kira-ai.top/deployment/windows.html).

First of all, you need to have Python 3.10+ installed and in the `PATH` environment variable

Go to [Releases](https://github.com/xxynet/KiraAI/releases) and download `Source code
(zip)` from the release tagged latest

Extract zip and run `scripts/run.bat` on Windows or run `scripts/run.sh` on Linux or Mac

## 🧪 Development Guide

<details>
<summary>Toggle Development Guide</summary>

## 📦 Requirements
- Python 3.10+
- Node.js 18+ and npm (required to build the WebUI admin panel)
- Windows, macOS, or Linux

## 🛠️ Setup
1. Clone this repository.
2. Enter KiraAI folder

## 🎨 Build the WebUI
The admin panel is a Vue 3 + Vite single-page app. Build it once before first run:

```bash
cd webui/frontend
npm install
npm run build
```

The Vite build emits to `webui/static/dist/`. At startup, the backend checks for the matching frontend dist in `data/dist/` — if missing or outdated, it automatically downloads the pre-built bundle from GitHub Releases. The backend returns HTTP 503 at `/` if no dist is available.

For frontend development with hot-reload, run `npm run dev` in the same directory (Vite dev server on `:3000`, proxies `/api` and `/sticker` to the Python backend on `:5267`).

To use your local build instead of the downloaded one, pass `--webui-dir` and optionally skip the version check:

```bash
python main.py --webui-dir webui/static/dist --ignore-webui-version-check
```

Re-run `npm run build` after pulling frontend changes.

## ▶️ Run
You can start KiraAI via (venv):
- Batch script: `scripts\run.bat`
- Linux script: `scripts/run.sh` (make executable first)

Make Linux script executable and run:
```bash
chmod +x scripts/run.sh
scripts/run.sh
```

</details>

## ⚙️ Configuration
Run the project & enter webui to configure:
- Providers
- Adapters
- Persona
...

## 🗂️ Project Structure

<details>
<summary>Toggle Project Structure</summary>

```
KiraAI/
  core/               # Core modules
    adapter/           # Chat platform adapters
    agent/             # Agent executor, MCP & skill management
    chat/              # Session management & message handling
    config/            # Configuration loading & field definitions
    db/                # Database management & models
    persona/           # Persona management
    plugin/            # Plugin system
    prompts/           # Prompt templates
    provider/          # LLM provider management
    statistics/        # Statistics module
    tag/               # Tag system
    telemetry/         # Telemetry module
    utils/             # Common utilities
    workflow/          # Workflow system
  data/               # Memory, stickers, configs, plugin data
  docs/               # Documentation
  scripts/            # Launch scripts
  screenshots/        # Screenshots
  webui/              # WebUI backend & frontend
  main.py             # Main launcher
```

</details>

## ✨ Star History
[![Star History Chart](https://api.star-history.com/svg?repos=xxynet/KiraAI&type=date&legend=top-left)](https://www.star-history.com/#xxynet/KiraAI&type=date&legend=top-left)