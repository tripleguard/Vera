const http = require('http');
const path = require('path');
const { spawn, execFile } = require('child_process');

const HOST = '127.0.0.1';
const PORT = 5173;
const APP_URL = `http://${HOST}:${PORT}`;
const electronPath = require('electron');

let viteProcess = null;
let electronProcess = null;
let shuttingDown = false;

function requestPage() {
    return new Promise((resolve, reject) => {
        const request = http.get(APP_URL, {
            headers: {
                Accept: 'text/html',
            },
        }, response => {
            let body = '';
            response.setEncoding('utf8');
            response.on('data', chunk => {
                body += chunk;
            });
            response.on('end', () => resolve({
                statusCode: response.statusCode || 0,
                body,
            }));
        });
        request.setTimeout(1000, () => request.destroy(new Error('timeout')));
        request.on('error', reject);
    });
}

async function inspectDevServer() {
    try {
        const response = await requestPage();
        const isVeraDevServer = (
            response.statusCode === 200
            && response.body.includes('/src/main.tsx')
            && response.body.includes('id="root"')
        );
        return { occupied: true, isVeraDevServer };
    } catch {
        return { occupied: false, isVeraDevServer: false };
    }
}

async function waitForVite(timeoutMs = 20000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const status = await inspectDevServer();
        if (status.isVeraDevServer) {
            return;
        }
        if (viteProcess && viteProcess.exitCode !== null) {
            throw new Error(`Vite завершился с кодом ${viteProcess.exitCode}`);
        }
        await new Promise(resolve => setTimeout(resolve, 250));
    }
    throw new Error(`Vite не запустился на ${APP_URL}`);
}

function terminateProcessTree(child) {
    if (!child || !child.pid || child.exitCode !== null) {
        return;
    }
    if (process.platform === 'win32') {
        execFile('taskkill.exe', ['/pid', String(child.pid), '/T', '/F'], () => undefined);
    } else {
        child.kill('SIGTERM');
    }
}

function shutdown(exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    terminateProcessTree(electronProcess);
    terminateProcessTree(viteProcess);
    setTimeout(() => process.exit(exitCode), 300);
}

async function main() {
    const existingServer = await inspectDevServer();
    if (existingServer.occupied && !existingServer.isVeraDevServer) {
        throw new Error(`Порт ${PORT} занят другим приложением`);
    }

    if (existingServer.isVeraDevServer) {
        console.log(`[dev] Используется уже запущенный Vera Vite: ${APP_URL}`);
    } else {
        const viteCli = path.join(__dirname, 'node_modules', 'vite', 'bin', 'vite.js');
        viteProcess = spawn(process.execPath, [viteCli], {
            cwd: __dirname,
            stdio: 'inherit',
            shell: false,
        });
        await waitForVite();
    }

    const env = { ...process.env };
    delete env.ELECTRON_RUN_AS_NODE;
    electronProcess = spawn(electronPath, ['.'], {
        cwd: __dirname,
        env,
        stdio: 'inherit',
        shell: false,
    });
    electronProcess.on('error', error => {
        console.error('[Electron] Ошибка запуска:', error.message);
        shutdown(1);
    });
    electronProcess.on('close', code => shutdown(code ?? 0));
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

main().catch(error => {
    console.error(`[dev] ${error.message}`);
    shutdown(1);
});
