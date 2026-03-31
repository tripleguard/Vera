import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from main.lang_ru import replace_number_words


def execute_taskmanager_command(text: str) -> Optional[str]:
    lower = text.lower()
    
    # Закрытие диспетчера задач
    close_patterns = [
        r"\b(закрой|закрыть|выключи|выруби|останови)\s+диспетчер\s+задач",
    ]
    
    if any(re.search(p, lower) for p in close_patterns):
        try:
            subprocess.run(["taskkill", "/IM", "taskmgr.exe", "/F"], 
                          capture_output=True, check=False)
            return "Закрываю диспетчер задач."
        except Exception as e:
            print(f"[TASKMGR] Ошибка закрытия: {e}")
            return "Не удалось закрыть диспетчер задач."
    
    # Открытие диспетчера задач
    open_patterns = [
        r"\b(открой|запусти|покажи)\s+диспетчер\s+задач",
    ]
    
    if any(re.search(p, lower) for p in open_patterns):
        try:
            subprocess.Popen(["taskmgr.exe"], shell=True)
            return "Открываю диспетчер задач."
        except Exception as e:
            print(f"[TASKMGR] Ошибка: {e}")
            return "Не удалось открыть диспетчер задач."
    
    return None


def execute_volume_command(text: str) -> Optional[str]:
    """Управление громкостью системы."""
    cleaned = replace_number_words(text.lower())
    
    # Поиск процентов
    if m := re.search(r"\b(?:громкост[ьи]|звук[ауе]?)\b\s*(?:на\s*)?(\d+)\s*(?:%|процент)", cleaned, re.IGNORECASE):
        pct = max(0, min(int(m.group(1)), 100))
        _set_master_volume(pct / 100)
        return f"Громкость установлена на {pct}%."
    
    # Поиск чисел 1-10 или 0-100
    if m := re.search(r"\b(?:громкост[ьи]|звук[ауе]?)\b\s*(?:на\s*)?(\d+)\b", cleaned, re.IGNORECASE):
        n = int(m.group(1))
        pct = n * 10 if 0 <= n <= 10 else max(0, min(n, 100))
        _set_master_volume(pct / 100)
        return f"Громкость установлена на {pct}%."
    
    return None


def _set_master_volume(level: float) -> bool:
    """Устанавливает системную громкость (0.0 - 1.0)."""

    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        from pycaw import pycaw
        
        # Создаём enumerator напрямую
        deviceEnumerator = pycaw.AudioUtilities.GetSpeakers()
        
        # Проверяем тип объекта и получаем правильный интерфейс
        if hasattr(deviceEnumerator, 'Activate'):
            interface = deviceEnumerator.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        elif hasattr(deviceEnumerator, 'QueryInterface'):
            # Альтернативный путь через QueryInterface
            from pycaw.pycaw import IMMDevice
            device = deviceEnumerator.QueryInterface(IMMDevice)
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        else:
            # Пробуем создать enumerator вручную
            from comtypes import CoCreateInstance, GUID
            CLSID_MMDeviceEnumerator = GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}')
            from pycaw.pycaw import IMMDeviceEnumerator
            
            enumerator = CoCreateInstance(
                CLSID_MMDeviceEnumerator,
                IMMDeviceEnumerator,
                CLSCTX_ALL
            )
            # eRender = 0, eMultimedia = 1
            device = enumerator.GetDefaultAudioEndpoint(0, 1)
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(level, None)
        return True
        
    except Exception as e:
        print(f"[VOLUME] pycaw ошибка: {e}")
    
    # Fallback: PowerShell с Set-Volume (если есть AudioDeviceCmdlets)
    try:
        pct = int(level * 100)
        result = subprocess.run(
            ['powershell', '-Command', f'(Get-AudioDevice -Playback).SetVolume({pct})'],
            capture_output=True, timeout=3
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass
    
    return False


def execute_brightness_command(text: str) -> Optional[str]:
    """Управление яркостью экрана."""
    cleaned = replace_number_words(text.lower())
    
    # Поиск процентов
    if m := re.search(r"\bяркост[ьи]\b\s*(?:на\s*)?(\d+)\s*(?:%|процент)", cleaned, re.IGNORECASE):
        pct = max(0, min(int(m.group(1)), 100))
        if _set_screen_brightness(pct):
            return f"Яркость установлена на {pct}%."
        return "Не удалось изменить яркость экрана."
    
    # Поиск чисел 1-10 или 0-100
    if m := re.search(r"\bяркост[ьи]\b\s*(?:на\s*)?(\d+)\b", cleaned, re.IGNORECASE):
        n = int(m.group(1))
        pct = n * 10 if 0 <= n <= 10 else max(0, min(n, 100))
        if _set_screen_brightness(pct):
            return f"Яркость установлена на {pct}%."
        return "Не удалось изменить яркость экрана."
    
    return None


def _set_screen_brightness(level: int) -> bool:
    #Устанавливает яркость экрана.
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        return True
    except Exception as e:
        print(f"[BRIGHTNESS] Ошибка установки яркости: {e}")
        return False


def execute_screenshot_command(text: str) -> Optional[str]:
    #Создание скриншота.
    if not re.search(r"\b(скриншот|снимок\s+экрана|сделай\s+снимок)\b", text.lower()):
        return None
    
    try:
        from PIL import ImageGrab
        
        # Папка для скриншотов
        screenshots_dir = Path.home() / "Pictures" / "Screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Имя файла с timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = screenshots_dir / filename
        
        # Создание скриншота
        screenshot = ImageGrab.grab()
        screenshot.save(filepath)
        
        return (
            "Скриншот сохранён в папке Screenshots\n"
            f"Файл создан: {filepath}"
        )
    except Exception as e:
        print(f"[SCREENSHOT] Ошибка: {e}")
        return "Не удалось создать скриншот."


def execute_ip_command(text: str) -> Optional[str]:
    #Получение IP адреса.
    ip_pattern = r"(ip|ай\s*-?\s*пи|айпи)"
    # Триггерные слова и фразы
    trigger_pattern = r"(какой|мой|узнай|покажи|скажи|назови|определи|получи)"
    
    text_lower = text.lower()
    
    patterns = [
        rf"{trigger_pattern}.*{ip_pattern}",
        rf"{ip_pattern}.*адрес",
        rf"у\s+меня\s+{ip_pattern}", 
    ]
    
    if not any(re.search(p, text_lower) for p in patterns):
        return None
    
    try:
        import requests
        
        # Используем несколько сервисов для надёжности
        services = [
            "https://api.ipify.org?format=json",
            "https://ifconfig.me/ip",
            "https://icanhazip.com",
        ]
        
        for service in services:
            try:
                resp = requests.get(service, timeout=3)
                if resp.status_code == 200:
                    if "json" in service:
                        ip = resp.json().get("ip", "").strip()
                    else:
                        ip = resp.text.strip()
                    
                    if ip:
                        return f"Ваш IP адрес: {ip}"
            except Exception:
                continue
        
        return "Не удалось получить IP адрес."
    except Exception as e:
        print(f"[IP] Ошибка: {e}")
        return "Ошибка получения IP адреса."


def execute_start_menu_command(text: str) -> Optional[str]:
    """Открытие меню Пуск."""
    lower = text.lower().strip()
    
    patterns = [
        r"^пуск$",
        r"\b(открой|открыть|покажи|запусти)\s+(меню\s+)?пуск\b",
        r"\bменю\s+пуск\b",
        r"\bстарт\s*меню\b",
        r"\bвера\s+пуск\b",  # если ключевое слово не удалилось
    ]
    
    if any(re.search(p, lower) for p in patterns):
        try:
            # Используем ctypes для эмуляции Win клавиши
            import ctypes
            user32 = ctypes.windll.user32
            # VK_LWIN = 0x5B (Left Windows key)
            user32.keybd_event(0x5B, 0, 0, 0)  # Key down
            user32.keybd_event(0x5B, 0, 2, 0)  # Key up
            return "Открываю меню Пуск."
        except Exception as e:
            print(f"[START_MENU] ctypes ошибка: {e}")
            # Fallback через pyautogui
            try:
                import pyautogui
                pyautogui.press('win')
                return "Открываю меню Пуск."
            except Exception:
                pass
            return "Не удалось открыть меню Пуск."
    
    return None


def execute_explorer_command(text: str) -> Optional[str]:
    """Открытие проводника / Мой компьютер / Этот компьютер."""
    lower = text.lower().strip()
    
    patterns = [
        r"\b(открой|открыть|покажи|запусти)\s+(мой\s+)?компьютер\b",
        r"\b(открой|открыть|покажи|запусти)\s+этот\s+компьютер\b",
        r"\b(открой|открыть|покажи|запусти)\s+проводник\b",
        r"\bмой\s+компьютер\b",
        r"\bэтот\s+компьютер\b",
    ]
    
    if any(re.search(p, lower) for p in patterns):
        try:
            # Открываем "Этот компьютер" через shell:MyComputerFolder
            subprocess.Popen(['explorer.exe', 'shell:MyComputerFolder'])
            return "Открываю проводник."
        except Exception as e:
            print(f"[EXPLORER] Ошибка: {e}")
            return "Не удалось открыть проводник."
    
    return None
