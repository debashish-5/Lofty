from __future__ import annotations 
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any, Dict, Annotated, Optional, TypedDict, Union

import tkinter as tk
from tkinter import filedialog,messagebox,scrolledtext

import langchain_core
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph,START,END
from langgraph.graph.message import add_messages
from langchain_ollama import ChatOllama
from streamlit import user

#let optional voice deps 
try:
    import pandas as pd
    import sounddevice as sd
    from scipy.io.wavfile import wav_write
except Exception: #program no cover
    np = None
    sd = None
    wav_write = None
try:
    from faster_whisper import WhisperModel
except Exception: #program no cover
    WhisperModel = None

try:
    import pyttsx3
except Exception: #program no cover
    pyttsx3 = None

try:
    from PIL import Image, ImageSequence, ImageTk
except Exception: #program no cover
    Image = None
    ImageSequence = None
    ImageTk = None


APP_NAME = "Lovify Assistant"
MODEL_NAME = os.getenv("MODEL_NAME","mistral")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL","http://localhost:11434")
THREAD_ID = os.getenv("ASSISTANT_THREAD_ID","default-thread")
WORKSPACE_ROOT = Path.cwd()/"assistant_workspace"
WORKSPACE_ROOT.mkdir(exist_ok=True)

# from pathlib import Path

# # 1. Define the path location
# WORKSPACE_ROOT = Path.cwd() / "assistant_workspace"

# # 2. Physically create the folder if it does not exist yet
# WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

MEMORY_FILE = Path.cwd()/"assistant_memory.json"
IDLE_IMAGE = os.getenv("IDLE_IMAGE","assets/idle.png")
SPEAKING_GIF = os.getenv("SPEAKING_GIF","assets/speaking.gif")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE","base")


SYSTEM_PROMPT = """
You are Lovify, a warm, highly capable local desktop assistant.

Personality:
- Speak naturally, like a helpful human assistant.
- Be concise by default, but detailed when asked.
- Use a friendly, caring tone.
- Never pretend to have done something unless a tool actually completed it.

Capabilities:
- Open local apps.
- Read and write files inside the approved workspace.
- Remember preferences.
- Open URLs in the browser.
- Call external booking/order APIs only when configured.

Safety rules:
- Before risky actions like placing orders, booking appointments, deleting files, or writing outside the workspace, ask for confirmation.
- For anything uncertain, ask a brief clarifying question.
- Do not invent tool results.

When a tool is useful, call it.
When the user wants a normal reply, answer directly.
""".strip()

class AssistantState(TypedDict,total=False):
    message: Annotated[list[BaseMessage], add_messages]
    padding_tool_calls: list[dict[str, Any]]
    approved: bool
    ui_state: str


@dataclass
class UserMemory:
    profile_path: Path = MEMORY_FILE
    data: dict[str, Any] = field(default_factory=dict)

    def load(self) -> None:
        if self.profile_path.exists():
            try:
                self.data = json.loads(self.profile_path.read_text(encoding="utf-8"))
            except Exception as e:
                self.data = {}
            else:
                self.data = {}
    def save(self) -> None:
        self.profile_path.write_text(json.dumps(self.data,indent=2,ensure_ascii=False),encoding="utf-8")
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)
    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()
    def all(self) -> dict[str,Any]:
        return dict(self.data)
    
class AssistantTools:
    def __init__(self, memory: UserMemory):
        self.memory = memory
    
    @tool
    def open_app(app_name:str) -> str:
        """Open a common local desktop app on windows, or attempt to launch a program by name."""
        app_map = {
            "notepad":["notepad.exe"],
            "calculator":["calc.exe"],
            "paint":["mspaint.exe"],
            "explorer":["explorer.exe"],
            "chrome":["chrome"],
            "edge":["msedge"],
            "vscode":["code"],
            "vs code":["code"],
            "cmd":["cmd.exe"],
            "terminal":["cmd.exe"],
            "instagram":["instagram.exe"], 
            "discord":["discord.exe"],
            "anaconda prompt":["anaconda prompt.exe"],
            "whatsapp":["whatsapp.exe"],

        }
        key = app_name.strip().lower()
        cmd = app_map.get(key,[app_name])
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(cmd,shell=False)
            else:
                subprocess.Popen(cmd)
            return f"Opened {app_name}."
        except Exception as exc:
            return f"Failed to open {app_name}:{exc}"
    
    @tool
    def open_url(url:str) -> str:
        """Open a URL in the default web browser."""
        try:
            webbrowser.open(url)
            return f"Opened {url} in the browser."
        except Exception as exc:
            return f"Failed to open {url}:{exc}"
