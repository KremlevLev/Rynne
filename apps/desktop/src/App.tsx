import {
  Activity,
  Bot,
  ChevronRight,
  Command,
  Cpu,
  History,
  MessageSquare,
  Mic,
  Plus,
  Radio,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
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
type TimelineItem = {
  id: string;
  kind: "user" | "assistant" | "tool" | "suggestion";
  title: string;
  body?: string;
  status?: "working" | "success" | "error";
  action?: string;
};

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

function eventToItem(event: NovaEvent): TimelineItem | null {
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
        body: text(payload, "text", text(payload, "message")),
        status: payload.success === false ? "error" : "success",
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
  const endRef = useRef<HTMLDivElement>(null);

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
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [timeline]);

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

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-orb"><Sparkles size={17} /></div>
          <div>
            <strong>Nova</strong>
            <span><i className={`status-dot ${connection}`} />{connection === "connected" ? "На связи" : "Нет связи с Core"}</span>
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
            <div className="conversation">
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
              <div ref={endRef} />
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
                  placeholder={connection === "connected" ? "Попроси Nova или поставь задачу…" : "Подключение к Nova Core…"}
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
          <div className={busy ? "large-orb working" : "large-orb"}>
            <span />
            <Sparkles size={23} />
          </div>
          <strong>{busy ? "Nova работает" : "Nova готова"}</strong>
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
