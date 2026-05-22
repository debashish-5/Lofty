Lofty — Terminal-Style Local AI Assistant
=========================================

=====================================================================
| Lofty Terminal — Local-first cinematic assistant                     |
|--------------------------------------------------------------------|
| Clean local UI · Ollama Model integration · Tool graph · Voice + TTS |
=====================================================================

Overview
--------

Lofty is a local-first, terminal-style assistant designed to run on your machine. It pairs a lightweight FastAPI backend with a cinematic terminal UI to deliver a fast, privacy-friendly assistant experience powered by Ollama (or a local model), with optional voice transcription and TTS.

Core Concepts
-------------
- **Assistant**: The conversational layer powered by local LLMs (via Ollama) and a tool-aware graph when enabled.
- **Tool Graph**: LangGraph-based flow that allows the LLM to emit tool calls (open URLs, run shell commands, read/write files, and more). Tools run on the host and return outputs as assistant messages.
- **Memory**: JSON-backed session and preference storage (`lofty_memory.json`) to persist conversation history and user preferences.
- **UI**: A single-page terminal-like frontend in `templates/chatbot.html` with clickable cards, voice control, and theme support.
- **Voice/TTS**: Optional serverside transcription using `faster-whisper` and TTS via `pyttsx3` (config-controlled).

Why this project
-----------------
- Works offline with local LLMs via Ollama.
- Tool-aware assistant capable of safe host interactions (file access, app launches, web links).
- Developer-friendly: small codebase, clear entrypoints, and modular wrappers.

Quickstart
----------

1. Install Python dependencies:

```bash
pip install -r requirements_lofty_backend.txt
```

2. Run the backend (recommended):

```bash
uvicorn lofty_backend_enhanced:app --reload --host 0.0.0.0 --port 8000
```

Or run directly (the module will start uvicorn if executed):

```bash
python lofty_backend_enhanced.py
```

Open the UI in your browser:

- http://127.0.0.1:8000/

Project Layout (core files)
---------------------------
- `lofty_backend_enhanced.py` — Main FastAPI app and original full implementation.
- `templates/` — HTML frontend; `chatbot.html` is the terminal UI.
- `tools.py` — Utility assistant and tool implementations (secondary assistant package).
- `lofty_backend/` — thin package wrappers created for modular imports (config, utils, assistant, memory).
- `lofty_memory.json` — persisted session and preferences store.

Architecture Diagram
--------------------

```mermaid
flowchart LR
  Browser[Browser UI (chatbot.html)] -->|POST /api/chat| FastAPI[FastAPI backend]
  FastAPI -->|system / messages| ToolAssistant[Tool Assistant / LangGraph]
  ToolAssistant --> Ollama[Ollama / Local LLM]
  ToolAssistant -->|calls| Tools[Host Tools (open_app, shell, file ops)]
  FastAPI -->|optional| Whisper[faster-whisper]
  FastAPI -->|optional| TTS[pyttsx3 TTS]
  Tools -->|reads/writes| Workspace[Workspace Files]
```

Badges & Stickers (Digital Collateral)
-------------------------------------
- Add decorative badges to `assets/badges/` (PNG or SVG). Examples: `badge-core.png`, `badge-local.png`, `badge-privacy.png`.
- Place modern sticker images in `assets/stickers/` and reference them in documentation or the UI.

How to add a banner or video
---------------------------
- Add `assets/intro.mp4` and reference in `templates/chatbot.html` using the `<video>` tag. The UI already checks for an intro video; place a web-optimized MP4 (H.264) into `assets/`.
- Add poster images (e.g., `assets/banner.jpg`) and reference in README or site.

Development Workflow
--------------------
- Branch pattern: `main` (stable), `develop` (integration), feature branches (`feature/*`).
- Run server locally and iterate on `templates/chatbot.html` for UI tweaks.
- Use the tool wrappers in `lofty_backend` when building new features; they keep `lofty_backend_enhanced.py` stable as the canonical app entry.

Components (Responsibilities)
-----------------------------
- **API Layer** (`lofty_backend_enhanced.py`): HTTP endpoints, file serving, transcribe/speak endpoints.
- **Assistant core** (`tools.py`, `AssistantCore`): LLM tool binding, graph orchestration, tool invocation.
- **Tools** (`tools.py` & `AssistantTools`): Host-level operations (open_app, shell_command, read/write files, web search).
- **UI** (`templates/chatbot.html`, `assets/`): Terminal UI, local voice capture, clickable link cards.

Testing & Checks
---------------
- Syntax check for Python files:

```bash
python -m py_compile lofty_backend_enhanced.py tools.py
```

- Basic import smoke test:

```bash
python -c "import lofty_backend_enhanced, tools; print('imports ok')"
```

Security & Safety Notes
-----------------------
- Tools that operate on the host (file writes, shell) are marked as risky. The assistant design requires confirmation before destructive actions.
- `safe_workspace_path()` enforces workspace-scoped file reads/writes in `tools.py` and the backend.

Advanced Recipes
----------------
- Forcing tool-aware model behavior: update `SYSTEM_PROMPT` to instruct the LLM to call tools for any actionable commands (open, read, write, search).
- To enable server-side TTS and transcription, install `pyttsx3` and `faster-whisper` and set environment variables:

```bash
export LOFTY_ENABLE_TTS=1
export WHISPER_MODEL_SIZE=base
```

Troubleshooting
---------------
- Ollama connectivity: ensure Ollama is running on `localhost:11434` or set `OLLAMA_BASE_URL`.
- App open failures on Windows: the code maps aliases (e.g., `camera` → `microsoft.windows.camera:`) but some systems require exact package names; check `open_application()` in `lofty_backend_enhanced.py`.

Contribution & Roadmap
----------------------
- Short-term: split `lofty_backend_enhanced.py` into modular modules (done partially with `lofty_backend/` wrappers); next, migrate implementations into smaller files.
- Mid-term: add tests, CI workflow, and a packaged installer for Windows/Mac.

Contact & Credits
-----------------
- Maintainer: local project workspace (you)
- Acknowledgements: Ollama, LangGraph, LangChain tooling, faster-whisper, pyttsx3, DuckDuckGo search.

License
-------
Choose a license for your project and add a `LICENSE` file. Common choices: MIT, Apache-2.0.

Assets & Next Steps
-------------------
1. Add `assets/badges/` and `assets/stickers/` images; reference paths in this README.
2. Add `assets/intro.mp4` for the intro video if desired.
3. If you want, I can fully refactor the large backend file into the `lofty_backend/` modules now and run tests.

----
Generated by your project tooling assistant — README created to be human- and developer-friendly.
