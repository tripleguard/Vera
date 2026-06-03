const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const crypto = require('crypto');

let widgetWindow;
let chatWindow;
let pythonProcess = null;
let tray = null;

const apiToken = crypto.randomBytes(32).toString('hex');


let isQuitting = false;
let backendRestartTimer = null;
let backendRestartAttempts = 0;
let backendStartedAt = 0;
let lastNetworkIssueAt = 0;
const MAX_BACKEND_RESTARTS = 5;
const NETWORK_ISSUE_COOLDOWN_MS = 30000;

function getDevRootPath() {
    return path.join(__dirname, '..');
}

function getPackagedBackendRoot() {
    return path.join(process.resourcesPath, 'backend');
}

function getBackendRootPath() {
    return app.isPackaged ? getPackagedBackendRoot() : getDevRootPath();
}

function broadcastBackendStatus(payload) {
    const windows = [chatWindow, widgetWindow];
    for (const win of windows) {
        if (win && !win.isDestroyed()) {
            win.webContents.send('backend-status', payload);
        }
    }
}


function killProcessTree(pid) {
    if (!pid) {
        return;
    }

    if (process.platform === 'win32') {
        try {
            execSync(`taskkill /pid ${pid} /T /F`);
        } catch (e) {
            console.error('Не удалось завершить дерево процессов:', e);
        }
    } else {
        try {
            process.kill(-pid);
        } catch (e) {
            console.error('Не удалось завершить дерево процессов:', e);
        }
    }
}

function focusChatWindow() {
    if (!chatWindow) {
        return;
    }
    if (!chatWindow.isVisible()) {
        chatWindow.show();
    }
    chatWindow.focus();
}

function stopPythonBackend() {
    if (backendRestartTimer) {
        clearTimeout(backendRestartTimer);
        backendRestartTimer = null;
    }

    if (pythonProcess && pythonProcess.pid) {
        killProcessTree(pythonProcess.pid);
    }
    pythonProcess = null;
}

function scheduleBackendRestart() {
    if (isQuitting || backendRestartTimer) {
        return;
    }

    if (backendRestartAttempts >= MAX_BACKEND_RESTARTS) {
        console.error(`[BACKEND] Достигнут лимит перезапусков (${MAX_BACKEND_RESTARTS}).`);
        broadcastBackendStatus({
            type: 'restart_failed',
            maxAttempts: MAX_BACKEND_RESTARTS,
        });
        return;
    }

    const delayMs = Math.min(15000, 1000 * (2 ** backendRestartAttempts));
    backendRestartAttempts += 1;
    console.error(`[BACKEND] Перезапуск через ${delayMs / 1000} сек (попытка ${backendRestartAttempts}/${MAX_BACKEND_RESTARTS})`);
    broadcastBackendStatus({
        type: 'restarting',
        delayMs,
        attempt: backendRestartAttempts,
        maxAttempts: MAX_BACKEND_RESTARTS,
    });

    backendRestartTimer = setTimeout(() => {
        backendRestartTimer = null;
        startPythonBackend();
    }, delayMs);
}

function startPythonBackend() {
    if (pythonProcess) {
        return;
    }

    console.log('[BACKEND] Запускаю Python backend...');
    broadcastBackendStatus({ type: 'starting' });
    const devRootPath = getDevRootPath();
    const backendRootPath = getBackendRootPath();

    let command = '';
    let args = [];
    let cwd = backendRootPath;

    if (app.isPackaged) {
        const backendExePath = path.join(backendRootPath, 'vera-backend.exe');
        if (!fs.existsSync(backendExePath)) {
            const errorText = `[BACKEND] Не найден backend exe: ${backendExePath}`;
            console.error(errorText);
            broadcastBackendStatus({
                type: 'start_error',
                error: errorText,
            });
            scheduleBackendRestart();
            return;
        }
        command = backendExePath;
        args = [];
        cwd = backendRootPath;
    } else {
        const venvPythonPath = path.join(devRootPath, '.venv', 'Scripts', 'python.exe');
        command = fs.existsSync(venvPythonPath) ? venvPythonPath : 'python';
        args = ['-u', 'server.py'];
        cwd = devRootPath;
    }

    console.log(`[BACKEND] Используемая команда backend: ${command}`);
    backendStartedAt = Date.now();
    pythonProcess = spawn(command, args, {
        cwd,
        env: {
            ...process.env,
            PYTHONIOENCODING: 'utf-8',
            VERA_INSTALL_ROOT: backendRootPath,
            VERA_API_TOKEN: apiToken,
        },
    });

    pythonProcess.stdout.on('data', (data) => console.log(`[Python]: ${data.toString('utf8')}`));
    pythonProcess.stderr.on('data', (data) => {
        const stderrText = data.toString('utf8');
        console.error(`[Python Err]: ${stderrText}`);

        const normalized = stderrText.toLowerCase();
        const isNetworkIssue = (
            normalized.includes('server closed the connection')
            && (normalized.includes('winerror 121') || normalized.includes(' '))
        ) || normalized.includes('winerror 121');

        if (isNetworkIssue) {
            const now = Date.now();
            if (now - lastNetworkIssueAt >= NETWORK_ISSUE_COOLDOWN_MS) {
                lastNetworkIssueAt = now;
                broadcastBackendStatus({ type: 'network_issue' });
            }
        }
    });

    pythonProcess.on('error', (err) => {
        console.error('[BACKEND] Ошибка запуска процесса Python:', err);
        broadcastBackendStatus({
            type: 'start_error',
            error: err?.message || String(err),
        });
        pythonProcess = null;
        scheduleBackendRestart();
    });

    pythonProcess.on('exit', (code, signal) => {
        const uptimeMs = Date.now() - backendStartedAt;
        console.error(`[BACKEND] Процесс завершился. код=${code} сигнал=${signal || 'нет'}`);
        if (uptimeMs >= 30000) {
            backendRestartAttempts = 0;
        }
        pythonProcess = null;
        if (!isQuitting) {
            scheduleBackendRestart();
        }
    });
}

function createWindows() {
    const { width } = screen.getPrimaryDisplay().workAreaSize;
    const rootPath = getBackendRootPath();
    const iconPath = path.join(rootPath, 'vera.ico');
    const rendererIndexPath = path.join(__dirname, 'dist', 'index.html');

    widgetWindow = new BrowserWindow({
        width: 80,
        height: 80,
        x: width - 100,
        y: 100,
        transparent: true,
        frame: false,
        hasShadow: false,
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable: false,
        icon: iconPath,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false,
        },
    });

    chatWindow = new BrowserWindow({
        width: 800,
        height: 600,
        show: false,
        frame: false,
        transparent: true,
        icon: iconPath,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false,
        },
    });

    chatWindow.center();
    chatWindow.on('close', (e) => {
        if (!isQuitting) {
            isQuitting = true;
            app.quit();
        }
    });

    widgetWindow.on('close', () => {
        if (!isQuitting) {
            isQuitting = true;
            app.quit();
        }
    });

    if (!app.isPackaged) {
        widgetWindow.loadURL('http://localhost:5173/#/widget');
        chatWindow.loadURL('http://localhost:5173/#/chat');
    } else {
        widgetWindow.loadFile(rendererIndexPath, { hash: '/widget' });
        chatWindow.loadFile(rendererIndexPath, { hash: '/chat' });
    }
}

function setupTrayIcon() {
    const trayIconPath = path.join(getBackendRootPath(), 'vera.ico');
    let trayIconImage = nativeImage.createFromPath(trayIconPath);

    if (trayIconImage.isEmpty()) {
        console.error(`[TRAY] конка не найдена: ${trayIconPath}. спользую резервную иконку.`);
        trayIconImage = nativeImage.createFromDataURL(
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5X0xQAAAAASUVORK5CYII='
        );
    }

    tray = new Tray(trayIconImage);
    tray.setToolTip('Vera Agent');
    tray.setContextMenu(Menu.buildFromTemplate([
        { label: 'Открыть чат', click: focusChatWindow },
        { type: 'separator' },
        {
            label: 'Выход',
            click: () => {
                isQuitting = true;
                stopPythonBackend();
                app.exit(0);
            },
        },
    ]));

    tray.on('double-click', focusChatWindow);
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
    app.quit();
} else {
    app.on('second-instance', () => {
        if (widgetWindow && !widgetWindow.isVisible()) {
            widgetWindow.show();
        }
        focusChatWindow();
    });

    app.whenReady().then(() => {
        startPythonBackend();
        createWindows();
        setupTrayIcon();

        ipcMain.handle('get-api-token', () => apiToken);
        ipcMain.on('get-api-token-sync', (event) => {
            event.returnValue = apiToken;
        });

        let toggleLock = false;
        ipcMain.on('toggle-chat', () => {
            if (toggleLock || !chatWindow) {
                return;
            }
            toggleLock = true;
            setTimeout(() => { toggleLock = false; }, 400);

            if (chatWindow.isVisible()) {
                chatWindow.hide();
            } else {
                chatWindow.setOpacity(0);
                focusChatWindow();

                let opacity = 0;
                const fadeIn = setInterval(() => {
                    opacity += 0.2;
                    if (opacity >= 1) {
                        opacity = 1;
                        clearInterval(fadeIn);
                    }
                    chatWindow.setOpacity(opacity);
                }, 30);
            }
        });

        ipcMain.on('close-chat', () => {
            if (chatWindow) {
                chatWindow.hide();
            }
        });

        ipcMain.on('restart-app', () => {
            isQuitting = true;
            stopPythonBackend();
            app.relaunch();
            app.exit(0);
        });
    });
}

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('before-quit', () => {
    isQuitting = true;
    stopPythonBackend();
});
