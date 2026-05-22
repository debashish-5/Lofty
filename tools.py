from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Annotated, Optional, TypedDict

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LinearRegression
from sklearn.metrics import accuracy_score, mean_squared_error
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langchain_ollama import ChatOllama
from duckduckgo_search import DDGS
# Optional voice deps
try:
    import numpy as np
    import sounddevice as sd
    from scipy.io.wavfile import write as wav_write
except Exception:  # pragma: no cover
    np = None
    sd = None
    wav_write = None

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover
    WhisperModel = None

try:
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None

try:
    from PIL import Image, ImageSequence, ImageTk
except Exception:  # pragma: no cover
    Image = None
    ImageSequence = None
    ImageTk = None


APP_NAME = "Lovify Assistant"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
THREAD_ID = os.getenv("ASSISTANT_THREAD_ID", "default-thread")
WORKSPACE_ROOT = Path.cwd() / "assistant_workspace"
MEMORY_FILE = Path.cwd() / "assistant_memory.json"
IDLE_IMAGE = os.getenv("IDLE_IMAGE", "assets/idle.png")
SPEAKING_GIF = os.getenv("SPEAKING_GIF", "assets/speaking.gif")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

WORKSPACE_ROOT.mkdir(exist_ok=True)

MODELS_DIR = WORKSPACE_ROOT/"models"
MODELS_DIR.mkdir(exist_ok=True)

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


class AssistantState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_tool_calls: list[dict[str, Any]]
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
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        self.profile_path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def all(self) -> dict[str, Any]:
        return dict(self.data)

class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, Any] = {"sessions": {}, "preferences": {}}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data = loaded
        except Exception:
            self.data = {"sessions": {}, "preferences": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def session_messages(self, session_id: str) -> List[Dict[str, str]]:
        sessions = self.data.setdefault("sessions", {})
        session = sessions.setdefault(session_id, {"messages": []})
        return session.setdefault("messages", [])

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.session_messages(session_id).append({"role": role, "content": content})
        self.save()

    def set_preference(self, key: str, value: Any) -> None:
        self.data.setdefault("preferences", {})[key] = value
        self.save()

    def all(self) -> Dict[str, Any]:
        return self.data


class AssistantTools:
    def __init__(self, memory: UserMemory):
        self.memory = memory
    def get_tool(self):
        memory = self.memory

            
        @tool
        def open_app(app_name: str) -> str:
            """Open a common local desktop app on Windows, or attempt to launch a program by name."""
            app_map = {
                "notepad": ["notepad.exe"],
                "calculator": ["calc.exe"],
                "paint": ["mspaint.exe"],
                "explorer": ["explorer.exe"],
                "chrome": ["chrome"],
                "edge": ["msedge"],
                "vscode": ["code"],
                "vs code": ["code"],
                "cmd": ["cmd.exe"],
                "terminal": ["cmd.exe"],
            }

            key = app_name.strip().lower()
            cmd = app_map.get(key, [app_name])

            try:
                if sys.platform.startswith("win"):
                    subprocess.Popen(cmd, shell=False)
                else:
                    subprocess.Popen(cmd)
                return f"Opened {app_name}."
            except Exception as exc:
                return f"Failed to open {app_name}: {exc}"

        @tool
        def open_url(url: str) -> str:
            """Open a URL in the default browser."""
            try:
                webbrowser.open(url)
                return f"Opened {url}."
            except Exception as exc:
                return f"Failed to open URL: {exc}"

        @tool
        def list_files(folder: str = ".") -> str:
            """List files in a folder inside the approved workspace."""
            target = safe_workspace_path(folder)
            try:
                if not target.exists():
                    return f"Folder does not exist: {target}"
                items = []
                for p in sorted(target.iterdir()):
                    items.append(f"{'[DIR]' if p.is_dir() else '[FILE]'} {p.name}")
                return "\n".join(items) if items else "Folder is empty."
            except Exception as exc:
                return f"Failed to list files: {exc}"

        @tool
        def read_file(path: str) -> str:
            """Read a text file inside the approved workspace."""
            target = safe_workspace_path(path)
            try:
                if not target.exists():
                    return f"File not found: {target}"
                return target.read_text(encoding="utf-8")
            except Exception as exc:
                return f"Failed to read file: {exc}"

        @tool
        def write_file(path: str, content: str) -> str:
            """Write a text file inside the approved workspace."""
            target = safe_workspace_path(path, create_parent=True)
            try:
                target.write_text(content, encoding="utf-8")
                return f"Wrote {len(content)} characters to {target}."
            except Exception as exc:
                return f"Failed to write file: {exc}"

        @tool
        def remember_preference(key: str, value: str) -> str:
            """Store a long-term user preference."""
            self.memory.set(key.strip(), value.strip())
            return f"Remembered {key} = {value}."

        @tool
        def recall_preference(key: str) -> str:
            """Recall a saved user preference."""
            value = self.memory.get(key.strip())
            if value is None:
                return f"No saved value for {key}."
            return f"{key} = {value}"

        @tool
        def show_memory() -> str:
            """Show the saved long-term memory profile."""
            return json.dumps(self.memory.all(), indent=2, ensure_ascii=False)

        @tool
        def call_booking_api(action: str, payload_json: str) -> str:
            """Call a booking API configured through environment variables."""
            import requests

            base_url = os.getenv("BOOKING_API_URL", "").strip()
            api_key = os.getenv("BOOKING_API_KEY", "").strip()
            if not base_url:
                return "BOOKING_API_URL is not configured."

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
                return f"Booking API call failed: {exc}"

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

        @tool 
        def search_links(topic:str) -> str:
            """search DuckDuckGo and return links related to a topic"""
            try:
                result_data = []
                with DDGS as ddgs:
                    results = ddgs.text(
                        keyword=topic,
                        region = "wt-wt",
                        safesearch = "moderate",
                        max_results = 5
                    )
                    for r in results:
                        result_data.append(
                            f"Title:{r.get('title')}\n"
                            f"Link:{r.get('link')}\n"
                            f"Description:{r.get('body')}\n"
                        )
                if not result_data:
                    return "No result found."
                return "\n -----------------------\n".join(result_data)
            except Exception as e:
                return f"Search Failed:{e}"
            
        @tool
        def ml_model_tool(action:str,dataset_path:str="",model_name:str="",target_column:str="",prediction_input_json:str ="",model_type="classification") -> str:
            """
            Train,Save,Load and predict using ML models
            Action:
            - train
            - predict
            """
            try:
                if "train" in action.lower().strip():
                    if not dataset_path:
                        return "dataset_path required"
                    if not model_name:
                        return "model_name required"
                    if not target_column:
                        return "target_column is required"
                    dataset_file = safe_workspace_path(dataset_path)
                    if not dataset_file.exists():
                        return f"Dataset not found:{dataset_file}"
                    df = pd.read_csv(dataset_file).dropna()
                    if target_column not in df.columns:
                        return f"target column:{target_column} not found"
                    #tsking feature
                    x = df.drop(columns=[target_column])
                    #labels
                    y = df[target_column]
                    #split
                    x_train,x_test,y_train,y_test = train_test_split(x,y,test_size=0.2,random_state=42)
                    
                    #based on users type
                    #classification
                    if model_type == "classification":
                        model = RandomForestClassifier()
                        model.fit(x_train, y_train)
                        preds = model.predict(x_test)
                        score = accuracy_score(y_test, preds)
                        metric = f"Accuracy: {score:.4f}"
                    else:
                        model = LinearRegression()
                        model.fit(x_train, y_train)
                        preds = model.predict(x_test)
                        score = mean_squared_error(y_test, preds)
                        metric = f"MSE: {score:.4f}"
                    model_path = MODELS_DIR / f"{model_name}.pkl"
                    joblib.dump(model, model_path)
                    return (
                        f"Model trained successfully.\n"
                        f"Saved to: {model_path}\n"
                        f"{metric}"
                    )
                elif "predict" in action.lower().strip():
                    if not model_name:
                        return "Model name not found"
                    if not prediction_input_json:
                        return "prediction_input_json not found"
                    model_path = MODELS_DIR / f"{model_name}.pkl"
                    if not model_path.exists():
                        return f'Model not found: {model_path}'
                    model = joblib.load(model_path)
                    try:
                        input_data = json.loads(prediction_input_json)
                    except Exception as exc:
                        return f"Invalid JSON input: {exc}"
                    df = pd.DataFrame([input_data])
                    prediction = model.predict(df)
                    return f"Prediction: {prediction.tolist()}"
                else:
                    return "Invalid action, use 'train' or 'predict'"
            except Exception as e:
                return f"ML tool failed: {e}"
        
        return [
            open_app,
            open_url,
            list_files,
            read_file,
            write_file,
            remember_preference,
            recall_preference,
            show_memory,
            call_booking_api,
            call_order_api,
            search_links,
            ml_model_tool
        ]


RISKY_TOOLS = {
    "write_file",
    "call_booking_api",
    "call_order_api",
}

def safe_workspace_path(path_str: str, create_parent: bool = False) -> Path:
    """Resolve a path safely inside the workspace."""
    candidate = (WORKSPACE_ROOT / path_str).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if workspace not in candidate.parents and candidate != workspace:
        raise ValueError("Path must stay inside the assistant workspace.")
    if create_parent:
        candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


class AssistantCore:
    def __init__(self,memory_store:MemoryStore):
        if ChatOllama is None or StateGraph is None:
            raise RuntimeError("LangChain/LangGraph tool support is not available.")
        self.memory_store = memory_store
        self.tools = AssistantTools(self.memory_store)
        self.tool_list = self.tools.get_tool()
        self.llm = ChatOllama(
            model=MODEL_NAME,
            base_url=OLLAMA_BASE_URL,
            temperature=0.2
        )
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        self.config  = {"configurable":{"thread_id":"advanced-thread"}}
    def _build_graph(self):
        builder = StateGraph(AssistantState)
        builder.add_node("llm",self._llm_node)  
        builder.add_node("tools",self._tool_node)
        builder.add_edge(START,"llm")
        builder.add_conditional_edges(
            "llm",
            self._route_after_llm,
            {"tools":"tools",END:END}
        )  
        builder.add_edge("tools","llm")
        return builder.compile(checkpointer=self.checkpointer)
    def _system_messages(self) -> list:
        profile = self.memory_store.all()
        profile_text = json.dumps(profile,indent=2,ensure_ascii=False)
        return [SystemMessage(content=f"{SYSTEM_PROMPT}\n\nUser memory:\n{profile_text}")]
    def _llm_node(self,state:AssistantState) -> Dict[str,Any]:
        messages = self._system_messages()+list(state.get("messages",[]))
        model = self.llm.bind_tools(self.tool_list)
        response = model.invoke(messages)
        pending = getattr(response,"tool_calls",None) or []
        return {
            "messages":[response],
            "pending_tool_calls":pending,
            "ui_state":"thinking" if pending else "speaking",
        }
    def _route_after_llm(self,state:AssistantState)  -> str:
        pending = state.get("pending_tool_calls") or []
        return "tools" if pending else END
    def _tool_node(self,state:AssistantState) -> Dict[str,Any]:
        pending = state.get("pending_tool_calls") or []
        tool_map = {tool_obj.name:tool_obj for tool_obj in self.tool_list}
        outputs:list = []
        for call in pending:
            name = call.get("name")
            tool_call_id = call.get("id","")
            args = call.get("args") or {}
            tool_obj = tool_map.get(name)
            if tool_obj is None:
                outputs.append(ToolMessage(content=f"Unknown tool:{name}",tool_call_id=tool_call_id))
                continue
            try:
                result = tool_obj.invoke(**args)
                if not isinstance(result,str):
                    result = json.dumps(result,ensure_ascii=False)
                outputs.append(ToolMessage(content=result,tool_call_id=tool_call_id))
            except Exception as e:
                outputs.append(ToolMessage(content=f"Tool {name} failed: {e}",tool_call_id=tool_call_id))

        return {
            "messages":outputs,
            "pending_tool_calls":[],
            "approved":True,
            "ui_state":"thinking"
        }

    def run(self, session_id: str, user_text: str) -> str:
        initial = {"messages": [HumanMessage(content=user_text)], "ui_state": "listening"}
        result = self.graph.invoke(initial, config=self.config)

        messages = result.get("messages", [])
        assistant_text = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and getattr(msg, "content", None):
                assistant_text = str(msg.content)
                break

        if assistant_text:
            self.memory_store.add_message(session_id, "user", user_text)
            self.memory_store.add_message(session_id, "assistant", assistant_text)

        return assistant_text
        
        
    