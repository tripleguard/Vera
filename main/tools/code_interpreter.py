import subprocess
import sys
import os
import re
from pathlib import Path

# Таймаут выполнения кода (секунды)
DEFAULT_TIMEOUT = 30
MAX_OUTPUT_LENGTH = 4000

# Ключевые слова Python-стейтментов (не являются выражениями)
_STATEMENT_PREFIXES = (
    'import ', 'from ', 'print(', 'print (',
    'def ', 'class ', 'for ', 'if ', 'elif ', 'else:', 'else :', 
    'while ', 'with ', 'try:', 'try :', 'except', 'finally:',
    'return ', 'return\n', 'raise ', 'pass', 'break', 'continue',
    'del ', 'assert ', 'global ', 'nonlocal ', 'yield ',
    '#',  # комментарии
)

def _auto_print_last_expr(code: str) -> str:
    """
    Имитация REPL: если последняя строка — голое выражение,
    оборачивает его в print(), чтобы результат попал в stdout.
    """
    lines = code.rstrip().split('\n')
    if not lines:
        return code
    
    last_line = lines[-1]
    stripped = last_line.strip()
    
    if not stripped:
        return code
    
    # Пропускаем стейтменты
    for prefix in _STATEMENT_PREFIXES:
        if stripped.startswith(prefix):
            return code
    
    # Пропускаем присваивания (=, +=, -=, *=, /=, etc.)
    # Но не сравнения (==, !=, <=, >=)
    if re.search(r'(?<!=)(?<![!<>])=(?!=)', stripped):
        return code
    
    # Определяем отступ последней строки
    indent = last_line[:len(last_line) - len(last_line.lstrip())]
    
    lines[-1] = f'{indent}print({stripped})'
    return '\n'.join(lines)


def execute_python_code(code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    if not code or not code.strip():
        return "Код не указан."
    
    # Авто-обёртка последнего выражения в print() (имитация REPL)
    code = _auto_print_last_expr(code)
    
    # Подавление input() чтобы избежать зависания
    safe_code = "def input(*args, **kwargs): return ''\n\n" + code
    
    # Mutable temp files must live in LocalAppData data dir.
    try:
        from main.config_manager import get_data_dir
        work_dir = get_data_dir() / "interpreter_tmp"
    except ImportError:
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            work_dir = Path(local_app_data) / "Vera" / "data" / "interpreter_tmp"
        else:
            work_dir = Path.home() / "AppData" / "Local" / "Vera" / "data" / "interpreter_tmp"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    script_file = work_dir / f"script_{os.getpid()}.py"
    
    try:
        # Записываем код во временный файл
        script_file.write_text(safe_code, encoding='utf-8')
        
        # Запускаем в отдельном процессе
        result = subprocess.run(
            [sys.executable, str(script_file)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            cwd=str(work_dir),
            stdin=subprocess.DEVNULL,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        
        output_parts = []
        
        if result.stdout:
            output_parts.append(result.stdout)
        
        if result.stderr:
            # Фильтруем warnings если есть stdout
            stderr = result.stderr
            if result.stdout and "Warning" in stderr:
                # Убираем обычные warnings, оставляем ошибки
                lines = [l for l in stderr.split('\n') if 'Warning' not in l and l.strip()]
                stderr = '\n'.join(lines)
            if stderr.strip():
                output_parts.append(f"[stderr]: {stderr}")
        
        if result.returncode != 0 and not output_parts:
            output_parts.append(f"Код завершился с ошибкой (код {result.returncode})")
        
        output = '\n'.join(output_parts).strip()
        
        if not output:
            output = "Код выполнен успешно (без вывода)."
        
        # Обрезаем слишком длинный вывод
        if len(output) > MAX_OUTPUT_LENGTH:
            output = output[:MAX_OUTPUT_LENGTH] + f"\n\n[... вывод обрезан, всего {len(output)} символов]"
        
        return output
        
    except subprocess.TimeoutExpired:
        return f"Ошибка: превышено время выполнения ({timeout} сек). Возможно, код содержит бесконечный цикл."
    
    except Exception as e:
        return f"Ошибка выполнения: {e}"
    
    finally:
        # Удаляем временный файл
        try:
            if script_file.exists():
                script_file.unlink()
        except Exception:
            pass


def extract_code_from_text(text: str) -> str:
    import re
    
    # Ищем код в markdown блоках ```python ... ``` или ``` ... ```
    patterns = [
        r'```python\s*\n(.*?)```',
        r'```py\s*\n(.*?)```', 
        r'```\s*\n(.*?)```',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # Если нет блоков — возвращаем весь текст
    return text.strip()


def execute_code_interpreter(arguments: dict) -> str:
    code = arguments.get("code", "")
    
    if not code:
        return "Укажите код для выполнения."
    
    # Извлекаем код из markdown если нужно
    code = extract_code_from_text(code)
    
    print(f"[CODE_INTERPRETER] Выполняю код:\n{code[:200]}{'...' if len(code) > 200 else ''}")
    
    result = execute_python_code(code)
    
    print(f"[CODE_INTERPRETER] Результат: {result[:200]}{'...' if len(result) > 200 else ''}")
    
    return result
