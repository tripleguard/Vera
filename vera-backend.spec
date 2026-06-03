# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec-файл для сборки vera-backend.exe

Использование:
    pyinstaller vera-backend.spec
"""

import os
import sys
from pathlib import Path

block_cipher = None

PROJECT_ROOT = os.path.abspath('.')

# Find the venv site-packages for package resolution
VENV_DIRS = [
    os.path.join(PROJECT_ROOT, 'venv'),
    os.path.join(PROJECT_ROOT, '.venv'),
]
VENV_SITE_PACKAGES = None
for vdir in VENV_DIRS:
    sp = os.path.join(vdir, 'Lib', 'site-packages')
    if os.path.isdir(sp):
        VENV_SITE_PACKAGES = sp
        break

# ── Скрытые импорты ──
# PyInstaller не всегда находит динамические импорты —
# перечисляем всё, что используется в проекте.
hidden_imports = [
    # FastAPI / Uvicorn
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'starlette',
    'starlette.routing',
    'starlette.middleware',
    'starlette.middleware.cors',
    'starlette.responses',
    'starlette.websockets',
    'anyio._backends._asyncio',
    'multipart',
    'python_multipart',

    # Sherpa-ONNX (распознавание речи)
    'sherpa_onnx',

    # TTS
    'supertonic',

    # Audio
    'sounddevice',
    '_sounddevice_data',

    # Windows COM / System
    'comtypes',
    'comtypes.client',
    'comtypes.stream',
    'pycaw',
    'pycaw.pycaw',
    'ctypes',
    'win32api',
    'win32con',
    'win32gui',
    'win32process',
    'win32com',
    'win32com.client',
    'win32com.shell',
    'win32com.shell.shell',
    'pythoncom',
    'pywintypes',
    'wmi',
    'psutil',

    # Windows notifications
    'win11toast',
    'winrt',

    # Screen brightness
    'screen_brightness_control',

    # Image processing
    'PIL',
    'PIL.Image',

    # Document processing
    'docx',
    'docx.oxml',
    'docx.oxml.ns',
    'pypdf',
    'pptx',
    'pptx.util',
    'openpyxl',

    # Telegram
    'telethon',
    'telethon.sync',

    # Web
    'requests',
    'bs4',

    # Проектные модули
    'main',
    'main.agent',
    'main.config_manager',
    'main.llm_server',
    'main.tool_definitions',
    'main.prompt_builder',
    'main.executor',
    'main.planner',
    'main.reflector',
    'main.lang_ru',
    'main.file_indexer',
    'main.app_indexer',
    'main.result_patterns',
    'main.safety',
    'main.audit',
    'main.utils',
    'main.utils.fuzzy',
    'main.commands',
    'main.commands.app_control',
    'main.commands.file_operations',
    'main.commands.heartbeat_commands',
    'main.commands.power_manager',
    'main.commands.recyclebin_commands',
    'main.commands.scheduler_base',
    'main.commands.sound_media',
    'main.commands.system_control',
    'main.commands.time_commands',
    'main.commands.web_commands',
    'main.commands.window_manager',
    'main.tools',
    'main.tools.code_interpreter',
    'main.tools.document_generator',
    'main.tools.presentation_generator',
    'main.tools.read_document',
    'main.tools.telegram',
    'main.tools.telegram_mode',
    'web',
    'web.web_search',
    'web.web_utils',
    'web.weather',
    'web.currency',
    'user',
    'user.memory',
    'user.memory_extractor',
    'user.json_storage',
    'user.notifications',
]

# ── Файлы данных ──
# Шаблоны данных, которые копируются при первом запуске
datas = [
    # Шаблоны конфигурации/данных
    (os.path.join('data', 'IDENTITY.md'), os.path.join('data')),
    (os.path.join('data', 'SOUL.md'), os.path.join('data')),
    (os.path.join('data', 'TOOLS.md'), os.path.join('data')),
    (os.path.join('data', 'USER.md'), os.path.join('data')),
    (os.path.join('data', 'MEMORY.md'), os.path.join('data')),
    (os.path.join('data', 'config.json'), os.path.join('data')),
    (os.path.join('data', 'heartbeat_tasks.json'), os.path.join('data')),
    (os.path.join('data', 'reminders.json'), os.path.join('data')),
    (os.path.join('data', 'scheduled_apps.json'), os.path.join('data')),
    # Звуковые файлы
    ('timer.mp3', '.'),
    # Иконка
    ('vera.ico', '.'),
]

# ── Бинарники ──
binaries = []

a = Analysis(
    ['server.py'],
    pathex=[p for p in [PROJECT_ROOT, VENV_SITE_PACKAGES] if p],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy.distutils',
        'test',
        'unittest',
        'xmlrpc',
        'lib2to3',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir mode
    name='vera-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # нужна консоль для stdout/stderr логов
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='vera.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='vera-backend',
)
