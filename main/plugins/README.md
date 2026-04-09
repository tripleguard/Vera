# Среда выполнения плагинов Vera (Единый исходный код + EXE)

Эта папка реализует единую архитектуру плагинов, которая работает как в режиме разработки из исходного кода, так и в упакованном режиме EXE.

## Основная идея

Используйте `mcp.runtime = "vera_python"` в `manifest.json`.

- В режиме исходного кода процесс плагина запускается через:
  - `python server.py --plugin-host --plugin-dir <...> --entrypoint <...>`
- В режиме EXE процесс плагина запускается через:
  - `vera_backend.exe --plugin-host --plugin-dir <...> --entrypoint <...>`

Тот же пакет плагина, тот же путь в коде менеджера.

## Пример минимального манифеста

```json
{
  "id": "example.todo",
  "name": "Todo Plugin",
  "version": "1.0.0",
  "compatibility": { "vera": ">=1.0.0" },
  "capabilities": [
    {
      "id": "todo_ops",
      "title": "Todo Operations",
      "intents": ["tasks", "reminders"],
      "tool_names": ["todo_add", "todo_list"]
    }
  ],
  "permissions": {
    "filesystem": { "read": ["${VERA_PLUGIN_DIR}"], "write": ["${VERA_PLUGIN_DIR}/data"] },
    "network": "restricted"
  },
  "mcp": {
    "transport": "stdio",
    "runtime": "vera_python",
    "entrypoint": "plugin_entry.py",
    "env": {
      "PLUGIN_DATA": "${VERA_PLUGIN_DIR}/data"
    }
  },
  "healthcheck": { "type": "stdio_ping" },
  "signature": { "required": false, "signed": false },
  "update_channel": { "channel": "stable" }
}
```

## Контракт точки входа (Entrypoint)

`entrypoint` плагина должен запускаться как отдельный процесс и взаимодействовать через JSON-RPC/MCP по stdio.

Переменные окружения, предоставляемые менеджером:

- `VERA_PLUGIN_DIR`
- `VERA_PLUGIN_ENTRYPOINT`
- `VERA_DATA_DIR`
- `VERA_INSTALL_ROOT`
- `VERA_EXECUTABLE`
- `VERA_SERVER_ENTRY`
- `VERA_IS_FROZEN`

## Устаревший режим (Legacy mode)

`mcp.command + mcp.args` все еще поддерживаются (`runtime_profile = external_command`).

