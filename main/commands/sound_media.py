import re
import ctypes
from typing import Optional

# VK codes for media keys
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

def _press_media_key(vk_code: int) -> None:
    try:
        user32 = ctypes.windll.user32
        # KEYEVENTF_EXTENDEDKEY = 0x0001
        # KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(vk_code, 0, 0x0001, 0)
        user32.keybd_event(vk_code, 0, 0x0001 | 0x0002, 0)
    except Exception as e:
        print(f"[SOUND_MEDIA] Ошибка нажатия медиа-клавиши {vk_code}: {e}")

def execute_sound_media_command(text: str) -> Optional[str]:
    lower = text.lower()
    
    # Плеер пауза / плей
    play_pause_patterns = [
        r"\b(стоп|продолжить)\s*музык[ау]\b",
        r"\bмузыка\s*(стоп|пауза)\b",
        r"\bпауз[ау]\s*музык[ау]?\b",
        r"\bпауз[ау]\b",
        r"\bпродолжи\b",
        r"\bиграй\b",
        r"\bвключи\s*музыку\b",
        r"\bвыключи\s*музыку\b",
        r"\bверни\s*музыку\b",
        r"\bпл[еэ]й\b",
    ]
    
    if any(re.search(p, lower) for p in play_pause_patterns):
        _press_media_key(VK_MEDIA_PLAY_PAUSE)
        return ""
        
    next_track_patterns = [
        r"\b(дальше\s*трек|следующий\s*трек|следующая\s*песня)\b",
        r"\bпереключи\s*трек\b",
        r"\bдальше\b",
        r"\bвключи\s*следующ\w+\b",
    ]
    
    if any(re.search(p, lower) for p in next_track_patterns):
        _press_media_key(VK_MEDIA_NEXT_TRACK)
        return ""
        
    prev_track_patterns = [
        r"\b(предыдущий\s*трек|прошлый\s*трек|предыдущая\s*песня)\b",
        r"\bверни\s*песню\b",
        r"\bвключи\s*предыдущ\w+\b",
    ]
    
    # "назад" может быть опасным словом-триггером (например, для браузера), 
    # но "назад трек/песню" более стабильно
    if any(re.search(p, lower) for p in prev_track_patterns) or re.search(r"\bназад\b", lower):
        _press_media_key(VK_MEDIA_PREV_TRACK)
        return ""

    return None
