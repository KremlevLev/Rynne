# Crash Recovery

Rynne автоматически сохраняет критическое состояние в SQLite и файловой системе.

## Что сохраняется

- История диалогов — SQLite `data/nova.db`.
- Долговременная память — SQLite `data/nova.db`.
- Метаданные процессов — JSON в `data/processes/`.
- Артефакты — файлы в `data/artifacts/`.
- Напоминания — JSON в `data/tasks/tasks.json`.

## После падения

1. Запустите Rynne снова.
2. Process Manager восстановит метаданные процессов.
3. Conversation Store восстановит историю.
4. Memory Store восстановит долговременную память.
5. Напоминания продолжат работать.

## Если Rynne не запускается

1. Проверьте `.env` — все ли ключи указаны.
2. Проверьте `data/nova.db` — если файл повреждён, удалите его.
3. Проверьте `data/tasks/tasks.json` — если файл повреждён, удалите его.
4. Запустите `python scripts/install_dependencies.py`.
5. Запустите `python -m main`.

## Сбор логов для диагностики

```powershell
python -m main 2> nova_error.log

Отправьте nova_error.log разработчику.

---
