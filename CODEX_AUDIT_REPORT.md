# Vera Agent Code Audit Report

## Summary

Проверены обязательные зоны: `README.md`, `server.py`, `main/agent.py`, `main/tool_router.py`, `main/commands/`, `main/tools/`, `web/`, `ui/src/App.tsx`, `ui/src/services/`, `tests/`, `requirements.txt`, `ui/package.json`.

Сделаны только небольшие безопасные изменения: вынесенная TTS-санитизация подключена к `main/agent.py`, upload filename handling и лимит загрузки усилены, WebSocket broadcast стал устойчивее к мертвым клиентам, HTTP/WebSocket token check выровнен через общий helper, убран `shell=True` из открытия Task Manager, WebSocket token в UI теперь кодируется, reconnect helper очищает таймеры/handlers, а routing guard tests расширены.

До начала правок рабочее дерево уже было грязным: `llama-common.dll`, `ui/src/App.tsx`, `ui/src/index.css`, а также untracked `main/response_sanitizer.py`, `main/upload_utils.py`, `tests/test_response_sanitizer.py`, `tests/test_upload_utils.py`, `CODEX_AUDIT_REPORT.md`. Эти существующие изменения не откатывались; отчет переписан корректной UTF-8 кириллицей.

## Repository map

* `server.py` - FastAPI app, auth middleware, WebSocket endpoint, upload API, session and memory API.
* `main/agent.py` - главный runtime: LLM lifecycle, STT/TTS, routing, queues, sessions, memory, Telegram mode, heartbeat, websocket events, tool-calling.
* `main/tool_router.py` - central intent router для LLM tools/skills; системные Windows-команды остаются в deterministic handlers.
* `main/commands/` - deterministic handlers для помощи, окон, файлов, web/open-source команд, корзины, питания, приложений, системы, времени и heartbeat.
* `main/tools/` - LLM-callable tools: document reading, code interpreter, Telegram, document/presentation generation.
* `web/` - HTTP shim, search/extraction, weather, currency.
* `ui/` - Electron/Vite/React UI. `App.tsx` содержит основной UI/runtime state; `services/` содержит socket/session sync helpers.
* `tests/` - `unittest` runner and focused unit tests for routing, tools, web, memory, prompts, sessions, voice control, and generation helpers.

## High-risk areas

* `main/agent.py`: явный god module. При import запускаются/инициализируются LLM server/client, TTS thread, Sherpa-ONNX STT, schedulers, memory/session stores and prompt validation.
* `ui/src/App.tsx`: очень большой контейнер UI и runtime state; settings, notes, workspace, sessions, streaming and window controls живут в одном файле.
* `server.py`: module-level import of `main.agent` inherits heavy side effects; upload and websocket handling are security-sensitive.
* `main/tools/code_interpreter.py`: subprocess timeout and temp dir exist, but this is not a real sandbox.
* `main/tools/telegram.py`: hardcoded Telegram `API_ID/API_HASH` and mojibake strings. Needs separate review because fixing text/credential flow can affect auth UX.
* `web/web_utils.py`: `fetch_urls_parallel` can break out early but still wait for already running executor tasks on context-manager exit.

## Changes made

| file | change | reason | behavior impact | validation |
|---|---|---|---|---|
| `main/agent.py`, `main/response_sanitizer.py` | `speak()` now uses `clean_for_tts`; duplicate inline markdown/emoji/source cleanup removed from `agent.py` | shrink the god module with a low-risk pure helper | same TTS cleanup behavior | `python -m unittest tests.test_response_sanitizer`, full test run |
| `server.py`, `main/upload_utils.py` | upload names now use `safe_upload_name`; upload read is capped at 20 MB | reduce path traversal/collision risk and reject oversized uploads | response shape unchanged; oversized uploads return 413 | `tests/test_upload_utils.py`, full test run |
| `server.py` | `ConnectionManager.disconnect()` tolerates stale sockets; `broadcast()` removes failed clients | one dead websocket should not poison later broadcasts | websocket event contract unchanged | `python -m py_compile server.py`, full test run |
| `server.py`, `ui/src/App.tsx` | token compare uses `verify_token()`/`secrets.compare_digest`; UI encodes token query param | make HTTP and WebSocket token flow more consistent | auth semantics unchanged | renderer build |
| `main/commands/system_control.py`, `tests/test_ping_command.py` | Task Manager open uses `subprocess.Popen(["taskmgr.exe"])` without `shell=True`; added test | remove unnecessary shell usage | same command result text | `python -m unittest tests.test_ping_command`, full test run |
| `ui/src/services/socketService.ts` | reconnect helper clears pending timer, avoids duplicate timers, clears WebSocket handlers on cleanup | reduce reconnect/listener leaks | same reconnect behavior | renderer build |
| `tests/test_tool_router.py` | added guard cases for system commands, requested document/presentation/web/plain file-context cases | preserve routing contract before future router changes | no production behavior change | `python -m unittest tests.test_tool_router`, full test run |

## Dead code removed

No confidently dead production behavior was removed. The removed block in `main/agent.py` was duplicated TTS cleanup code that now lives in `main/response_sanitizer.py` and is covered by tests.

## Duplications reduced

* TTS markdown/emoji/source cleanup is centralized in `main/response_sanitizer.py` instead of being embedded in `main/agent.py`.
* Upload filename normalization is centralized in `main/upload_utils.py` instead of ad hoc replacement in `server.py`.

Broader duplication remains in document-reading branches and UI helper/state code; those are better handled in separate focused PRs.

## Routing safety

Confirmed by tests:

* `Вера, открой хром`, `Вера, громкость 50`, `Вера, сделай скриншот`, `Вера, таймер стоп` select no LLM tools.
* `Вера, сделай презентацию про ядро ОС` routes to the presentation skill.
* `Вера, напиши реферат и сохрани в docx` routes to the document skill and `create_document`.
* `Напиши код на Python для сортировки списка` is plain code and does not call `code_interpreter`.
* `Выполни Python код print(2 + 2)` selects `code_interpreter`.
* `Кто такой Илон Маск сейчас` selects `web_search`.
* Attached file context prevents repeated `read_document`.
* Telegram phone/code flow routes as Telegram action.

## Security notes

Fixed:

* Removed the remaining production `shell=True` occurrence.
* Upload filenames are local-only, unique, and sanitized.
* Uploads larger than 20 MB are rejected before document/image processing.
* WebSocket token validation now uses the same helper as HTTP token validation.
* Broadcast removes stale WebSocket connections.

Found but left for manual review:

* `code_interpreter` is timeout-bounded but not sandboxed.
* `main/tools/telegram.py` contains embedded Telegram credentials and mojibake strings.
* `main.agent` import starts heavy runtime components.
* `read_document` can read arbitrary files found by local fuzzy search; acceptable for this local assistant model, but worth threat-modeling.
* Several exception handlers still intentionally swallow errors in UI/web/runtime paths; some are fallback behavior, others deserve targeted logging review.

## Performance notes

Optimized:

* Stale WebSocket clients are removed after failed broadcast.
* Frontend reconnect timer handling avoids duplicate scheduled reconnects.

Observed but not changed:

* `main/agent.py` starts LLM/TTS/STT at import time.
* `ui/src/App.tsx` remains large enough to make effect interactions hard to audit.
* `web_utils.fetch_urls_parallel` can wait for already-started fetch workers after early break.

## Tests and checks

Baseline before edits:

* `python tests/run_all.py` - passed, 94 tests.
* `cd ui && npm run build:renderer` - passed.

Targeted checks during edits:

* `python -m unittest tests.test_response_sanitizer` - passed, 3 tests.
* `python -m unittest tests.test_ping_command` - passed, 4 tests.
* `python -m unittest tests.test_tool_router` - passed, 23 tests.
* `python -m py_compile server.py main/agent.py main/commands/system_control.py main/response_sanitizer.py main/upload_utils.py` - passed.
* `rg -n "shell=True" main server.py web ui/src` - no production matches.

After edits:

* `python tests/run_all.py` - passed, 100 tests.
* `cd ui && npm run build:renderer` - passed.

## Manual follow-up

Best handled as separate PRs:

* staged decomposition of `main/agent.py` around LLM lifecycle, STT/TTS lifecycle, sessions/memory, routing, websocket events and tool-call loop;
* move heavy server/agent initialization out of module import paths;
* deeper `App.tsx` split into focused hooks/components without redesign;
* proper sandbox for `code_interpreter`;
* e2e tests for Electron/FastAPI/WebSocket flows;
* CI pipeline;
* type-check/lint setup recommendation, not a large migration inside a cleanup PR;
* Telegram credentials/config review and mojibake cleanup in `main/tools/telegram.py`;
* focused review of arbitrary local file read/write expectations for document/file tools.
