"""
Менеджер долгосрочной памяти с использованием MEMORY.md

Разработан с учётом быстродействия на слабом/среднем железе:
- Жёсткие лимиты на размер контекста для LLM (макс. 500 символов)
- Ограничение количества фактов и профильных полей
- Простой парсинг без тяжёлых зависимостей
"""
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import re


# Лимиты для быстродействия
MAX_PROFILE_FIELDS = 10       # Максимум полей профиля
MAX_FACTS = 10                # Максимум фактов
MAX_CONTEXT_LENGTH = 500      # Максимум символов контекста для промпта
MAX_SESSION_SUMMARY_LENGTH = 200  # Максимум символов для краткого содержания
MAX_DIALOG_MESSAGES = 5       # Максимум сообщений диалога для сохранения


class MemoryManager:
    """
    Управляет долгосрочной памятью агента через MEMORY.md файл.
    
    Структура MEMORY.md:
    - Профиль пользователя (имя, город, работа...)
    - Важные факты
    - Краткое содержание последнего диалога
    """
    
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.profile: Dict[str, str] = {}          # Имя, город, работа...
        self.facts: List[str] = []                  # Важные факты
        self.last_session_summary: str = ""         # Краткое содержание последнего диалога
        self.last_dialog_messages: List[Dict[str, str]] = []  # Последние сообщения диалога
        self._load()
    
    def _load(self) -> None:
        """Парсит MEMORY.md и загружает данные."""
        if not self.memory_path.exists():
            self._create_default()
            return
        
        try:
            content = self.memory_path.read_text(encoding='utf-8')
            self._parse_markdown(content)
        except Exception as e:
            print(f"[MEMORY] Ошибка загрузки MEMORY.md: {e}")
            self._create_default()
    
    def _create_default(self) -> None:
        """Создаёт пустой MEMORY.md."""
        default = """# Память Веры

> Этот файл автоматически обновляется агентом.
> Можно редактировать вручную.

## Профиль

*(пока нет данных)*

## Факты

*(пока нет данных)*

## Последний диалог

*(нет данных)*
"""
        try:
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.memory_path.write_text(default, encoding='utf-8')
        except Exception as e:
            print(f"[MEMORY] Ошибка создания MEMORY.md: {e}")
    
    def _parse_markdown(self, content: str) -> None:
        """Парсит markdown и извлекает структурированные данные."""
        # Профиль пользователя
        profile_match = re.search(
            r'## Профиль\s*(.*?)(?=##|$)', 
            content, re.DOTALL
        )
        if profile_match:
            for line in profile_match.group(1).strip().split('\n'):
                m = re.match(r'-\s*\*\*(.+?):\*\*\s*(.+)', line)
                if m:
                    key = m.group(1).lower().strip()
                    value = m.group(2).strip()
                    if key and value and 'нет данных' not in value.lower():
                        self.profile[key] = value
        
        # Важные факты
        facts_match = re.search(
            r'## Факты\s*(.*?)(?=##|$)', 
            content, re.DOTALL
        )
        if facts_match:
            for line in facts_match.group(1).strip().split('\n'):
                if line.startswith('- ') and 'нет данных' not in line.lower():
                    fact = line[2:].strip()
                    if fact:
                        self.facts.append(fact)
        
        # Последний диалог (парсим сообщения в формате "**Вы:** ..." / "**Вера:** ...")
        dialog_match = re.search(
            r'## Последний диалог\s*(.*?)(?=##|$)', 
            content, re.DOTALL
        )
        if dialog_match:
            dialog_content = dialog_match.group(1).strip()
            if 'нет данных' not in dialog_content.lower():
                # Парсим сообщения
                for line in dialog_content.split('\n'):
                    line = line.strip()
                    if line.startswith('- **Вы:**'):
                        msg = line[9:].strip()
                        if msg:
                            self.last_dialog_messages.append({'role': 'user', 'content': msg})
                    elif line.startswith('- **Вера:**'):
                        msg = line[11:].strip()
                        if msg:
                            self.last_dialog_messages.append({'role': 'assistant', 'content': msg})
    
    def save(self) -> None:
        """Сохраняет данные в MEMORY.md."""
        lines = [
            "# Память Веры\n",
            "> Этот файл автоматически обновляется агентом.",
            "> Можно редактировать вручную.\n",
            "## Профиль\n"
        ]
        
        if self.profile:
            for key, value in list(self.profile.items())[:MAX_PROFILE_FIELDS]:
                lines.append(f"- **{key.capitalize()}:** {value}")
        else:
            lines.append("*(пока нет данных)*")
        
        lines.append("\n## Факты\n")
        if self.facts:
            for fact in self.facts[:MAX_FACTS]:
                lines.append(f"- {fact}")
        else:
            lines.append("*(пока нет данных)*")
        
        lines.append("\n## Последний диалог\n")
        if self.last_dialog_messages:
            for msg in self.last_dialog_messages[-MAX_DIALOG_MESSAGES:]:
                role = "Вы" if msg.get('role') == 'user' else "Вера"
                content = msg.get('content', '')[:200]  # Ограничиваем длину
                lines.append(f"- **{role}:** {content}")
        else:
            lines.append("*(нет данных)*")
        
        try:
            self.memory_path.write_text('\n'.join(lines), encoding='utf-8')
        except Exception as e:
            print(f"[MEMORY] Ошибка сохранения: {e}")
    
    # === API для работы с памятью ===
    
    def set_profile(self, key: str, value: str) -> None:
        """Устанавливает поле профиля."""
        key = key.lower().strip()
        value = value.strip()
        
        if not key or not value:
            return
        
        # Ограничиваем количество полей
        if key not in self.profile and len(self.profile) >= MAX_PROFILE_FIELDS:
            # Удаляем самое старое поле
            oldest = next(iter(self.profile))
            del self.profile[oldest]
        
        self.profile[key] = value
        self.save()
    
    def get_profile(self, key: str) -> Optional[str]:
        """Получает поле профиля."""
        return self.profile.get(key.lower().strip())
    
    def get_name(self) -> str:
        """Получает имя пользователя (для совместимости)."""
        return self.profile.get("имя", "")
    
    def set_name(self, name: str) -> None:
        """Устанавливает имя пользователя (для совместимости)."""
        self.set_profile("имя", name)
    
    def add_fact(self, fact: str) -> None:
        """Добавляет факт о пользователе."""
        fact = fact.strip()
        if not fact or fact in self.facts:
            return
        
        # Ограничиваем количество фактов
        if len(self.facts) >= MAX_FACTS:
            self.facts.pop(0)  # Удаляем самый старый
        
        self.facts.append(fact)
        self.save()
    
    def delete_fact(self, fact_fragment: str) -> bool:
        """Удаляет факт, содержащий указанный фрагмент."""
        fragment = fact_fragment.lower().strip()
        for i, fact in enumerate(self.facts):
            if fragment in fact.lower():
                del self.facts[i]
                self.save()
                return True
        return False

    def clear_all(self):
        """Очищает всю память (профиль, факты, историю диалога)."""
        self.profile.clear()
        self.facts.clear()
        self.last_dialog_messages.clear()
        self.save()
        
    
    def update_session_summary(self, summary: str) -> None:
        """Обновляет краткое содержание последней сессии (устаревший метод)."""
        now = datetime.now().strftime("%d.%m %H:%M")
        # Обрезаем до лимита
        summary_short = summary[:MAX_SESSION_SUMMARY_LENGTH]
        self.last_session_summary = f"**{now}:** {summary_short}"
        self.save()
    
    def add_dialog_message(self, role: str, content: str) -> None:
        """
        Добавляет сообщение в историю диалога и сохраняет в MEMORY.md.
        
        Args:
            role: 'user' или 'assistant'
            content: текст сообщения
        """
        if not content or not content.strip():
            return
        
        self.last_dialog_messages.append({
            'role': role,
            'content': content.strip()
        })
        
        # Ограничиваем количество сообщений
        if len(self.last_dialog_messages) > MAX_DIALOG_MESSAGES:
            self.last_dialog_messages = self.last_dialog_messages[-MAX_DIALOG_MESSAGES:]
        
        self.save()
    
    def get_last_dialog(self) -> List[Dict[str, str]]:
        """Возвращает последние сообщения диалога."""
        return self.last_dialog_messages[-MAX_DIALOG_MESSAGES:]
    
    def get_context_for_prompt(self) -> str:
        """
        Возвращает контекст для добавления в system prompt.
        
        ВАЖНО: Возвращает НЕ БОЛЕЕ MAX_CONTEXT_LENGTH символов
        для обеспечения быстродействия на слабом железе.
        """
        parts = []
        current_length = 0
        
        # Приоритет 1: Имя пользователя (всегда важно)
        if name := self.profile.get("имя"):
            line = f"Пользователя зовут {name}."
            parts.append(line)
            current_length += len(line)
        
        # Приоритет 2: Ключевые поля профиля
        priority_keys = ["город", "работа", "возраст"]
        for key in priority_keys:
            if current_length >= MAX_CONTEXT_LENGTH:
                break
            if value := self.profile.get(key):
                line = f"{key.capitalize()}: {value}."
                if current_length + len(line) <= MAX_CONTEXT_LENGTH:
                    parts.append(line)
                    current_length += len(line)
        
        # Приоритет 3: Последние факты (не более 3)
        if current_length < MAX_CONTEXT_LENGTH and self.facts:
            for fact in self.facts[-3:]:
                if current_length >= MAX_CONTEXT_LENGTH:
                    break
                if current_length + len(fact) + 2 <= MAX_CONTEXT_LENGTH:
                    parts.append(fact)
                    current_length += len(fact) + 2
        
        # Приоритет 4: Краткое содержание последнего диалога
        if (current_length < MAX_CONTEXT_LENGTH and 
            self.last_session_summary and 
            'нет данных' not in self.last_session_summary.lower()):
            remaining = MAX_CONTEXT_LENGTH - current_length
            if remaining > 50:
                summary_short = self.last_session_summary[:remaining - 20]
                parts.append(f"Ранее: {summary_short}")
        
        return ' '.join(parts) if parts else ""
    
    def get_all_info(self) -> str:
        """
        Возвращает всю информацию о пользователе для команды
        'что ты знаешь обо мне'.
        """
        parts = []
        
        if self.profile:
            for key, value in self.profile.items():
                parts.append(f"{key.capitalize()}: {value}")
        
        if self.facts:
            parts.append("\nФакты:")
            for fact in self.facts:
                parts.append(f"- {fact}")
        
        if not parts:
            return "Я пока ничего не знаю о вас. Скажите 'запомни' с информацией."
        
        return ". ".join(parts) if len(parts) <= 5 else "\n".join(parts)
