# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Overview

KiraAI is a modular, multi-platform AI "digital life" system that connects various AI models (LLM, TTS, STT, image/video generation, etc.) to chat platforms (QQ, Telegram, WeChat, Discord, Bilibili, etc.), optimized for virtual companion scenarios.

- **GitHub**: https://github.com/KiraAI-Dev/KiraAI
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
- PR body **must** strictly follow `.github/PULL_REQUEST_TEMPLATE.md` — read it before every `gh pr create`, fill every required section, and never freestyle the body.
- Always check `core/utils/` for existing reusable interfaces before writing new ones.
- Use `core/logging_manager.py` for project logging; obtain loggers through `get_logger(name, color)` to keep console, file, and WebUI log output consistent. Plugins should reuse the existing logger via `from core.plugin import logger` for plugin logging.
- All new code comments must be written in English.
- When developing plugins, expose user-invoked capabilities through LLM-native extension points, such as `@register.tool` and `@register.tag` (XML tags), instead of command syntax for better digital life experience. 
- Plugins must store their runtime data through `ctx.get_plugin_data_dir()` (which resolves to a per-plugin directory under `data/plugin_data/`) instead of writing into the plugin's own source directory.
- JavaScript in a plugin's own WebUI (the plugin's webui assets, e.g. `web/js/*.js`) must be split into separate files; do not pile all of it into a single file.

## Architecture

### Entry Point and Supervisor Pattern

`main.py` is the entry point and supervisor; it spawns a child process (`--_child`). The supervisor loop lives in `core/supervisor.py`, and the child bootstrap (signal handling, data dirs, launcher startup) in `core/child.py`. If the child exits with code 42, the supervisor restarts it with exponential backoff (up to 10 restarts). This enables self-restart after updates.

### Configuration

App config is json-based, loaded by `KiraConfig`. Default values live in `core/config/default.py`. Runtime WebUI config is in `data/webui.json`. The `data/` directory holds all runtime state (config, memory, plugins, DB, stickers, skills).
