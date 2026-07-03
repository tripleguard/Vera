export type SocketHandlers = {
  onOpen?: (ws: WebSocket) => void;
  onMessage?: (event: MessageEvent<string>) => void;
  onClose?: () => void;
  onError?: () => void;
};

export function connectSocketWithReconnect(
  url: string,
  handlers: SocketHandlers,
  reconnectMs: number,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let timer: number | null = null;

  const connect = () => {
    if (closed) return;
    if (timer != null) {
      window.clearTimeout(timer);
      timer = null;
    }
    ws = new WebSocket(url);
    ws.onopen = () => handlers.onOpen?.(ws as WebSocket);
    ws.onmessage = (event) => handlers.onMessage?.(event as MessageEvent<string>);
    ws.onerror = () => handlers.onError?.();
    ws.onclose = () => {
      handlers.onClose?.();
      ws = null;
      if (!closed && timer == null) {
        timer = window.setTimeout(() => {
          timer = null;
          connect();
        }, reconnectMs);
      }
    };
  };

  connect();

  return () => {
    closed = true;
    if (timer != null) {
      window.clearTimeout(timer);
      timer = null;
    }
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.close();
      ws = null;
    }
  };
}
