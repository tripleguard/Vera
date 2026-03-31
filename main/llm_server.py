"""
Управление внешним llama-server.exe и HTTP-клиент для взаимодействия с LLM.

Заменяет внутреннее использование LLM на HTTP-запросы
к нативному llama-server (OpenAI-совместимый API).
"""

import atexit
import glob
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
import ctypes
import json

import requests
from main.config_manager import get_install_root


# ──────────────────────────────────────────────────────────────────
#  Управление Job Object (Windows) для надежного убийства дочерних процессов
# ──────────────────────────────────────────────────────────────────
def _assign_to_job_object(pid: int) -> int:
    """Привязывает процесс к Job Object для автозавершения при падении родителя."""
    if sys.platform != "win32":
        return 0
    
    try:
        from ctypes import wintypes
        
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if job:
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            res = kernel32.SetInformationJobObject(
                job, 9, ctypes.pointer(info), ctypes.sizeof(info) 
            )
            if res:
                handle = kernel32.OpenProcess(0x1F0FFF, False, pid)
                if handle:
                    kernel32.AssignProcessToJobObject(job, handle)
                    kernel32.CloseHandle(handle)
            return job
    except Exception as e:
        print(f"[LLM_SERVER] Ошибка при создании Job Object: {e}")
    return 0


# ──────────────────────────────────────────────────────────────────
#  LlamaServer — управление процессом llama-server.exe
# ──────────────────────────────────────────────────────────────────

class LlamaServer:
    """Запускает и контролирует процесс llama-server.exe."""

    _EXE_NAME = "llama-server.exe"
    _HEALTH_TIMEOUT = 90          # макс. ожидание запуска (сек)
    _HEALTH_INTERVAL = 1.0        # интервал проверки /health
    _STOP_TIMEOUT = 5             # таймаут на завершение процесса

    def __init__(
        self,
        model_path: str,
        ctx_size: int = 16384,
        port: int = 29741,
        host: str = "127.0.0.1",
        n_gpu_layers: int = -1,
        extra_args: Optional[List[str]] = None,
    ):
        self.model_path = self._resolve_model_path(model_path)
        self.ctx_size = ctx_size
        self.port = port
        self.host = host
        self.n_gpu_layers = n_gpu_layers
        self.extra_args = extra_args or []

        self._process: Optional[subprocess.Popen] = None
        self._exe_path = self._find_executable()
        self._job_handle = 0

    # ── публичные методы ──

    def start(self) -> None:
        """Запускает llama-server и ждёт готовности."""
        if self._process and self._process.poll() is None:
            print("[LLM_SERVER] Сервер уже запущен.")
            return

        if not self._exe_path:
            raise FileNotFoundError(
                f"{self._EXE_NAME} not found. "
                "Download it with download_llama_server.py or install optional runtime."
            )

        # Убиваем возможные зависшие копии прошлого запуска
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", self._EXE_NAME],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                time.sleep(0.5)
            except Exception:
                pass

        cmd = [
            str(self._exe_path),
            "--model", str(self.model_path),
            "--ctx-size", str(self.ctx_size),
            "--port", str(self.port),
            "--host", self.host,
            "--n-gpu-layers", str(self.n_gpu_layers),
            "--jinja",
        ]
        cmd.extend(self.extra_args)

        print(f"[LLM_SERVER] Запуск: {' '.join(cmd)}")

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        
        # Привязываем процесс к Job Object, чтобы он умер вместе с нами
        if sys.platform == "win32":
            self._job_handle = _assign_to_job_object(self._process.pid)
            
        atexit.register(self.stop)

        if not self._wait_for_health():
            # Читаем лог процесса для диагностики
            self.stop()
            raise RuntimeError("llama-server did not pass /health check in time")

        print(f"[LLM_SERVER] Сервер готов на http://{self.host}:{self.port}")

    def stop(self) -> None:
        """Корректно завершает процесс сервера."""
        if self._process is None:
            return
        if self._process.poll() is not None:
            self._process = None
            return
        
        # Закрываем хэндл Job Object, если он был создан
        if self._job_handle != 0:
            try:
                ctypes.windll.kernel32.CloseHandle(self._job_handle)
                self._job_handle = 0
            except Exception:
                pass
                
        try:
            self._process.terminate()
            self._process.wait(timeout=self._STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
        except Exception as e:
            print(f"[LLM_SERVER] Ошибка при остановке: {e}")
        finally:
            self._process = None
        print("[LLM_SERVER] Сервер остановлен.")

    def restart(self) -> None:
        """Перезапускает сервер."""
        print("[LLM_SERVER] Перезапуск сервера...")
        self.stop()
        time.sleep(1)
        self.start()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ── приватные методы ──

    def _resolve_model_path(self, path: str) -> Path:
        """Находит путь к модели. 'auto' — ищет первый .gguf в папке проекта."""
        path = str(path or "").strip()
        if not path or path.lower() == "auto":
            project_root = get_install_root()
            gguf_files = sorted(project_root.glob("*.gguf"))
            if not gguf_files:
                raise FileNotFoundError("No .gguf model found in install root")
            chosen = gguf_files[0]
            print(f"[LLM_SERVER] Авто-определение модели: {chosen.name}")
            return chosen
        model_path = Path(path)
        if not model_path.is_absolute():
            model_path = get_install_root() / model_path
        return model_path.resolve()

    def _find_executable(self) -> Optional[Path]:
        """Ищет llama-server.exe в папке проекта и подпапках."""
        project_root = get_install_root()
        # Прямо в корне
        direct = project_root / self._EXE_NAME
        if direct.is_file():
            return direct
        # В подпапках (например, bin/, build/)
        for candidate in project_root.rglob(self._EXE_NAME):
            if candidate.is_file():
                return candidate
        return None

    def _wait_for_health(self) -> bool:
        """Ждёт пока сервер начнёт отвечать на /health."""
        url = f"http://{self.host}:{self.port}/health"
        deadline = time.time() + self._HEALTH_TIMEOUT
        print(f"[LLM_SERVER] Ожидание готовности сервера (до {self._HEALTH_TIMEOUT} сек)...")

        while time.time() < deadline:
            # Проверяем, не упал ли процесс
            if self._process.poll() is not None:
                # Читаем вывод для диагностики
                try:
                    out = self._process.stdout.read().decode("utf-8", errors="replace")
                    if out.strip():
                        print(f"[LLM_SERVER] Вывод сервера:\n{out[-2000:]}")
                except Exception:
                    pass
                print("[LLM_SERVER] Процесс сервера завершился преждевременно.")
                return False
            try:
                r = requests.get(url, timeout=2)
                if r.status_code == 200:
                    return True
            except requests.ConnectionError:
                pass
            except Exception:
                pass
            time.sleep(self._HEALTH_INTERVAL)

        return False


# ──────────────────────────────────────────────────────────────────
#  LlamaClient — HTTP-клиент, совместимый с llama_cpp.Llama
# ──────────────────────────────────────────────────────────────────

class LlamaClient:
    """
    Drop-in замена для llama_cpp.Llama.
    
    Предоставляет метод create_chat_completion() c тем же интерфейсом,
    но под капотом делает HTTP POST на llama-server.
    """

    _REQUEST_TIMEOUT = 120  # таймаут на генерацию (сек)

    # Параметры, которые принимает /v1/chat/completions
    _ALLOWED_PARAMS = {
        "temperature", "top_p", "top_k", "min_p",
        "repeat_penalty", "presence_penalty", "frequency_penalty",
        "max_tokens", "stop", "seed", "stream",
        "tools", "tool_choice",
        "chat_template_kwargs", "reasoning_budget", "reasoning_format",
    }

    def __init__(self, host: str = "127.0.0.1", port: int = 29741, base_url: Optional[str] = None):
        if base_url:
            self._base_url = base_url.rstrip("/")
        else:
            self._base_url = f"http://{host}:{port}"
        self._chat_url = f"{self._base_url}/v1/chat/completions"

    def _parse_stream(self, response: requests.Response) -> Iterator[Dict[str, Any]]:
        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8")
            if line_str.startswith("data: "):
                data_str = line_str[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    continue

    def create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Отправляет запрос на /v1/chat/completions.
        
        Возвращает ответ в формате OpenAI:
        {"choices": [{"message": {"content": "..."}}]}
        """
        payload: Dict[str, Any] = {"messages": messages}

        # Фильтруем параметры — передаём только поддерживаемые
        for key, value in kwargs.items():
            if key in self._ALLOWED_PARAMS and value is not None:
                payload[key] = value

        # repeat_penalty → маппинг на frequency_penalty если нужно
        if "repeat_penalty" in payload:
            rp = payload.pop("repeat_penalty")
            # llama-server поддерживает repeat_penalty напрямую
            payload["repeat_penalty"] = rp

        try:
            is_streaming = payload.get("stream", False)
            response = requests.post(
                self._chat_url,
                json=payload,
                timeout=self._REQUEST_TIMEOUT,
                stream=is_streaming
            )
            response.raise_for_status()
            if is_streaming:
                return self._parse_stream(response)
            return response.json()
        except requests.Timeout:
            raise RuntimeError(
                f"[LLM_CLIENT] Таймаут ответа от сервера ({self._REQUEST_TIMEOUT} сек)"
            )
        except requests.ConnectionError:
            raise RuntimeError(
                "[LLM_CLIENT] Не удалось подключиться к LLM-серверу. "
                "Проверьте, что llama-server запущен."
            )
        except requests.HTTPError as e:
            raise RuntimeError(f"[LLM_CLIENT] HTTP ошибка: {e}")
