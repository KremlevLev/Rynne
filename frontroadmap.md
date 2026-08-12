# Задача для агента: новый фронтенд Rynne

Нужно сделать **очень красивый, премиальный и живой desktop UI** для Rynne — голосового Windows-агента.

Ощущение: **Raycast + Linear + Arc + немного sci-fi JARVIS**, но без дешёвого «киберпанка», кислотного неона, перегруженных стеклянных панелей и анимаций ради анимаций.

Rynne должна выглядеть как дорогой, быстрый и умный персональный агент, а не как обычный чат-бот.

---

## Статус миграции на React/Tauri

- ✅ Создан отдельный React 19 + TypeScript + Vite presentation layer.
- ✅ Вынесены единые design tokens и адаптивный трёхзонный desktop layout.
- ✅ Реализованы кликабельные sidebar, proactive toggle, chat composer,
  timeline и context/activity panel.
- ✅ UI использует типизированные envelopes существующего Python-протокола.
- ✅ Production transport fail-closed: без handshake с Rynne Core показывает
  offline, а не фейковую активность.
- ✅ Demo transport доступен только в Vite dev-режиме через `?demo=1`.
- ✅ Добавлены Tauri shell, Windows bundle configuration, иконки и updater
  dependency; updater останется выключенным до настройки подписей.
- ✅ Добавлен JSONL transport к реальному Python Core и отдельный sidecar
  entry point без смешивания protocol frames с логами.
- 🟡 Tauri supervisor скомпилирован и запускает настоящий Core, передаёт
  команды/события; version handshake и restart policy впереди.
- ✅ Dev server и Tauri используют единый `http://127.0.0.1:1420`; updater не
  инициализируется до появления подписанного release manifest и public key.
- ✅ Старый непрерывный Tk overlay отключён для Tauri; runtime-состояния
  «слушает / думает / выполняет / отвечает» встроены в React activity panel.
- ✅ Headless `nova-core.exe` собирается PyInstaller `onedir` и автоматически
  включается в пользовательский NSIS installer.
- ⬜ Затем: перенос task/activity, approvals и settings.

Архитектурное решение и критерии для возможных Go-workers:
[`docs/desktop_architecture.md`](docs/desktop_architecture.md).

---

## 0. Жёсткие правила

1. **Сначала изучи текущий UI и точки интеграции.**  
   Найди текущий frontend entry point, существующие компоненты, event bus, API/IPC, состояние задач, voice state и tool events.

2. **Не переписывай backend Rynne.**
   Не ломай текущие tool calling, агентный цикл, MCP, память, голос, ModelGateway и бизнес-логику.

3. Новый UI должен быть отдельным presentation layer:
   - подписывается на уже существующие события;
   - отправляет команды через существующие интерфейсы;
   - не содержит логики агента;
   - не делает прямых вызовов к провайдерам, MCP или базе в обход backend.

4. Делай изменения **инкрементально**:
   - сначала design tokens и layout;
   - затем chat;
   - затем task/activity UI;
   - затем voice overlay;
   - затем настройки и polish.

5. Перед заменой существующего экрана сохрани старый вариант за feature flag / fallback, если это возможно.

6. Не создавай «фейковый UI». Все статусы, tool calls, прогресс и результаты должны быть привязаны к реальным данным Rynne.

---

# 1. Визуальное направление

## Общая эстетика

- Тёмная тема — основная.
- Светлая тема — позже, но архитектура токенов должна её позволять.
- Много воздуха, ровная типографика, спокойные поверхности.
- Контрастный акцентный цвет: холодный electric violet / blue.
- Второй акцент: мягкий cyan для success/active states.
- Красный — только для ошибок и опасных действий.
- Зелёный — только для подтверждённого успеха.
- Никаких ярких rainbow-gradient на всём экране.
- Градиенты использовать тонко: в фоне, активной орбите Rynne, подсветке focus.
- Стекло — умеренно: не превращать весь интерфейс в glassmorphism.

## Впечатление от интерфейса

Интерфейс должен передавать три состояния:

1. **Rynne ждёт**
   Тихая, спокойная, почти незаметная.

2. **Rynne думает / слушает / работает**
   Живая, но не нервная: мягкая пульсация, поток, движение света.

3. **Rynne завершила задачу**
   Ясный результат, короткая красивая success-анимация, никаких долгих конфетти.

---

# 2. Design system

Создай единый слой design tokens. Не разбрасывай цвета, размеры и transition values по компонентам.

## Цветовые токены

Примерное направление:

```text
bg.base            #0B0D12
bg.elevated        #11141C
bg.surface         #171B25
bg.surfaceHover    #1D2330
bg.overlay         rgba(8, 10, 15, 0.72)

text.primary       #F5F7FB
text.secondary     #A7B0C0
text.muted         #6F7888
text.disabled      #4C5360

accent.primary     #8B7CFF
accent.secondary   #4CC9F0
accent.soft        rgba(139, 124, 255, 0.14)

success             #4ADE80
warning             #FBBF24
danger              #FB7185
info                #60A5FA

border.subtle      rgba(255, 255, 255, 0.07)
border.active      rgba(139, 124, 255, 0.55)
```

Цвета можно скорректировать после просмотра текущей реализации, но должна сохраниться эта иерархия.

## Геометрия

```text
radius.sm     8px
radius.md     12px
radius.lg     16px
radius.xl     22px
radius.pill   999px

spacing: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48
```

## Типографика

- Интерфейс: `Inter`, `Geist`, `Manrope` или аналогичный современный sans-serif.
- Код и tool output: `JetBrains Mono` или `Geist Mono`.
- Чёткая шкала:
  - 12 — metadata;
  - 13–14 — secondary text;
  - 15–16 — основной UI;
  - 18–20 — секции;
  - 24–32 — ключевые заголовки.
- Не использовать огромные заголовки на каждом экране.
- Плотность должна быть как у профессионального desktop-приложения.

## Тени и глубина

- Очень мягкие, широкие, почти незаметные тени.
- Активные панели могут иметь слабое цветное свечение.
- Не использовать тяжёлые чёрные box-shadow.
- Поверхности различать не только тенями, но и `border.subtle`, цветом и blur.

---

# 3. Главная структура приложения

Сделай desktop layout из трёх зон.

```text
┌──────────────┬─────────────────────────────────────┬────────────────────┐
│ Sidebar      │ Main workspace                      │ Context / Activity │
│              │                                     │                    │
│ Rynne         │ Chat / task result / artifacts      │ Current task       │
│ Chats        │                                     │ Plan / tools       │
│ Workspaces   │                                     │ Sources / files    │
│ Skills       │                                     │                    │
│ Automations  │                                     │                    │
│ Settings     │                                     │                    │
└──────────────┴─────────────────────────────────────┴────────────────────┘
```

## Левая sidebar

Сделать узкой, аккуратной, с режимом collapse.

Содержимое:

- логотип / статус Rynne;
- кнопка **New task**;
- список последних сессий;
- workspace / project switcher;
- Skills;
- Automations;
- Memory;
- Settings;
- нижняя зона: статус модели, сети и voice.

Требования:

- Активный пункт — мягкая акцентная подсветка, не огромная яркая плашка.
- Sidebar должна сворачиваться до icon-only режима.
- Tooltip при hover в collapsed режиме.
- Переход между expanded/collapsed — плавный, ~220–280ms.
- Не анимировать ширину через тяжёлые layout jumps; использовать transform/layout animation аккуратно.

## Центральная зона

Это основной экран Rynne.

Режимы:

1. Empty state / старт.
2. Активный чат.
3. Выполнение задачи.
4. Просмотр результата.
5. Артефакт: код, файл, таблица, исследование, diff.
6. Ошибка или запрос подтверждения.

## Правая панель Context / Activity

Показывать только когда есть активная задача, артефакты или пользователь её открыл.

Секции:

- Current task;
- Status;
- Plan;
- Activity;
- Tool calls;
- Files / artifacts;
- Sources;
- Cost / duration — компактно, только по желанию.

Панель должна открываться и закрываться плавно, не ломая центральный layout.

---

# 4. Главный экран / empty state

Когда пользователь ещё ничего не спросил, центр должен выглядеть очень чисто.

Состав:

- небольшой живой Rynne Orb;
- текст вроде:  
  **«Чем займёмся?»**
- подзаголовок:  
  «Я могу работать с приложениями, кодом, файлами, браузером и задачами.»
- поле ввода;
- набор красивых starter cards:
  - «Разбери папку Downloads»
  - «Открой проект и запусти тесты»
  - «Исследуй тему и создай заметку»
  - «Подготовь меня к следующей встрече»
  - «Создай workflow из повторяющейся задачи»

Карточки не должны быть огромными. Hover — лёгкий подъём на 1–2px, подсветка border и мягкий accent glow.

---

# 5. Chat UI

## Сообщения пользователя

- Справа или нейтрально в центре — выбрать то, что лучше подходит текущему UI.
- Чёткая и компактная bubble.
- Не использовать огромные закруглённые пузыри.
- Под сообщением: время, при необходимости статус отправки.

## Сообщения Rynne

Сообщение Rynne должно быть не обычным полотном текста, а **умной структурой**:

- краткий ответ;
- progress/status;
- раскрываемые детали;
- действия;
- артефакты;
- подтверждения;
- ссылки на результаты.

Пример:

```text
Rynne
Готово — создала заметку в Obsidian и добавила 6 источников.

[ Открыть заметку ] [ Показать источники ] [ Что именно сделано? ]

▸ 4 действия выполнено
▸ 6 источников проверено
```

## Tool calls

Не показывать пользователю сырые JSON payloads по умолчанию.

Вместо этого сделать compact activity cards:

```text
✓ Открыла Obsidian
✓ Создала заметку «MCP Research»
✓ Добавила 6 источников
↗ Открыть результат
```

При раскрытии:

```text
Obsidian · create_note
Выполнено за 0.4 сек

Путь:
Vault/Research/MCP Research.md

[ Скопировать путь ] [ Открыть ]
```

Для ошибок:

```text
! Не удалось подключиться к Jira

Причина: истёк токен доступа.

[ Повторить ] [ Открыть настройки ] [ Подробнее ]
```

## Streaming response

- Текст Rynne появляется постепенно, но без неприятного «печатания по одной букве».
- Использовать chunk-based reveal или короткие фразы.
- Если пришёл tool call, текст должен естественно перейти в activity state.
- Не дёргать высоту сообщения при каждом токене.
- При завершении — мягко проявить action buttons и artifacts.

---

# 6. Composer / поле ввода

Это одна из самых важных частей интерфейса.

## Требования

- Закреплено внизу центральной области.
- Не обычный прямоугольный input, а компактная premium command surface.
- Поддержка multiline.
- Поддержка drag-and-drop файлов.
- Вставка скриншота.
- Вставка изображения из clipboard.
- Voice input.
- Выбор режима работы.
- Отправка Enter, новая строка Shift+Enter.

Пример структуры:

```text
[ + ]  Спроси Rynne или дай задачу...                 [ 🎙 ] [ ↑ ]
      Local mode · Gemini Flash · Safe autonomy
```

## Элементы

- `+`: добавить файл, скриншот, папку или контекст.
- микрофон: удержание / toggle — зависит от текущей voice архитектуры;
- модель: компактный dropdown;
- privacy mode: маленький индикатор;
- autonomy mode: `Ask`, `Safe`, `Autonomous`;
- send: акцентная круглая кнопка.

## Состояния

- idle;
- focus;
- voice listening;
- processing;
- task running;
- approval pending;
- disabled / offline.

При voice listening поле ввода должно мягко подсвечиваться, а рядом появляется waveform.

---

# 7. Rynne Orb и голосовой интерфейс

Сделай **узнаваемую визуальную сущность Rynne**: orb / ядро / световая форма.

Это не должна быть 3D-рендеренная тяжёлая сфера. Лучше лёгкий SVG/CSS/canvas-объект.

## Состояния Orb

| Состояние | Визуальное поведение |
|---|---|
| Idle | медленное почти незаметное дыхание |
| Listening | расширяющиеся волны / реакция на уровень микрофона |
| Thinking | медленное вращение внутреннего градиента |
| Working | направленный поток или мягкая орбитальная линия |
| Speaking | синхронизация с амплитудой TTS |
| Success | короткая вспышка cyan/green, затем возврат в idle |
| Error | короткий приглушённый красный импульс |
| Offline | статичный приглушённый контур |

## Voice overlay

По горячей клавише или wake word показывать отдельный маленький overlay по центру снизу.

```text
          ◉
      Слушаю…

«Открой Obsidian и создай заметку»
```

Требования:

- overlay не должен блокировать работу;
- лёгкий blur заднего фона;
- появляется за 160–220ms;
- исчезает после завершения или отмены;
- можно раскрыть в полноценное окно;
- поддерживать barge-in и кнопку stop;
- при обработке показывать не «Thinking…» бесконечно, а понятный статус:
  - «Ищу приложение…»
  - «Создаю заметку…»
  - «Проверяю результат…»

---

# 8. Экран активной задачи

Когда Rynne работает, пользователь должен видеть, что происходит, но не утонуть в технических деталях.

## Верхняя часть

```text
Создаю исследование по MCP для Obsidian
Выполняется · 01:24

[ Пауза ] [ Отменить ] [ Скрыть детали ]
```

## План

Показывать простой план с состояниями:

```text
✓ Собрать источники
✓ Проверить официальную документацию
● Сформировать заметку в Obsidian
○ Добавить citations
```

- completed — тихий success;
- active — акцентная точка + subtle pulse;
- pending — muted;
- failed — error + причина;
- skipped — нейтрально.

## Activity timeline

- Время, tool, человеческое описание, статус.
- Группировать однотипные действия.
- Не показывать 20 однотипных `read_file`.
- Пример:  
  `Прочитала 8 файлов проекта · 3.2 сек`  
  Раскрытие — список файлов.

## Управление задачей

- Pause;
- Resume;
- Cancel;
- Retry failed step;
- Approve;
- Open artifact;
- Copy result;
- Export report.

Кнопка Cancel не должна быть яркой destructive-кнопкой, пока пользователь не hover/focus.

---

# 9. Approval / опасные действия

Подтверждения должны выглядеть серьёзно и понятно.

Пример:

```text
Rynne просит разрешение

Отправить письмо 3 получателям?

Кому:
• alice@example.com
• team@example.com
• manager@example.com

Что будет отправлено:
«Черновик отчёта за неделю…»

[ Отклонить ] [ Изменить ] [ Отправить ]
```

Требования:

- Ясно писать: **что**, **куда**, **кому**, **какие последствия**.
- Для удаления — показать количество файлов и суммарный размер.
- Для команд терминала — показывать саму команду и working directory.
- Для установки приложения — источник, версию и права.
- Для сетевых действий — домен и тип передаваемых данных.
- Не делать confirm modal «красивым, но непонятным».
- По умолчанию фокус — на безопасной кнопке, не на подтверждении.
- Поддержать «разрешить один раз», «разрешить для этой сессии», «всегда для этого skill».

---

# 10. Артефакты и результаты

Rynne создаёт файлы, заметки, код, отчёты и исследования. Их нужно показывать красиво.

## Artifact cards

Поддержать типы:

- файл;
- папка;
- заметка Obsidian;
- ссылка;
- изображение;
- PDF;
- таблица;
- кодовый patch;
- git diff;
- PR;
- Jira issue;
- исследовательский отчёт;
- workflow.

Пример:

```text
┌──────────────────────────────────────┐
│  ◈  MCP Research.md                  │
│  Obsidian note · 4 min ago           │
│                                      │
│  Краткое исследование с 6 ссылками   │
│                                      │
│  [ Открыть ] [ Показать ] [ ⋯ ]      │
└──────────────────────────────────────┘
```

## Code / diff viewer

- Нормальный monospace.
- Подсветка синтаксиса.
- Inline diff.
- Строки добавления / удаления.
- Кнопки:
  - Copy;
  - Open file;
  - Revert;
  - Show full diff.
- Большие diffs по умолчанию сворачивать.
- Не грузить весь репозиторий в DOM.

---

# 11. Настройки

Сделай настройки как профессиональную control center панель, а не длинную свалку checkbox-ов.

Разделы:

- General;
- Appearance;
- Voice;
- Models;
- MCP integrations;
- Permissions;
- Memory;
- Automations;
- Privacy;
- Notifications;
- Advanced;
- Diagnostics.

## Models

Показывать:

- активный provider;
- активную модель;
- fallback chain;
- состояние ключей без показа секретов;
- quota / cooldown;
- latency и success rate;
- режимы `Fast`, `Balanced`, `Quality`, `Local only`.

## MCP integrations

Каждый сервер — отдельная карточка:

```text
GitHub MCP
Connected · 12 tools available
Last check: 15 sec ago

[ Configure ] [ View tools ] [ Disable ]
```

Нужны:

- health;
- транспорт;
- список tools;
- permissions;
- последнее использование;
- error diagnostics;
- reconnect;
- log view.

---

# 12. Анимации

## Общие правила

Анимации должны создавать ощущение скорости и качества, а не тормозить работу.

### Разрешённые длительности

```text
micro interaction: 120–160ms
button / hover:    140–180ms
panel transition:  180–260ms
modal:             180–240ms
page transition:   220–320ms
orb ambient loop:  3–8s
```

### Easing

Использовать естественные easing curves, например:

```text
ease-out: cubic-bezier(0.16, 1, 0.3, 1)
ease-in-out: cubic-bezier(0.65, 0, 0.35, 1)
```

Не использовать стандартный медленный `ease` везде.

## Что анимировать

- hover и press у кнопок;
- раскрытие tool details;
- переключение вкладок;
- открытие sidebar/right panel;
- появление сообщений;
- переход статуса задачи;
- появление approval card;
- drag-and-drop зоны;
- Rynne Orb;
- voice waveform;
- лёгкий success feedback;
- reorder списка задач при необходимости.

## Что не анимировать или анимировать минимально

- длинные списки сообщений;
- большой scroll;
- каждую строку tool output;
- таблицы;
- большие файлы;
- частые streaming updates;
- layout всей страницы при каждом статусе.

## Accessibility

- Добавить `Reduce motion`.
- При включённом reduce motion:
  - убрать looping анимации;
  - убрать масштабирование;
  - заменить переходы на короткие fade;
  - voice waveform можно оставить статичным индикатором.

---

# 13. Производительность

Это desktop-агент. UI должен быть быстрым даже во время активной работы моделей, TTS, OCR, браузера и MCP.

Требования:

- Не блокировать UI thread.
- Виртуализировать длинные списки сообщений, activity и логов.
- Не рендерить большие raw tool outputs без явного раскрытия.
- Дебаунсить частые события прогресса.
- Батчить streaming updates в UI.
- Не перерисовывать весь chat при каждом tool event.
- Избегать тяжёлого blur на больших поверхностях.
- Blur применять только на overlay/modal и в разумных пределах.
- Не использовать тяжёлую 3D-графику для Orb.
- Не делать бесконечные layout calculations.
- Измерить FPS и memory usage на длинной сессии.
- Не допустить утечки подписок на backend events.
- Корректно cleanup всех listeners, timers и animation loops.

---

# 14. Горячие клавиши

Минимум:

| Hotkey | Действие |
|---|---|
| `Ctrl/Cmd + K` | открыть command palette |
| `Ctrl/Cmd + N` | новая задача |
| `Ctrl/Cmd + Enter` | отправить запрос |
| `Esc` | закрыть overlay/modal или отменить ввод |
| `Ctrl/Cmd + Shift + Space` | открыть голосовой overlay |
| `Ctrl/Cmd + Shift + V` | вставить plain text / voice toggle, если не конфликтует |
| `Ctrl/Cmd + ,` | настройки |

Проверить конфликты с Windows и текущими hotkeys Rynne.

---

# 15. Command Palette

Сделай красивую command palette в стиле Raycast.

Команды:

- New task;
- Start voice mode;
- Open recent session;
- Search memories;
- Search files;
- Run skill;
- Open settings;
- Switch model mode;
- Toggle privacy;
- Toggle autonomy;
- Pause active task;
- Cancel active task;
- Open diagnostics;
- Open MCP manager.

Требования:

- fuzzy search;
- навигация клавиатурой;
- recent commands;
- pinned commands;
- показывать hotkeys;
- не блокировать текущую активную задачу;
- поддержать команды вида `> Run skill: ...`.

---

# 16. Реализационный план

## Этап 1 — аудит и фундамент

1. Изучи существующий UI stack и структуру проекта.
2. Найди реальные источники:
   - chat messages;
   - task state;
   - tool events;
   - approval requests;
   - voice state;
   - model/provider state;
   - MCP health;
   - artifacts.
3. Опиши кратко точки интеграции до начала работ.
4. Добавь design tokens.
5. Добавь базовые UI primitives:
   - Button;
   - IconButton;
   - Input;
   - Card;
   - Badge;
   - Tooltip;
   - Modal;
   - Dropdown;
   - Tabs;
   - Toggle;
   - Skeleton;
   - Toast;
   - EmptyState;
   - StatusIndicator.
6. Добавь единый слой анимаций.
7. Добавь поддержку reduced motion.
8. Не меняй логику агента.

## Этап 2 — shell приложения

1. Реализуй AppShell.
2. Добавь sidebar.
3. Добавь центральную workspace-зону.
4. Добавь collapsible context/activity panel.
5. Добавь responsive поведение для маленькой ширины окна.
6. Добавь command palette.
7. Добавь глобальные hotkeys.

## Этап 3 — chat и composer

1. Переработай chat messages.
2. Сделай composer.
3. Реализуй streaming UI без дёргания.
4. Добавь attachments.
5. Добавь artifact cards.
6. Добавь tool activity cards.
7. Добавь error cards и retry actions.
8. Добавь skeleton/loading states.

## Этап 4 — task execution UI

1. Подключи реальный task lifecycle.
2. Реализуй task header.
3. Реализуй plan view.
4. Реализуй timeline.
5. Реализуй pause/resume/cancel.
6. Реализуй approval UI.
7. Реализуй verification/result states.
8. Добавь понятное отображение partial success.

## Этап 5 — голос

1. Создай Rynne Orb.
2. Подключи реальные voice states.
3. Добавь mic level animation.
4. Создай compact voice overlay.
5. Поддержи stop/cancel.
6. Добавь визуальную связь TTS state ↔ Orb.
7. Проверь, что overlay не мешает активным приложениям.

## Этап 6 — control center

1. Settings layout.
2. Models dashboard.
3. MCP manager.
4. Permission manager.
5. Memory viewer.
6. Diagnostics screen.
7. Логи и traces — только в advanced/debug разделе.

## Этап 7 — polish и quality

1. Пройтись по всем hover/focus/disabled/error/loading состояниям.
2. Проверить keyboard navigation.
3. Проверить screen reader labels, если stack это поддерживает.
4. Проверить reduced motion.
5. Проверить UI на 100%, 125%, 150%, 200% Windows scaling.
6. Проверить маленькое и большое окно.
7. Проверить долгую сессию с сотнями activity events.
8. Проверить offline/provider error/MCP error.
9. Проверить, что все анимации не снижают responsiveness.
10. Сделать screenshots до/после и краткий UI changelog.

---

# 17. Definition of Done

Фича считается законченной, только если:

- UI выглядит цельно, а не как набор разрозненных карточек.
- Есть единая дизайн-система и токены.
- Chat, task state, tool activity, approval, voice и artifacts получают **реальные** backend-данные.
- Нет заглушек, которые выдают себя за работающие функции.
- Интерфейс работает без лагов при стриминге и фоновых задачах.
- Длинные логи и tool outputs не убивают производительность.
- Все опасные действия имеют понятный approval UI.
- Можно работать только с клавиатуры.
- Есть `Reduce motion`.
- Нет ломания старого backend-кода.
- Все новые UI-модули имеют базовые тесты.
- Добавлены минимум:
  - unit tests для state-to-UI mapping;
  - tests на approval actions;
  - tests на task lifecycle;
  - tests на cleanup subscriptions;
  - smoke test запуска UI.
- Агент предоставляет финальный отчёт:
  - какие файлы изменены;
  - какие реальные backend events подключены;
  - что осталось за feature flag;
  - какие тесты запущены;
  - какие команды использовать для запуска и проверки.

- [x] Cloud Remote approvals: local PermissionManager publishes requests to Mini App and consumes one-time owner decisions.
- [x] Cloud Remote Live Execution streams real ToolRunner starts, outcomes, failures and durations into a persistent task replay.
