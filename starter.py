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
import torch

from lovify_assistant_split_package.assistant_app.tools import safe_workspace_path

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
    
    @tool
    def list_files(folder:str=".") -> str:
        """List files in a folder inside the approved workspace."""
        target = safe_workspace_path(folder)
        try:
            if not target.exists():
                return f"Folder does not exist: {target}"
            items = []
            for p in sorted(target.iterdir()):
                items.append(f"{'[DIR]'if p.is_dir() else '[FILE]'} {p.name}")
            return "\n".join(items) if items else "No files found."
        except Exception as exc:
            return f"Failed to list files in {folder}:{exc}"
    @tool
    def read_file(file_path:str) -> str:
        """Read a file inside the approved workspace and return its contents as text."""
        target = safe_workspace_path(file_path)
        try:
            if not target.exists():
                return f"File does not exist: {target}"
            return target.read_text(encoding="utf-8")
        except Exception as exc:
            return f'Failed to read file {file_path}:{exc}'

    @tool
    def write_file(file_path:str, content:str) -> str:
        """Write text content to a file inside the approved workspace. Create parent folders if needed."""
        target = safe_workspace_path(file_path)
        try:
            target.write_text(content, encoding = "utf-8")
            return f"Wrote {len(content)} characters to {file_path}"
        except Exception as exec:
            return f"Failed to write file {file_path}:{exec}"
    @tool
    def remember_preference(key:str, value:str) -> str:
        """Remember a user preference as a key-value pair. Use the 'get_preference' tool to retrieve it later."""
        try:
            self.memory.set(key,value)
            return f"Remembered preference {key}={value}"
        except Exception as exc:
            return f"Failed to remember preference {key}:{exc}"
    
    @tool
    def recall_preference(key:str) -> str:
        """Recall a previously remembered user preference by key"""
        try:
            value = self.memory.get(key.strip())
            if value is None:
                return f"No preference found for {key}"
            return f"{key} = {value}"
        except Exception as exc:
            return f"Failed to recall preference {key}:{exc}"
    @tool
    def show_memory() -> str:
        """Show the saved long-term memory as a JSON string. This includes all remembered preferences.
        """
        try:
            mem = self.memory.all()
            if not mem:
                return "Memory is empty."
            return json.dumps(mem, indent=2, ensure_ascii=False)
        except Exception as exc:
            return f"Failed to show memory:{exc}"
    
    @tool
    def call_booking_api(service:str,payload_json:str) -> str:
        """Call a booking API for a configured through enviroment variables. This is a placeholder tool and will not work unless properly set up. Only use this when you are sure the API is configured, and always ask for confirmation before calling it.
        """ 
        import requests
        base_url = os.getenv("BOOKING_API_BASE_URL", "").strip()
        api_key = os.getenv("BOOKING_API_KEY", "").strip()
        if not base_url or not api_key:
            return "Booking API is not configured."
        try:
            payload = json.loads(payload_json)
        except Exception as exc:
            return f"Invalid JSON payload:{exc}"
        headers = {'content-type':'application/json'}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            response = requests.post(
                base_url.rstrip("/") + f"/{service.lstrip('/')}",
                json=payload,
                headers=headers
                timeout=10
            )
            return f"Status: {response.status_code}: {response.text[:1500]}"
        except Exception as exc:
            return f"Failed to call booking API:{exc}"
        

    @tool
    def call_order_api(action: str, payload_json: str) -> str:
        """Call an order API configured through environment variables."""
        import requests

        base_url = os.getenv("ORDER_API_URL", "").strip()
        api_key = os.getenv("ORDER_API_KEY", "").strip()
        if not base_url:
            return "ORDER_API_URL is not configured."

        try:
            payload = json.loads(payload_json)
        except Exception as exc:
            return f"Invalid JSON payload: {exc}"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            response = requests.post(
                base_url.rstrip("/") + f"/{action.lstrip('/')}",
                json=payload,
                headers=headers,
                timeout=30,
            )
            return f"Status {response.status_code}: {response.text[:1500]}"
        except Exception as exc:
            return f"Order API call failed: {exc}"
        
    
RISKY_TOOLS = {
    "write_file",
    "call_booking_api",
    "call_order_api",
}

def safe_workspace_path(path_str:str,create_parent:bool=False) -> Path:
    """Resolve a path safely inside the workspace, preventing directory traversal. Optionally create parent folders if they don't exist."""
    candidate = (WORKSPACE_ROOT/path_str).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if workspace not in candidate.parents and candidate != workspace:
        raise ValueError(f"Path must stay inside the workspace.")
    if create_parent:
        candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate

class WhisperTranscriber:
    def __init__(self) -> None:
        self._model = None
        self.error  = None
    try:
        import numpy as np
        import sounddevice as sd
        from scipy.io.wavfile import wav_write
        from faster_whisper import WhisperModel

        self.np = np
        self.sd = sd
        self.wav_write = wav_write
        self.WhisperModel = WhisperModel
        print("VOICE INIT OK")
    except Exception as e:
        self.np = None
        self.sd = None
        self.wav_write = None
        self.WhisperModel = None
        self.error = repr(e)
        print(f"VOICE INIT FAILED:{self.error}")
    def available(self) ->  bool:
        return self.error is None 
    
    def model(self):
        if self._model is None:
            if self.WhisperModel is None:
                raise RuntimeError(f"Whisper model is not available: {self.error}")
            self._model = self.WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        return self._model
    def record_seconds(self,seconds:float = 5.0, sample_rate:int = 16000) -> Path:
        if not self.available():
            raise RuntimeError(f"Voice dependencies are missing: {self.error}")
        print(f"Recording for {seconds} seconds...")
        audio = self.sd.rec(int(seconds * sample_rate),samplerate=sample_rate,channels=1,dtype="float32")
        self.sd.wait()
        data = self.sd.rec(int(audio))
        temp_path = Path(tempfile.gettempdir()) / f"lovify_{int(time.time())}.wav"
        int16_audio = self.np.int16(self.np.clip(data, -1.0, 1.0) * 32767)
        self.wav_write(str(temp_path), sample_rate, int16_audio)
        return temp_path
    def transcribe(self,wav_path:Path) -> str:
        model = self.model()
        segments, _info  = model.transcribe(str(wav_path),language="en")
        return " ".join(segments.text.strip() for segment in segments).strip()
        
