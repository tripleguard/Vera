# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec-файл для сборки vera-backend.exe

Использование:
    pyinstaller vera-backend.spec
"""

import os

block_cipher = None

PROJECT_ROOT = os.path.abspath('.')

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
    'psutil',

    # Windows notifications
    'win11toast',

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

]

# ── Файлы данных ──
# Шаблоны данных, которые копируются при первом запуске
datas = [
    # Шаблоны конфигурации/данных
    (os.path.join('data', 'CORE.md'), os.path.join('data')),
    (os.path.join('data', 'IDENTITY.md'), os.path.join('data')),
    (os.path.join('data', 'SOUL.md'), os.path.join('data')),
    (os.path.join('data', 'TOOLS.md'), os.path.join('data')),
    (os.path.join('data', 'USER.md'), os.path.join('data')),
    (os.path.join('data', 'memory.json'), os.path.join('data')),
    (os.path.join('data', 'config.json'), os.path.join('data')),
    (os.path.join('data', 'heartbeat_tasks.json'), os.path.join('data')),
    (os.path.join('data', 'reminders.json'), os.path.join('data')),
    (os.path.join('skills', 'presentations', 'SKILL.md'), os.path.join('skills', 'presentations')),
    (os.path.join('skills', 'documents', 'SKILL.md'), os.path.join('skills', 'documents')),
    # Звуковые файлы
    ('timer.mp3', '.'),
    # Иконка
    ('vera.ico', '.'),
]

# ── Бинарники ──
binaries = []

a = Analysis(
    ['server.py'],
    pathex=[PROJECT_ROOT],
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
