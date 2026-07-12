const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage, dialog, shell, clipboard } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const crypto = require('crypto');

let widgetWindow;
let chatWindow;
let pythonProcess = null;
let terminalProcess = null;
let terminalWorkingDirectory = null;
let tray = null;

const apiToken = crypto.randomBytes(32).toString('hex');


let isQuitting = false;
let backendRestartTimer = null;
let backendRestartAttempts = 0;
let backendStartedAt = 0;
let lastNetworkIssueAt = 0;
let isManualBackendRestart = false;
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

function broadcastTheme(themeId, excludeSender = null) {
    const windows = [chatWindow, widgetWindow];
    for (const win of windows) {
        if (!win || win.isDestroyed()) {
            continue;
        }
        if (excludeSender && win.webContents === excludeSender) {
            continue;
        }
        win.webContents.send('theme-changed', themeId);
    }
}

function getChatBackgroundColor(themeId) {
    const colors = {
        obsidian: '#171b22',
        daylight: '#f5f5f7',
        terminal: '#07100b',
        sakura: '#fff5f8',
        graphite: '#1c2027',
        aurora: '#08151a',
    };
    return colors[themeId] || colors.obsidian;
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

function sendTerminalEvent(channel, payload) {
    if (chatWindow && !chatWindow.isDestroyed()) {
        chatWindow.webContents.send(channel, payload);
    }
}

function stopTerminal() {
    if (!terminalProcess) {
        return;
    }
    const processToStop = terminalProcess;
    terminalProcess = null;
    terminalWorkingDirectory = null;
    if (processToStop.pid) {
        killProcessTree(processToStop.pid);
    }
}

function getTerminalRootDirectory() {
    const systemDrive = String(process.env.SystemDrive || '').trim();
    const candidates = [
        systemDrive ? path.parse(`${systemDrive}\\`).root : '',
        path.parse(process.execPath).root,
        'C:\\',
    ];
    return candidates.find(candidate => (
        candidate
        && fs.existsSync(candidate)
        && fs.statSync(candidate).isDirectory()
    )) || app.getPath('home');
}

function startTerminal() {
    if (terminalProcess && !terminalProcess.killed) {
        return { running: true, cwd: terminalWorkingDirectory };
    }

    const terminalCwd = getTerminalRootDirectory();
    const command = process.env.ComSpec || 'cmd.exe';

    terminalProcess = spawn(command, ['/D', '/Q', '/K', 'chcp 65001>nul'], {
        cwd: terminalCwd,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
    });
    terminalWorkingDirectory = terminalCwd;

    terminalProcess.stdout.setEncoding('utf8');
    terminalProcess.stderr.setEncoding('utf8');
    terminalProcess.stdout.on('data', data => sendTerminalEvent('terminal-output', String(data)));
    terminalProcess.stderr.on('data', data => sendTerminalEvent('terminal-output', String(data)));
    terminalProcess.on('error', error => {
        sendTerminalEvent('terminal-output', `\r\n[Terminal error] ${error.message}\r\n`);
    });
    terminalProcess.on('close', code => {
        terminalProcess = null;
        terminalWorkingDirectory = null;
        sendTerminalEvent('terminal-exit', { code });
    });

    return { running: true, cwd: terminalCwd };
}

function restartPythonBackendNow() {
    backendRestartAttempts = 0;
    isManualBackendRestart = true;
    stopPythonBackend();
    setTimeout(() => {
        isManualBackendRestart = false;
        if (!isQuitting) {
            startPythonBackend();
        }
    }, 600);
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

    pythonProcess.stdout.setEncoding('utf8');
    pythonProcess.stderr.setEncoding('utf8');
    pythonProcess.stdout.on('data', (data) => console.log(`[Python]: ${data}`));
    pythonProcess.stderr.on('data', (stderrText) => {
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
        if (isManualBackendRestart) {
            return;
        }
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
        backgroundColor: '#00000000',
        frame: false,
        hasShadow: false,
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable: false,
        icon: iconPath,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: true,
        },
    });

    chatWindow = new BrowserWindow({
        width: 1280,
        height: 760,
        minWidth: 980,
        minHeight: 640,
        show: false,
        frame: false,
        transparent: false,
        backgroundColor: getChatBackgroundColor('obsidian'),
        icon: iconPath,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: true,
        },
    });

    chatWindow.center();

    const sendWindowState = () => {
        setTimeout(() => {
            if (chatWindow && !chatWindow.isDestroyed()) {
                chatWindow.webContents.send('window-state-changed', {
                    isMaximized: chatWindow.isMaximized(),
                    isFullScreen: chatWindow.isFullScreen()
                });
            }
        }, 100);
    };

    chatWindow.on('maximize', sendWindowState);
    chatWindow.on('unmaximize', sendWindowState);
    chatWindow.on('enter-full-screen', sendWindowState);
    chatWindow.on('leave-full-screen', sendWindowState);
    chatWindow.webContents.on('did-finish-load', sendWindowState);
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
        widgetWindow.loadURL('http://127.0.0.1:5173/#/widget');
        chatWindow.loadURL('http://127.0.0.1:5173/#/chat');
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

        ipcMain.on('get-api-token-sync', (event) => {
            event.returnValue = apiToken;
        });

        ipcMain.handle('workspace-select-directory', async () => {
            const result = await dialog.showOpenDialog(chatWindow, {
                title: 'Выберите рабочую папку',
                properties: ['openDirectory'],
            });
            if (result.canceled || result.filePaths.length === 0) {
                return null;
            }
            return result.filePaths[0];
        });

        ipcMain.handle('workspace-list-directory', async (_event, directoryPath) => {
            if (typeof directoryPath !== 'string' || !fs.existsSync(directoryPath)) {
                throw new Error('Directory does not exist');
            }
            const stats = await fs.promises.stat(directoryPath);
            if (!stats.isDirectory()) {
                throw new Error('Path is not a directory');
            }
            const entries = await fs.promises.readdir(directoryPath, { withFileTypes: true });
            const items = await Promise.all(entries.map(async entry => {
                const entryPath = path.join(directoryPath, entry.name);
                let size = 0;
                try {
                    if (entry.isFile()) {
                        size = (await fs.promises.stat(entryPath)).size;
                    }
                } catch {
                    // The entry may disappear while the directory is being read.
                }
                return {
                    name: entry.name,
                    path: entryPath,
                    isDirectory: entry.isDirectory(),
                    size,
                };
            }));
            return items.sort((left, right) => {
                if (left.isDirectory !== right.isDirectory) {
                    return left.isDirectory ? -1 : 1;
                }
                return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
            });
        });

        ipcMain.handle('workspace-read-file', async (_event, filePath) => {
            if (typeof filePath !== 'string' || !fs.existsSync(filePath)) {
                throw new Error('File does not exist');
            }
            const stats = await fs.promises.stat(filePath);
            if (!stats.isFile()) {
                throw new Error('Path is not a file');
            }
            const data = await fs.promises.readFile(filePath);
            return {
                name: path.basename(filePath),
                size: stats.size,
                data,
            };
        });

        ipcMain.handle('workspace-open-file', async (_event, filePath) => {
            if (typeof filePath !== 'string' || !fs.existsSync(filePath)) {
                throw new Error('File does not exist');
            }
            const errorMessage = await shell.openPath(filePath);
            if (errorMessage) {
                throw new Error(errorMessage);
            }
            return true;
        });

        ipcMain.handle('open-external-url', async (_event, url) => {
            if (typeof url !== 'string') {
                throw new Error('Invalid URL');
            }
            const parsedUrl = new URL(url);
            if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
                throw new Error('Unsupported URL protocol');
            }
            await shell.openExternal(parsedUrl.toString());
        });

        ipcMain.handle('clipboard-write-image', async (_event, imageSource) => {
            if (typeof imageSource !== 'string' || !imageSource.trim()) {
                throw new Error('Invalid image source');
            }
            if (!imageSource.startsWith('data:image/')) {
                throw new Error('Unsupported image source');
            }
            const image = nativeImage.createFromDataURL(imageSource);
            if (image.isEmpty()) {
                throw new Error('Image is empty');
            }
            clipboard.writeImage(image);
            return true;
        });

        ipcMain.handle('workspace-reveal-item', (_event, itemPath) => {
            if (typeof itemPath !== 'string') {
                throw new Error('Path does not exist');
            }
            let resolvedPath = itemPath.trim().replace(/\s+\([^)]*\)\s*$/, '');
            if (!fs.existsSync(resolvedPath)) {
                const projectsCandidate = path.join(
                    app.getPath('documents'),
                    'Vera',
                    'Projects',
                    path.basename(resolvedPath),
                );
                if (fs.existsSync(projectsCandidate)) {
                    resolvedPath = projectsCandidate;
                }
            }
            if (!fs.existsSync(resolvedPath)) {
                throw new Error('Path does not exist');
            }
            shell.showItemInFolder(resolvedPath);
            return true;
        });

        ipcMain.handle('projects-list', async () => {
            const veraDocumentsPath = path.join(app.getPath('documents'), 'Vera');
            const projectsPath = path.join(veraDocumentsPath, 'Projects');
            await fs.promises.mkdir(projectsPath, { recursive: true });
            const legacyEntries = await fs.promises.readdir(veraDocumentsPath, { withFileTypes: true });
            for (const entry of legacyEntries) {
                if (!entry.isFile() || !entry.name.toLowerCase().endsWith('.pptx')) continue;
                const sourcePath = path.join(veraDocumentsPath, entry.name);
                const targetPath = path.join(projectsPath, entry.name);
                if (!fs.existsSync(targetPath)) {
                    await fs.promises.rename(sourcePath, targetPath);
                }
            }
            const entries = await fs.promises.readdir(projectsPath, { withFileTypes: true });
            const projects = await Promise.all(entries
                .filter(entry => entry.isFile() && entry.name.toLowerCase().endsWith('.pptx'))
                .map(async entry => {
                    const filePath = path.join(projectsPath, entry.name);
                    const stats = await fs.promises.stat(filePath);
                    return {
                        name: entry.name,
                        path: filePath,
                        size: stats.size,
                        updatedAt: stats.mtimeMs,
                    };
                }));
            return projects.sort((left, right) => right.updatedAt - left.updatedAt);
        });

        ipcMain.handle('projects-trash', async (_event, projectPath) => {
            if (typeof projectPath !== 'string' || !projectPath.trim()) {
                throw new Error('Invalid project path');
            }
            const projectsPath = path.resolve(app.getPath('documents'), 'Vera', 'Projects');
            const resolvedPath = path.resolve(projectPath);
            if (path.dirname(resolvedPath) !== projectsPath) {
                throw new Error('File is outside the projects directory');
            }
            const stats = await fs.promises.stat(resolvedPath);
            if (!stats.isFile() || path.extname(resolvedPath).toLowerCase() !== '.pptx') {
                throw new Error('Project file does not exist');
            }
            await shell.trashItem(resolvedPath);
            return true;
        });

        ipcMain.handle('terminal-start', () => startTerminal());
        ipcMain.on('terminal-input', (_event, input) => {
            if (!terminalProcess || terminalProcess.killed || typeof input !== 'string') {
                return;
            }
            terminalProcess.stdin.write(input);
        });
        ipcMain.on('terminal-stop', stopTerminal);

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

        ipcMain.on('minimize-chat', () => {
            if (chatWindow && !chatWindow.isDestroyed()) {
                chatWindow.minimize();
            }
        });

        ipcMain.on('focus-chat', () => {
            focusChatWindow();
        });

        ipcMain.on('toggle-chat-fullscreen', () => {
            if (chatWindow && !chatWindow.isDestroyed()) {
                if (chatWindow.isFullScreen()) {
                    chatWindow.setFullScreen(false);
                } else if (chatWindow.isMaximized()) {
                    chatWindow.unmaximize();
                } else {
                    chatWindow.setFullScreen(true);
                }
            }
        });

        ipcMain.on('quit-app', () => {
            isQuitting = true;
            stopPythonBackend();
            app.quit();
        });

        ipcMain.on('restart-app', () => {
            if (!app.isPackaged) {
                restartPythonBackendNow();
                setTimeout(() => {
                    if (chatWindow && !chatWindow.isDestroyed()) {
                        chatWindow.webContents.reloadIgnoringCache();
                    }
                    if (widgetWindow && !widgetWindow.isDestroyed()) {
                        widgetWindow.webContents.reloadIgnoringCache();
                    }
                }, 900);
                return;
            }

            isQuitting = true;
            stopPythonBackend();
            app.relaunch();
            app.exit(0);
        });

        ipcMain.on('theme-updated', (event, themeId) => {
            if (chatWindow && !chatWindow.isDestroyed()) {
                chatWindow.setBackgroundColor(getChatBackgroundColor(themeId));
            }
            broadcastTheme(themeId, event.sender);
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
    stopTerminal();
    stopPythonBackend();
});
