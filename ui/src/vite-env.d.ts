/// <reference types="vite/client" />

type VeraDesktopListener = (event: unknown, ...args: any[]) => void;

interface VeraDesktopApi {
    getApiToken(): string;
    send(channel: string, ...args: any[]): void;
    invoke<T = unknown>(channel: string, ...args: any[]): Promise<T>;
    on(channel: string, listener: VeraDesktopListener): void;
    removeListener(channel: string, listener: VeraDesktopListener): void;
    openExternal(url: string): Promise<void>;
}

interface Window {
    veraDesktop?: VeraDesktopApi;
}
