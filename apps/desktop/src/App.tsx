import {
  Activity,
  Bot,
  ChevronRight,
  Command,
  Cpu,
  History,
  LayoutDashboard,
  MessageSquare,
  Mic,
  PanelLeftClose,
  Plus,
  Radio,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
  Workflow,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { JsonObject, NovaEvent } from "./protocol";
import {
  createNovaTransport,
  type ConnectionState,
  type NovaTransport,
} from "./transport";

type ViewKey = "dialog" | "tasks" | "automations" | "settings";
export type UiMode = "aura" | "focus" | "console";
type TimelineItem = {
  id: string;
  kind: "user" | "assistant" | "tool" | "suggestion";
  title: string;
  body?: string;
  status?: "working" | "success" | "error";
  action?: string;
};

const UI_MODE_STORAGE_KEY = "nova.ui-mode";

export const UI_MODE_OPTIONS: ReadonlyArray<{
  key: UiMode;
  label: string;
  shortLabel: string;
  description: string;
}> = [
  {
    key: "aura",
    label: "Aura · максимум",
    shortLabel: "Aura",
    description: "Полный интерфейс с живой активностью, статусами и атмосферными эффектами.",
  },
  {
    key: "focus",
    label: "Focus · баланс",
    shortLabel: "Focus",
    description: "Компактная навигация и больше места для диалога без правой панели.",
  },
  {
    key: "console",
    label: "Console · минимум",
    shortLabel: "Console",
    description: "Чистая рабочая область в духе CLI: быстро, плотно и без визуального шума.",
  },
];

export function normalizeUiMode(value: unknown): UiMode {
  return UI_MODE_OPTIONS.some((option) => option.key === value)
    ? value as UiMode
    : "aura";
}

export function readUiMode(
  storage: Pick<Storage, "getItem"> | null = null,
): UiMode {
  try {
    return normalizeUiMode(storage?.getItem(UI_MODE_STORAGE_KEY));
  } catch {
    return "aura";
  }
}

export function writeUiMode(
  storage: Pick<Storage, "setItem"> | null,
  mode: UiMode,
): void {
  try {
    storage?.setItem(UI_MODE_STORAGE_KEY, mode);
  } catch {
    // Presentation preference must never make the desktop UI unavailable.
  }
}

const runtimeLabels: Record<string, string> = {
  "СПИТ": "Nova готова",
  "СЛУШАЕТ": "Nova слушает",
  "РАСПОЗНАЕТ": "Распознаю речь",
  "ДУМАЕТ": "Nova думает",
  "ЖДЕТ РАЗРЕШЕНИЕ": "Нужно подтверждение",
  "ВЫПОЛНЯЕТ": "Nova выполняет",
  "ГОВОРИТ": "Nova отвечает",
  "ОШИБКА": "Нужна проверка",
  "ЗАВЕРШАЕТ РАБОТУ": "Nova завершает работу",
};

export function runtimePresentation(state: unknown): {
  label: string;
  working: boolean;
} {
  const value = typeof state === "string" ? state : "СПИТ";
  return {
    label: runtimeLabels[value] ?? "Nova готова",
    working: !["СПИТ", "ОШИБКА", "ЗАВЕРШАЕТ РАБОТУ"].includes(value),
  };
}

export function scrollConversationToBottom(
  element: Pick<HTMLElement, "scrollTo" | "scrollHeight"> | null,
): void {
  if (!element) return;
  element.scrollTo({
    top: element.scrollHeight,
    behavior: "smooth",
  });
}

const nav = [
  { key: "dialog" as const, label: "Диалог", icon: MessageSquare },
  { key: "tasks" as const, label: "Задачи", icon: Activity },
  { key: "automations" as const, label: "Автоматизации", icon: Workflow },
  { key: "settings" as const, label: "Настройки", icon: Settings },
];

const initialTimeline: TimelineItem[] = [
  {
    id: "welcome",
    kind: "assistant",
    title: "Nova",
    body: "Я рядом. Поставь задачу — найду нужные инструменты, выполню и покажу проверяемый результат.",
    status: "success",
  },
];

function text(payload: JsonObject, key: string, fallback = ""): string {
  const value = payload[key];
  return typeof value === "string" ? value : fallback;
}

export function eventToItem(event: NovaEvent): TimelineItem | null {
  const id = `${event.event_type}_${event.created_at}_${Math.random()}`;
  const payload = event.payload;
  switch (event.event_type) {
    case "user_message":
      return { id, kind: "user", title: "Вы", body: text(payload, "text") };
    case "assistant_message":
      return {
        id,
        kind: "assistant",
        title: "Nova",
        body: text(
          payload,
          "display_text",
          text(payload, "text", text(payload, "message")),
        ),
        status: payload.success === false ? "error" : "success",
      };
    case "request_failed":
      return {
        id,
        kind: "assistant",
        title: "Nova",
        body: text(payload, "error", "Не удалось выполнить запрос."),
        status: "error",
      };
    case "tool_started":
      return {
        id,
        kind: "tool",
        title: text(payload, "description", "Запускаю инструмент"),
        body: text(payload, "tool_name"),
        status: "working",
      };
    case "tool_completed":
      return {
        id,
        kind: "tool",
        title: payload.success === false ? "Инструмент завершился с ошибкой" : "Действие выполнено",
        body: text(payload, "tool_name"),
        status: payload.success === false ? "error" : "success",
      };
    case "proactive_suggestion":
      return {
        id,
        kind: "suggestion",
        title: text(payload, "title", "Nova заметила кое-что"),
        body: text(payload, "message"),
        action: text(payload, "suggested_request"),
      };
    default:
      return null;
  }
}

export function App() {
  const transport = useMemo<NovaTransport>(() => createNovaTransport(), []);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [view, setView] = useState<ViewKey>("dialog");
  const [timeline, setTimeline] = useState<TimelineItem[]>(initialTimeline);
  const [composer, setComposer] = useState("");
  const [busy, setBusy] = useState(false);
  const [proactive, setProactive] = useState(false);
  const [activeTool, setActiveTool] = useState("Ожидаю задачу");
  const [taskProgress, setTaskProgress] = useState(0);
  const [runtimeState, setRuntimeState] = useState("СПИТ");
  const [provider, setProvider] = useState("groq");
  const [apiKey, setApiKey] = useState("");
  const [settingsStatus, setSettingsStatus] = useState("");
  const [uiMode, setUiMode] = useState<UiMode>(() => (
    readUiMode(typeof window === "undefined" ? null : window.localStorage)
  ));
  const conversationRef = useRef<HTMLDivElement>(null);
  const runtime = runtimePresentation(runtimeState);

  useEffect(() => {
    let dispose: () => void = () => undefined;
    let mounted = true;
    transport
      .connect(
        (event) => {
          if (!mounted) return;
          const item = eventToItem(event);
          if (item) setTimeline((current) => [...current, item]);
          if (event.event_type === "request_started") setBusy(true);
          if (event.event_type === "runtime") {
            const state = event.payload.state;
            if (typeof state === "string") setRuntimeState(state);
          }
          if (event.event_type === "assistant_message" || event.event_type === "request_failed") {
            setBusy(false);
            setActiveTool("Ожидаю задачу");
          }
          if (event.event_type === "tool_started") {
            setActiveTool(text(event.payload, "description", text(event.payload, "tool_name")));
          }
          if (event.event_type === "preferences") {
            setProactive(event.payload.proactive_vision_enabled === true);
          }
          if (event.event_type === "task_progress") {
            const value = event.payload.progress;
            if (typeof value === "number") setTaskProgress(value);
          }
        },
        setConnection,
      )
      .then((cleanup) => {
        if (mounted) dispose = cleanup;
        else cleanup();
      });
    return () => {
      mounted = false;
      dispose();
    };
  }, [transport]);

  useEffect(() => {
    scrollConversationToBottom(conversationRef.current);
  }, [timeline]);

  useEffect(() => {
    writeUiMode(
      typeof window === "undefined" ? null : window.localStorage,
      uiMode,
    );
  }, [uiMode]);

  async function send(request = composer) {
    const value = request.trim();
    if (!value || busy || connection !== "connected") return;
    setComposer("");
    await transport.send("submit_user_request", { text: value });
  }

  async function toggleProactive() {
    const next = !proactive;
    setProactive(next);
    await transport.send("set_preference", {
      key: "proactive_vision_enabled",
      value: next,
    });
  }

  async function saveProvider() {
    if (apiKey.trim().length < 12) return;
    setSettingsStatus("Сохраняю и перезапускаю Nova Core…");
    try {
      await transport.configureProvider(provider, apiKey.trim());
      setApiKey("");
      setSettingsStatus("Ключ сохранён. Nova Core переподключается.");
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось сохранить API-ключ.",
      );
    }
  }

  return (
    <main className={`app-shell ui-${uiMode}`} data-ui-mode={uiMode}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-orb"><Sparkles size={17} /></div>
          <div>
            <strong>Nova</strong>
            <span>
              <i className={`status-dot ${connection}`} />
              {connection === "connected"
                ? "На связи"
                : connection === "connecting"
                  ? "Core запускается…"
                  : "Core не отвечает"}
            </span>
          </div>
        </div>

        <button className="new-task" onClick={() => transport.send("new_task")}>
          <Plus size={16} /> Новая задача <kbd>Ctrl N</kbd>
        </button>

        <nav>
          <p className="eyebrow">Рабочее пространство</p>
          {nav.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={view === key ? "nav-item active" : "nav-item"}
              onClick={() => setView(key)}
            >
              <Icon size={17} />
              <span>{label}</span>
              {key === "tasks" && <b>1</b>}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="core-load">
            <span><Cpu size={15} /> Nova Core</span>
            <small>GPT OSS 120B</small>
          </div>
          <button className="profile"><span>ЛК</span><div><strong>Lev</strong><small>Локальный профиль</small></div></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">ПЕРСОНАЛЬНЫЙ АГЕНТ</span>
            <h1>{nav.find((item) => item.key === view)?.label}</h1>
          </div>
          <div className="top-actions">
            <div className="mode-switcher" aria-label="Режим интерфейса">
              {UI_MODE_OPTIONS.map((option) => {
                const Icon = option.key === "aura"
                  ? LayoutDashboard
                  : option.key === "focus"
                    ? PanelLeftClose
                    : Terminal;
                return (
                  <button
                    key={option.key}
                    className={uiMode === option.key ? "active" : ""}
                    onClick={() => setUiMode(option.key)}
                    aria-label={option.label}
                    aria-pressed={uiMode === option.key}
                    title={option.label}
                  >
                    <Icon size={14} />
                  </button>
                );
              })}
            </div>
            <button className={proactive ? "proactive active" : "proactive"} onClick={toggleProactive}>
              <Radio size={15} />
              Nova рядом
              <span>{proactive ? "Вкл" : "Выкл"}</span>
            </button>
            <button className="icon-button" aria-label="Команды"><Command size={18} /></button>
          </div>
        </header>

        {view === "dialog" ? (
          <>
            <div className="conversation" ref={conversationRef}>
              <div className="date-divider"><span>Сегодня</span></div>
              {timeline.map((item) => (
                <article key={item.id} className={`timeline ${item.kind}`}>
                  <div className="timeline-rail">
                    <span className={`timeline-dot ${item.status ?? ""}`}>
                      {item.kind === "tool" ? <Wrench size={13} /> : item.kind === "suggestion" ? <Sparkles size={13} /> : item.kind === "assistant" ? <Bot size={13} /> : null}
                    </span>
                  </div>
                  <div className="timeline-content">
                    <div className="message-meta">
                      <strong>{item.title}</strong>
                      {item.status === "working" && <span className="working-label">выполняется</span>}
                      {item.status === "success" && item.kind === "tool" && <span className="success-label">готово</span>}
                    </div>
                    {item.body && <p>{item.body}</p>}
                    {item.kind === "tool" && <small className="tool-id">{item.body}</small>}
                    {item.action && (
                      <button className="suggestion-action" onClick={() => send(item.action)}>
                        Помочь с этим <ChevronRight size={15} />
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>

            <div className="composer-wrap">
              <div className={busy ? "composer busy" : "composer"}>
                <textarea
                  value={composer}
                  onChange={(event) => setComposer(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void send();
                    }
                  }}
                  placeholder={
                    connection === "connected"
                      ? "Попроси Nova или поставь задачу…"
                      : connection === "connecting"
                        ? "Nova Core запускается…"
                        : "Core не отвечает — Nova продолжает переподключение…"
                  }
                  disabled={connection !== "connected"}
                  rows={1}
                />
                <div className="composer-actions">
                  <button className="attach" aria-label="Голосовой ввод"><Mic size={18} /></button>
                  {busy ? (
                    <button className="send stop" onClick={() => transport.send("cancel_current_request")} aria-label="Остановить"><Square size={14} /></button>
                  ) : (
                    <button className="send" onClick={() => void send()} disabled={!composer.trim()} aria-label="Отправить"><Send size={17} /></button>
                  )}
                </div>
              </div>
              <p>Enter — отправить · Shift Enter — новая строка · Nova попросит подтверждение перед рискованным действием</p>
            </div>
          </>
        ) : view === "settings" ? (
          <div className="settings-view">
            <div className="settings-card appearance-card">
              <span className="settings-icon"><LayoutDashboard size={22} /></span>
              <div>
                <span className="eyebrow">ВНЕШНИЙ ВИД</span>
                <h2>Как Nova занимает экран</h2>
                <p>Режим сохраняется на этом компьютере и переключается мгновенно, без перезапуска Core.</p>
              </div>
              <div className="appearance-options">
                {UI_MODE_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    className={uiMode === option.key ? "appearance-option active" : "appearance-option"}
                    onClick={() => setUiMode(option.key)}
                    aria-pressed={uiMode === option.key}
                  >
                    <span className={`mode-preview ${option.key}`}>
                      <i /><i /><i />
                    </span>
                    <span>
                      <strong>{option.label}</strong>
                      <small>{option.description}</small>
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <div className="settings-card">
              <span className="settings-icon"><Settings size={22} /></span>
              <div>
                <span className="eyebrow">МОДЕЛЬНЫЙ ПРОВАЙДЕР</span>
                <h2>Подключить Nova</h2>
                <p>Ключ хранится только в пользовательских данных Nova на этом компьютере и не попадает в чат.</p>
              </div>
              <label>
                Провайдер
                <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                  <option value="groq">Groq · GPT OSS 120B</option>
                  <option value="openrouter">OpenRouter</option>
                  <option value="gemini">Google Gemini</option>
                </select>
              </label>
              <label>
                API-ключ
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void saveProvider();
                  }}
                  placeholder={provider === "groq" ? "gsk_…" : "Вставьте API-ключ"}
                  autoComplete="off"
                />
              </label>
              <button
                className="save-settings"
                onClick={() => void saveProvider()}
                disabled={apiKey.trim().length < 12}
              >
                Сохранить и подключить
              </button>
              {settingsStatus && <p className="settings-status">{settingsStatus}</p>}
            </div>
          </div>
        ) : (
          <div className="view-placeholder">
            <span><History size={26} /></span>
            <h2>{nav.find((item) => item.key === view)?.label}</h2>
            <p>Экран подключается к существующим событиям Nova Core следующим инкрементом.</p>
            <button onClick={() => setView("dialog")}>Вернуться в диалог</button>
          </div>
        )}
      </section>

      <aside className="context-panel">
        <div className="context-header">
          <div><span className="live-pulse" />Живая активность</div>
          <button className="icon-button"><ChevronRight size={17} /></button>
        </div>

        <section className="agent-state">
          <div className={busy || runtime.working ? "large-orb working" : "large-orb"}>
            <span />
            <Sparkles size={23} />
          </div>
          <strong>{busy ? "Nova работает" : runtime.label}</strong>
          <p>{activeTool}</p>
        </section>

        <section className="context-card">
          <header><span><Activity size={15} />Текущая задача</span><small>{taskProgress || (busy ? 42 : 0)}%</small></header>
          <div className="progress"><i style={{ width: `${taskProgress || (busy ? 42 : 0)}%` }} /></div>
          <ul>
            <li className="done"><ShieldCheck size={14} />Контекст собран</li>
            <li className={busy ? "active" : ""}><span />Выполнение инструментов</li>
            <li><span />Проверка результата</li>
          </ul>
        </section>

        <section className="context-card compact">
          <header><span><Wrench size={15} />Возможности</span></header>
          <div className="capabilities">
            <span>Windows</span><span>Browser</span><span>Files</span><span>MCP</span><span>Vision</span>
          </div>
        </section>
      </aside>
    </main>
  );
}
