# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Overview

KiraAI is a modular, multi-platform AI "digital life" system that connects various AI models (LLM, TTS, STT, image/video generation, etc.) to chat platforms (QQ, Telegram, WeChat, Discord, Bilibili, etc.), optimized for virtual companion scenarios.

- **GitHub**: https://github.com/xxynet/KiraAI
- **Docs**: https://docs.kira-ai.top

Version is defined in `core/config/default.py` and mirrored in `pyproject.toml`.

## Development Commands

### Backend (Python 3.10+)

```bash
python main.py                    # Run the application
python main.py --env dev          # Dev mode (enables API docs + access logs)
python -m pytest tests/ -v        # Run all tests
python -m pytest tests/test_config_loader.py -v  # Run a single test file
```

Either pip or [uv](https://docs.astral.sh/uv/) can manage the environment:

```bash
pip install -r requirements.txt        # pip
export UV_PROJECT_ENVIRONMENT=venv     # uv: keep the environment at venv/, not .venv/
uv sync                                # uv: create venv/ and install (dev group included)
uv run python main.py                  # Run without activating the environment
```

The environment directory is always `venv/`. `.python-version` pins the
interpreter to 3.11 (same as the Docker image); `requires-python` stays `>=3.10`
because CI tests 3.10–3.12.

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
- All new code comments must be written in English.
- New runtime dependencies must be added to **both** `requirements.txt` and `pyproject.toml`; `tests/test_pyproject_sync.py` fails if they drift.
- Never shell out to `sys.executable -m pip` — environments created by `uv venv` have no pip. Use `core/utils/pkg_installer.py` instead.

## Architecture

### Entry Point and Supervisor Pattern

`main.py` is a supervisor that spawns a child process (`--_child`). If the child exits with code 42, the supervisor restarts it with exponential backoff (up to 10 restarts). This enables self-restart after updates.

### Configuration

App config is json-based, loaded by `KiraConfig`. Default values live in `core/config/default.py`. Runtime WebUI config is in `data/webui.json`. The `data/` directory holds all runtime state (config, memory, plugins, DB, stickers, skills).
