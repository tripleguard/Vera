@echo off
setlocal EnableDelayedExpansion

echo ============================================
echo   Vera Build System
echo ============================================
echo.

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

REM == 1. Check environment ==
echo [1/4] Checking environment...

set "VENV_DIR=%PROJECT_ROOT%venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    set "VENV_DIR=%PROJECT_ROOT%.venv"
)
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] Python venv not found! Create it first: python -m venv venv
    exit /b 1
)
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"

if not exist "%VENV_PYINSTALLER%" (
    echo [ERROR] PyInstaller not found in venv. Install: %VENV_PYTHON% -m pip install pyinstaller
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found.
    exit /b 1
)

echo [OK] Environment ready.

REM == 2. Build Python backend ==
echo.
echo [2/4] Building Python backend (PyInstaller)...

if exist "dist\vera-backend" (
    echo Cleaning previous build...
    rmdir /s /q "dist\vera-backend"
)

"%VENV_PYINSTALLER%" vera-backend.spec --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    exit /b 1
)

echo [OK] Backend built: dist\vera-backend\vera-backend.exe

REM == 3. Build Electron UI ==
echo.
echo [3/4] Building Electron UI...

cd /d "%PROJECT_ROOT%ui"

if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed!
        exit /b 1
    )
)

echo Building renderer (Vite)...
call npm run build:renderer
if errorlevel 1 (
    echo [ERROR] Vite build failed!
    exit /b 1
)

echo Building Electron app...
set CSC_IDENTITY_AUTO_DISCOVERY=false
call npx electron-builder --win dir
if errorlevel 1 (
    echo [ERROR] Electron-builder failed!
    exit /b 1
)

echo [OK] UI built: ui\dist-electron\win-unpacked\

cd /d "%PROJECT_ROOT%"

REM == 4. Prepare staging directory ==
echo.
echo [4/4] Preparing staging directory...

set "STAGING=%PROJECT_ROOT%build\staging"

if exist "%STAGING%" rmdir /s /q "%STAGING%"
mkdir "%STAGING%"

REM Copy Electron UI
echo Copying Electron UI...
xcopy /e /i /q "%PROJECT_ROOT%ui\dist-electron\win-unpacked\*" "%STAGING%\" >nul

REM Copy backend into resources\backend
echo Copying backend...
mkdir "%STAGING%\resources\backend" 2>nul
xcopy /e /i /q "%PROJECT_ROOT%dist\vera-backend\*" "%STAGING%\resources\backend\" >nul

REM Copy icon
copy /y "%PROJECT_ROOT%vera.ico" "%STAGING%\vera.ico" >nul
copy /y "%PROJECT_ROOT%vera.ico" "%STAGING%\resources\backend\vera.ico" >nul

REM Copy Sherpa-ONNX STT model
set "STT_MODEL=sherpa-onnx-streaming-zipformer-small-ru-vosk-2025-08-16"
if exist "%PROJECT_ROOT%%STT_MODEL%" (
    echo Copying Sherpa-ONNX STT model...
    xcopy /e /i /q "%PROJECT_ROOT%%STT_MODEL%" "%STAGING%\resources\backend\%STT_MODEL%\" >nul
) else (
    echo [WARN] Sherpa-ONNX model not found! STT will not work.
)

REM Prepare Supertonic as a separate installer component (not part of main staging)
set "SUPERTONIC_SOURCE=%USERPROFILE%\.cache\supertonic3"
set "SUPERTONIC_STAGING=%PROJECT_ROOT%build\supertonic3"
if exist "%SUPERTONIC_STAGING%" rmdir /s /q "%SUPERTONIC_STAGING%"
if not exist "%SUPERTONIC_SOURCE%\config.json" (
    echo [ERROR] Supertonic cache not found: %SUPERTONIC_SOURCE%
    echo [ERROR] Initialize Supertonic once before building the installer.
    exit /b 1
)
if not exist "%SUPERTONIC_SOURCE%\onnx" (
    echo [ERROR] Supertonic ONNX models are missing: %SUPERTONIC_SOURCE%\onnx
    exit /b 1
)
if not exist "%SUPERTONIC_SOURCE%\voice_styles" (
    echo [ERROR] Supertonic voice styles are missing: %SUPERTONIC_SOURCE%\voice_styles
    exit /b 1
)
for %%F in (duration_predictor.onnx text_encoder.onnx vector_estimator.onnx vocoder.onnx tts.json unicode_indexer.json) do (
    if not exist "%SUPERTONIC_SOURCE%\onnx\%%F" (
        echo [ERROR] Required Supertonic file is missing: %SUPERTONIC_SOURCE%\onnx\%%F
        exit /b 1
    )
)
if not exist "%SUPERTONIC_SOURCE%\voice_styles\F2.json" (
    echo [ERROR] Vera voice style is missing: %SUPERTONIC_SOURCE%\voice_styles\F2.json
    exit /b 1
)
echo Preparing separate Supertonic installer component...
mkdir "%SUPERTONIC_STAGING%" 2>nul
copy /y "%SUPERTONIC_SOURCE%\config.json" "%SUPERTONIC_STAGING%\config.json" >nul
copy /y "%SUPERTONIC_SOURCE%\LICENSE" "%SUPERTONIC_STAGING%\LICENSE" >nul 2>nul
xcopy /e /i /q "%SUPERTONIC_SOURCE%\onnx" "%SUPERTONIC_STAGING%\onnx\" >nul
xcopy /e /i /q "%SUPERTONIC_SOURCE%\voice_styles" "%SUPERTONIC_STAGING%\voice_styles\" >nul

REM Cleanup problematic DLLs that cause crashes in production
if exist "%STAGING%\vulkan-1.dll" (
    echo [INFO] Removing bundled vulkan-1.dll to ensure system-wide driver usage...
    del /f /q "%STAGING%\vulkan-1.dll"
)
if exist "%STAGING%\vk_swiftshader.dll" (
    echo [INFO] Removing bundled vk_swiftshader.dll...
    del /f /q "%STAGING%\vk_swiftshader.dll"
)

REM Copy download scripts
copy /y "%PROJECT_ROOT%download_llama_server.py" "%STAGING%\download_llama_server.py" >nul 2>nul
copy /y "%PROJECT_ROOT%download_model.py" "%STAGING%\download_model.py" >nul 2>nul

echo.
echo ============================================
echo   Build complete!
echo ============================================
echo.
echo   Staging dir: %STAGING%
echo   Supertonic component: %SUPERTONIC_STAGING%
echo.
echo   Next step: compile vera.iss with Inno Setup
echo   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" vera.iss
