import time

from main.commands import time_commands
from user import notifications


def test_backend_notification_uses_the_previous_win11toast_contract(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "_TOAST_AVAILABLE", True)
    monkeypatch.setattr(
        notifications,
        "win11toast_func",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert notifications.show_reminder_notification("Напоминание", "Проверить почту") is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("Напоминание", "Проверить почту")
    assert kwargs["app_id"] == "Вера - Голосовой ассистент"
    assert callable(kwargs["on_click"])
    assert callable(kwargs["on_dismissed"])


def test_scheduler_creates_exactly_one_backend_toast_per_timer_and_reminder(monkeypatch):
    spoken = []
    toast_calls = []
    original_scheduled = time_commands._scheduled
    original_speak = time_commands._reminder_scheduler._speak_cb
    time_commands._scheduled = [
        time_commands._Reminder(
            time_commands._Reminder.from_timestamp(time.time() - 2),
            "Таймер завершён.",
            is_timer=True,
        ),
        time_commands._Reminder(
            time_commands._Reminder.from_timestamp(time.time() - 2),
            "Проверить почту",
            is_timer=False,
        ),
    ]
    time_commands._reminder_scheduler.set_speak_callback(spoken.append)
    monkeypatch.setattr(time_commands, "_save_reminders", lambda: None)
    monkeypatch.setattr(time_commands, "_start_timer_ring", lambda: None)
    monkeypatch.setattr(
        time_commands,
        "show_reminder_notification",
        lambda title, body: toast_calls.append((title, body)),
    )

    try:
        time_commands._reminder_scheduler._tick()
        time_commands._reminder_scheduler._tick()
    finally:
        time_commands._scheduled = original_scheduled
        time_commands._reminder_scheduler._speak_cb = original_speak

    assert len(spoken) == 2
    assert spoken[0] == "Таймер завершён. Скажите стоп чтобы отключить."
    assert toast_calls == [
        ("⏰ Таймер завершён", "Таймер завершён."),
        ("⏰ Напоминание", "Проверить почту"),
    ]
