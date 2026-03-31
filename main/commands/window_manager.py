import re
from typing import Optional
import win32gui
import win32con
import win32process
import psutil
from pathlib import Path

# Импорт индекса приложений для нечёткого поиска
try:
    from main.commands.app_control import APP_INDEX, _best_app_match
except ImportError:
    APP_INDEX = []
    _best_app_match = None


def execute_window_command(text: str) -> Optional[str]:
    """Обрабатывает команды управления окнами."""

    lowered = text.lower().strip()
    
    # Свернуть все окна
    if re.search(r"\b(сверни|свернуть)\s+(все|всё)\s+(окн[ао]|окна)\b", lowered):
        return _minimize_all_windows()
    
    # Свернуть окна (множественное число именительный/винительный) - обрабатываем как "свернуть все"
    if re.search(r"\b(сверни|свернуть)\s+окна\b", lowered) and "все" not in lowered:
        return _minimize_all_windows()
    
    # Свернуть активное окно (единственное число, любой падеж)
    # окно (им/вин), окном (твор), окну (дат)
    if re.search(r"\b(сверни|свернуть)\s+окн(о|ом|у)\b", lowered) and "все" not in lowered:
        return _minimize_active_window()
    
    # Развернуть все окна
    if re.search(r"\b(разверни|развернуть)\s+(все|всё)\s+(окн[ао]|окна)\b", lowered):
        return _restore_all_windows()
    
    # Развернуть окна (множественное число)
    if re.search(r"\b(разверни|развернуть)\s+окн(а|ам)\b", lowered):
        return _restore_all_windows()
    
    # Развернуть приложение
    if m := re.search(r"\b(разверни|развернуть)\s+(.+)", lowered):
        app_name = m.group(2).strip()
        return _restore_window(app_name)
    
    # Переключиться на приложение
    if m := re.search(r"\b(переключ[иь](?:тесь|сь)|переключаться)\s+(?:на\s+)?(.+)", lowered):
        app_name = m.group(2).strip()
        return _switch_to_window(app_name)
    
    return None


def _minimize_all_windows() -> str:
    """Минимизирует все окна (эмуляция Win+D)."""
    try:
        # Используем Shell для минимизации всех окон
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        shell.MinimizeAll()
        return "Все окна свёрнуты."
    except Exception as e:
        print(f"[WINDOW] Ошибка сворачивания всех окон: {e}")
        return "Не удалось свернуть все окна."


def _minimize_active_window() -> str:
    """Минимизирует текущее активное окно."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            return "Окно свёрнуто."
        return "Активное окно не найдено."
    except Exception as e:
        print(f"[WINDOW] Ошибка сворачивания активного окна: {e}")
        return "Не удалось свернуть окно."


def _restore_all_windows() -> str:
    """Разворачивает все свёрнутые окна."""
    try:
        restored_count = 0
        
        def enum_callback(hwnd, _):
            nonlocal restored_count
            if not win32gui.IsWindowVisible(hwnd):
                return True
            
            try:
                # Проверяем, свёрнуто ли окно
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement[1] == win32con.SW_SHOWMINIMIZED:
                    # Проверяем, что это не системное окно
                    title = win32gui.GetWindowText(hwnd)
                    if title:  # Только окна с заголовком
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        restored_count += 1
            except Exception:
                pass
            
            return True
        
        win32gui.EnumWindows(enum_callback, None)
        
        if restored_count > 0:
            return f"Развёрнуто окон: {restored_count}."
        return "Нет свёрнутых окон."
    except Exception as e:
        print(f"[WINDOW] Ошибка разворачивания всех окон: {e}")
        return "Не удалось развернуть окна."


def _find_window_by_app_name(app_query: str) -> Optional[int]:
    # Сначала пытаемся найти приложение в индексе
    app_match = None
    if _best_app_match and APP_INDEX:
        try:
            app_match = _best_app_match(app_query)
        except Exception:
            pass
    
    # Определяем имя процесса для поиска
    if app_match and app_match.get("exe_name"):
        # Используем имя процесса из индекса
        target_names = [app_match["exe_name"]]
    else:
        # Fallback: используем запрос напрямую
        target_names = [app_query, app_query + ".exe"]
    
    found_hwnd = None
    
    def enum_callback(hwnd, _):
        nonlocal found_hwnd
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
        except Exception:
            return True
        
        try:
            # Получаем PID окна
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()
            
            # Проверяем совпадение с любым из target_names
            for target in target_names:
                target_lower = target.lower()
                proc_name_clean = Path(proc_name).stem.lower()
                target_clean = Path(target_lower).stem.lower()
                
                # Проверка различными способами
                if (target_clean == proc_name_clean or
                    target_clean in proc_name_clean or 
                    proc_name_clean in target_clean or
                    target_lower == proc_name or
                    target_lower.replace(" ", "") in proc_name.replace(" ", "")):
                    found_hwnd = hwnd
                    return False  # Останавливаем перечисление
        except Exception:
            # Игнорируем любые ошибки (процесс завершился, нет доступа и т.д.)
            pass
        
        return True
    
    try:
        win32gui.EnumWindows(enum_callback, None)
    except Exception:
        pass    
    return found_hwnd


def _force_foreground(hwnd: int) -> bool:
    """Принудительно активирует окно, обходя ограничения Windows."""
    try:
        # Получаем текущее активное окно
        foreground = win32gui.GetForegroundWindow()
        if foreground == hwnd:
            return True
        
        # Получаем ID потоков
        fg_thread = win32process.GetWindowThreadProcessId(foreground)[0]
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        
        # Присоединяем потоки для обхода ограничений
        if fg_thread != target_thread:
            try:
                win32process.AttachThreadInput(fg_thread, target_thread, True)
                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
                win32process.AttachThreadInput(fg_thread, target_thread, False)
            except Exception:
                # Если не удалось - пробуем простой метод
                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
        else:
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        
        return True
    except Exception:
        return False


def _restore_window(app_name: str) -> str:
    """Разворачивает окно приложения."""
    try:
        hwnd = _find_window_by_app_name(app_name)
        if not hwnd:
            return f"Окно '{app_name}' не найдено."
        
        # Проверяем текущее состояние
        placement = win32gui.GetWindowPlacement(hwnd)
        
        # Если свёрнуто - разворачиваем
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            # Если уже развёрнуто - максимизируем
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        
        # Активируем окно
        _force_foreground(hwnd)
        
        return f"Окно '{app_name}' развёрнуто."
    except Exception:
        return f"Не удалось развернуть окно '{app_name}'."


def _switch_to_window(app_name: str) -> str:
    """Переключается на окно приложения."""
    try:
        hwnd = _find_window_by_app_name(app_name)
        if not hwnd:
            return f"Окно '{app_name}' не найдено."
        
        # Если окно свёрнуто - восстанавливаем
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        
        # Активируем окно (выводим на передний план)
        _force_foreground(hwnd)
        
        return f"Переключаюсь на '{app_name}'."
    except Exception as e:
        print(f"[WINDOW] Ошибка переключения: {e}")
        return f"Не удалось переключиться на '{app_name}'."
