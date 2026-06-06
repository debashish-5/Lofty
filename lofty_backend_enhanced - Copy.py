"""
Lofty Terminal Backend
FastAPI backend for a terminal-style frontend.

Routes
- /       -> index_up.html
- /about  -> about.html
- /lofty  -> chatbot.html

Also includes:
- Ollama chat endpoint
- session memory stored in JSON
- clickable link/search tools
- optional voice transcription with faster-whisper
- optional server-side TTS with pyttsx3
- automatic browser open (Chrome first on Windows, then fallback)

Run:
    pip install -r requirements_lofty_backend.txt
    uvicorn lofty_backend_enhanced:app --reload --host 0.0.0.0 --port 8000

Environment:
    OLLAMA_BASE_URL=http://localhost:11434
    OLLAMA_MODEL=mistral
    LOFTY_MEMORY_FILE=lofty_memory.json
    LOFTY_STATIC_DIR=.
    LOFTY_ENABLE_TTS=0
    LOFTY_OPEN_BROWSER=1
    LOFTY_BROWSER_URL=http://127.0.0.1:8000/
"""

from __future__ import annotations
import requests
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langchain_ollama import ChatOllama
except Exception:  # pragma: no cover
    AIMessage = BaseMessage = HumanMessage = SystemMessage = ToolMessage = None
    def _noop_tool(fn):
        return fn
    tool = _noop_tool
    MemorySaver = None
    StateGraph = None
    START = END = None
    add_messages = None
    ChatOllama = None

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover
    WhisperModel = None

try:
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None


APP_NAME = "Lofty Terminal Backend"
BASE_DIR = Path(__file__).resolve().parent

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
MEMORY_FILE = Path(os.getenv("LOFTY_MEMORY_FILE", str(BASE_DIR / "lofty_memory.json"))).resolve()
STATIC_DIR = Path(os.getenv("LOFTY_STATIC_DIR", str(BASE_DIR))).resolve()
ENABLE_TTS = os.getenv("LOFTY_ENABLE_TTS", "0") == "1"
OPEN_BROWSER = os.getenv("LOFTY_OPEN_BROWSER", "1") == "1"
BROWSER_URL = os.getenv("LOFTY_BROWSER_URL", "http://127.0.0.1:8000/")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
ENABLE_TOOL_GRAPH = os.getenv("LOFTY_TOOL_GRAPH", "1") == "1"

class GroqAgent:
    question: str
    result: str
from langchain_groq import ChatGroq
from API_TOOL import APIAGENT
from PREBUILT import PrebuiltTools
from tools import AssistantTools
import os
from dotenv import load_dotenv
# 1. Point load_dotenv to your custom file
load_dotenv(dotenv_path="key.env")

# 2. Extract the key manually using os.getenv
my_groq_key = os.getenv("GROQ_API_KEY")
# Initialize the Groq LLM
llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key = my_groq_key,
    temperature=0.7
)

api_tools = APIAGENT().get_tool()
prebuilt = PrebuiltTools()

knowledge_tools = [
    prebuilt.websearch_tool(),
    prebuilt.retrieve_data_tool()
]
action_tools = prebuilt.get_gmail_tools()
data_tools = prebuilt.get_sql_tools("sqlite:///company.db")

from langchain.agents import create_agent


api_agent = create_agent(llm_groq,api_tools, verbose=True)
knowledge_agent = create_agent(llm_groq,knowledge_tools, verbose=True)
action_agent = create_agent(llm_groq,action_tools,verbose=True)
data_agent = create_agent(llm_groq,data_tools,verbose=True)

@tool
def run_api_agent(query:str) -> str:
    """Run the API Agent to answer questions or perform tasks that require API calls."""
    result = api_agent.invoke({
        "messages":[HumanMessage(content=query)]

    })
    return result['messages'][-1].content if 'messages' in result else "No repsonse from API agent."

@tool
def run_data_agent(query:str) -> str:
    """Run the Data Agent to answer questions o perform tasks the require database access or SQL queries."""
    result = data_agent.invoke({
        "messages":[HumanMessage(content=query)]
    })
    return result['messages'][-1].content if 'messages' in result else "No response from Data agent."

@tool
def run_knowledge_agent(query:str) -> str:
    """Run the knowledge agent to answer questions or retrieve information."""
    result = knowledge_agent.invoke(
        {
            "messages": [HumanMessage(content=query)]
        }
    )
    return result['message'][-1].content if 'message' in result else "No response from knowledge agent."

@tool
def run_action_agent(query:str) -> str:
    """Run the action agent to perform task like:
    - sending emails
    - reading notifications
    - managing calendar events
    - other productivity tasks.
    """
    result = action_agent.invoke(
        {
            "messages":[HumanMessage(content=query)]
        }
    )
    return result['messages'][-1].content if 'messages' in result else "No response from action agent."

groq_agent = create_agent(
    model=llm_groq,
    tools = [
        run_api_agent,
        run_knowledge_agent,
        run_action_agent,
        run_data_agent
    ],
    verbose=True
)


class AssistantState(TypedDict, total=False):
    messages: list
    pending_tool_calls: list[dict[str, Any]]
    approved: bool
    ui_state: str


def safe_workspace_path(path_str: str, create_parent: bool = False) -> Path:
    candidate = (BASE_DIR / path_str).resolve()
    root = BASE_DIR.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Path must stay inside the workspace.")
    if create_parent:
        candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


class AssistantTools:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    @tool
    def open_url(self, url: str) -> str:
        """Open a URL in the default browser."""
        try:
            webbrowser.open(url)
            return f"Opened {url}."
        except Exception as exc:
            return f"Failed to open URL: {exc}"

    @tool
    def open_app(self, app_name: str) -> str:
        """Open a local desktop application or supported Windows alias."""
        try:
            return open_application(app_name)
        except Exception as exc:
            return f"Failed to open app {app_name}: {exc}"

    @tool
    def shell_command(self, command: str) -> str:
        """Run a shell-style command or open an app with open <app>."""
        normalized = command.strip()
        if not normalized:
            return "No shell command provided."
        if normalized.lower().startswith("open "):
            return open_application(normalized[5:].strip())
        if normalized.lower().startswith("start "):
            return open_application(normalized[6:].strip())
        try:
            proc = subprocess.run(normalized, shell=True, capture_output=True, text=True, timeout=20)
            output = proc.stdout.strip() or proc.stderr.strip() or "Command completed."
            return output
        except Exception as exc:
            return f"Shell command failed: {exc}"

    @tool
    def list_files(self, folder: str = ".") -> str:
        """List files in the safe workspace."""
        target = safe_workspace_path(folder)
        if not target.exists():
            return f"Folder does not exist: {target}"
        items = [f"{'[DIR]' if p.is_dir() else '[FILE]'} {p.name}" for p in sorted(target.iterdir())]
        return "\n".join(items) if items else "Folder is empty."

    @tool
    def read_file(self, path: str) -> str:
        """Read a file from the safe workspace."""
        target = safe_workspace_path(path)
        if not target.exists():
            return f"File not found: {target}"
        try:
            return target.read_text(encoding="utf-8")
        except Exception as exc:
            return f"Failed to read file: {exc}"

    @tool
    def write_file(self, path: str, content: str) -> str:
        """Write text to a file in the safe workspace."""
        target = safe_workspace_path(path, create_parent=True)
        try:
            target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} characters to {path}."
        except Exception as exc:
            return f"Failed to write file: {exc}"

    @tool
    def remember_preference(self, key: str, value: str) -> str:
        """Remember a long-term preference."""
        self.memory_store.set_preference(key.strip(), value.strip())
        return f"Remembered {key} = {value}."

    @tool
    def recall_preference(self, key: str) -> str:
        """Recall a previously saved preference."""
        value = self.memory_store.all().get("preferences", {}).get(key.strip())
        if value is None:
            return f"No saved preference for {key}."
        return f"{key} = {value}"

    @tool
    def show_memory(self) -> str:
        """Display saved memory as JSON."""
        try:
            return json.dumps(self.memory_store.all(), indent=2, ensure_ascii=False)
        except Exception as exc:
            return f"Failed to show memory: {exc}"


class ToolAssistant:
    def __init__(self) -> None:
        if ChatOllama is None or StateGraph is None or tool is None:
            raise RuntimeError("LangChain/LangGraph tool support is not available.")
        self.memory_store = memory
        self.tools = AssistantTools(self.memory_store)
        self.tool_list = [
            self.tools.open_url,
            self.tools.open_app,
            self.tools.shell_command,
            self.tools.list_files,
            self.tools.read_file,
            self.tools.write_file,
            self.tools.remember_preference,
            self.tools.recall_preference,
            self.tools.show_memory,
        ]
        self.llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.2)
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        self.config = {"configurable": {"thread_id": "tool-graph"}}

    def _build_graph(self):
        builder = StateGraph(AssistantState)
        builder.add_node("llm", self._llm_node)
        builder.add_node("tools", self._tool_node)
        builder.add_edge(START, "llm")
        builder.add_conditional_edges(
            "llm",
            self._route_after_llm,
            {"tools": "tools", END: END},
        )
        builder.add_edge("tools", "llm")
        return builder.compile(checkpointer=self.checkpointer)

    def _system_messages(self) -> list:
        profile = self.memory_store.all()
        profile_text = json.dumps(profile, indent=2, ensure_ascii=False) if profile else "{}"
        return [SystemMessage(content=f"{SYSTEM_PROMPT}\n\nUser memory:\n{profile_text}")]

    def _llm_node(self, state: AssistantState) -> Dict[str, Any]:
        messages = self._system_messages() + list(state.get("messages", []))
        model = self.llm.bind_tools(self.tool_list)
        response = model.invoke(messages)
        pending = getattr(response, "tool_calls", None) or []
        return {
            "messages": [response],
            "pending_tool_calls": pending,
            "ui_state": "thinking" if pending else "speaking",
        }

    def _route_after_llm(self, state: AssistantState) -> str:
        pending = state.get("pending_tool_calls") or []
        return "tools" if pending else END

    def _tool_node(self, state: AssistantState) -> Dict[str, Any]:
        pending = state.get("pending_tool_calls") or []
        tool_map = {tool_obj.name: tool_obj for tool_obj in self.tool_list}
        outputs: list = []

        for call in pending:
            name = call.get("name")
            tool_call_id = call.get("id", "")
            args = call.get("args") or {}
            tool_obj = tool_map.get(name)
            if tool_obj is None:
                outputs.append(ToolMessage(content=f"Unknown tool: {name}", tool_call_id=tool_call_id))
                continue
            try:
                result = tool_obj.invoke(**args)
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)
                outputs.append(ToolMessage(content=result, tool_call_id=tool_call_id))
            except Exception as exc:
                outputs.append(ToolMessage(content=f"Tool error in {name}: {exc}", tool_call_id=tool_call_id))

        return {
            "messages": outputs,
            "pending_tool_calls": [],
            "approved": False,
            "ui_state": "thinking",
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


tool_assistant: Optional[ToolAssistant] = None


def ensure_tool_assistant() -> Optional[ToolAssistant]:
    global tool_assistant
    if not ENABLE_TOOL_GRAPH:
        return None
    if tool_assistant is None:
        try:
            tool_assistant = ToolAssistant()
        except Exception:
            tool_assistant = None
    return tool_assistant

SYSTEM_PROMPT = """
You are Lofty, a cinematic black-terminal assistant.

Style:
- Be concise, clear, and premium.
- Match the user's tone.
- Use terminal-friendly formatting when useful.

Safety:
- Never claim to have used a tool unless the backend actually did.
- For risky actions, ask for confirmation.
- Keep responses useful and grounded.

Tool-aware behavior:
- If the user asks for a link, return a short useful answer and the URL.
- If the user asks for search help, provide a clean web search suggestion.
- If the user asks to remember something, store it in memory.
""".strip()


class ChatRequest(BaseModel):
    session_id: str = Field(default="default-thread")
    message: str = Field(..., min_length=1)
    model: Optional[str] = Field(default=None)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    model: str
    tool: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None


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


memory = MemoryStore(MEMORY_FILE)
app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def safe_page(name: str) -> Path:
    templates_dir = BASE_DIR / "templates"
    candidate = (templates_dir / name).resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"{name} not found in {templates_dir}")
    if templates_dir.resolve() not in candidate.parents and candidate != templates_dir.resolve():
        raise ValueError("Unsafe path.")
    return candidate


def safe_session_history(session_id: str) -> List[Dict[str, str]]:
    return memory.session_messages(session_id)


def ollama_chat(messages: List[Dict[str, str]], model: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {"model": model, "messages": messages, "stream": False}
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        reply = data.get("message", {}).get("content") or data.get("response") or ""
        return str(reply).strip()
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc


def build_system_message() -> Dict[str, str]:
    profile = memory.all()
    return {
        "role": "system",
        "content": f"{SYSTEM_PROMPT}\n\nUser memory:\n{json.dumps(profile, indent=2, ensure_ascii=False)}",
    }


def detect_tool(message: str) -> Optional[Dict[str, Any]]:
    text = message.strip()

    m = re.match(r"^lofty:link\s+(.+)$", text, re.I)
    if m:
        url = m.group(1).strip()
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        return {
            "type": "link",
            "title": "Live Link Tool",
            "url": url,
            "label": "Open link",
        }

    m = re.match(r"^lofty:search\s+(.+)$", text, re.I)
    if m:
        query = m.group(1).strip()
        url = "https://www.google.com/search?q=" + requests.utils.quote(query)
        return {
            "type": "search",
            "title": "Realtime Search Tool",
            "url": url,
            "label": f"Search: {query}",
            "query": query,
        }

    m = re.match(r"^lofty:remember\s+([^=]+?)\s*=\s*(.+)$", text, re.I)
    if m:
        key = m.group(1).strip()
        value = m.group(2).strip()
        memory.set_preference(key, value)
        return {
            "type": "memory",
            "title": "Memory Saved",
            "key": key,
            "value": value,
        }

    return None

ACTIVE_THINK_SESSIONS: dict[str, bool] = {}

def is_think_mode_active(session_id: str) -> bool:
    return ACTIVE_THINK_SESSIONS.get(session_id, False)


def set_think_mode(session_id: str, active: bool) -> None:
    if active:
        ACTIVE_THINK_SESSIONS[session_id] = True
    else:
        ACTIVE_THINK_SESSIONS.pop(session_id, None)


def run_groq_think(query: str, session_id: str) -> str:
    prompt = (
        "You are Lofty Think Mode, a Groq-powered reasoning assistant. "
        "Answer carefully, thinking step-by-step and offering helpful, interactive guidance. "
        "When the user asks follow-up questions, keep the context and continue reasoning.")
    history = safe_session_history(session_id)
    if history:
        history_lines = []
        for item in history[-8:]:
            role = item.get("role", "unknown")
            history_lines.append(f"{role}: {item.get('content', '')}")
        query = f"{query}\n\nSession history:\n{chr(10).join(history_lines)}"

    messages = [SystemMessage(content=prompt), HumanMessage(content=query)]
    try:
        result = groq_agent.invoke({"messages": messages})
        return result['messages'][-1].content if 'messages' in result else "No response from Groq think mode."
    except Exception as exc:
        return f"Groq think mode failed: {exc}"


def handle_lofty_think_command(session_id: str, message: str) -> Optional[str]:
    text = message.strip()
    if not re.match(r"^lofty:think", text, re.I):
        return None

    remainder = text[len("lofty:think"):].strip()
    if not remainder:
        set_think_mode(session_id, True)
        return (
            "Think mode activated. Ask your follow-up questions and I will use Groq reasoning to help you. "
            "Type 'lofty:think stop' to exit think mode."
        )

    if remainder.lower() in {"stop", "exit", "end", "done"}:
        set_think_mode(session_id, False)
        return "Think mode ended. Back to normal assistant mode."

    set_think_mode(session_id, True)
    return run_groq_think(remainder, session_id)

import os
import shutil
import subprocess

def open_application(app_name: str) -> str:
    normalized = app_name.strip()
    if not normalized:
        return "Usage: lofty:open <app_name>"

    # FIX: Map aliases to their proper system launch protocols or exact executable names
    win_aliases = {
        "camera": "microsoft.windows.camera:",
        "paint": "mspaint",
        "notepad": "notepad",
        "calculator": "calc",
        "wordpad": "write",
        "explorer": "explorer",
        "cmd": "cmd",
        "whatsapp": "whatsapp:",       # Fixed to use Windows Store URI protocol
        "instagram": "instagram:",     # Fixed to use Windows Store URI protocol
        "vs code": "code",             # Fixed: The actual CLI executable name is 'code'
        "cursor": "cursor"
    }

    try:
        if os.name == "nt":
            # Check custom alias mapping
            target = win_aliases.get(normalized.lower())
            
            if target:
                # Handle Windows Protocol URIs (e.g., camera:, instagram:)
                if target.endswith(":"):
                    subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
                    return f"Opened {normalized}."
                # Handle direct executables mapping
                else:
                    exe_path = shutil.which(target)
                    if exe_path:
                        subprocess.Popen([exe_path], shell=False)
                        return f"Opened {normalized}."
                    
                    # Fallback for alias if shutil.which fails
                    subprocess.Popen(target, shell=True)
                    return f"Opened {normalized}."

            # Check if user typed a globally accessible system command directly
            exe_path = shutil.which(normalized)
            if exe_path:
                subprocess.Popen([exe_path], shell=False)
                return f"Opened {normalized}."

            # Final Windows Fallback: Use shell=True to let the OS resolve strings/URLs safely
            # without throwing a hard WinError 2 crash in Python.
            subprocess.Popen(f"start {normalized}", shell=True)
            return f"Opened {normalized}."

        if os.name == "posix":
            if shutil.which("open"):  # macOS
                subprocess.Popen(["open", "-a", normalized], shell=False)
                return f"Opened {normalized}."
            if shutil.which("xdg-open"):  # Linux
                subprocess.Popen(["xdg-open", normalized], shell=False)
                return f"Opened {normalized}."

        return f"Could not open {normalized}: unsupported platform."
    except Exception as exc:
        return f"Failed to open {normalized}: {exc}"

def apply_shortcuts(message: str) -> Optional[str]:
    lowered = message.lower().strip()

    if lowered == "lofty:help":
        return (
            "Commands: lofty:help, lofty:assistant, lofty:new, lofty:history <id>, "
            "lofty:think, lofty:think <question>, lofty:think stop, "
            "lofty:voice, lofty:speak on/off, lofty:theme midnight|crimson|neon, "
            "lofty:model mistral, lofty:open <app>, lofty:link <url>, lofty:search <query>, "
            "lofty:remember key = value"
        )

    if lowered == "lofty:new":
        return "New session ready. The terminal memory is separated by session_id."

    if lowered == "lofty:assistant":
        return "Assistant panel opened."

    if lowered.startswith("lofty:history"):
        parts = lowered.split()
        sid = parts[1] if len(parts) > 1 else "default-thread"
        history = safe_session_history(sid)
        if not history:
            return f"No history found for {sid}."
        lines = []
        for i, item in enumerate(history, 1):
            lines.append(f"{i}. {item.get('role', 'unknown')}: {item.get('content', '')}")
        return "\n".join(lines)

    if lowered.startswith("lofty:open"):
        app_name = message[len("lofty:open"):].strip()
        return open_application(app_name)

    return None


def make_reply(session_id: str, message: str, model: str) -> tuple[str, Optional[Dict[str, Any]]]:
    shortcut = apply_shortcuts(message)
    if shortcut is not None:
        return shortcut, None

    think_result = handle_lofty_think_command(session_id, message)
    if think_result is not None:
        return think_result, None

    if is_think_mode_active(session_id):
        reply = run_groq_think(message, session_id)
        return reply, None

    # Quick heuristic: if user says plain-language "open <app>" or "please open <app>
    # try opening the app directly as a fallback when the LLM doesn't call tools.
    m_plain_open = re.match(r'^(?:please\s+)?(?:open|start|launch)\s+(.+)$', message.strip(), re.I)
    if m_plain_open:
        app_name = m_plain_open.group(1).strip()
        try:
            result = open_application(app_name)
            # record and return an action-like tool response
            memory.add_message(session_id, "user", message)
            memory.add_message(session_id, "assistant", result)
            return result, {"type": "action", "action": "open_app", "target": app_name}
        except Exception:
            # fallthrough to regular assistant flow
            pass

    tool = detect_tool(message)
    if tool and tool["type"] in {"link", "search", "memory"}:
        if tool["type"] == "memory":
            return f"Remembered {tool['key']} = {tool['value']}.", tool
        if tool["type"] == "search":
            return f"Search ready: {tool['query']}", tool
        return f"Link ready: {tool['url']}", tool

    assistant = ensure_tool_assistant()
    if assistant is not None:
        try:
            reply = assistant.run(session_id=session_id, user_text=message)
            if reply:
                return reply, None
        except Exception:
            pass

    history = safe_session_history(session_id)
    messages = [build_system_message()] + history + [{"role": "user", "content": message}]
    reply = ollama_chat(messages, model=model)

    memory.add_message(session_id, "user", message)
    memory.add_message(session_id, "assistant", reply)
    return reply, None


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": APP_NAME,
        "model": OLLAMA_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "memory_file": str(MEMORY_FILE),
        "static_dir": str(STATIC_DIR),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    try:
        return FileResponse(str(safe_page("index_up.html")))
    except Exception as exc:
        return PlainTextResponse(f"index_up.html not found: {exc}", status_code=404)

@app.get("/index.html", response_class=HTMLResponse)
def index_html_alias():
    """Serve the upgraded index page when a browser requests /index.html."""
    try:
        return FileResponse(str(safe_page("index_up.html")))
    except Exception as exc:
        return PlainTextResponse(f"index_up.html not found: {exc}", status_code=404)


@app.get("/index_up.html", response_class=HTMLResponse)
def index_up_alias():
    """Serve the upgraded index page for the explicit index_up.html path."""
    try:
        return FileResponse(str(safe_page("index_up.html")))
    except Exception as exc:
        return PlainTextResponse(f"index_up.html not found: {exc}", status_code=404)


from FineQwenGen import FineQwenInference
from fastapi import FastAPI, HTTPException, Request
@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id", "default-thread")
    model = body.get("model", OLLAMA_MODEL)
    ChatResponse = FineQwenInference(message).fine_tuned_qwen_response()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    return {"session_id": session_id, "reply": ChatResponse, "model": model}



     

# @app.get("/home", response_class=HTMLResponse)
# def home():
#     try:
#         return FileResponse(str(safe_page("index2.html")))
#     except Exception as exc:
#         return PlainTextResponse(f"index2.html not found: {exc}", status_code=404)


@app.get("/about", response_class=HTMLResponse)
def about():
    try:
        return FileResponse(str(safe_page("about.html")))
    except Exception as exc:
        return PlainTextResponse(f"about.html not found: {exc}", status_code=404)

@app.get("/feature",response_class = HTMLResponse)
def feature():
    try:
        return FileResponse(str(safe_page("feature.html")))
    except Exception as exc:
        return PlainTextResponse(f"feature.html not found: {exc}",status_code=404)

@app.get("/lofty", response_class=HTMLResponse)
def lofty():
    try:
        return FileResponse(str(safe_page("chatbot.html")))
    except Exception as exc:
        return PlainTextResponse(f"chatbot.html not found: {exc}", status_code=404)


@app.get("/chatbot-upgrade", response_class=HTMLResponse)
def chatbot_upgrade():
    try:
        return FileResponse(str(safe_page("chatbot_upgrade.html")))
    except Exception as exc:
        return PlainTextResponse(f"chatbot_upgrade.html not found: {exc}", status_code=404)


@app.get("/upgrade")
def upgrade_alias():
    return RedirectResponse(url="/chatbot-upgrade", status_code=307)


@app.get("/chatbot")
def chatbot_alias():
    return RedirectResponse(url="/lofty", status_code=307)


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(req: ChatRequest):
    session_id = req.session_id.strip() or "default-thread"
    message = req.message.strip()
    model = (req.model or OLLAMA_MODEL).strip() or OLLAMA_MODEL

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        reply, tool = make_reply(session_id=session_id, message=message, model=model)
        return ChatResponse(
            session_id=session_id,
            reply=reply,
            model=model,
            tool=tool,
            memory=memory.all().get("preferences", {}),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/history/{session_id}")
def api_history(session_id: str):
    return {"session_id": session_id, "messages": safe_session_history(session_id)}


@app.get("/api/status")
def api_status():
    return {
        "ok": True,
        "app": APP_NAME,
        "model": OLLAMA_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "memory_file": str(MEMORY_FILE),
        "static_dir": str(STATIC_DIR),
        "tool_graph": ENABLE_TOOL_GRAPH,
        "tts_enabled": ENABLE_TTS,
        "browser_open": OPEN_BROWSER,
    }


@app.post("/api/remember")
def api_remember(key: str = Form(...), value: str = Form(...)):
    memory.set_preference(key.strip(), value.strip())
    return {"ok": True, "key": key, "value": value}


@app.get("/api/memory")
def api_memory():
    return memory.all()


@app.post("/api/link")
def api_link(url: str = Form(...), label: str = Form("Open link")):
    clean = url.strip()
    if not re.match(r"^https?://", clean, re.I):
        clean = "https://" + clean
    return {"type": "link", "url": clean, "label": label, "title": "Live Link Tool"}


# ---------- Optional voice transcription ----------
whisper_model = None


def get_whisper_model():
    global whisper_model
    if WhisperModel is None:
        raise RuntimeError("faster-whisper is not installed.")
    if whisper_model is None:
        whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return whisper_model


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    if WhisperModel is None:
        raise HTTPException(status_code=400, detail="faster-whisper is not installed.")
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    temp_path = Path(tempfile.gettempdir()) / f"lofty_upload_{os.getpid()}{suffix}"
    temp_path.write_bytes(await file.read())

    try:
        model = get_whisper_model()
        segments, info = model.transcribe(str(temp_path), language="en")
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {"text": text, "language": getattr(info, "language", "en")}
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


# ---------- Optional TTS ----------
tts_engine = None


def get_tts_engine():
    global tts_engine
    if pyttsx3 is None:
        raise RuntimeError("pyttsx3 is not installed.")
    if tts_engine is None:
        tts_engine = pyttsx3.init()
        try:
            tts_engine.setProperty("rate", 175)
        except Exception:
            pass
    return tts_engine


@app.post("/api/speak")
def api_speak(text: str = Form(...)):
    if not ENABLE_TTS:
        return {
            "ok": False,
            "message": "Server-side TTS is disabled. Set LOFTY_ENABLE_TTS=1 to enable it.",
        }
    if pyttsx3 is None:
        raise HTTPException(status_code=400, detail="pyttsx3 is not installed.")
    engine = get_tts_engine()
    engine.say(text)
    engine.runAndWait()
    return {"ok": True}


def _find_chrome_executable() -> Optional[str]:
    if os.name != "nt":
        return None

    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def open_in_browser(url: str) -> None:
    try:
        chrome = _find_chrome_executable()
        if chrome:
            subprocess.Popen([chrome, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass


def maybe_open_browser() -> None:
    if not OPEN_BROWSER:
        return

    def _runner():
        time.sleep(0.8)
        open_in_browser(BROWSER_URL)

    threading.Thread(target=_runner, daemon=True).start()


@app.on_event("startup")
def on_startup():
    memory.load()
    maybe_open_browser()


if __name__ == "__main__":
    import uvicorn  # type: ignore[import]
    # Run the FastAPI `app` defined in this file so executing this script
    # directly starts the server and serves `templates/index_up.html`.
    # Use 127.0.0.1 to ensure the browser open URL matches the default BROWSER_URL.
    # When running the file directly we cannot use `reload=True` because
    # uvicorn requires an import string for auto-reload. Run without reload.
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
