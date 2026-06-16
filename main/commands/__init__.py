from .app_control import (
    execute_predefined_command,
    execute_app_command,
    execute_browser_command,
    execute_rebuild_index_command,
    execute_coin_flip_command,
)

from .system_control import (
    execute_taskmanager_command,
    execute_volume_command,
    execute_brightness_command,
    execute_screenshot_command,
    execute_ip_command,
    execute_ping_command,
    execute_start_menu_command,
    execute_explorer_command,
)

from .window_manager import (
    execute_window_command,
)

from .file_operations import (
    execute_file_command,
    execute_folder_command,
    find_file,  # Публичная функция для поиска файлов
)

from .web_commands import (
    execute_open_site_command,
    execute_open_sources_command,
    execute_ambiguous_clean_command,
    set_last_search_urls_ref,
)

from .time_commands import (
    execute_time_command,
    execute_date_command,
    execute_reminder_command,
    execute_list_reminders_command,
    set_speak_callback,
    set_ws_callback as set_timer_ws_callback,
    stop_timer_ring,
    is_timer_ringing,
    set_shutdown_event as set_reminder_shutdown_event,
)


from .power_manager import (
    execute_power_command,
)

from .heartbeat_commands import (
    execute_heartbeat_command,
    start_heartbeat_scheduler,
    set_heartbeat_speak_callback,
    set_heartbeat_route_callback,
    set_heartbeat_shutdown_event,
)

from .recyclebin_commands import (
    execute_recyclebin_command,
)

from .sound_media import (
    execute_sound_media_command,
)

from .help_commands import (
    execute_help_command,
)


# set_last_search_urls_ref экспортируется из web_commands
# set_speak_callback экспортируется из time_commands

# Список всех обработчиков команд в порядке приоритета
HANDLERS = (
    # Помощь и список команд (наивысший приоритет)
    execute_help_command,

    # Управление окнами
    execute_window_command,
    
    # Файловые операции
    execute_file_command,
    execute_folder_command,
    
    # Веб-команды
    execute_open_sources_command,
    execute_open_site_command,
    execute_ambiguous_clean_command,
    
    # Корзина
    execute_recyclebin_command,
    
    # Питание (ПЕРЕД приложениями, чтобы "выключи компьютер" не путалось с закрытием приложений)
    execute_power_command,
    
    # Heartbeat задачи
    execute_heartbeat_command,
    

    # Приложения
    execute_predefined_command,
    execute_browser_command,
    execute_rebuild_index_command,
    execute_app_command,
    
    # Система
    execute_sound_media_command,
    execute_start_menu_command,
    execute_explorer_command,
    execute_taskmanager_command,
    execute_volume_command,
    execute_brightness_command,
    execute_screenshot_command,
    execute_ip_command,
    execute_ping_command,
    
    # Время
    execute_time_command,
    execute_date_command,
    execute_reminder_command,
    execute_list_reminders_command,
    
    # Прочее
    execute_coin_flip_command,
)

__all__ = [
    'HANDLERS',
    'set_last_search_urls_ref',
    'set_speak_callback',
    'set_timer_ws_callback',
    'stop_timer_ring',
    'is_timer_ringing',
    'find_file',
    'set_reminder_shutdown_event',
    'start_heartbeat_scheduler',
    'set_heartbeat_speak_callback',
    'set_heartbeat_route_callback',
    'set_heartbeat_shutdown_event',
]
