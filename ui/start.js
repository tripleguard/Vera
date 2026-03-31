const { spawn } = require('child_process');

// Запустим Electron, удалив переменную окружения, заставляющую его работать как Node
const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

const proc = spawn('node_modules\\.bin\\electron.cmd', ['.'], {
    env,
    stdio: 'inherit',
    shell: true
});

proc.on('close', (code) => {
    process.exit(code);
});
