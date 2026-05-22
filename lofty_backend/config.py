# Config wrapper that re-exports constants from the main backend file
from lofty_backend_enhanced import (
    APP_NAME,
    BASE_DIR,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    MEMORY_FILE,
    STATIC_DIR,
    ENABLE_TTS,
    OPEN_BROWSER,
    BROWSER_URL,
    WHISPER_MODEL_SIZE,
    ENABLE_TOOL_GRAPH,
)

__all__ = [
    'APP_NAME','BASE_DIR','OLLAMA_BASE_URL','OLLAMA_MODEL','MEMORY_FILE','STATIC_DIR',
    'ENABLE_TTS','OPEN_BROWSER','BROWSER_URL','WHISPER_MODEL_SIZE','ENABLE_TOOL_GRAPH'
]
