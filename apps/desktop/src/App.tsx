import {
  Activity,
  BookOpen,
  Bot,
  ChevronRight,
  Command,
  Cpu,
  History,
  KeyRound,
  Languages,
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
import { Guide, type GuideLocale } from "./Guide";

type ViewKey = "dialog" | "tasks" | "automations" | "guide" | "settings";
export type UiMode = "aura" | "focus" | "console";
export type UiLocale = GuideLocale;
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
const UI_LOCALE_STORAGE_KEY = "nova.ui-locale";

function tx(locale: UiLocale, ru: string, en: string): string {
  return locale === "ru" ? ru : en;
}

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

export function uiModeOptions(locale: UiLocale) {
  if (locale === "ru") return UI_MODE_OPTIONS;
  return [
    {
      key: "aura" as const,
      label: "Beautiful · maximum",
      shortLabel: "Beautiful",
      description: "Full visual experience with live activity, context panel, and atmospheric effects.",
    },
    {
      key: "focus" as const,
      label: "Balanced · medium",
      shortLabel: "Balanced",
      description: "Compact navigation and more room for the conversation without the right panel.",
    },
    {
      key: "console" as const,
      label: "Light · minimum",
      shortLabel: "Light",
      description: "Minimum resource use and a clean CLI-inspired workspace.",
    },
  ];
}

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

function providerOptions(locale: UiLocale) {
  if (locale === "ru") return PROVIDER_OPTIONS;
  return [
    { ...PROVIDER_OPTIONS[0], description: "GPT OSS 120B for text and tools · Qwen for images · Whisper STT" },
    { ...PROVIDER_OPTIONS[1], description: "Fallback models and independent rate limits" },
    { ...PROVIDER_OPTIONS[2], description: "Additional route for vision and complex tasks" },
  ];
}

export function normalizeUiLocale(value: unknown): UiLocale {
  return value === "en" ? "en" : "ru";
}

export function readUiLocale(
  storage: Pick<Storage, "getItem"> | null = null,
): UiLocale {
  try {
    return normalizeUiLocale(storage?.getItem(UI_LOCALE_STORAGE_KEY));
  } catch {
    return "ru";
  }
}

export function writeUiLocale(
  storage: Pick<Storage, "setItem"> | null,
  locale: UiLocale,
): void {
  try {
    storage?.setItem(UI_LOCALE_STORAGE_KEY, locale);
  } catch {
    // Locale is a presentation preference and must not break the UI.
  }
}

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

const runtimeLabelsRu: Record<string, string> = {
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

const runtimeLabelsEn: Record<string, string> = {
  "СПИТ": "Nova is ready",
  "СЛУШАЕТ": "Nova is listening",
  "РАСПОЗНАЕТ": "Recognizing speech",
  "ДУМАЕТ": "Nova is thinking",
  "ЖДЕТ РАЗРЕШЕНИЕ": "Confirmation required",
  "ВЫПОЛНЯЕТ": "Nova is working",
  "ГОВОРИТ": "Nova is speaking",
  "ОШИБКА": "Check required",
  "ЗАВЕРШАЕТ РАБОТУ": "Nova is shutting down",
};

export function runtimePresentation(state: unknown, locale: UiLocale = "ru"): {
  label: string;
  working: boolean;
} {
  const value = typeof state === "string" ? state : "СПИТ";
  return {
    label: (locale === "ru" ? runtimeLabelsRu : runtimeLabelsEn)[value]
      ?? tx(locale, "Nova готова", "Nova is ready"),
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

function navigation(locale: UiLocale) {
  return [
    { key: "dialog" as const, label: tx(locale, "Диалог", "Chat"), icon: MessageSquare },
    { key: "tasks" as const, label: tx(locale, "Задачи", "Tasks"), icon: Activity },
    { key: "automations" as const, label: tx(locale, "Автоматизации", "Automations"), icon: Workflow },
    { key: "guide" as const, label: tx(locale, "Памятка", "Guide"), icon: BookOpen },
    { key: "settings" as const, label: tx(locale, "Настройки", "Settings"), icon: Settings },
  ];
}

function initialTimeline(locale: UiLocale): TimelineItem[] { return [
  {
    id: "welcome",
    kind: "assistant",
    title: "Nova",
    body: tx(
      locale,
      "Я рядом. Поставь задачу — найду нужные инструменты, выполню и покажу проверяемый результат.",
      "I'm here. Give me a task — I'll find the right tools, execute it, and show a verifiable result.",
    ),
    status: "success",
  },
]};

function text(payload: JsonObject, key: string, fallback = ""): string {
  const value = payload[key];
  return typeof value === "string" ? value : fallback;
}

export function eventToItem(event: NovaEvent, locale: UiLocale = "ru"): TimelineItem | null {
  const id = `${event.event_type}_${event.created_at}_${Math.random()}`;
  const payload = event.payload;
  switch (event.event_type) {
    case "user_message":
      return { id, kind: "user", title: tx(locale, "Вы", "You"), body: text(payload, "text") };
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
        body: text(payload, "error", tx(locale, "Не удалось выполнить запрос.", "The request could not be completed.")),
        status: "error",
      };
    case "tool_started":
      return {
        id,
        kind: "tool",
        title: text(payload, "description", tx(locale, "Запускаю инструмент", "Running tool")),
        body: text(payload, "tool_name"),
        status: "working",
      };
    case "tool_completed":
      return {
        id,
        kind: "tool",
        title: payload.success === false
          ? tx(locale, "Инструмент завершился с ошибкой", "Tool failed")
          : tx(locale, "Действие выполнено", "Action completed"),
        body: text(payload, "tool_name"),
        status: payload.success === false ? "error" : "success",
      };
    case "proactive_suggestion":
      return {
        id,
        kind: "suggestion",
        title: text(payload, "title", tx(locale, "Nova заметила кое-что", "Nova noticed something")),
        body: text(payload, "message"),
        action: text(payload, "suggested_request"),
        actionLabel: text(payload, "action_label", tx(locale, "Помочь с этим", "Help with this")),
        proactiveEventId: text(payload, "event_id"),
        proactiveContextKey: text(payload, "source_key"),
      };
    case "proactive_check_result":
      return {
        id,
        kind: "assistant",
        title: tx(locale, "Nova рядом", "Nova Nearby"),
        body: text(payload, "message", tx(locale, "Проверка активного окна завершена.", "Active-window check completed.")),
        status: text(payload, "outcome") === "blocked" ? "error" : "success",
      };
    default:
      return null;
  }
}

export function App() {
  const transport = useMemo<NovaTransport>(() => createNovaTransport(), []);
  const [locale, setLocale] = useState<UiLocale>(() => (
    readUiLocale(typeof window === "undefined" ? null : window.localStorage)
  ));
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [view, setView] = useState<ViewKey>("dialog");
  const [timeline, setTimeline] = useState<TimelineItem[]>(() => initialTimeline(locale));
  const [composer, setComposer] = useState("");
  const [busy, setBusy] = useState(false);
  const [proactive, setProactive] = useState(false);
  const [activeTool, setActiveTool] = useState(() => tx(locale, "Ожидаю задачу", "Waiting for a task"));
  const [taskProgress, setTaskProgress] = useState(0);
  const [runtimeState, setRuntimeState] = useState("СПИТ");
  const [inputMode, setInputMode] = useState("sleep");
  const [voicePending, setVoicePending] = useState(false);
  const [proactivePending, setProactivePending] = useState(false);
  const [proactiveStatus, setProactiveStatus] = useState(() => tx(locale, "Выключено", "Off"));
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
  const localeRef = useRef(locale);
  const followConversationRef = useRef(true);
  const [followingConversation, setFollowingConversation] = useState(true);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [confirmingSuggestionId, setConfirmingSuggestionId] = useState<string | null>(null);
  const runtime = runtimePresentation(runtimeState, locale);
  const nav = navigation(locale);
  const modes = uiModeOptions(locale);
  const providers = providerOptions(locale);

  useEffect(() => {
    let dispose: () => void = () => undefined;
    let mounted = true;
    transport
      .connect(
        (event) => {
          if (!mounted) return;
          const item = eventToItem(event, localeRef.current);
          if (item) setTimeline((current) => [...current, item]);
          if (event.event_type === "request_started") setBusy(true);
          if (event.event_type === "runtime") {
            const state = event.payload.state;
            if (typeof state === "string") setRuntimeState(state);
          }
          if (event.event_type === "assistant_message" || event.event_type === "request_failed") {
            setBusy(false);
            setActiveTool(tx(localeRef.current, "Ожидаю задачу", "Waiting for a task"));
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
              setActiveTool(tx(localeRef.current, "Nova рядом наблюдает за активным окном", "Nova Nearby is observing the active window"));
              setProactiveStatus((current) => ["Выключено", "Off"].includes(current)
                ? tx(localeRef.current, "Запускаю…", "Starting…")
                : current);
            } else {
              setProactiveStatus(tx(localeRef.current, "Выключено", "Off"));
              setProactivePhase("idle");
            }
          }
          if (event.event_type === "proactive_status") {
            const phase = text(event.payload, "phase", "idle");
            const message = text(event.payload, "message", tx(localeRef.current, "Nova рядом работает", "Nova Nearby is running"));
            setProactivePhase(phase);
            setProactiveStatus(message);
            if (phase === "scanning") setActiveTool(message);
            if (phase === "checked") setActiveTool(tx(localeRef.current, "Ожидаю задачу", "Waiting for a task"));
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

  useEffect(() => {
    localeRef.current = locale;
    writeUiLocale(
      typeof window === "undefined" ? null : window.localStorage,
      locale,
    );
    if (typeof document !== "undefined") document.documentElement.lang = locale;
    if (!busy) setActiveTool(tx(locale, "Ожидаю задачу", "Waiting for a task"));
    if (!proactive) setProactiveStatus(tx(locale, "Выключено", "Off"));
    setTimeline((current) => current.map((item) => (
      item.id === "welcome" ? initialTimeline(locale)[0] : item
    )));
  }, [locale]);

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
        error instanceof Error ? error.message : tx(locale, "Не удалось переключить Nova рядом.", "Could not toggle Nova Nearby."),
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
        error instanceof Error ? error.message : tx(locale, "Не удалось сохранить реакцию.", "Could not save feedback."),
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
        error instanceof Error ? error.message : tx(locale, "Не удалось включить микрофон.", "Could not enable the microphone."),
      );
    }
  }

  async function selectInputMode(mode: "wake_word" | "continuous" | "sleep") {
    setVoicePending(true);
    setVoiceStatus(mode === "wake_word"
      ? tx(locale, `Включаю ожидание «${wakeWord}»…`, `Enabling wake word “${wakeWord}”…`)
      : tx(locale, "Переключаю микрофон…", "Switching microphone mode…"));
    try {
      await transport.send("set_input_mode", { input_mode: mode });
    } catch (error) {
      setVoicePending(false);
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось переключить голосовой режим.", "Could not switch voice mode."),
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
        error instanceof Error ? error.message : tx(locale, "Не удалось изменить чувствительность.", "Could not update sensitivity."),
      );
    }
  }

  async function runProactiveCheck() {
    setProactiveStatus(tx(locale, "Переключитесь на нужное окно — снимок через 3 секунды…", "Switch to the target window — capture starts in 3 seconds…"));
    setProactivePhase("scanning");
    try {
      await transport.send("run_proactive_check");
    } catch (error) {
      setProactivePhase("error");
      setProactiveStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось запустить проверку.", "Could not start the check."),
      );
    }
  }

  async function refreshProviderKeys() {
    setProviderKeysLoading(true);
    try {
      setProviderKeys(await transport.listProviderKeys());
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось получить список ключей.", "Could not load provider keys."),
      );
    } finally {
      setProviderKeysLoading(false);
    }
  }

  async function addProviderKey() {
    if (apiKey.trim().length < 12) return;
    setSettingsStatus(tx(locale, "Добавляю ключ и перезапускаю Nova Core…", "Adding the key and restarting Nova Core…"));
    try {
      await transport.addProviderKey(provider, apiKey.trim());
      setApiKey("");
      setSettingsStatus(tx(locale, "Ключ добавлен. Nova Core переподключается.", "Key added. Nova Core is reconnecting."));
      await refreshProviderKeys();
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось сохранить API-ключ.", "Could not save the API key."),
      );
    }
  }

  async function removeProviderKey(key: ProviderKeySummary) {
    if (!key.removable) return;
    setSettingsStatus(tx(locale, `Удаляю ключ ${key.hint}…`, `Removing key ${key.hint}…`));
    try {
      await transport.removeProviderKey(key.provider, key.index);
      setSettingsStatus(tx(locale, "Ключ удалён. Nova Core переподключается.", "Key removed. Nova Core is reconnecting."));
      await refreshProviderKeys();
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось удалить API-ключ.", "Could not remove the API key."),
      );
    }
  }

  const voiceActive = inputMode === "continuous";
  const wakeWordActive = inputMode === "wake_word";
  const proactiveBadge = proactivePending
    ? "…"
    : !proactive
      ? tx(locale, "Выкл", "Off")
      : proactivePhase === "scanning"
        ? tx(locale, "Смотрю", "Scanning")
        : proactivePhase === "investigating"
          ? tx(locale, "Исследую", "Investigating")
          : proactivePhase === "error"
            ? tx(locale, "Ошибка", "Error")
            : tx(locale, "Вкл", "On");

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
                ? tx(locale, "На связи", "Connected")
                : connection === "connecting"
                  ? tx(locale, "Core запускается…", "Core is starting…")
                  : tx(locale, "Core не отвечает", "Core is not responding")}
            </span>
          </div>
        </div>

        <button className="new-task" onClick={() => transport.send("new_task")}>
          <Plus size={16} /> <span>{tx(locale, "Новая задача", "New task")}</span> <kbd>Ctrl N</kbd>
        </button>

        <nav>
          <p className="eyebrow">{tx(locale, "Рабочее пространство", "Workspace")}</p>
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
          <button className="profile"><span>ЛК</span><div><strong>Lev</strong><small>{tx(locale, "Локальный профиль", "Local profile")}</small></div></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">{tx(locale, "ПЕРСОНАЛЬНЫЙ АГЕНТ", "PERSONAL AGENT")}</span>
            <h1>{nav.find((item) => item.key === view)?.label}</h1>
          </div>
          <nav className="compact-nav" aria-label={tx(locale, "Разделы Nova", "Nova sections")}>
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
            <div className="mode-switcher" aria-label={tx(locale, "Режим интерфейса", "Interface mode")}>
              {modes.map((option) => {
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
            <div className="language-switcher" aria-label={tx(locale, "Язык интерфейса", "Interface language")}>
              <Languages size={14} />
              <button className={locale === "ru" ? "active" : ""} onClick={() => setLocale("ru")}>RU</button>
              <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}>EN</button>
            </div>
            <button
              className={proactive ? "proactive active" : "proactive"}
              onClick={() => void toggleProactive()}
              disabled={proactivePending || connection !== "connected"}
              title={proactive
                ? proactiveStatus
                : tx(locale, "Включить наблюдение за активным окном", "Enable active-window observation")}
            >
              <Radio size={15} />
              {tx(locale, "Nova рядом", "Nova Nearby")}
              <span>{proactiveBadge}</span>
            </button>
            <button className="icon-button" aria-label={tx(locale, "Команды", "Commands")} onClick={() => setView("guide")}><Command size={18} /></button>
          </div>
        </header>

        {view === "dialog" ? (
          <div className="dialog-view">
            <div
              className="conversation"
              ref={conversationRef}
              onScroll={handleConversationScroll}
              tabIndex={0}
              aria-label={tx(locale, "История диалога", "Conversation history")}
            >
              <div className="date-divider"><span>{tx(locale, "Сегодня", "Today")}</span></div>
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
                      {item.status === "working" && <span className="working-label">{tx(locale, "выполняется", "working")}</span>}
                      {item.status === "success" && item.kind === "tool" && <span className="success-label">{tx(locale, "готово", "done")}</span>}
                    </div>
                    {item.body && <p>{item.body}</p>}
                    {item.kind === "tool" && <small className="tool-id">{item.body}</small>}
                    {item.kind === "suggestion" && (
                      <div className="suggestion-actions">
                        {item.action && (
                          confirmingSuggestionId === item.id ? (
                            <button className="suggestion-action confirm" onClick={() => void acceptSuggestion(item)}>
                              {tx(locale, "Да, выполнить", "Yes, run it")} <ChevronRight size={15} />
                            </button>
                          ) : (
                            <button className="suggestion-action" onClick={() => setConfirmingSuggestionId(item.id)}>
                              {item.actionLabel ?? tx(locale, "Помочь с этим", "Help with this")} <ChevronRight size={15} />
                            </button>
                          )
                        )}
                        <button className="suggestion-dismiss" onClick={() => void dismissSuggestion(item)}>
                          {tx(locale, "Не сейчас", "Not now")}
                        </button>
                      </div>
                    )}
                    {item.kind === "suggestion" && confirmingSuggestionId === item.id && (
                      <small className="voice-confirm-hint">{tx(locale, "Или скажите: «Нова, давай»", "Or say: “Nova, go ahead”")}</small>
                    )}
                  </div>
                </article>
              ))}
            </div>

            {!followingConversation && (
              <button className="jump-to-latest" onClick={resumeConversationFollow}>
                {tx(locale, "К новым сообщениям", "Jump to latest")}
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
                      ? tx(locale, "Попроси Nova или поставь задачу…", "Ask Nova or delegate a task…")
                      : connection === "connecting"
                        ? tx(locale, "Nova Core запускается…", "Nova Core is starting…")
                        : tx(locale, "Core не отвечает — Nova продолжает переподключение…", "Core is not responding — Nova keeps reconnecting…")
                  }
                  disabled={connection !== "connected"}
                  rows={1}
                />
                <div className="composer-actions">
                  <button
                    className={voiceActive ? "attach voice-active" : "attach"}
                    onClick={() => void toggleVoice()}
                    disabled={voicePending || connection !== "connected"}
                    aria-label={voiceActive ? tx(locale, "Остановить голосовой ввод", "Stop voice input") : tx(locale, "Включить голосовой ввод", "Start voice input")}
                    aria-pressed={voiceActive}
                    title={voiceActive ? tx(locale, "Nova слушает · нажмите, чтобы остановить", "Nova is listening · click to stop") : tx(locale, "Включить микрофон", "Enable microphone")}
                  >
                    <Mic size={18} />
                  </button>
                  {busy ? (
                    <button className="send stop" onClick={() => transport.send("cancel_current_request")} aria-label={tx(locale, "Остановить", "Stop")}><Square size={14} /></button>
                  ) : (
                    <button className="send" onClick={() => void send()} disabled={!composer.trim()} aria-label={tx(locale, "Отправить", "Send")}><Send size={17} /></button>
                  )}
                </div>
              </div>
              {(voiceActive || wakeWordActive) && (
                <div className="voice-status" role="status">
                  <span />{voiceStatus || (wakeWordActive
                    ? tx(locale, `Жду «${wakeWord}» · Vosk локально`, `Waiting for “${wakeWord}” · local Vosk`)
                    : tx(locale, "Слушаю микрофон…", "Listening…"))}
                </div>
              )}
              <div className="composer-voice-modes" aria-label={tx(locale, "Режим микрофона", "Microphone mode")}>
                <button
                  className={wakeWordActive ? "active" : ""}
                  onClick={() => void selectInputMode("wake_word")}
                  disabled={voicePending || !wakeWordAvailable || connection !== "connected"}
                  title={tx(locale, `Ждать обращение «${wakeWord}»`, `Wait for “${wakeWord}”`)}
                ><Radio size={12} /> Wake «{wakeWord}»</button>
                <button
                  className={voiceActive ? "active" : ""}
                  onClick={() => void selectInputMode("continuous")}
                  disabled={voicePending || connection !== "connected"}
                ><Mic size={12} /> {tx(locale, "Слушать", "Listen")}</button>
                <button
                  className={inputMode === "sleep" ? "active" : ""}
                  onClick={() => void selectInputMode("sleep")}
                  disabled={voicePending || connection !== "connected"}
                ><Square size={10} /> {tx(locale, "Выкл.", "Off")}</button>
              </div>
              <p>{tx(
                locale,
                "Enter — отправить · Shift Enter — новая строка · Nova попросит подтверждение перед рискованным действием",
                "Enter — send · Shift Enter — new line · Nova asks for confirmation before risky actions",
              )}</p>
            </div>
          </div>
        ) : view === "guide" ? (
          <Guide locale={locale} />
        ) : view === "settings" ? (
          <div className="settings-view">
            <div className="settings-card language-card">
              <span className="settings-icon"><Languages size={22} /></span>
              <div>
                <span className="eyebrow">{tx(locale, "ЯЗЫК", "LANGUAGE")}</span>
                <h2>{tx(locale, "Язык интерфейса", "Interface language")}</h2>
                <p>{tx(
                  locale,
                  "Переключение применяется мгновенно и сохраняется на этом компьютере. Ответы Nova остаются на языке вашего запроса.",
                  "The change applies immediately and is saved on this computer. Nova still answers in the language of your request.",
                )}</p>
              </div>
              <div className="locale-options">
                <button className={locale === "ru" ? "active" : ""} onClick={() => setLocale("ru")}><strong>Русский</strong><small>RU</small></button>
                <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}><strong>English</strong><small>EN</small></button>
              </div>
              <div className="tts-roadmap-note">
                <Mic size={16} />
                <span><strong>{tx(locale, "Следом: язык и голос TTS", "Next: TTS language and voice")}</strong><small>{tx(locale, "Отдельные настройки RU/EN голоса появятся здесь и не будут зависеть от языка UI.", "Separate RU/EN voice controls will live here and remain independent from the UI language.")}</small></span>
              </div>
            </div>
            <div className="settings-card appearance-card">
              <span className="settings-icon"><LayoutDashboard size={22} /></span>
              <div>
                <span className="eyebrow">{tx(locale, "ВНЕШНИЙ ВИД", "APPEARANCE")}</span>
                <h2>{tx(locale, "Три режима интерфейса", "Three interface modes")}</h2>
                <p>{tx(locale, "Выберите лёгкий, средний или красивый UI. Режим сохраняется на этом компьютере и переключается мгновенно, без перезапуска Core.", "Choose a light, balanced, or beautiful UI. The mode is saved on this computer and switches instantly without restarting Core.")}</p>
              </div>
              <div className="appearance-options">
                {modes.map((option) => (
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
                <span className="eyebrow">{tx(locale, "ГОЛОС И WAKE WORD", "VOICE AND WAKE WORD")}</span>
                <h2>{tx(locale, "Позови Nova без кнопки", "Call Nova without pressing a button")}</h2>
                <p>{tx(locale, `Vosk локально слушает только короткое слово «${wakeWord}». После него Nova записывает команду и передаёт её обычному STT.`, `Vosk listens locally only for the short word “${wakeWord}”. Nova then records the command and passes it to regular STT.`)}</p>
              </div>
              <div className="voice-mode-options">
                <button
                  className={wakeWordActive ? "active" : ""}
                  onClick={() => void selectInputMode("wake_word")}
                  disabled={voicePending || !wakeWordAvailable}
                >
                  <Radio size={16} />
                  <span><strong>Wake word</strong><small>{wakeWordAvailable ? tx(locale, `Всегда жду «${wakeWord}»`, `Always wait for “${wakeWord}”`) : tx(locale, "Vosk-модель не установлена", "Vosk model is not installed")}</small></span>
                </button>
                <button
                  className={voiceActive ? "active" : ""}
                  onClick={() => void selectInputMode("continuous")}
                  disabled={voicePending}
                >
                  <Mic size={16} />
                  <span><strong>{tx(locale, "Непрерывно", "Continuous")}</strong><small>{tx(locale, "Слушать речь без ключевого слова", "Listen without a wake word")}</small></span>
                </button>
                <button
                  className={inputMode === "sleep" ? "active" : ""}
                  onClick={() => void selectInputMode("sleep")}
                  disabled={voicePending}
                >
                  <Square size={15} />
                  <span><strong>{tx(locale, "Выключено", "Off")}</strong><small>{tx(locale, "Не использовать микрофон", "Do not use the microphone")}</small></span>
                </button>
              </div>
              {!wakeWordAvailable && (
                <p className="settings-status">{tx(locale, "Для dev-режима выполните", "In development, run")}: <code>python -m vosk_install</code>, {tx(locale, "затем перезапустите Core.", "then restart Core.")}</p>
              )}
              {wakeWordAvailable && (
                <label className="wake-sensitivity">
                  <span><strong>{tx(locale, "Чувствительность", "Sensitivity")}</strong><small>{Math.round(wakeSensitivity * 100)}% · {tx(locale, "выше — легче услышать обращение", "higher values detect the wake word more easily")}</small></span>
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
                <span className="eyebrow">{tx(locale, "NOVA РЯДОМ", "NOVA NEARBY")}</span>
                <h2>{tx(locale, "Понятная проверка активного окна", "Transparent active-window checks")}</h2>
                <p>{tx(locale, "Режим делает локальный снимок активного окна, ищет видимую проблему и предлагает действие. Ничего не нажимает и не отправляет без вашего подтверждения.", "The mode captures the active window locally, detects visible problems, and suggests an action. It never clicks or submits without your confirmation.")}</p>
              </div>
              <div className="proactive-test">
                <span className={`proactive-phase ${proactivePhase}`}><i />{proactive ? proactiveStatus : tx(locale, "Режим выключен", "Mode is off")}</span>
                <button onClick={() => void runProactiveCheck()} disabled={!proactive || ["scanning", "investigating"].includes(proactivePhase) || connection !== "connected"}>
                  {tx(locale, "Проверить сейчас", "Check now")}
                </button>
              </div>
            </div>
            <div className="settings-card provider-card">
              <span className="settings-icon"><KeyRound size={22} /></span>
              <div>
                <span className="eyebrow">{tx(locale, "МОДЕЛЬНЫЕ ПРОВАЙДЕРЫ", "MODEL PROVIDERS")}</span>
                <h2>{tx(locale, "Пул API-ключей", "API key pool")}</h2>
                <p>{tx(locale, "Добавляйте сколько угодно ключей Groq, OpenRouter и Gemini. Начало и конец каждого ключа видны для проверки, середина скрыта; полный секрет никогда не отправляется в React UI.", "Add any number of Groq, OpenRouter, and Gemini keys. The prefix and suffix remain visible while the middle is masked; the full secret never enters the React UI.")}</p>
              </div>
              <div className="provider-pool">
                {providers.map((option) => {
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
                          <p>{tx(locale, "Ключей пока нет", "No keys yet")}</p>
                        ) : keys.map((key) => (
                          <div className="provider-key" key={`${key.provider}-${key.source}-${key.index}-${key.hint}`}>
                            <span>
                              <code>{key.hint}</code>
                              <small>{key.source === "nova" ? tx(locale, "Добавлен в Nova", "Added in Nova") : tx(locale, "Системная переменная", "System environment variable")}</small>
                            </span>
                            {key.removable && (
                              <button
                                onClick={() => void removeProviderKey(key)}
                                aria-label={tx(locale, `Удалить ключ ${key.hint}`, `Remove key ${key.hint}`)}
                                title={tx(locale, "Удалить ключ", "Remove key")}
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
                {tx(locale, "Провайдер", "Provider")}
                <select
                  value={provider}
                  onChange={(event) => setProvider(event.target.value as ProviderName)}
                >
                  {providers.map((option) => (
                    <option key={option.key} value={option.key}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label>
                {tx(locale, "Новый API-ключ", "New API key")}
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void addProviderKey();
                  }}
                  placeholder={providers.find((option) => option.key === provider)?.placeholder}
                  autoComplete="off"
                />
              </label>
              </div>
              <button
                className="save-settings"
                onClick={() => void addProviderKey()}
                disabled={apiKey.trim().length < 12}
              >
                <Plus size={15} /> {tx(locale, "Добавить ключ", "Add key")}
              </button>
              {settingsStatus && <p className="settings-status">{settingsStatus}</p>}
            </div>
          </div>
        ) : (
          <div className="view-placeholder">
            <span><History size={26} /></span>
            <h2>{nav.find((item) => item.key === view)?.label}</h2>
            <p>{tx(locale, "Экран подключается к существующим событиям Nova Core следующим инкрементом.", "This screen will connect to existing Nova Core events in the next increment.")}</p>
            <button onClick={() => setView("dialog")}>{tx(locale, "Вернуться в диалог", "Return to chat")}</button>
          </div>
        )}
      </section>

      <aside className="context-panel">
        <div className="context-header">
          <div><span className="live-pulse" />{tx(locale, "Живая активность", "Live activity")}</div>
          <button className="icon-button"><ChevronRight size={17} /></button>
        </div>

        <section className="agent-state">
          <div className={busy || runtime.working ? "large-orb working" : "large-orb"}>
            <span />
            <Sparkles size={23} />
          </div>
          <strong>{busy ? tx(locale, "Nova работает", "Nova is working") : runtime.label}</strong>
          <p>{activeTool}</p>
        </section>

        <section className="context-card">
          <header><span><Activity size={15} />{tx(locale, "Текущая задача", "Current task")}</span><small>{taskProgress || (busy ? 42 : 0)}%</small></header>
          <div className="progress"><i style={{ width: `${taskProgress || (busy ? 42 : 0)}%` }} /></div>
          <ul>
            <li className="done"><ShieldCheck size={14} />{tx(locale, "Контекст собран", "Context collected")}</li>
            <li className={busy ? "active" : ""}><span />{tx(locale, "Выполнение инструментов", "Running tools")}</li>
            <li><span />{tx(locale, "Проверка результата", "Verifying outcome")}</li>
          </ul>
        </section>

        <section className="context-card compact">
          <header><span><Radio size={15} />{tx(locale, "Nova рядом", "Nova Nearby")}</span><small>{proactiveBadge}</small></header>
          <div className={`nearby-status ${proactivePhase}`}>
            <i />
            <span>{proactive ? proactiveStatus : tx(locale, "Наблюдение выключено", "Observation is off")}</span>
          </div>
          <button
            className="nearby-check"
            onClick={() => void runProactiveCheck()}
            disabled={!proactive || ["scanning", "investigating"].includes(proactivePhase) || connection !== "connected"}
          >
            {tx(locale, "Проверить через 3 секунды", "Check in 3 seconds")}
          </button>
        </section>

        <section className="context-card compact">
          <header><span><Wrench size={15} />{tx(locale, "Возможности", "Capabilities")}</span></header>
          <div className="capabilities">
            <span>Windows</span><span>Browser</span><span>Files</span><span>MCP</span><span>Vision</span>
          </div>
        </section>
      </aside>
    </main>
  );
}
