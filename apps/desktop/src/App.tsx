import {
  Activity,
  Bot,
  ChevronRight,
  Command,
  Cpu,
  History,
  KeyRound,
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
  Trash2,
  Workflow,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { JsonObject, NovaEvent } from "./protocol";
import {
  createNovaTransport,
  type ConnectionState,
  type NovaTransport,
  type ProviderKeySummary,
  type ProviderName,
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
  actionLabel?: string;
  proactiveEventId?: string;
  proactiveContextKey?: string;
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
    label: "Красивый · максимум",
    shortLabel: "Красивый",
    description: "Максимум визуала: живая активность, контекстная панель и атмосферные эффекты.",
  },
  {
    key: "focus",
    label: "Сбалансированный · средний",
    shortLabel: "Средний",
    description: "Компактная навигация и больше места для диалога без правой панели.",
  },
  {
    key: "console",
    label: "Лёгкий · минимум",
    shortLabel: "Лёгкий",
    description: "Минимальная нагрузка и чистая рабочая область в духе CLI.",
  },
];

export const PROVIDER_OPTIONS: ReadonlyArray<{
  key: ProviderName;
  label: string;
  description: string;
  placeholder: string;
}> = [
  {
    key: "groq",
    label: "Groq",
    description: "GPT OSS 120B для текста и tools · Qwen для изображений · Whisper STT",
    placeholder: "gsk_…",
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    description: "Резервные модели и независимые лимиты",
    placeholder: "sk-or-v1-…",
  },
  {
    key: "gemini",
    label: "Google Gemini",
    description: "Дополнительный маршрут для vision и сложных задач",
    placeholder: "AIza…",
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
    behavior: "auto",
  });
}

export function isConversationNearBottom(
  element: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight">,
  threshold = 96,
): boolean {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
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
        actionLabel: text(payload, "action_label", "Помочь с этим"),
        proactiveEventId: text(payload, "event_id"),
        proactiveContextKey: text(payload, "source_key"),
      };
    case "proactive_check_result":
      return {
        id,
        kind: "assistant",
        title: "Nova рядом",
        body: text(payload, "message", "Проверка активного окна завершена."),
        status: text(payload, "outcome") === "blocked" ? "error" : "success",
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
  const [inputMode, setInputMode] = useState("sleep");
  const [voicePending, setVoicePending] = useState(false);
  const [proactivePending, setProactivePending] = useState(false);
  const [proactiveStatus, setProactiveStatus] = useState("Выключено");
  const [proactivePhase, setProactivePhase] = useState("idle");
  const [wakeWordAvailable, setWakeWordAvailable] = useState(false);
  const [wakeWord, setWakeWord] = useState("Нова");
  const [wakeSensitivity, setWakeSensitivity] = useState(0.72);
  const [provider, setProvider] = useState<ProviderName>("groq");
  const [apiKey, setApiKey] = useState("");
  const [providerKeys, setProviderKeys] = useState<ProviderKeySummary[]>([]);
  const [providerKeysLoading, setProviderKeysLoading] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState("");
  const [uiMode, setUiMode] = useState<UiMode>(() => (
    readUiMode(typeof window === "undefined" ? null : window.localStorage)
  ));
  const conversationRef = useRef<HTMLDivElement>(null);
  const followConversationRef = useRef(true);
  const [followingConversation, setFollowingConversation] = useState(true);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [confirmingSuggestionId, setConfirmingSuggestionId] = useState<string | null>(null);
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
            const mode = event.payload.input_mode;
            if (typeof mode === "string") setInputMode(mode);
            setWakeWordAvailable(event.payload.wake_word_available === true);
            const configuredWakeWord = event.payload.wake_word;
            if (typeof configuredWakeWord === "string" && configuredWakeWord) {
              setWakeWord(configuredWakeWord);
            }
            const sensitivity = event.payload.wake_word_sensitivity;
            if (typeof sensitivity === "number") setWakeSensitivity(sensitivity);
            setVoicePending(false);
            setProactivePending(false);
            if (event.payload.proactive_vision_enabled === true) {
              setActiveTool("Nova рядом наблюдает за активным окном");
              setProactiveStatus((current) => current === "Выключено" ? "Запускаю…" : current);
            } else {
              setProactiveStatus("Выключено");
              setProactivePhase("idle");
            }
          }
          if (event.event_type === "proactive_status") {
            const phase = text(event.payload, "phase", "idle");
            const message = text(event.payload, "message", "Nova рядом работает");
            setProactivePhase(phase);
            setProactiveStatus(message);
            if (phase === "scanning") setActiveTool(message);
            if (phase === "checked") setActiveTool("Ожидаю задачу");
          }
          if (event.event_type === "proactive_confirmation_resolved") {
            const eventId = text(event.payload, "event_id");
            setTimeline((current) => current.filter(
              (item) => item.proactiveEventId !== eventId,
            ));
            setConfirmingSuggestionId(null);
          }
          if (event.event_type === "voice_status") {
            setVoiceStatus(text(event.payload, "message"));
            setVoicePending(false);
          }
          if (event.event_type === "task_progress") {
            const value = event.payload.progress;
            if (typeof value === "number") setTaskProgress(value);
          }
          if (event.event_type === "command_result") {
            const message = text(event.payload, "message");
            if (event.payload.success === false && message) {
              setSettingsStatus(message);
            }
            setVoicePending(false);
            setProactivePending(false);
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
    if (followConversationRef.current) {
      scrollConversationToBottom(conversationRef.current);
    }
  }, [timeline]);

  function handleConversationScroll() {
    const element = conversationRef.current;
    if (!element) return;
    const nearBottom = isConversationNearBottom(element);
    followConversationRef.current = nearBottom;
    setFollowingConversation(nearBottom);
  }

  function resumeConversationFollow() {
    followConversationRef.current = true;
    setFollowingConversation(true);
    scrollConversationToBottom(conversationRef.current);
  }

  useEffect(() => {
    if (connection === "connected") void refreshProviderKeys();
  }, [connection]);

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
    setProactivePending(true);
    try {
      await transport.send("set_preference", {
        key: "proactive_vision_enabled",
        value: next,
      });
    } catch (error) {
      setProactivePending(false);
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось переключить Nova рядом.",
      );
    }
  }

  async function acceptSuggestion(item: TimelineItem) {
    if (!item.action || busy || connection !== "connected") return;
    await transport.send("submit_user_request", {
      text: item.action,
      proactive_event_id: item.proactiveEventId ?? "",
      proactive_context_key: item.proactiveContextKey ?? "",
    });
    setTimeline((current) => current.filter((candidate) => candidate.id !== item.id));
    setConfirmingSuggestionId(null);
  }

  async function dismissSuggestion(item: TimelineItem) {
    setTimeline((current) => current.filter((candidate) => candidate.id !== item.id));
    setConfirmingSuggestionId(null);
    if (!item.proactiveEventId || connection !== "connected") return;
    try {
      await transport.send("proactive_feedback", {
        event_id: item.proactiveEventId,
        feedback: "dismissed",
      });
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось сохранить реакцию.",
      );
    }
  }

  async function toggleVoice() {
    setVoicePending(true);
    try {
      await transport.send("toggle_voice_mode");
    } catch (error) {
      setVoicePending(false);
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось включить микрофон.",
      );
    }
  }

  async function selectInputMode(mode: "wake_word" | "continuous" | "sleep") {
    setVoicePending(true);
    setVoiceStatus(mode === "wake_word" ? `Включаю ожидание «${wakeWord}»…` : "Переключаю микрофон…");
    try {
      await transport.send("set_input_mode", { input_mode: mode });
    } catch (error) {
      setVoicePending(false);
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось переключить голосовой режим.",
      );
    }
  }

  async function setWakeWordSensitivity(value: number) {
    const normalized = Math.min(1, Math.max(0, value));
    setWakeSensitivity(normalized);
    try {
      await transport.send("set_wake_word_sensitivity", { value: normalized });
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось изменить чувствительность.",
      );
    }
  }

  async function runProactiveCheck() {
    setProactiveStatus("Переключитесь на нужное окно — снимок через 3 секунды…");
    setProactivePhase("scanning");
    try {
      await transport.send("run_proactive_check");
    } catch (error) {
      setProactivePhase("error");
      setProactiveStatus(
        error instanceof Error ? error.message : "Не удалось запустить проверку.",
      );
    }
  }

  async function refreshProviderKeys() {
    setProviderKeysLoading(true);
    try {
      setProviderKeys(await transport.listProviderKeys());
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось получить список ключей.",
      );
    } finally {
      setProviderKeysLoading(false);
    }
  }

  async function addProviderKey() {
    if (apiKey.trim().length < 12) return;
    setSettingsStatus("Добавляю ключ и перезапускаю Nova Core…");
    try {
      await transport.addProviderKey(provider, apiKey.trim());
      setApiKey("");
      setSettingsStatus("Ключ добавлен. Nova Core переподключается.");
      await refreshProviderKeys();
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось сохранить API-ключ.",
      );
    }
  }

  async function removeProviderKey(key: ProviderKeySummary) {
    if (!key.removable) return;
    setSettingsStatus(`Удаляю ключ ${key.hint}…`);
    try {
      await transport.removeProviderKey(key.provider, key.index);
      setSettingsStatus("Ключ удалён. Nova Core переподключается.");
      await refreshProviderKeys();
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : "Не удалось удалить API-ключ.",
      );
    }
  }

  const voiceActive = inputMode === "continuous";
  const wakeWordActive = inputMode === "wake_word";
  const proactiveBadge = proactivePending
    ? "…"
    : !proactive
      ? "Выкл"
      : proactivePhase === "scanning"
        ? "Смотрю"
        : proactivePhase === "investigating"
          ? "Исследую"
          : proactivePhase === "error"
            ? "Ошибка"
            : "Вкл";

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
          <Plus size={16} /> <span>Новая задача</span> <kbd>Ctrl N</kbd>
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
          <nav className="compact-nav" aria-label="Разделы Nova">
            {nav.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                className={view === key ? "active" : ""}
                onClick={() => setView(key)}
                aria-label={label}
                title={label}
              >
                <Icon size={15} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
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
                    <span>{option.shortLabel}</span>
                  </button>
                );
              })}
            </div>
            <button
              className={proactive ? "proactive active" : "proactive"}
              onClick={() => void toggleProactive()}
              disabled={proactivePending || connection !== "connected"}
              title={proactive
                ? proactiveStatus
                : "Включить наблюдение за активным окном"}
            >
              <Radio size={15} />
              Nova рядом
              <span>{proactiveBadge}</span>
            </button>
            <button className="icon-button" aria-label="Команды"><Command size={18} /></button>
          </div>
        </header>

        {view === "dialog" ? (
          <div className="dialog-view">
            <div
              className="conversation"
              ref={conversationRef}
              onScroll={handleConversationScroll}
              tabIndex={0}
              aria-label="История диалога"
            >
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
                    {item.kind === "suggestion" && (
                      <div className="suggestion-actions">
                        {item.action && (
                          confirmingSuggestionId === item.id ? (
                            <button className="suggestion-action confirm" onClick={() => void acceptSuggestion(item)}>
                              Да, выполнить <ChevronRight size={15} />
                            </button>
                          ) : (
                            <button className="suggestion-action" onClick={() => setConfirmingSuggestionId(item.id)}>
                              {item.actionLabel ?? "Помочь с этим"} <ChevronRight size={15} />
                            </button>
                          )
                        )}
                        <button className="suggestion-dismiss" onClick={() => void dismissSuggestion(item)}>
                          Не сейчас
                        </button>
                      </div>
                    )}
                    {item.kind === "suggestion" && confirmingSuggestionId === item.id && (
                      <small className="voice-confirm-hint">Или скажите: «Нова, давай»</small>
                    )}
                  </div>
                </article>
              ))}
            </div>

            {!followingConversation && (
              <button className="jump-to-latest" onClick={resumeConversationFollow}>
                К новым сообщениям
                <ChevronRight size={14} />
              </button>
            )}

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
                  <button
                    className={voiceActive ? "attach voice-active" : "attach"}
                    onClick={() => void toggleVoice()}
                    disabled={voicePending || connection !== "connected"}
                    aria-label={voiceActive ? "Остановить голосовой ввод" : "Включить голосовой ввод"}
                    aria-pressed={voiceActive}
                    title={voiceActive ? "Nova слушает · нажмите, чтобы остановить" : "Включить микрофон"}
                  >
                    <Mic size={18} />
                  </button>
                  {busy ? (
                    <button className="send stop" onClick={() => transport.send("cancel_current_request")} aria-label="Остановить"><Square size={14} /></button>
                  ) : (
                    <button className="send" onClick={() => void send()} disabled={!composer.trim()} aria-label="Отправить"><Send size={17} /></button>
                  )}
                </div>
              </div>
              {(voiceActive || wakeWordActive) && (
                <div className="voice-status" role="status">
                  <span />{voiceStatus || (wakeWordActive ? `Жду «${wakeWord}» · Vosk локально` : "Слушаю микрофон…")}
                </div>
              )}
              <div className="composer-voice-modes" aria-label="Режим микрофона">
                <button
                  className={wakeWordActive ? "active" : ""}
                  onClick={() => void selectInputMode("wake_word")}
                  disabled={voicePending || !wakeWordAvailable || connection !== "connected"}
                  title={`Ждать обращение «${wakeWord}»`}
                ><Radio size={12} /> Wake «{wakeWord}»</button>
                <button
                  className={voiceActive ? "active" : ""}
                  onClick={() => void selectInputMode("continuous")}
                  disabled={voicePending || connection !== "connected"}
                ><Mic size={12} /> Слушать</button>
                <button
                  className={inputMode === "sleep" ? "active" : ""}
                  onClick={() => void selectInputMode("sleep")}
                  disabled={voicePending || connection !== "connected"}
                ><Square size={10} /> Выкл.</button>
              </div>
              <p>Enter — отправить · Shift Enter — новая строка · Nova попросит подтверждение перед рискованным действием</p>
            </div>
          </div>
        ) : view === "settings" ? (
          <div className="settings-view">
            <div className="settings-card appearance-card">
              <span className="settings-icon"><LayoutDashboard size={22} /></span>
              <div>
                <span className="eyebrow">ВНЕШНИЙ ВИД</span>
                <h2>Три режима интерфейса</h2>
                <p>Выберите лёгкий, средний или красивый UI. Режим сохраняется на этом компьютере и переключается мгновенно, без перезапуска Core.</p>
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
            <div className="settings-card voice-card">
              <span className="settings-icon"><Mic size={22} /></span>
              <div>
                <span className="eyebrow">ГОЛОС И WAKE WORD</span>
                <h2>Позови Nova без кнопки</h2>
                <p>Vosk локально слушает только короткое слово «{wakeWord}». После него Nova записывает команду и передаёт её обычному STT.</p>
              </div>
              <div className="voice-mode-options">
                <button
                  className={wakeWordActive ? "active" : ""}
                  onClick={() => void selectInputMode("wake_word")}
                  disabled={voicePending || !wakeWordAvailable}
                >
                  <Radio size={16} />
                  <span><strong>Wake word</strong><small>{wakeWordAvailable ? `Всегда жду «${wakeWord}»` : "Vosk-модель не установлена"}</small></span>
                </button>
                <button
                  className={voiceActive ? "active" : ""}
                  onClick={() => void selectInputMode("continuous")}
                  disabled={voicePending}
                >
                  <Mic size={16} />
                  <span><strong>Непрерывно</strong><small>Слушать речь без ключевого слова</small></span>
                </button>
                <button
                  className={inputMode === "sleep" ? "active" : ""}
                  onClick={() => void selectInputMode("sleep")}
                  disabled={voicePending}
                >
                  <Square size={15} />
                  <span><strong>Выключено</strong><small>Не использовать микрофон</small></span>
                </button>
              </div>
              {!wakeWordAvailable && (
                <p className="settings-status">Для dev-режима выполните: <code>python -m vosk_install</code>, затем перезапустите Core.</p>
              )}
              {wakeWordAvailable && (
                <label className="wake-sensitivity">
                  <span><strong>Чувствительность</strong><small>{Math.round(wakeSensitivity * 100)}% · выше — легче услышать обращение</small></span>
                  <input
                    type="range"
                    min="0.35"
                    max="1"
                    step="0.05"
                    value={wakeSensitivity}
                    onChange={(event) => setWakeSensitivity(Number(event.target.value))}
                    onPointerUp={(event) => void setWakeWordSensitivity(Number(event.currentTarget.value))}
                    onKeyUp={(event) => void setWakeWordSensitivity(Number(event.currentTarget.value))}
                  />
                </label>
              )}
            </div>
            <div className="settings-card proactive-card">
              <span className="settings-icon"><Radio size={22} /></span>
              <div>
                <span className="eyebrow">NOVA РЯДОМ</span>
                <h2>Понятная проверка активного окна</h2>
                <p>Режим делает локальный снимок активного окна, ищет видимую проблему и предлагает действие. Ничего не нажимает и не отправляет без вашего подтверждения.</p>
              </div>
              <div className="proactive-test">
                <span className={`proactive-phase ${proactivePhase}`}><i />{proactive ? proactiveStatus : "Режим выключен"}</span>
                <button onClick={() => void runProactiveCheck()} disabled={!proactive || ["scanning", "investigating"].includes(proactivePhase) || connection !== "connected"}>
                  Проверить сейчас
                </button>
              </div>
            </div>
            <div className="settings-card provider-card">
              <span className="settings-icon"><KeyRound size={22} /></span>
              <div>
                <span className="eyebrow">МОДЕЛЬНЫЕ ПРОВАЙДЕРЫ</span>
                <h2>Пул API-ключей</h2>
                <p>Добавляйте сколько угодно ключей Groq, OpenRouter и Gemini. Начало и конец каждого ключа видны для проверки, середина скрыта; полный секрет никогда не отправляется в React UI.</p>
              </div>
              <div className="provider-pool">
                {PROVIDER_OPTIONS.map((option) => {
                  const keys = providerKeys.filter((key) => key.provider === option.key);
                  return (
                    <section className="provider-group" key={option.key}>
                      <header>
                        <span>
                          <strong>{option.label}</strong>
                          <small>{option.description}</small>
                        </span>
                        <b>{providerKeysLoading ? "…" : keys.length}</b>
                      </header>
                      <div className="provider-key-list">
                        {keys.length === 0 ? (
                          <p>Ключей пока нет</p>
                        ) : keys.map((key) => (
                          <div className="provider-key" key={`${key.provider}-${key.source}-${key.index}-${key.hint}`}>
                            <span>
                              <code>{key.hint}</code>
                              <small>{key.source === "nova" ? "Добавлен в Nova" : "Системная переменная"}</small>
                            </span>
                            {key.removable && (
                              <button
                                onClick={() => void removeProviderKey(key)}
                                aria-label={`Удалить ключ ${key.hint}`}
                                title="Удалить ключ"
                              >
                                <Trash2 size={13} />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  );
                })}
              </div>
              <div className="provider-add-row">
              <label>
                Провайдер
                <select
                  value={provider}
                  onChange={(event) => setProvider(event.target.value as ProviderName)}
                >
                  {PROVIDER_OPTIONS.map((option) => (
                    <option key={option.key} value={option.key}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label>
                Новый API-ключ
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void addProviderKey();
                  }}
                  placeholder={PROVIDER_OPTIONS.find((option) => option.key === provider)?.placeholder}
                  autoComplete="off"
                />
              </label>
              </div>
              <button
                className="save-settings"
                onClick={() => void addProviderKey()}
                disabled={apiKey.trim().length < 12}
              >
                <Plus size={15} /> Добавить ключ
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
          <header><span><Radio size={15} />Nova рядом</span><small>{proactiveBadge}</small></header>
          <div className={`nearby-status ${proactivePhase}`}>
            <i />
            <span>{proactive ? proactiveStatus : "Наблюдение выключено"}</span>
          </div>
          <button
            className="nearby-check"
            onClick={() => void runProactiveCheck()}
            disabled={!proactive || ["scanning", "investigating"].includes(proactivePhase) || connection !== "connected"}
          >
            Проверить через 3 секунды
          </button>
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
