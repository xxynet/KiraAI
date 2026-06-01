# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Overview

KiraAI is a modular, multi-platform AI "digital life" system that connects various AI models (LLM, TTS, STT, image/video generation, etc.) to chat platforms (QQ, Telegram, WeChat, Discord, Bilibili, etc.), optimized for virtual companion scenarios.

- **GitHub**: https://github.com/xxynet/KiraAI
- **Docs**: https://docs.kira-ai.top

Version is defined in `core/config/default.py`.

## Development Commands

### Backend (Python 3.10+)

```bash
python main.py                    # Run the application
python main.py --env dev          # Dev mode (enables API docs + access logs)
python -m pytest tests/ -v        # Run all tests
python -m pytest tests/test_config_loader.py -v  # Run a single test file
```

### Frontend (Node.js 18+, Vue 3 + Vite)

```bash
cd webui/frontend
npm install
npm run dev      # Dev server on :3000, proxies /api → :5267
npm run build    # Type-check (vue-tsc) + build → webui/static/dist/
```

### Docker

```bash
docker-compose up
```

## Rules

- WebUI changes must include corresponding i18n updates (sync both CN and EN translation files under `webui/frontend/src/i18n/`).
- Always read and follow `.github/PULL_REQUEST_TEMPLATE.md` before submitting a PR.
- Always check `core/utils/` for existing reusable interfaces before writing new ones.
- All new code comments must be written in English.

## Architecture

### Entry Point and Supervisor Pattern

`main.py` is a supervisor that spawns a child process (`--_child`). If the child exits with code 42, the supervisor restarts it with exponential backoff (up to 10 restarts). This enables self-restart after updates.

### Configuration

App config is json-based, loaded by `KiraConfig`. Default values live in `core/config/default.py`. Runtime WebUI config is in `data/webui.json`. The `data/` directory holds all runtime state (config, memory, plugins, DB, stickers, skills).
