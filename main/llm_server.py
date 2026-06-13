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
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
import ctypes
import json

import requests
from main.config_manager import get_install_root, get_data_dir, get_config


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
        ctx_size: int = 16384,
        port: int = 29741,
        host: str = "127.0.0.1",
        n_gpu_layers: Any = "auto",
        extra_args: Optional[List[str]] = None,
    ):
        self.model_path = self._resolve_model_path()
        self.mmproj_path = self._resolve_mmproj_path()
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
            "--parallel", "1",
            "--jinja",
            "--fit", "on",
        ]
        if self.mmproj_path:
            cmd.extend(["--mmproj", str(self.mmproj_path)])
            # A full-precision projector does not fit alongside a 4B model on
            # common 4 GB GPUs. Keep vision available without exhausting VRAM.
            cmd.append("--no-mmproj-offload")
        cmd.extend(self.extra_args)

        print(f"[LLM_SERVER] Запуск: {' '.join(cmd)}")

        # Создаем директорию для логов, если её нет
        log_dir = get_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = log_dir / "llama_server.log"
        
        # Открываем файл для записи вывода сервера
        # Используем 'a' (append), чтобы не затирать логи при каждом перезапуске
        log_file = open(log_file_path, "a", encoding="utf-8")
        log_file.write(f"\n\n--- Запуск сервера: {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_file.flush()

        self._process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(self._exe_path.parent),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        
        # Привязываем процесс к Job Object, чтобы он умер вместе с нами
        if sys.platform == "win32":
            self._job_handle = _assign_to_job_object(self._process.pid)
            
        atexit.register(self.stop)

        if not self._wait_for_health():
            failed_projector = self.mmproj_path
            self.stop()
            if failed_projector:
                print(
                    f"[LLM_SERVER] Projector {failed_projector.name} could not be "
                    "loaded with this model. Retrying in text-only mode."
                )
                self.mmproj_path = None
                self.start()
                return
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

    def _resolve_model_path(self) -> Path:
        """Находит путь к модели через ConfigManager или авто-поиск."""
        # Пытаемся взять уже разрешенный путь из конфига
        config_path = get_config().get("model", "path")
        if config_path and Path(config_path).exists():
            return Path(config_path).resolve()

        # Fallback: ручной поиск если в конфиге пусто
        project_root = get_install_root()
        gguf_files = sorted(
            path for path in project_root.glob("*.gguf")
            if "mmproj" not in path.name.lower()
        )
        if not gguf_files:
            # Also check parent dirs (for Inno Setup layout)
            for parent in project_root.parents:
                gguf_files = sorted(
                    path for path in parent.glob("*.gguf")
                    if "mmproj" not in path.name.lower()
                )
                if gguf_files:
                    break
                if parent == project_root.parent.parent:
                    break
        
        if not gguf_files:
            raise FileNotFoundError("Критическая ошибка: Файл модели .gguf не найден в папке приложения.")
        
        chosen = gguf_files[0]
        print(f"[LLM_SERVER] Авто-определение модели: {chosen.name}")
        return chosen.resolve()

    def _resolve_mmproj_path(self) -> Optional[Path]:
        """Find a local multimodal projector next to the selected model."""
        configured = str(
            get_config().get("model", "vision_projector_path", default="auto") or ""
        ).strip()
        if configured and configured.lower() != "auto":
            configured_path = Path(configured)
            if not configured_path.is_absolute():
                configured_path = get_install_root() / configured_path
            if configured_path.is_file():
                chosen = configured_path.resolve()
                print(f"[LLM_SERVER] Multimodal projector from config: {chosen.name}")
                return chosen
            print(
                f"[LLM_SERVER] Configured multimodal projector not found: "
                f"{configured_path}"
            )

        search_dirs = [self.model_path.parent, get_install_root()]
        seen = set()
        candidates: List[Path] = []
        for directory in search_dirs:
            resolved = directory.resolve()
            if resolved in seen or not resolved.exists():
                continue
            seen.add(resolved)
            candidates.extend(sorted(
                path for path in resolved.glob("*.gguf")
                if "mmproj" in path.name.lower()
            ))
        if not candidates:
            print("[LLM_SERVER] Multimodal projector not found; vision input is disabled.")
            return None

        model_size = self._model_size_tag(self.model_path)
        size_compatible = [
            candidate for candidate in candidates
            if (
                not model_size
                or not self._model_size_tag(candidate)
                or self._model_size_tag(candidate) == model_size
            )
        ]
        if not size_compatible:
            names = ", ".join(candidate.name for candidate in candidates)
            print(
                f"[LLM_SERVER] Ignoring size-incompatible multimodal projector(s) "
                f"for {self.model_path.name}: {names}"
            )
            return None
        sized_matches = [
            candidate for candidate in size_compatible
            if self._model_size_tag(candidate) == model_size
        ]
        pool = sized_matches or size_compatible
        ranked = sorted(
            (
                (self._projector_match_score(candidate), candidate)
                for candidate in pool
            ),
            key=lambda item: (-item[0], item[1].name.lower()),
        )
        best_score = ranked[0][0] if ranked else 0
        best = [candidate for score, candidate in ranked if score == best_score]

        if best_score > 0 and len(best) == 1:
            chosen = best[0].resolve()
        elif len(size_compatible) == 1:
            # Many model releases use a generic name such as mmproj-F32.gguf.
            chosen = size_compatible[0].resolve()
        else:
            names = ", ".join(candidate.name for candidate in candidates)
            print(
                f"[LLM_SERVER] Cannot choose a unique multimodal projector for "
                f"{self.model_path.name}: {names}. Set model.vision_projector_path."
            )
            return None

        print(f"[LLM_SERVER] Multimodal projector: {chosen.name}")
        return chosen

    @staticmethod
    def _model_size_tag(path: Path) -> Optional[str]:
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[bB](?![A-Za-z])", path.stem)
        return match.group(1).lower() if match else None

    def _projector_match_score(self, projector: Path) -> int:
        model_tokens = self._model_family_tokens(self.model_path)
        projector_tokens = self._model_family_tokens(projector)
        return len(model_tokens & projector_tokens)

    @staticmethod
    def _model_family_tokens(path: Path) -> set[str]:
        ignored = {
            "gguf", "mmproj", "model", "vision", "projector",
            "f16", "f32", "bf16", "fp16", "fp32",
            "q", "q2", "q3", "q4", "q5", "q6", "q8",
            "k", "s", "m", "l", "xs",
        }
        tokens = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?b?", path.stem.lower()))
        return {
            token for token in tokens
            if (
                token not in ignored
                and not token.isdigit()
                and not re.fullmatch(r"q\d+(?:_[a-z0-9]+)*", token)
            )
        }

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
        # В родительских папках (для Inno Setup)
        for parent in project_root.parents:
            candidate = parent / self._EXE_NAME
            if candidate.is_file():
                return candidate
            if parent == project_root.parent.parent:
                break
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
        api_prefix = self._base_url if self._base_url.endswith("/v1") else f"{self._base_url}/v1"
        self._chat_url = f"{api_prefix}/chat/completions"

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
        messages: List[Dict[str, Any]],
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
            details = ""
            if e.response is not None:
                try:
                    details = str(e.response.text or "").strip()
                except Exception:
                    details = ""
            suffix = f": {details[:1000]}" if details else ""
            raise RuntimeError(f"[LLM_CLIENT] HTTP ошибка: {e}{suffix}")
