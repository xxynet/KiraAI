<div align="center">

# ✨ KiraAI

Light up the digital soul

English | [简体中文](docs/README.zh.md)

[🧭 Documentation](https://docs.kira-ai.top)

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/) [![Releases](https://img.shields.io/github/v/release/xxynet/KiraAI)](https://github.com/xxynet/KiraAI/releases) [![Commit](https://img.shields.io/github/last-commit/xxynet/KiraAI?color=green)]() [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/xxynet/KiraAI) [![QQ群](https://custom-icon-badges.demolab.com/badge/QQ群-874381335-00BFFF?style=flat&logo=tencent-qq)](https://qm.qq.com/q/eZBJu9wfFC) [![Discord](https://custom-icon-badges.demolab.com/badge/Discord-KiraAI-00BFFF?style=flat&logo=icons8-discord-48)](https://discord.gg/tPRNggzR)

</div>

KiraAI, a modular, multi-platform AI virtual being that connects Large Language Models (LLMs), and various chat platforms (QQ, Telegram, WeChat) with a virtual being centered architecture.

## 🚀 Features
- Optimized for anthropomorphic scenarios
- Customizable LLM providers and models
- Flexible message sending mechanism, various message elements
- Add-ons, expand the boundarieds of AI virtual being
- Function calling
- Persistent memory

## 🧩 Architecture
- `core/`: orchestration for config, LLMs, prompts, memory, logging
- `data/`: runtime data
    - `config/`: INI/JSON configs for adapters, models, providers, stickers
- `scripts/`: convenience launchers
- `webui/`: Management panel

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

The production bundle is emitted to `webui/static/dist/` and served automatically at `/` by the Python backend. The backend returns HTTP 503 at `/` if the bundle is missing — this step is required.

For frontend development with hot-reload, run `npm run dev` in the same directory (Vite dev server on `:3000`, proxies `/api` and `/sticker` to the Python backend on `:5267`).

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

## ⚙️ Configuration
Run the project & enter webui to configure:
- Providers
- Adapters
- Persona
...

## 🗂️ Project Structure
```
KiraAI/
  core/               # Config/LLM/logging/memory/prompt managers
  data/               # Memory store, stickers and configuration
  scripts/            # Launch scripts
  main.py           # Main launcher
```

## 🐞 Troubleshooting
- Check errors printed in system logs on WebUI

## ✨ Star History
[![Star History Chart](https://api.star-history.com/svg?repos=xxynet/KiraAI&type=date&legend=top-left)](https://www.star-history.com/#xxynet/KiraAI&type=date&legend=top-left)