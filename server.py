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
import secrets
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
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        stale_connections: list[WebSocket] = []
        payload = json.dumps(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                stale_connections.append(connection)
        for connection in stale_connections:
            self.disconnect(connection)

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
from main.audio_devices import (
    choose_input_samplerate,
    choose_output_parameters,
    list_audio_devices,
    normalize_device_selector,
    preferred_audio_devices,
    resolve_audio_device,
)
from main.commands.heartbeat_commands import get_heartbeat_tasks, replace_heartbeat_tasks
from main.upload_utils import safe_upload_name

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
    return secrets.compare_digest(str(token or ""), VERA_API_TOKEN)

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


@app.get("/api/audio/devices")
async def get_audio_devices_api():
    try:
        config = get_config()
        audio_config = config.get("audio", default={}) or {}
        all_devices = list_audio_devices()
        payload = preferred_audio_devices(all_devices)
        payload["selected"] = {
            "input": audio_config.get("input_device"),
            "output": audio_config.get("output_device"),
        }
        payload["active"] = {}
        for kind in ("input", "output"):
            try:
                device = resolve_audio_device(
                    kind,
                    audio_config.get(f"{kind}_device"),
                    available_devices=all_devices,
                )
                payload["active"][kind] = {
                    key: device[key]
                    for key in ("name", "host_api", "default_samplerate", "fallback_reason")
                }
            except Exception as error:
                payload["active"][kind] = {"error": str(error)}
        return JSONResponse(content=payload)
    except Exception as error:
        return JSONResponse(content={"error": str(error)}, status_code=500)


def _audio_device_summary(device: dict) -> dict:
    return {
        key: device.get(key)
        for key in (
            "name",
            "host_api",
            "default_samplerate",
            "fallback_reason",
            "playback_samplerate",
        )
        if key in device
    }


@app.post("/api/audio/device")
async def set_audio_device_api(payload: dict):
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in {"input", "output"}:
        return JSONResponse(content={"error": "Укажите тип устройства: input или output"}, status_code=400)

    raw_selector = payload.get("device")
    selector = normalize_device_selector(raw_selector)
    if raw_selector is not None and selector is None:
        return JSONResponse(content={"error": "Некорректное описание аудиоустройства"}, status_code=400)

    config = get_config()
    previous_selector = config.get("audio", f"{kind}_device")
    try:
        all_devices = list_audio_devices()
        device = resolve_audio_device(
            kind,
            selector,
            available_devices=all_devices,
        )
        if kind == "input":
            choose_input_samplerate(device)
        else:
            choose_output_parameters(device, device["default_samplerate"])
    except Exception as error:
        return JSONResponse(content={"error": str(error)}, status_code=409)

    config.set("audio", f"{kind}_device", value=selector)
    config.save()

    if kind == "output":
        try:
            from main.agent import reconfigure_audio_output

            active = reconfigure_audio_output(selector)
            return JSONResponse(content={
                "status": "applied",
                "selected": selector,
                "active": _audio_device_summary(active),
            })
        except Exception as error:
            config.set("audio", "output_device", value=previous_selector)
            config.save()
            try:
                reconfigure_audio_output(previous_selector)
            except Exception:
                pass
            return JSONResponse(content={"error": str(error)}, status_code=409)

    readiness = get_agent_readiness()
    if readiness.get("components", {}).get("stt", {}).get("status") != "ready":
        return JSONResponse(content={
            "status": "saved",
            "selected": selector,
            "active": _audio_device_summary(device),
            "warning": "Распознавание речи недоступно; микрофон применится при следующем запуске голосового режима",
        }, status_code=202)

    from main.agent import request_audio_input_switch, wait_audio_input_switch

    request_audio_input_switch()
    completed = await asyncio.to_thread(wait_audio_input_switch, 5.0)
    readiness = get_agent_readiness()
    if completed and readiness.get("audio_ready"):
        return JSONResponse(content={
            "status": "applied",
            "selected": selector,
            "active": _audio_device_summary(device),
        })

    error = readiness.get("components", {}).get("audio", {}).get("error")
    config.set("audio", "input_device", value=previous_selector)
    config.save()
    request_audio_input_switch()
    await asyncio.to_thread(wait_audio_input_switch, 5.0)
    return JSONResponse(
        content={"error": error or "Не удалось переключить микрофон; восстановлено предыдущее устройство"},
        status_code=409,
    )


@app.post("/api/audio/test-input")
async def test_audio_input_api():
    readiness = get_agent_readiness()
    if not readiness.get("audio_ready"):
        error = readiness.get("components", {}).get("audio", {}).get("error")
        return JSONResponse(
            content={"error": error or "Микрофон недоступен"},
            status_code=409,
        )
    from main.agent import get_audio_input_level, reset_audio_level_test

    reset_audio_level_test()
    await asyncio.sleep(2)
    levels = get_audio_input_level()
    return JSONResponse(content={
        **levels,
        "signal_detected": levels["peak"] >= 0.01,
    })


@app.post("/api/audio/test-output")
async def test_audio_output_api():
    readiness = get_agent_readiness()
    if not readiness.get("tts_ready"):
        error = readiness.get("components", {}).get("tts", {}).get("error")
        return JSONResponse(
            content={"error": error or "Озвучивание недоступно"},
            status_code=409,
        )
    from main.agent import speak

    speak("Проверка звука. Я Вера, и голос работает.")
    return JSONResponse(content={"status": "queued"})


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
    max_upload_bytes = 20 * 1024 * 1024
    uploads_dir = get_data_dir() / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    # Сохраняем во временную папку
    original_name = file.filename or "upload"
    tmp_path = uploads_dir / safe_upload_name(original_name)
    
    try:
        content = await file.read(max_upload_bytes + 1)
        if len(content) > max_upload_bytes:
            return JSONResponse(
                content={"error": "File is larger than 20 MB", "filename": original_name},
                status_code=413,
            )
        content_type = str(file.content_type or "").lower()
        suffix = Path(original_name).suffix.lower()
        if content_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
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
                "filename": original_name,
                "image_data_url": f"data:image/jpeg;base64,{encoded}",
                "image_preview_data_url": f"data:image/jpeg;base64,{preview_encoded}",
            })

        tmp_path.write_bytes(content)
        
        from main.tools.read_document import read_document_from_path
        text = read_document_from_path(tmp_path)
        
        return JSONResponse(content={"text": text, "filename": original_name})
    except Exception as e:
        return JSONResponse(content={"text": f"Ошибка чтения файла: {e}", "filename": original_name}, status_code=500)
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
        if not verify_token(token):
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



