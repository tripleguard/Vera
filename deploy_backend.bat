@echo off
echo ============================================
echo   Deploying updated vera-backend
echo ============================================
echo.

set "SRC=D:\agent_vera\dist\vera-backend"
set "DST=C:\Program Files\Vera\resources\backend"

echo Stopping Vera processes...
taskkill /IM Vera.exe /F >nul 2>&1
taskkill /IM vera-backend.exe /F >nul 2>&1
taskkill /IM llama-server.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo Removing old _internal...
rmdir /s /q "%DST%\_internal" 2>nul

echo Copying new backend...
copy /y "%SRC%\vera-backend.exe" "%DST%\vera-backend.exe"
xcopy /e /i /q /y "%SRC%\_internal" "%DST%\_internal\"

echo.
echo ============================================
echo   Deployment complete!
echo ============================================
echo.
echo Starting Vera...
start "" "C:\Program Files\Vera\Vera.exe"
timeout /t 3 /nobreak >nul
