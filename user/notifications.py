try:
    from win11toast import toast as win11toast_func
    _TOAST_AVAILABLE = True
except ImportError:
    _TOAST_AVAILABLE = False


# Пустые обработчики для подавления вывода win11toast
def _silent_callback(*args, **kwargs):
    """Заглушка для подавления вывода от win11toast."""
    pass


def show_reminder_notification(title: str, message: str, duration: int = 10) -> bool:
    if not _TOAST_AVAILABLE:
        print(f"[NOTIFICATION] win11toast не установлен. Текст: {title} - {message}")
        return False
    
    try:
        # win11toast выводит результат callbacks в консоль
        # Используем заглушки для on_click и on_dismissed
        win11toast_func(
            title,
            message,
            duration='short' if duration <= 5 else 'long',
            app_id='Вера - Голосовой ассистент',
            icon=None,
            on_click=_silent_callback,
            on_dismissed=_silent_callback,
        )
        
        return True
    except Exception as e:
        print(f"[NOTIFICATION] Ошибка показа уведомления: {e}")
        return False

