# ✨ KiraAI

KiraAI, a modular, multi-platform AI virtual being that connects Large Language Models (LLMs), Text-to-Speech (TTS), and various chat adapters (QQ, Telegram, Bilibili) with a clean configuration-driven architecture.

## 🚀 Features
- Multi-adapter messaging: QQ, Telegram, Bilibili
- Customizable LLM providers and models
- Configurable TTS (SiliconFlow) with reference audio support
- Persistent memory
- Centralized logging and prompt management

## 🧩 Architecture
- `core/`: orchestration for config, LLMs, prompts, memory, logging
- `adapters/`: platform bridges (qq, telegram, bilibili)
- `utils/`: utils for adapters and messages
- `prompts/`: system/persona/tool/format prompt templates
- `config/`: INI/JSON configs for adapters, models, providers, stickers
- `data/`: runtime data
- `scripts/`: convenience launchers

## 📦 Requirements
- Python 3.10+
- Windows, macOS, or Linux
- Platform credentials/tokens for enabled adapters (QQ, Telegram, etc.)
- Python dependencies in `requirements.txt` (install via `pip install -r requirements.txt`)

## 🛠️ Setup
1. Clone this repository.
2. Create and activate a venv(virtual environment).
3. Install dependencies: `pip install -r requirements.txt`.
4. Prepare configuration files under `config/`

Example (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Example (Bash/Linux):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## ⚙️ Configuration
Key configuration files in `config/`:
- `bot.ini`: core bot settings and runtime toggles
- `models.ini`: model names, parameters, and defaults
- `providers.ini`: LLM/TTS provider credentials and endpoints
- `adapters.ini`: enable/disable platform adapters and their tokens
- `sticker.json`: sticker mapping used by adapters
- `tools/*.ini`: per-tool configs like `tavily.ini`, `ntfy.ini`, `bili.ini`

## ▶️ Run
You can start KiraAI via:
- PowerShell: `python launch.py`
- Batch script: `scripts\run.bat`
- Linux script: `scripts/run.sh` (make executable first)

Make Linux script executable and run:
```bash
chmod +x scripts/run.sh
scripts/run.sh
```

Platform-specific entry points:
- Telegram adapter: `adapters/telegram/tg.py`
- QQ adapter: `adapters/qq/qq_reply.py`

## 🗂️ Project Structure
```
KiraAI/
  adapters/           # Platform bridges (qq, telegram)
  config/             # INI/JSON configs for adapters/models/providers/tools
  core/               # Config/LLM/logging/memory/prompt managers
  data/               # Memory store and assets (stickers)
  prompts/            # Prompt templates
  scripts/            # Launch scripts
  src/tools/          # Tool manager and search utilities
  utils/              # Adapter/message utilities
  launch.py           # Main launcher
```

## 🐞 Troubleshooting
- Check logs under adapter-specific `logs/` directories (e.g., `adapters/qq/logs/`).
- Verify INI paths and sections match the enabled adapters and models.
- Ensure platform tokens are valid and not rate-limited.

## ✨ Star History
