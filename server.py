import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Request, status
import json
import asyncio
from contextlib import asynccontextmanager, suppress
import threading
import sys
import subprocess
import time
import os
import re
import base64
import io
from pathlib import Path
from PIL import Image

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')




class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                pass

from main.agent import (
    _ws_out_queue,
    get_agent_readiness,
    queue_command,
)

manager = ConnectionManager()

async def ws_broadcaster():
    """Фоновая задача FastAPI для рассылки сообщений из очереди всем клиентам без active polling"""
    loop = asyncio.get_running_loop()
    while True:
        try:
            # Выполняем блокирующее чтение очереди в отдельном системном потоке, чтобы не блокировать event loop
            msg = await loop.run_in_executor(None, _ws_out_queue.get)
            await manager.broadcast(msg)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[SERVER] Ошибка ws_broadcaster: {e}")
            await asyncio.sleep(0.5)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from main.config_manager import get_config, get_data_dir
from main.commands.heartbeat_commands import get_heartbeat_tasks, replace_heartbeat_tasks

@asynccontextmanager
async def lifespan(app: FastAPI):
    broadcaster_task = asyncio.create_task(ws_broadcaster())
    try:
        yield
    finally:
        broadcaster_task.cancel()
        with suppress(asyncio.CancelledError):
            await broadcaster_task

app = FastAPI(lifespan=lifespan)

# CORS configuration: allow local development origins and null (for file:// protocol)
allow_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VERA_API_TOKEN = os.environ.get("VERA_API_TOKEN", "")
VERA_APP_VERSION = "1.1.1"


def _format_model_name(model_path: str) -> str:
    name = Path(model_path).stem
    name = re.sub(r"[-_]?Q\d+(?:_[A-Z0-9]+)*$", "", name, flags=re.IGNORECASE)
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", name)
    name = re.sub(r"\b(\d+(?:\.\d+)?)B\b", r"\1B", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "Unknown model"


def _get_runtime_info() -> dict:
    from main.agent import _external_url, _llm_server, _use_external
    from main.llama_update import get_local_llama_version

    if _use_external:
        model_path = str(_external_url)
        model_name = "External LLM"
    else:
        model_path = str(getattr(_llm_server, "model_path", "") or "")
        if not model_path:
            configured_path = str(get_config().get("model", "path") or "")
            if configured_path and configured_path.lower() != "auto" and Path(configured_path).exists():
                model_path = configured_path
            else:
                model_files = sorted(Path(__file__).resolve().parent.glob("*.gguf"))
                if model_files:
                    model_path = str(model_files[0])
        model_name = _format_model_name(model_path)
    return {
        "version": VERA_APP_VERSION,
        "model_name": model_name,
        "model_path": model_path,
        "llama_cpp": get_local_llama_version(),
    }

def verify_token(token: str | None) -> bool:
    if not VERA_API_TOKEN:
        return True  # В небезопасном режиме (запуск напрямую), если токен не задан
    return token == VERA_API_TOKEN

@app.middleware("http")
async def verify_auth_token(request: Request, call_next):
    # Пропускаем запросы OPTIONS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    if VERA_API_TOKEN:
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.headers.get("X-Vera-Token")
            
        if not verify_token(token):
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: Invalid or missing API token."}
            )
            
    return await call_next(request)

@app.get("/api/config")
async def get_config_api():
    config = get_config().get_raw()
    return JSONResponse(content=config)


@app.get("/api/runtime-info")
async def get_runtime_info_api():
    try:
        return JSONResponse(content=_get_runtime_info())
    except Exception as e:
        return JSONResponse(content={
            "version": VERA_APP_VERSION,
            "model_name": "Unknown model",
            "model_path": "",
            "llama_cpp": {"build": None, "raw": ""},
            "error": str(e),
        })


@app.get("/api/llama-update")
async def get_llama_update_api(force: bool = False):
    try:
        from main.llama_update import check_llama_update

        return JSONResponse(content=check_llama_update(force_refresh=force))
    except Exception as e:
        return JSONResponse(content={
            "status": "error",
            "update_available": False,
            "error": str(e),
        }, status_code=500)


@app.post("/api/llama-update/install")
async def install_llama_update_api():
    try:
        from main.llama_update import install_latest_llama_update

        payload = install_latest_llama_update()
        status_code = 500 if payload.get("status") == "error" else 200
        return JSONResponse(content=payload, status_code=status_code)
    except Exception as e:
        return JSONResponse(content={
            "status": "error",
            "update_available": True,
            "restart_required": False,
            "error": str(e),
        }, status_code=500)


@app.get("/api/skills")
async def get_skills_api():
    from main.skills import list_installed_skills

    return JSONResponse(content={"skills": list_installed_skills()})


@app.post("/api/config")
async def update_config_api(new_config: dict):
    config_manager = get_config()
    
    # Completely replace the configuration dictionary
    config_manager.set_all(new_config)
    
    # Save to file
    config_manager.save()
    
    # Reload to apply path resolutions
    config_manager.reload()
    
    return JSONResponse(content={"status": "success", "message": "Настройки сохранены. Перезапустите агента, чтобы применить некоторые изменения."})

@app.post("/api/upload")
async def upload_file_api(file: UploadFile = File(...)):
    """Принимает файл, извлекает текст и возвращает его."""
    uploads_dir = get_data_dir() / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    # Сохраняем во временную папку
    safe_name = file.filename.replace("..", "_").replace("/", "_").replace("\\", "_")
    tmp_path = uploads_dir / safe_name
    
    try:
        content = await file.read()
        content_type = str(file.content_type or "").lower()
        suffix = Path(file.filename or "").suffix.lower()
        if content_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            if len(content) > 20 * 1024 * 1024:
                return JSONResponse(
                    content={"error": "Image is larger than 20 MB", "filename": file.filename},
                    status_code=413,
                )
            with Image.open(io.BytesIO(content)) as image:
                image = image.convert("RGB")
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True)
                preview = image.copy()
                preview.thumbnail((480, 480), Image.Resampling.LANCZOS)
                preview_output = io.BytesIO()
                preview.save(preview_output, format="JPEG", quality=78, optimize=True)
            encoded = base64.b64encode(output.getvalue()).decode("ascii")
            preview_encoded = base64.b64encode(preview_output.getvalue()).decode("ascii")
            return JSONResponse(content={
                "kind": "image",
                "text": "",
                "filename": file.filename,
                "image_data_url": f"data:image/jpeg;base64,{encoded}",
                "image_preview_data_url": f"data:image/jpeg;base64,{preview_encoded}",
            })

        tmp_path.write_bytes(content)
        
        from main.tools.read_document import read_document_from_path
        text = read_document_from_path(tmp_path)
        
        return JSONResponse(content={"text": text, "filename": file.filename})
    except Exception as e:
        return JSONResponse(content={"text": f"Ошибка чтения файла: {e}", "filename": file.filename}, status_code=500)
    finally:
        # Удаляем временный файл
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass

@app.get("/api/heartbeat-tasks")
async def get_heartbeat_tasks_api():
    """Возвращает список периодических задач."""
    try:
        return JSONResponse(content=get_heartbeat_tasks())
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/api/heartbeat-tasks")
async def save_heartbeat_tasks_api(request: Request):
    """Сохраняет список периодических задач."""
    try:
        payload = await request.json()
        tasks = payload if isinstance(payload, list) else payload.get("tasks", [])
        return JSONResponse(content={
            "status": "success",
            "tasks": replace_heartbeat_tasks(tasks),
            "message": "Tasks updated.",
        })
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/memory")
async def get_memory_api():
    """Возвращает структурированную память для UI-панели."""
    try:
        from main.agent import memory_manager
        from user.memory import CATEGORIES

        facts = sorted(
            [dict(f) for f in memory_manager.facts],
            key=lambda f: (not bool(f.get("pinned")), -float(f.get("timestamp") or 0)),
        )
        return JSONResponse(content={
            "profile": dict(memory_manager.profile),
            "facts": facts,
            "categories": list(CATEGORIES),
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.patch("/api/memory/profile/{profile_key}")
async def update_memory_profile_api(profile_key: str, payload: dict):
    """Обновляет одно поле профиля памяти."""
    try:
        from main.agent import memory_manager

        key = str(profile_key or "").strip().lower()
        value = str(payload.get("value") or "").strip()
        if not key:
            return JSONResponse(content={"error": "Invalid profile key"}, status_code=400)
        if not value:
            return JSONResponse(content={"error": "Value cannot be empty"}, status_code=400)

        memory_manager.set_profile(key, value)
        return JSONResponse(content={"status": "success", "key": key, "value": value})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.delete("/api/memory/profile/{profile_key}")
async def delete_memory_profile_api(profile_key: str):
    """Удаляет одно поле профиля памяти."""
    try:
        from main.agent import memory_manager

        key = str(profile_key or "").strip().lower()
        if not key:
            return JSONResponse(content={"error": "Invalid profile key"}, status_code=400)
        if key not in memory_manager.profile:
            return JSONResponse(content={"error": "Profile field not found"}, status_code=404)

        del memory_manager.profile[key]
        memory_manager.save()
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.patch("/api/memory/facts/{fact_id}")
async def update_memory_fact_api(fact_id: str, payload: dict):
    """Обновляет pin/category/text для одного факта."""
    try:
        from main.agent import memory_manager
        from user.memory import CATEGORIES

        fact = None
        for item in memory_manager.facts:
            if item.get("id") == fact_id:
                fact = item
                break
        if fact is None:
            return JSONResponse(content={"error": "Fact not found"}, status_code=404)

        if "pinned" in payload:
            fact["pinned"] = bool(payload.get("pinned"))
        if "category" in payload:
            category = str(payload.get("category") or "fact")
            if category not in CATEGORIES:
                return JSONResponse(content={"error": "Invalid category"}, status_code=400)
            fact["category"] = category
        if "text" in payload:
            text = str(payload.get("text") or "").strip()
            if not text:
                return JSONResponse(content={"error": "Text cannot be empty"}, status_code=400)
            fact["text"] = text

        memory_manager._bm25_dirty = True
        memory_manager.save()
        return JSONResponse(content={"status": "success", "fact": dict(fact)})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.delete("/api/memory/facts/{fact_id}")
async def delete_memory_fact_api(fact_id: str):
    """Удаляет факт по id."""
    try:
        from main.agent import memory_manager

        before = len(memory_manager.facts)
        memory_manager.facts = [f for f in memory_manager.facts if f.get("id") != fact_id]
        if len(memory_manager.facts) == before:
            return JSONResponse(content={"error": "Fact not found"}, status_code=404)
        memory_manager._bm25_dirty = True
        memory_manager.save()
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/sessions")
async def list_sessions_api(
    archived: bool = False,
    limit: int = 100,
    q: str = "",
):
    try:
        from main.agent import session_store

        return JSONResponse(content={
            "sessions": session_store.list_sessions(
                archived=archived,
                limit=limit,
                search=q,
            )
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/api/sessions")
async def create_session_api(payload: dict = None):
    try:
        from main.agent import session_store

        data = payload or {}
        session = session_store.create_session(
            str(data.get("title") or "Новая сессия"),
            source=str(data.get("source") or "chat"),
        )
        return JSONResponse(content={"session": session}, status_code=201)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/sessions/{session_id}")
async def get_session_api(session_id: str):
    try:
        from main.agent import session_store

        session = session_store.get_session(session_id)
        if not session:
            return JSONResponse(content={"error": "Session not found"}, status_code=404)
        return JSONResponse(content={"session": session})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.patch("/api/sessions/{session_id}")
async def update_session_api(session_id: str, payload: dict):
    try:
        from main.agent import session_store

        session = session_store.update_session(
            session_id,
            title=str(payload["title"]) if "title" in payload else None,
            archived=bool(payload["archived"]) if "archived" in payload else None,
            pinned=bool(payload["pinned"]) if "pinned" in payload else None,
        )
        if not session:
            return JSONResponse(content={"error": "Session not found"}, status_code=404)
        return JSONResponse(content={"session": session})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.delete("/api/sessions/{session_id}")
async def delete_session_api(session_id: str):
    try:
        from main.agent import session_store

        if not session_store.delete_session(session_id):
            return JSONResponse(content={"error": "Session not found"}, status_code=404)
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages_api(session_id: str):
    try:
        from main.agent import session_store

        if not session_store.get_session(session_id):
            return JSONResponse(content={"error": "Session not found"}, status_code=404)
        return JSONResponse(content={
            "session_id": session_id,
            "messages": session_store.get_messages(session_id),
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)




@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    if VERA_API_TOKEN:
        if not token or token != VERA_API_TOKEN:
            await websocket.accept()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid API token")
            return
            
    await manager.connect(websocket)
    await websocket.send_text(json.dumps({
        "type": "agent_status",
        **get_agent_readiness(),
    }))
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                # Обработка текстовых команд из UI-чата
                if payload.get("type") == "command":
                    text = payload.get("text", "").strip()
                    file_name = payload.get("file_name")
                    file_context = payload.get("file_context")
                    image_data_url = payload.get("image_data_url")
                    image_preview_data_url = payload.get("image_preview_data_url")
                    file_size = payload.get("file_size")
                    session_id = str(payload.get("session_id") or "").strip() or None
                    
                    # Обработка команд /mute, /unmute, /exit, /tg и других
                    if text.startswith("/"):
                        from main.agent import execute_slash_command
                        response = execute_slash_command(text)
                        if response:
                            event = {"type": "chat", "role": "system", "text": response}
                            if session_id:
                                event["session_id"] = session_id
                            _ws_out_queue.put(event)
                    else:
                        # Обычная команда — в очередь с пометкой 'chat' и контекстом файла
                        queue_command(
                            text,
                            source='chat',
                            file_name=file_name,
                            file_context=file_context,
                            image_data_url=image_data_url,
                            image_preview_data_url=image_preview_data_url,
                            file_size=file_size,
                            task_id=payload.get("task_id"),
                            session_id=session_id,
                        )
                
                # Команда прерывания речи (от кнопки в UI)
                elif payload.get("type") == "interrupt":
                    from main.agent import interrupt_speech
                    interrupt_speech()
                elif payload.get("type") == "set_thinking_mode":
                    from main.agent import set_thinking_mode
                    enabled = bool(payload.get("enabled", True))
                    set_thinking_mode(enabled=enabled)
                elif payload.get("type") == "get_thinking_mode":
                    from main.agent import get_thinking_mode
                    state = get_thinking_mode()
                    _ws_out_queue.put({"type": "thinking_mode", **state})
                elif payload.get("type") == "get_runtime_info":
                    _ws_out_queue.put({"type": "runtime_info", **_get_runtime_info()})
                elif payload.get("type") == "get_agent_status":
                    await websocket.send_text(json.dumps({
                        "type": "agent_status",
                        **get_agent_readiness(),
                    }))

            except Exception as e:
                print(f"[WS] Ошибка обработки данных от UI: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

def _free_port(port: int):
    """Находит и убивает процесс, занимающий указанный порт на Windows."""
    if sys.platform == "win32":
        try:
            # РС‰РµРј PID РїСЂРѕС†РµСЃСЃР°, СЃР»СѓС€Р°СЋС‰РµРіРѕ РїРѕСЂС‚
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid != "0":
                            print(f"[SERVER] Освобождение порта {port} (убиваем PID {pid})")
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW
                            )
                            time.sleep(0.5)
        except Exception as e:
            print(f"[SERVER] Ошибка при освобождении порта: {e}")

def start_server():
    print("[SERVER] Запуск FastAPI сервера на ws://127.0.0.1:8000/ws")
    try:
        _free_port(8000)
    except Exception as e:
        print(f"[SERVER] Ошибка освобождения порта 8000: {e}")
        
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    except Exception as e:
        print(f"[CRITICAL] Не удалось запустить сервер на порту 8000: {e}")
        print("Пожалуйста, убедитесь, что порт 8000 свободен от других приложений.")
        sys.exit(1)

if __name__ == "__main__":
    # Запускаем оригинальный цикл агента в отдельном потоке
    from main.agent import run_main_loop
    agent_thread = threading.Thread(target=run_main_loop, daemon=True)
    agent_thread.start()
    
    # Запускаем Uvicorn в главном потоке
    start_server()



