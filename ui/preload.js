const { contextBridge, ipcRenderer } = require('electron');

const SEND_CHANNELS = new Set([
    'minimize-chat',
    'focus-chat',
    'quit-app',
    'restart-app',
    'terminal-input',
    'terminal-stop',
    'theme-updated',
    'toggle-chat',
    'toggle-chat-fullscreen',
]);

const INVOKE_CHANNELS = new Set([
    'clipboard-write-image',
    'projects-list',
    'projects-trash',
    'terminal-start',
    'workspace-list-directory',
    'workspace-open-file',
    'workspace-read-file',
    'workspace-reveal-item',
    'workspace-select-directory',
]);

const RECEIVE_CHANNELS = new Set([
    'backend-status',
    'terminal-exit',
    'terminal-output',
    'theme-changed',
    'window-state-changed',
]);

const listenerWrappers = new Map();

function assertAllowed(channel, allowedChannels) {
    if (!allowedChannels.has(channel)) {
        throw new Error(`Unsupported IPC channel: ${channel}`);
    }
}

function rememberWrapper(channel, listener, wrapper) {
    let channelListeners = listenerWrappers.get(channel);
    if (!channelListeners) {
        channelListeners = new Map();
        listenerWrappers.set(channel, channelListeners);
    }
    channelListeners.set(listener, wrapper);
}

function forgetWrapper(channel, listener) {
    const channelListeners = listenerWrappers.get(channel);
    const wrapper = channelListeners?.get(listener);
    if (!wrapper) {
        return null;
    }
    channelListeners.delete(listener);
    if (channelListeners.size === 0) {
        listenerWrappers.delete(channel);
    }
    return wrapper;
}

contextBridge.exposeInMainWorld('veraDesktop', {
    getApiToken: () => ipcRenderer.sendSync('get-api-token-sync'),
    send: (channel, ...args) => {
        assertAllowed(channel, SEND_CHANNELS);
        ipcRenderer.send(channel, ...args);
    },
    invoke: (channel, ...args) => {
        assertAllowed(channel, INVOKE_CHANNELS);
        return ipcRenderer.invoke(channel, ...args);
    },
    on: (channel, listener) => {
        assertAllowed(channel, RECEIVE_CHANNELS);
        const wrapper = (event, ...args) => listener(event, ...args);
        rememberWrapper(channel, listener, wrapper);
        ipcRenderer.on(channel, wrapper);
    },
    removeListener: (channel, listener) => {
        assertAllowed(channel, RECEIVE_CHANNELS);
        const wrapper = forgetWrapper(channel, listener);
        if (wrapper) {
            ipcRenderer.removeListener(channel, wrapper);
        }
    },
    openExternal: url => ipcRenderer.invoke('open-external-url', url),
});
