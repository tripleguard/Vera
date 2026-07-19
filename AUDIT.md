# Полный аудит Vera

Дата: 19 июля 2026 года

## Резюме

Проект работоспособен и production-сборка UI проходит, но цена изменений сейчас высока из-за двух монолитов: `ui/src/App.tsx` (5031 строка) и `main/agent.py` (более 2200 физических строк, 1256 AST-инструкций). Самая опасная проблема backend — запуск LLM, TTS, STT, scheduler и хранилищ прямо во время импорта `main.agent`. Это затрудняет тестирование, замедляет импорт и превращает любой импорт `server.py` в потенциальный запуск тяжёлого runtime.

До аудита pytest собирал 145 тестов: 144 проходили, один падал из-за записи в реальный `%LOCALAPPDATA%`. При этом штатный `tests/run_all.py` фактически выполнял только 127 тестов и пропускал 18 pytest-функций. После исправлений единый runner выполняет 146 тестов, все проходят.

Подтверждённого автоматически удаляемого мёртвого кода во frontend не найдено: TypeScript проходит с `noUnusedLocals` и `noUnusedParameters`, все 223 CSS-класса текстово используются. Главный подтверждённый кандидат на удаление — отключённая Telegram-подсистема: два модуля содержат 691 строку, кроме этого её ветки остаются в `agent.py`, `tool_router.py`, `tool_definitions.py`, registry и тестах, а production-зависимость `telethon` продолжает устанавливаться.

## Что проверено

- Все отслеживаемые Python-, TypeScript-, JavaScript- и CSS-файлы.
- Импорты, top-level определения, реестры команд и инструментов, FastAPI routes и Electron IPC.
- Размер и связность крупных функций, точные дубликаты тел функций, broad exception handlers и import-time side effects.
- Все 29 существующих тестовых файлов, способ их обнаружения, изоляция, типы assertions и покрываемые модули.
- Production-сборка UI через TypeScript и Vite.
- Полный pytest-прогон после исправлений.
- Приближённый statement trace. Он показывает ориентир около 32%, но не заменяет `pytest-cov`: branch coverage в проекте до аудита не был настроен.

## Уже исправлено

1. `main/commands/app_control.py`: индекс Windows-приложений загружается лениво при первой реальной команде, а не во время импорта backend.
2. `main/llm_server.py`: файловый handle `llama_server.log` теперь хранится и закрывается при stop, завершившемся процессе и ошибке запуска. Регистрация `atexit` больше не дублируется при каждом restart.
3. `tests/test_multimodal.py`: лог LLM изолирован во временной директории, тест вызывает штатный `stop()` и обнаруживает утечки файлового handle.
4. `tests/run_all.py`: runner переведён на pytest и выполняет как `unittest.TestCase`, так и pytest-функции.
5. `tests/test_app_control.py`: добавлен regression-тест ленивой однократной загрузки индекса.
6. `requirements-dev.txt`: зафиксирован отдельный тестовый контур (`pytest`, `pytest-cov`).

## Frontend/UI

### Что можно удалить сейчас

Безопасных удалений импортов, компонентов или CSS-селекторов статический анализ не подтвердил:

- `npm run build` проходит при включённых `noUnusedLocals` и `noUnusedParameters`.
- Все runtime-зависимости `react`, `react-dom`, `framer-motion`, `lucide-react` и `react-markdown` реально импортируются.
- Tailwind реально используется, это не лишний build-step.
- Все 223 custom CSS-класса имеют текстовые ссылки в TSX/HTML/JS.

Удалять отдельные функции или CSS-правила только по имени нельзя: UI широко использует условные class names, Electron routes и IPC callbacks.

### Проблемы

#### P0. UI не имеет исполняемых тестов

В проекте нет Vitest/React Testing Library и нет Playwright Electron tests. Десять тестов в `test_startup_contract.py` и `test_widget_visibility_contract.py` ищут строки в исходниках. Они полезны как smoke-contract, но могут пройти при сломанном реальном поведении.

Решение:

- Добавить Vitest + React Testing Library для чистых компонентов и services.
- Добавить Playwright Electron минимум для startup, widget/chat windows, settings, sessions, file attachment и reconnect.
- Сохранить string-contract tests только для installer/build-инвариантов, которые трудно исполнить в unit-среде.

#### P1. `App.tsx` объединяет почти весь продукт

В одном файле находятся themes, Markdown rendering, settings, widget, chat, workspace tree, terminal, notes canvas, projects, skills, sessions и WebSocket state. Крупные блоки начинаются примерно в `SettingsModal` (651), `App` (1812), `WidgetView` (2008), `WorkspacePanel` (2609), `NotesView` (2950) и `ChatView` (3640).

Решение:

- Вынести routes/features в `features/settings`, `features/chat`, `features/widget`, `features/workspace`, `features/notes`, `features/projects` и `features/skills`.
- Вынести pure helpers и domain types отдельно; покрыть их unit-тестами до переноса JSX.
- Загружать тяжёлые route-компоненты через `React.lazy`, чтобы Vite мог сформировать отдельные chunks.
- Не смешивать это изменение с визуальным редизайном; проверять screenshots до/после на всех шести themes.

#### P1. Слабая типизация сетевого контракта

В `ui/src` найдено 40 употреблений `any`, включая config, tasks, WebSocket chunks и IPC payloads. `strict: true` поэтому не даёт полной защиты.

Решение:

- Описать `ConfigPayload`, `HeartbeatTask`, WebSocket inbound/outbound union и типизированную карту IPC channels.
- Заменить `catch (error: any)` на `unknown` + helper получения сообщения.
- Валидировать сетевые payloads на границе, а не внутри render callbacks.

#### P1. Дублирование адресов и транспорта

Base URL `http://127.0.0.1:8000` повторяется 25 раз, WebSocket URL — в нескольких местах. Настройки, chat и services реализуют fetch/error handling отдельно.

Решение:

- Создать один `apiClient.ts` с `API_BASE_URL`, `WS_URL`, auth headers, JSON/error parsing и AbortController.
- Выделить typed methods для config, memory, audio, updates, skills и uploads.
- Оставить отдельные WebSocket connections widget/chat, но использовать один lifecycle helper.

#### P2. CSS трудно безопасно сокращать

`index.css` содержит 3716 строк, 26 `!important` и более 20 групп идентичных declaration blocks. Часть дублей намеренна из-за specificity и theme overrides.

Решение:

- После screenshot-baseline объединить только byte-identical правила через `:is(...)` или общие component classes.
- Разделить CSS по features без изменения порядка cascade.
- Добавить Stylelint и запрет новых `!important`, кроме документированных исключений.

#### P2. Initial bundle

Production bundle: JavaScript 485.03 kB / 151.31 kB gzip, CSS 82.75 kB / 15.34 kB gzip. Для desktop это не авария, но все features парсятся при старте.

Решение: feature chunks после декомпозиции `App.tsx`; измерять cold start и не вводить ручные `manualChunks`, пока natural dynamic imports не дадут результат.

#### P1. Electron IPC capabilities шире выбранной workspace

Electron sandbox, `contextIsolation` и `nodeIntegration: false` настроены правильно. Однако `workspace-read-file`, `workspace-open-file` и `workspace-list-directory` принимают произвольный существующий путь от renderer. Выбранный workspace root не хранится как capability в main process.

Решение: хранить разрешённые roots в main process, проверять `path.relative(root, target)` для read/list/open, отдельно разрешать явно выбранные/перетащенные файлы.

## Backend

### P0. Тяжёлый runtime запускается при импорте

`server.py` импортирует `main.agent` на уровне модуля. В свою очередь `main.agent` во время импорта:

- читает config и может вызвать `sys.exit(1)`;
- создаёт и запускает локальный LLM;
- запускает TTS thread;
- загружает Sherpa-ONNX STT;
- запускает scheduler;
- открывает memory/session stores.

Это главная причина низкой тестируемости и скрытых side effects.

Решение:

1. Ввести `AgentRuntime` с явными `start()`, `stop()` и зависимостями в constructor.
2. Перенести LLM/TTS/STT/schedulers в FastAPI lifespan или desktop bootstrap.
3. Оставить import-time только definitions и pure helpers.
4. Перед переносом добавить lifecycle tests: частичный startup, degraded voice, повторный start/stop, failed component cleanup.

Критерий: `python -c "import server"` не запускает процессы, threads, модели и не пишет пользовательские файлы.

### P0. Недостаточное runtime-покрытие API

В `server.py` 23 HTTP routes и один WebSocket route. Поведенческие API-тесты есть только для переключения audio device; остальные routes в основном не вызываются через ASGI client.

Решение: создать fixture приложения с fake `AgentRuntime`, temp data directory и `httpx.AsyncClient(ASGITransport)`. Проверить auth 401/успех, validation 400/404/409/500 contract и отсутствие записи за пределами temp.

### P1. Отключённая Telegram-подсистема

`TELEGRAM_INTEGRATION_ENABLED = False`; тесты требуют, чтобы инструмент не был доступен. При этом остаются:

- `main/tools/telegram.py` — 368 строк;
- `main/tools/telegram_mode.py` — 323 строки;
- Telegram branches в `agent.py`, `tool_router.py`, `tool_definitions.py` и registry;
- production dependency `telethon`;
- migration legacy Telegram sessions.

Если Telegram не входит в roadmap, удалить подсистему полностью. Это крупнейшее безопасное сокращение текущего кода (ориентировочно 750–900 строк с glue-кодом) и одна production-зависимость. Если feature планируется, вынести в optional plugin/extra; не держать disabled implementation в core.

### P1. Крупные функции

Наиболее сложные функции по размеру/ветвлению:

- `main.agent.ask_llm`: около 396 строк, более 100 branch nodes;
- `main.tools.document_generator.create_pptx`: около 363 строк;
- `heartbeat_commands.execute_heartbeat_command`: около 184 строк;
- `time_commands._execute_reminder_inner`: около 167 строк;
- `agent._tts_worker`: около 151 строки;
- `web_search_answer`: около 133 строк.

Решение: выделять не произвольные мелкие методы, а стадии pipeline с typed result: parse → validate → execute → persist → emit. На каждую выделенную стадию сначала добавить characterization tests.

### P1. Ошибки и наблюдаемость

В 54 backend-файлах найдено 236 `except Exception`, из них 41 молча выполняют `pass`; используется около 183 `print`. Для Windows automation часть broad catch оправдана, но сейчас реальные дефекты легко превращаются в ложный «не найдено».

Решение:

- Единый structured logger с component/action/error code.
- Ловить ожидаемые `OSError`, `subprocess.SubprocessError`, request exceptions и parse errors отдельно.
- Silent fallback логировать на debug/warning с контекстом.
- Не показывать сырые exception strings как стабильный API contract.

### P2. Небольшие дубли

- `agent._sanitize_assistant_response` и `web_search._strip_thinking_markup` — одинаковые thin wrappers над `strip_thinking_markup(...).strip()`.
- В `lang_ru.convert_years_in_text` два одинаковых nested callback для года после «в».
- Generic `create_document` продолжает поддерживать presentation, хотя есть отдельный presentation skill pipeline. Удалять ветку нельзя без telemetry/characterization test: это может быть прямой LLM tool-call.

Эти сокращения делать после P0/P1; выигрыш мал по сравнению с риском регрессии.

### P2. Репозиторий и зависимости

`llama-common.dll` (около 7.9 MB) отслеживается Git, хотя остальные runtime binaries исключены. Проверить, нужен ли он в source repository; предпочтительнее получать весь llama runtime единым download/build step. Не удалять до проверки offline installer.

## Аудит тестов и план новых сценариев

### Сильные стороны текущих тестов

- Хорошо покрыты normalization и rollback audio devices.
- Есть проверки безопасного argv для ping/power commands.
- Хорошо покрыты tool routing, session store, memory limits, response sanitizer и Llama update replacement.
- Веб-извлечение проверяет timeout/parallel behavior и fallback parsing.
- Тесты в основном короткие и содержат явные assertions.

### Недостатки текущих тестов

- До исправления runner пропускал 18 тестов.
- Нет реального coverage gate и отдельного dev requirements.
- `main.agent`, `user.memory_extractor`, `web.currency` и `main.audit` фактически не исполняются тестами.
- Из 28 command handlers прямые тесты есть только для power, taskmanager и ping; heartbeat тестирует storage/scheduler, но не полный command parser.
- Нет ASGI/WebSocket интеграционных тестов для большинства endpoint contracts.
- Нет frontend component/Electron runtime tests.
- Десять source-contract tests хрупко зависят от точного текста реализации.
- Нет CI-конфигурации, которая запускает Python tests и UI build на чистом окружении.

### Приоритетный набор новых тестов

#### P0 — backend lifecycle

- Import `server` не запускает models/processes/threads и не пишет файлы.
- `AgentRuntime.start()` идемпотентен; partial failure переводит только соответствующий component в degraded/error.
- `stop()` закрывает LLM process/log, audio, scheduler threads и SQLite handles.
- Restart после failed start не оставляет старых callbacks/threads.

#### P0 — API/auth/WebSocket

- Каждый HTTP route: без token, корректный token, malformed payload, missing entity, storage error.
- Upload: path traversal, duplicate names, size limit, unsupported/corrupt image, cleanup после ошибки.
- Sessions: create/list/update/archive/pin/delete через API, isolation и ordering.
- Memory: patch/delete profile/fact, invalid ID, persistence rollback.
- WebSocket: connect/disconnect, invalid JSON, command/interrupt/thinking/status, reconnect и stale client.

#### P0 — UI

- `sessionService`: URL encoding, non-2xx errors, JSON contracts.
- Settings: initial load, dirty state, save error, audio rollback.
- Chat: optimistic user message, streaming chunks, interrupt, reconnect, active session reconciliation.
- Attachments: image/non-image preview, remove, upload failure, workspace drop.
- Notes: persistence debounce, drawing restore, zoom bounds, task CRUD.
- Electron smoke: widget visibility persistence, tray restore, chat fullscreen, IPC allowlist.

#### P1 — command handlers

Табличные tests для всех 28 handlers: positive phrases, negative/ambiguous phrases, morphology, subprocess failure и отсутствие shell injection. Приоритет: file/folder, app/browser, recycle bin, volume/brightness/screenshot, reminders/time/date и web/open sources.

#### P1 — documents/web/memory

- Реальные minimal txt/md/docx/pptx/xlsx artifacts с чтением результата обратно.
- Presentation themes/layout boundaries, overflow и invalid slide data.
- Currency parsing/rates/fallback/cache/network errors.
- Memory extraction: remember command, negation, duplicates, malformed LLM output.
- Audit logger concurrency и invalid/unwritable destination.

## План сокращения без потери функционала и визуала

1. Зафиксировать safety net: pytest-cov, UI tests, Electron smoke и screenshots шести themes.
2. Убрать import-time side effects через `AgentRuntime`; функционально ничего не удалять.
3. Принять решение по Telegram. При отказе удалить core implementation, glue и `telethon`; при сохранении вынести optional plugin.
4. Декомпозировать `App.tsx` и `agent.py` по feature boundaries. Это сначала улучшит структуру, но не обязательно уменьшит LOC.
5. После characterization tests удалить дублирующие wrappers, объединить CSS blocks и проверить generic/specialized document paths.
6. Сравнить до/после: все tests, UI build, bundle sizes, cold start, screenshots и ручной Windows smoke.

Реалистичный первый выигрыш без потери текущего включённого функционала: 750–900 строк за счёт disabled Telegram subsystem, одна production-зависимость, отсутствие eager app-index scan и корректное освобождение LLM log handle. Дальнейшее сокращение должно опираться на тесты и telemetry, а не на статическое отсутствие прямых вызовов: значительная часть проекта вызывается через registries, decorators, IPC и LLM tool names.

## Рекомендуемый порядок задач

| Приоритет | Задача | Ожидаемый эффект | Критерий готовности |
|---|---|---|---|
| P0 | Ввести `AgentRuntime` и чистый import | Убирает главный side effect и открывает полноценные tests | Import без процессов/threads/files |
| P0 | ASGI/WebSocket integration suite | Защищает 24 сетевых contract | Все routes имеют success/error/auth tests |
| P0 | UI/Electron test foundation | Защищает функционал и визуал перед refactor | Component tests + 6-theme screenshots + smoke |
| P1 | Решить судьбу Telegram | Минус до ~900 строк и `telethon` либо чистый plugin boundary | Core не содержит disabled implementation |
| P1 | Разделить `App.tsx` и типизировать API/IPC | Снижает связанность и initial parse | Нет feature-файлов >800 строк, меньше `any` |
| P1 | Разделить `ask_llm`/TTS/command pipelines | Упрощает ошибки и tests | Stages имеют typed input/output и tests |
| P1 | Structured logging и exception taxonomy | Устраняет молчаливые failures | Нет необоснованных silent `except Exception` |
| P1 | CI: pytest + coverage + UI build | Не допускает возврата дефектов runner/build | Чистый pipeline на новом checkout |
| P2 | CSS consolidation после screenshots | Уменьшает CSS без изменения cascade | Pixel diff в допуске, CSS меньше |
| P2 | Проверить document path overlap и DLL | Уменьшает core/repository size | Удаление подтверждено usage tests/build |

## Проверки после изменений аудита

- `python tests/run_all.py`: 146 passed.
- `python -m compileall -q main user web server.py tests`: успешно.
- `npm run build`: успешно.
- Production UI: JS 485.03 kB (151.31 kB gzip), CSS 82.75 kB (15.34 kB gzip).
