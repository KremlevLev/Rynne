# Nova Desktop: языковые границы

## Решение

Nova развивается как модульный desktop-продукт, но не как набор микросервисов
на одном компьютере.

| Слой | Язык | Ответственность |
|---|---|---|
| Desktop presentation | TypeScript, React | окна, навигация, chat, task timeline, настройки, accessibility |
| Desktop shell | Tauri/Rust | lifecycle окна, tray, updater, подпись, запуск sidecar, IPC |
| Agent Core | Python | LLM, orchestration, tools, MCP, memory, policy, proactive engine |
| Hot system workers | Go, только по профилю | длительный сбор событий, высокочастотный I/O, индексирование |

## Почему Python остаётся ядром

Почти вся ценность Nova находится в orchestration, tool calling, MCP и
интеграции с AI-библиотеками. Перенос этого слоя не даст пользователю новой
возможности, но создаст две реализации политик, ошибок и состояния задач.

## Когда разрешён Go

Новый Go-worker появляется только если выполнены все условия:

1. Профилирование показывает устойчивое узкое место в Python.
2. Работа имеет маленький типизированный контракт и не содержит agent logic.
3. Изоляция процесса повышает надёжность или заметно уменьшает CPU/RAM.
4. Есть benchmark до и после миграции.

Первые кандидаты: filesystem watcher/indexer, поток телеметрии процессов,
локальный full-text index и очень частые Windows event subscriptions.
Browser automation, permissions, planning и LLM routing в Go не переносятся.

## IPC

Контракт сохраняет существующие JSON envelopes:

```json
{"event_type":"tool_started","payload":{},"created_at":1785300000.0}
{"command_id":"ui_command_...","action":"submit_user_request","payload":{},"created_at":1785300000.0}
```

Tauri запускает упакованный Python Core как sidecar. Между shell и Core
используется JSON Lines через stdin/stdout:

- одна строка — одно сообщение;
- stdout Core содержит только protocol frames;
- логи пишутся в stderr;
- первая команда — handshake с версиями протокола и Core;
- неизвестные события игнорируются, несовместимая major-версия блокирует ввод;
- каждый side effect по-прежнему проходит Python policy/approval layer.

## Этапы миграции

- [x] React/Vite workspace и единый набор design tokens.
- [x] Типизированные event/command envelopes.
- [x] Кликабельный dialog shell и dev-only transport.
- [x] Tauri container, который до подключения Core честно показывает offline.
- [ ] Python stdio adapter для существующего `DesktopService`.
- [ ] Tauri sidecar supervisor и handshake.
- [ ] Перенос реальных chat/task/process/settings экранов.
- [ ] PyInstaller onedir bundle для `nova-core.exe`.
- [ ] Подписанные NSIS/MSI releases и Tauri updater.
- [ ] Профилирование Python и решение по первому Go-worker.
