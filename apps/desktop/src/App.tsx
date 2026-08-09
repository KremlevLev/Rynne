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
  Play,
  Plus,
  Radio,
  Send,
  Settings,
  ShieldCheck,
  Orbit,
  Square,
  Terminal,
  Trash2,
  Volume2,
  Workflow,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { JsonObject, NovaEvent } from "./protocol";
import {
  createNovaTransport,
  type ConnectionState,
  type NovaTransport,
  type PermissionMode,
  type ProviderKeySummary,
  type ProviderName,
  type ServiceName,
  type ServiceSecretSummary,
} from "./transport";
import { Guide, type GuideLocale } from "./Guide";
import { NovaMark } from "./NovaMark";

type ViewKey = "dialog" | "tasks" | "automations" | "guide" | "settings";
export type UiMode = "aura" | "focus" | "console";
export type UiLocale = GuideLocale;
type TimelineItem = {
  id: string;
  kind: "user" | "assistant" | "tool" | "progress" | "suggestion";
  title: string;
  body?: string;
  status?: "working" | "success" | "error";
  action?: string;
  actionLabel?: string;
  proactiveEventId?: string;
  proactiveContextKey?: string;
  operationId?: string;
  progress?: number;
};

type PendingPermission = {
  operationId: string;
  toolName: string;
  risk: string;
  message: string;
  arguments: JsonObject;
  expiresAt: number;
};

type TtsLanguage = "auto" | "ru" | "en";
type TtsStyle = "neutral" | "warm" | "cheerful" | "professional" | "confident";
type TtsSettings = {
  language: TtsLanguage;
  ru_voice: string;
  en_voice: string;
  speed: number;
  style: TtsStyle;
};
type TtsVoice = {
  id: string;
  name: string;
  gender: "female" | "male";
  language: "ru" | "en";
  engine: "silero" | "groq";
  model: string;
  online: boolean;
  available: boolean;
};
type ProviderRuntimeKey = {
  provider: ProviderName;
  index: number;
  available: boolean;
  disabled: boolean;
  in_flight_requests: number;
  global_cooldown_seconds: number;
  model_override: string;
};
type ProviderRuntime = {
  keys: ProviderRuntimeKey[];
  capacity: {
    providers: Partial<Record<ProviderName, { total: number; available: number; in_flight: number }>>;
    total_keys: number;
    available_keys: number;
    parallel_lanes: number;
    in_flight: number;
  };
};

const DEFAULT_TTS_SETTINGS: TtsSettings = {
  language: "auto",
  ru_voice: "baya",
  en_voice: "autumn",
  speed: 1,
  style: "neutral",
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
  modelPlaceholder: string;
}> = [
  {
    key: "groq",
    label: "Groq",
    description: "GPT OSS 120B для текста и tools · Qwen для изображений · Whisper STT",
    placeholder: "gsk_…",
    modelPlaceholder: "openai/gpt-oss-120b",
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    description: "Резервные модели и независимые лимиты",
    placeholder: "sk-or-v1-…",
    modelPlaceholder: "openai/gpt-oss-120b:free",
  },
  {
    key: "gemini",
    label: "Google Gemini",
    description: "Дополнительный маршрут для vision и сложных задач",
    placeholder: "AIza…",
    modelPlaceholder: "gemini-2.5-flash",
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

function stringList(payload: JsonObject, key: string): string[] {
  const value = payload[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function agentProgressCopy(payload: JsonObject, locale: UiLocale): {
  title: string;
  body: string;
} {
  const phase = text(payload, "phase", "working");
  const tools = Number(payload.available_tools ?? payload.proposed_tools ?? 0);
  const completed = Number(payload.completed_tools ?? 0);
  const toolNames = stringList(payload, "tool_names");
  const visibleTools = toolNames.length > 0 ? toolNames.join(", ") : tx(locale, "уточняются", "being selected");
  const copies: Record<string, [string, string, string, string]> = {
    understanding: ["Запрос принят", "Request accepted", "Собираю контекст, историю и вложения.", "Collecting context, history, and attachments."],
    routing: ["Разбираю задачу", "Understanding the task", `Определяю маршрут: ${text(payload, "intent", "general")} · ${text(payload, "strategy", "agent")}.`, `Selecting route: ${text(payload, "intent", "general")} · ${text(payload, "strategy", "agent")}.`],
    delegating: ["Подключаю субагентов", "Starting parallel specialists", `Независимые части задачи анализируются параллельно. Доступная ёмкость: ${Number(payload.capacity ?? 0)}.`, `Independent parts are being analyzed in parallel. Available capacity: ${Number(payload.capacity ?? 0)}.`],
    preparing: ["Готовлю возможности", "Preparing capabilities", `Подобрано инструментов: ${tools}. Кандидаты: ${visibleTools}.`, `${tools} tools selected. Candidates: ${visibleTools}.`],
    model: ["Модель строит следующий шаг", "Model is building the next step", "Жду ответ провайдера и исполнимый план действий.", "Waiting for the provider and an executable action plan."],
    planning: ["Проверяю план", "Validating the plan", `Предложено действий: ${tools}. Следующие вызовы: ${visibleTools}.`, `${tools} action(s) proposed. Next calls: ${visibleTools}.`],
    capability_recovery: ["Расширяю набор инструментов", "Expanding capabilities", `Первый ответ не содержал исполнимого действия. Повторяю с ${tools} инструментами.`, `The first response had no executable action. Retrying with ${tools} tools.`],
    tool_call_repair: ["Исправляю план действий", "Repairing the action plan", "Модель описала намерение вместо вызова инструмента — запрашиваю конкретный первый шаг.", "The model described an intention instead of calling a tool; requesting a concrete first step."],
    executing: ["Начинаю выполнение", "Starting execution", `План готов: ${visibleTools}. Действий в пакете — ${tools}.`, `Plan ready: ${visibleTools}. ${tools} action(s) in the batch.`],
    replanning: [payload.previous_step_failed === true ? "Ищу альтернативу после ошибки" : "Анализирую результат шага", payload.previous_step_failed === true ? "Finding an alternative after a failure" : "Reviewing step results", `Выполнено инструментов: ${completed}. ${payload.previous_step_failed === true ? "Предыдущий шаг не сработал — выбираю другой путь." : "Сверяю результат и выбираю следующий шаг."}`, `${completed} tool action(s) completed. ${payload.previous_step_failed === true ? "The previous step failed; choosing another route." : "Checking the result and selecting the next step."}`],
    verifying: ["Проверяю конечный результат", "Verifying the outcome", `Инструментов выполнено: ${completed}. Сверяю результат с исходной задачей.`, `${completed} tool action(s) completed. Comparing the result with the original request.`],
    finalizing: ["Формирую итог", "Preparing the final response", "Проверка завершена. Готовлю честный отчёт без ложного «готово».", "Verification finished. Preparing an evidence-based final report."],
  };
  const copy = copies[phase] ?? ["Nova работает", "Nova is working", text(payload, "message"), text(payload, "message")];
  return {
    title: locale === "ru" ? copy[0] : copy[1],
    body: locale === "ru" ? copy[2] : copy[3],
  };
}

export function pendingPermissionFromEvent(event: NovaEvent): PendingPermission | null {
  if (event.event_type !== "permissions" && event.event_type !== "approval_requested") return null;
  const candidate = event.event_type === "approval_requested"
    ? event.payload
    : Array.isArray(event.payload.items) ? event.payload.items[0] : null;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const value = candidate as Record<string, unknown>;
  const operationId = typeof value.operation_id === "string" ? value.operation_id : "";
  if (!operationId) return null;
  return {
    operationId,
    toolName: typeof value.tool_name === "string" ? value.tool_name : "tool",
    risk: typeof value.risk === "string" ? value.risk : "execute",
    message: typeof value.message === "string" ? value.message : "",
    arguments: value.arguments && typeof value.arguments === "object" && !Array.isArray(value.arguments)
      ? value.arguments as JsonObject
      : {},
    expiresAt: typeof value.expires_at === "number" ? value.expires_at : 0,
  };
}

export function eventToItem(event: NovaEvent, locale: UiLocale = "ru"): TimelineItem | null {
  const id = `${event.event_type}_${event.created_at}_${Math.random()}`;
  const payload = event.payload;
  switch (event.event_type) {
    case "request_started":
      return {
        id,
        kind: "progress",
        title: tx(locale, "Передаю задачу Nova Core", "Sending the task to Nova Core"),
        body: tx(locale, "Запрос получен и поставлен в выполнение.", "The request was received and queued for execution."),
        status: "working",
        progress: 3,
      };
    case "request_heartbeat": {
      const elapsed = Number(payload.elapsed_seconds ?? 0);
      return {
        id,
        kind: "progress",
        title: tx(locale, "Nova всё ещё работает", "Nova is still working"),
        body: tx(
          locale,
          `Core отвечает, текущий этап длится ${elapsed} сек. Дождитесь результата или таймаута провайдера.`,
          `Core is responsive; the current stage has been running for ${elapsed}s. Waiting for a result or provider timeout.`,
        ),
        status: "working",
      };
    }
    case "voice_activity": {
      if (text(payload, "source") !== "wake_word" || text(payload, "phase") !== "wake_detected") {
        return null;
      }
      return {
        id,
        kind: "progress",
        title: tx(locale, "Услышала «Нова»", "Wake word detected"),
        body: tx(locale, "Записываю команду и автоматически завершу фразу после короткой паузы.", "Recording the command; the utterance will end automatically after a short pause."),
        status: "working",
        progress: 6,
      };
    }
    case "voice_status": {
      const status = text(payload, "status");
      if (!["wake_word_detected", "command_recognized", "unavailable"].includes(status)) return null;
      return {
        id,
        kind: "progress",
        title: status === "wake_word_detected"
          ? tx(locale, "Фраза записана", "Utterance captured")
          : status === "command_recognized"
            ? tx(locale, "Голосовая команда распознана", "Voice command recognized")
            : tx(locale, "Wake word недоступен", "Wake word is unavailable"),
        body: text(payload, "message"),
        status: status === "unavailable" ? "error" : status === "command_recognized" ? "success" : "working",
        progress: status === "wake_word_detected" ? 10 : status === "command_recognized" ? 14 : undefined,
      };
    }
    case "agent_progress": {
      const copy = agentProgressCopy(payload, locale);
      return {
        id,
        kind: "progress",
        title: copy.title,
        body: copy.body,
        status: Number(payload.progress ?? 0) >= 100 ? "success" : "working",
        progress: Number(payload.progress ?? 0),
      };
    }
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
    case "request_cancelled":
      return {
        id,
        kind: "assistant",
        title: "Nova",
        body: tx(locale, "Задача остановлена.", "Task stopped."),
        status: "error",
      };
    case "tool_started":
      {
        const argumentNames = stringList(payload, "argument_names");
      return {
        id,
        kind: "tool",
        title: text(payload, "description", tx(locale, "Запускаю инструмент", "Running tool")),
        body: tx(
          locale,
          `Инструмент: ${text(payload, "tool_name")} · параметры: ${argumentNames.join(", ") || "нет"} · риск: ${text(payload, "risk", "unknown")}`,
          `Tool: ${text(payload, "tool_name")} · parameters: ${argumentNames.join(", ") || "none"} · risk: ${text(payload, "risk", "unknown")}`,
        ),
        status: "working",
        operationId: text(payload, "operation_id"),
      };
      }
    case "tool_completed":
      return {
        id,
        kind: "tool",
        title: payload.success === false
          ? tx(locale, "Инструмент завершился с ошибкой", "Tool failed")
          : tx(locale, "Действие выполнено", "Action completed"),
        body: `${text(payload, "message", text(payload, "tool_name"))}${typeof payload.duration_ms === "number" ? ` · ${(payload.duration_ms / 1000).toFixed(1)}s` : ""}`,
        status: payload.success === false ? "error" : "success",
        operationId: text(payload, "operation_id"),
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
    case "subagent_team_started":
      return {
        id,
        kind: "tool",
        title: tx(locale, "Nova собрала команду", "Nova assembled a team"),
        body: tx(
          locale,
          `Параллельных агентов: ${Number(payload.agents ?? 0)} · доступная ёмкость: ${Number(payload.capacity ?? 0)}`,
          `Parallel agents: ${Number(payload.agents ?? 0)} · available capacity: ${Number(payload.capacity ?? 0)}`,
        ),
        status: "working",
      };
    case "subagent_started":
      return {
        id,
        kind: "tool",
        title: `${tx(locale, "Субагент", "Subagent")} · ${text(payload, "role", "specialist")}`,
        body: text(payload, "task"),
        status: "working",
      };
    case "subagent_completed":
      return {
        id,
        kind: "tool",
        title: `${text(payload, "role", "specialist")} · ${payload.success === true ? tx(locale, "готов", "ready") : tx(locale, "ошибка", "failed")}`,
        body: payload.success === true
          ? `${text(payload, "provider")}:${text(payload, "model")}`
          : text(payload, "error", tx(locale, "Субагент не ответил.", "Subagent did not respond.")),
        status: payload.success === true ? "success" : "error",
      };
    case "subagent_critic_started":
      return {
        id,
        kind: "tool",
        title: tx(locale, "Critic проверяет план", "Critic is evaluating the plan"),
        body: tx(locale, "Ищу потерянные требования, ложные успехи и непроверенные шаги.", "Checking for lost requirements, false success, and unverified steps."),
        status: "working",
      };
    case "subagent_critic_completed":
      return {
        id,
        kind: "tool",
        title: payload.passed === true ? tx(locale, "Critic принял план", "Critic accepted the plan") : tx(locale, "Critic отправил план на доработку", "Critic requested a revision"),
        body: text(payload, "critique"),
        status: payload.passed === true ? "success" : "working",
      };
    case "subagent_team_completed":
      return {
        id,
        kind: "assistant",
        title: tx(locale, "Reviewer команды", "Team reviewer"),
        body: text(payload, "synthesis", tx(locale, "Командный анализ завершён.", "Team analysis completed.")),
        status: payload.success === true ? "success" : "error",
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
  const [cancelPending, setCancelPending] = useState(false);
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
  const [apiModel, setApiModel] = useState("");
  const [providerKeys, setProviderKeys] = useState<ProviderKeySummary[]>([]);
  const [providerRuntime, setProviderRuntime] = useState<ProviderRuntime | null>(null);
  const [providerKeysLoading, setProviderKeysLoading] = useState(false);
  const [serviceSecrets, setServiceSecrets] = useState<ServiceSecretSummary[]>([]);
  const [serviceDrafts, setServiceDrafts] = useState<Record<ServiceName, string>>({
    telegram: "",
    tavily: "",
  });
  const [settingsStatus, setSettingsStatus] = useState("");
  const [ttsSettings, setTtsSettings] = useState<TtsSettings>(DEFAULT_TTS_SETTINGS);
  const [ttsSpeedDraft, setTtsSpeedDraft] = useState(1);
  const [ttsVoices, setTtsVoices] = useState<TtsVoice[]>([]);
  const [ttsPending, setTtsPending] = useState(false);
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null);
  const [uiMode, setUiMode] = useState<UiMode>(() => (
    readUiMode(typeof window === "undefined" ? null : window.localStorage)
  ));
  const conversationRef = useRef<HTMLDivElement>(null);
  const wakeSensitivityDraggingRef = useRef(false);
  const ttsSpeedDraggingRef = useRef(false);
  const wakeSensitivityCommittedRef = useRef(0.72);
  const ttsSpeedCommittedRef = useRef(1);
  const localeRef = useRef(locale);
  const followConversationRef = useRef(true);
  const [followingConversation, setFollowingConversation] = useState(true);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [voicePhase, setVoicePhase] = useState("idle");
  const [voiceLevel, setVoiceLevel] = useState(0);
  const [voiceSource, setVoiceSource] = useState("stt");
  const [confirmingSuggestionId, setConfirmingSuggestionId] = useState<string | null>(null);
  const [pendingPermission, setPendingPermission] = useState<PendingPermission | null>(null);
  const [permissionPending, setPermissionPending] = useState(false);
  const [permissionMode, setPermissionMode] = useState<PermissionMode>("risky_only");
  const [permissionModePending, setPermissionModePending] = useState(false);
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
          if (item) setTimeline((current) => {
            if (item.kind === "user") {
              const alreadyVisible = [...current].reverse().find((candidate) => candidate.kind === "user");
              if (alreadyVisible?.body === item.body) return current;
            }
            if (event.event_type === "request_started") {
              const last = current[current.length - 1];
              if (last?.id.startsWith("local_progress_")) {
                return [...current.slice(0, -1), item];
              }
            }
            if (event.event_type === "request_heartbeat") {
              const last = current[current.length - 1];
              if (last?.id.startsWith("request_heartbeat_")) {
                return [...current.slice(0, -1), item];
              }
            }
            if (event.event_type === "tool_completed" && item.operationId) {
              const index = current.findIndex((candidate) => (
                candidate.kind === "tool" && candidate.operationId === item.operationId
              ));
              if (index >= 0) {
                return current.map((candidate, candidateIndex) => (
                  candidateIndex === index ? item : candidate
                ));
              }
            }
            if (event.event_type === "agent_progress" || event.event_type === "tool_started") {
              const settled = current.map((candidate) => (
                candidate.kind === "progress" && candidate.status === "working"
                  ? { ...candidate, status: "success" as const }
                  : candidate
              ));
              return [...settled, item];
            }
            return [...current, item];
          });
          if (event.event_type === "request_started") setBusy(true);
          if (event.event_type === "agent_progress") {
            const copy = agentProgressCopy(event.payload, localeRef.current);
            setActiveTool(copy.title);
            const progress = event.payload.progress;
            if (typeof progress === "number") setTaskProgress(progress);
          }
          if (event.event_type === "runtime") {
            const state = event.payload.state;
            if (typeof state === "string") setRuntimeState(state);
          }
          if (["assistant_message", "request_failed", "request_cancelled"].includes(event.event_type)) {
            setBusy(false);
            setCancelPending(false);
            setTaskProgress(0);
            setActiveTool(tx(localeRef.current, "Ожидаю задачу", "Waiting for a task"));
            setTimeline((current) => current.map((candidate) => (
              candidate.status === "working" && (candidate.kind === "progress" || candidate.kind === "tool")
                  ? { ...candidate, status: ["request_failed", "request_cancelled"].includes(event.event_type) ? "error" : "success" }
                : candidate
            )));
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
            if (typeof sensitivity === "number" && !wakeSensitivityDraggingRef.current) {
              setWakeSensitivity(sensitivity);
              wakeSensitivityCommittedRef.current = sensitivity;
            }
            const receivedTtsSettings = event.payload.tts_settings;
            if (receivedTtsSettings && typeof receivedTtsSettings === "object" && !Array.isArray(receivedTtsSettings)) {
              const value = receivedTtsSettings as Record<string, unknown>;
              const nextTtsSettings: TtsSettings = {
                language: ["auto", "ru", "en"].includes(String(value.language))
                  ? String(value.language) as TtsLanguage
                  : "auto",
                ru_voice: typeof value.ru_voice === "string" ? value.ru_voice : "baya",
                en_voice: typeof value.en_voice === "string" ? value.en_voice : "autumn",
                speed: typeof value.speed === "number" ? value.speed : 1,
                style: ["neutral", "warm", "cheerful", "professional", "confident"].includes(String(value.style))
                  ? String(value.style) as TtsStyle
                  : "neutral",
              };
              setTtsSettings(nextTtsSettings);
              if (!ttsSpeedDraggingRef.current) {
                setTtsSpeedDraft(nextTtsSettings.speed);
                ttsSpeedCommittedRef.current = nextTtsSettings.speed;
              }
              setTtsPending(false);
            }
            const receivedCatalog = event.payload.tts_catalog;
            if (receivedCatalog && typeof receivedCatalog === "object" && !Array.isArray(receivedCatalog)) {
              const voices = (receivedCatalog as Record<string, unknown>).voices;
              if (Array.isArray(voices)) setTtsVoices(voices as unknown as TtsVoice[]);
            }
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
            const status = text(event.payload, "status");
            if (status) setVoicePhase(status);
            setVoicePending(false);
          }
          if (event.event_type === "voice_activity") {
            const phase = text(event.payload, "phase", "idle");
            const source = text(event.payload, "source", "stt");
            const level = event.payload.level;
            setVoicePhase(phase);
            setVoiceSource(source);
            setVoiceLevel(typeof level === "number" ? Math.min(1, Math.max(0, level)) : 0);
          }
          if (event.event_type === "task_progress") {
            const value = event.payload.progress;
            if (typeof value === "number") setTaskProgress(value);
          }
          if (event.event_type === "models") {
            setProviderRuntime(event.payload as unknown as ProviderRuntime);
          }
          if (event.event_type === "permissions") {
            setPendingPermission(pendingPermissionFromEvent(event));
          }
          if (event.event_type === "approval_requested") {
            setPendingPermission(pendingPermissionFromEvent(event));
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
  }, [timeline, pendingPermission]);

  async function resolvePermission(granted: boolean) {
    if (!pendingPermission || permissionPending) return;
    setPermissionPending(true);
    try {
      await transport.send(
        granted ? "confirm_permission" : "deny_permission",
        { operation_id: pendingPermission.operationId },
      );
      setPendingPermission(null);
    } finally {
      setPermissionPending(false);
    }
  }

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
    if (connection === "connected") {
      void refreshProviderKeys();
      void refreshServiceSecrets();
      void refreshPermissionMode();
    }
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
    const localId = Date.now();
    setBusy(true);
    setTaskProgress(1);
    setActiveTool(tx(locale, "Передаю запрос Nova Core", "Sending request to Nova Core"));
    setTimeline((current) => [
      ...current,
      {
        id: `local_user_${localId}`,
        kind: "user",
        title: tx(locale, "Вы", "You"),
        body: value,
      },
      {
        id: `local_progress_${localId}`,
        kind: "progress",
        title: tx(locale, "Отправляю запрос", "Sending request"),
        body: tx(locale, "Жду подтверждения от Nova Core…", "Waiting for Nova Core to acknowledge the request…"),
        status: "working",
        progress: 1,
      },
    ]);
    try {
      await transport.send("submit_user_request", {
        text: value,
        response_language: locale,
      });
    } catch (error) {
      setBusy(false);
      setTaskProgress(0);
      setTimeline((current) => [
        ...current.map((candidate) => candidate.id === `local_progress_${localId}`
          ? { ...candidate, status: "error" as const }
          : candidate),
        {
          id: `local_error_${localId}`,
          kind: "assistant",
          title: "Nova",
          body: error instanceof Error ? error.message : tx(locale, "Не удалось передать запрос Core.", "Could not send the request to Core."),
          status: "error",
        },
      ]);
    }
  }

  async function cancelCurrentRequest() {
    if (!busy || cancelPending || connection !== "connected") return;
    setCancelPending(true);
    setActiveTool(tx(locale, "Останавливаю задачу…", "Stopping task…"));
    try {
      await transport.send("cancel_current_request");
    } catch (error) {
      setCancelPending(false);
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось остановить задачу.", "Could not stop the task."),
      );
    }
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
      response_language: locale,
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

  async function refreshServiceSecrets() {
    try {
      setServiceSecrets(await transport.listServiceSecrets());
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось загрузить интеграции.", "Could not load integrations."),
      );
    }
  }

  async function refreshPermissionMode() {
    try {
      setPermissionMode(await transport.getPermissionMode());
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось загрузить режим доступа.", "Could not load access mode."),
      );
    }
  }

  async function selectPermissionMode(mode: PermissionMode) {
    if (mode === permissionMode || permissionModePending) return;
    setPermissionModePending(true);
    setSettingsStatus(tx(locale, "Сохраняю режим и перезапускаю Nova Core…", "Saving mode and restarting Nova Core…"));
    try {
      await transport.setPermissionMode(mode);
      setPermissionMode(mode);
      setSettingsStatus(tx(locale, "Режим доступа изменён.", "Access mode updated."));
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось изменить режим доступа.", "Could not update access mode."),
      );
    } finally {
      setPermissionModePending(false);
    }
  }

  async function saveServiceSecret(service: ServiceName) {
    const secret = serviceDrafts[service].trim();
    if (secret.length < 12) return;
    setSettingsStatus(tx(locale, "Сохраняю ключ и перезапускаю Nova Core…", "Saving the key and restarting Nova Core…"));
    try {
      await transport.setServiceSecret(service, secret);
      setServiceDrafts((current) => ({ ...current, [service]: "" }));
      await refreshServiceSecrets();
      setSettingsStatus(tx(locale, "Интеграция подключена.", "Integration connected."));
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : tx(locale, "Не удалось сохранить ключ.", "Could not save the key."));
    }
  }

  async function removeServiceSecret(service: ServiceName) {
    try {
      await transport.removeServiceSecret(service);
      await refreshServiceSecrets();
      setSettingsStatus(tx(locale, "Интеграция отключена.", "Integration disconnected."));
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : tx(locale, "Не удалось удалить ключ.", "Could not remove the key."));
    }
  }

  async function addProviderKey() {
    if (apiKey.trim().length < 12) return;
    setSettingsStatus(tx(locale, "Добавляю ключ и перезапускаю Nova Core…", "Adding the key and restarting Nova Core…"));
    try {
      await transport.addProviderKey(provider, apiKey.trim(), apiModel.trim());
      setApiKey("");
      setApiModel("");
      setSettingsStatus(tx(locale, "Ключ добавлен. Nova Core переподключается.", "Key added. Nova Core is reconnecting."));
      await refreshProviderKeys();
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось сохранить API-ключ.", "Could not save the API key."),
      );
    }
  }

  async function updateProviderModel(key: ProviderKeySummary, model: string) {
    if (!key.removable || model === key.model) return;
    setSettingsStatus(tx(locale, "Сохраняю модель ключа и перезапускаю Nova Core…", "Saving the key model and restarting Nova Core…"));
    try {
      await transport.updateProviderKeyModel(key.provider, key.index, model.trim());
      setProviderKeys((current) => current.map((item) => (
        item.provider === key.provider && item.source === key.source && item.index === key.index
          ? { ...item, model: model.trim() }
          : item
      )));
      setSettingsStatus(tx(locale, "Модель ключа обновлена.", "Key model updated."));
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : tx(locale, "Не удалось обновить модель.", "Could not update the model."));
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

  async function saveTtsSettings(patch: Partial<TtsSettings>) {
    const next = { ...ttsSettings, ...patch };
    setTtsSettings(next);
    setTtsPending(true);
    setSettingsStatus(tx(locale, "Сохраняю настройки голоса…", "Saving voice settings…"));
    try {
      await transport.send("set_tts_settings", next);
      setSettingsStatus(tx(locale, "Голос Nova настроен.", "Nova's voice is configured."));
    } catch (error) {
      setTtsPending(false);
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось сохранить настройки TTS.", "Could not save TTS settings."),
      );
    }
  }

  async function previewTtsVoice(voice: TtsVoice) {
    setPreviewingVoice(voice.id);
    setSettingsStatus(tx(locale, `Слушаем ${voice.name}…`, `Playing ${voice.name}…`));
    try {
      await transport.send("preview_tts", {
        language: voice.language,
        voice: voice.id,
        speed: ttsSettings.speed,
        style: ttsSettings.style,
      });
    } catch (error) {
      setSettingsStatus(
        error instanceof Error ? error.message : tx(locale, "Не удалось воспроизвести пример.", "Could not play the preview."),
      );
    } finally {
      window.setTimeout(() => setPreviewingVoice(null), 5_000);
    }
  }

  const voiceActive = inputMode === "continuous";
  const wakeWordActive = inputMode === "wake_word";
  const voiceCaptureVisible = voiceActive || [
    "recording",
    "transcribing",
    "wake_detected",
    "wake_word_detected",
    "paused_tts",
  ].includes(voicePhase);
  const voiceCaptureTitle = voicePhase === "paused_tts"
    ? tx(locale, "Микрофон на паузе, пока Nova говорит", "Microphone paused while Nova speaks")
    : voicePhase === "transcribing" || voicePhase === "wake_word_detected"
    ? tx(locale, "Распознаю речь…", "Transcribing speech…")
    : voicePhase === "recording" || voicePhase === "wake_detected"
      ? tx(locale, "Слышу тебя", "I can hear you")
      : tx(locale, "Слушаю…", "Listening…");
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
          <div className="brand-orb"><NovaMark size={42} /></div>
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
                      {item.kind === "tool" ? <Wrench size={13} /> : item.kind === "progress" ? <Activity size={13} /> : item.kind === "suggestion" ? <Orbit size={13} /> : item.kind === "assistant" ? <Bot size={13} /> : null}
                    </span>
                  </div>
                  <div className="timeline-content">
                    <div className="message-meta">
                      <strong>{item.title}</strong>
                      {item.status === "working" && <span className="working-label">{tx(locale, "выполняется", "working")}</span>}
                      {item.status === "success" && item.kind === "tool" && <span className="success-label">{tx(locale, "готово", "done")}</span>}
                    </div>
                    {item.body && <p>{item.body}</p>}
                    {item.kind === "progress" && typeof item.progress === "number" && (
                      <span className="stage-progress" aria-label={`${item.progress}%`}>
                        <i style={{ width: `${Math.max(2, Math.min(100, item.progress))}%` }} />
                      </span>
                    )}
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
              {pendingPermission && (
                <article className="permission-card" role="alert" aria-live="assertive">
                  <div className="permission-icon"><ShieldCheck size={19} /></div>
                  <div className="permission-copy">
                    <span>{tx(locale, "НУЖНО ПОДТВЕРЖДЕНИЕ", "CONFIRMATION REQUIRED")}</span>
                    <strong>{tx(locale, "Разрешить Nova выполнить действие?", "Allow Nova to run this action?")}</strong>
                    <p>{pendingPermission.message || pendingPermission.toolName}</p>
                    <code>{String(pendingPermission.arguments.command ?? pendingPermission.arguments.path ?? pendingPermission.toolName)}</code>
                    <div className="permission-actions">
                      <button className="permission-approve" disabled={permissionPending} onClick={() => void resolvePermission(true)}>
                        {tx(locale, "Разрешить", "Allow")}
                      </button>
                      <button className="permission-deny" disabled={permissionPending} onClick={() => void resolvePermission(false)}>
                        {tx(locale, "Отклонить", "Deny")}
                      </button>
                    </div>
                  </div>
                </article>
              )}
            </div>

            {!followingConversation && (
              <button className="jump-to-latest" onClick={resumeConversationFollow}>
                {tx(locale, "К новым сообщениям", "Jump to latest")}
                <ChevronRight size={14} />
              </button>
            )}

            <div className="composer-wrap">
              {voiceCaptureVisible && (
                <div className={`voice-capture-panel phase-${voicePhase}`} role="status" aria-live="polite">
                  <div className="voice-capture-orb"><Mic size={17} /></div>
                  <div className="voice-capture-copy">
                    <strong>{voiceCaptureTitle}</strong>
                    <small>{voicePhase === "paused_tts"
                      ? tx(locale, "Защита от самопрослушивания включена", "Echo protection is active")
                      : voiceSource === "wake_word"
                      ? tx(locale, `Wake «${wakeWord}» · звук остаётся на устройстве`, `Wake “${wakeWord}” · audio stays on device`)
                      : tx(locale, "Голосовой ввод активен", "Voice input is active")}</small>
                  </div>
                  <div className="voice-wave" aria-hidden="true">
                    {Array.from({ length: 17 }, (_, index) => {
                      const shape = 0.35 + Math.sin((index + 1) * 1.7) * 0.18 + (index % 3) * 0.08;
                      const height = 4 + Math.max(0.06, voiceLevel) * shape * 34;
                      return <i key={index} style={{ height: `${height}px` }} />;
                    })}
                  </div>
                  <button
                    className="voice-capture-stop"
                    onClick={() => void selectInputMode("sleep")}
                    aria-label={tx(locale, "Остановить голосовой ввод", "Stop voice input")}
                    title={tx(locale, "Остановить", "Stop")}
                  ><Square size={12} /></button>
                </div>
              )}
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
                    <button className="send stop" onClick={() => void cancelCurrentRequest()} disabled={cancelPending} aria-label={tx(locale, "Остановить", "Stop")} title={tx(locale, "Немедленно остановить текущую задачу", "Stop the current task immediately")}><Square size={14} /></button>
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
                permissionMode === "full_access"
                  ? "Enter — отправить · Shift Enter — новая строка · Полный доступ: без запросов подтверждения"
                  : permissionMode === "always_ask"
                    ? "Enter — отправить · Shift Enter — новая строка · Подтверждение перед каждым инструментом"
                    : "Enter — отправить · Shift Enter — новая строка · Подтверждение только рискованных действий",
                permissionMode === "full_access"
                  ? "Enter — send · Shift Enter — new line · Full access: no approval prompts"
                  : permissionMode === "always_ask"
                    ? "Enter — send · Shift Enter — new line · Approval before every tool"
                    : "Enter — send · Shift Enter — new line · Approval for risky actions only",
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
                <h2>{tx(locale, "Язык Nova", "Nova language")}</h2>
                <p>{tx(
                  locale,
                  "Переключение применяется мгновенно к интерфейсу, ответам и итогам инструментов и сохраняется на этом компьютере.",
                  "The change applies immediately to the interface, replies, and tool summaries, and is saved on this computer.",
                )}</p>
              </div>
              <div className="locale-options">
                <button className={locale === "ru" ? "active" : ""} onClick={() => setLocale("ru")}><strong>Русский</strong><small>RU</small></button>
                <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}><strong>English</strong><small>EN</small></button>
              </div>
              <div className="tts-roadmap-note">
                <Volume2 size={16} />
                <span><strong>{tx(locale, "Язык UI и голос независимы", "UI and voice languages are independent")}</strong><small>{tx(locale, "Ниже можно отдельно выбрать Auto/RU/EN, движок, голос, стиль и скорость.", "Choose Auto/RU/EN, engine, voice, style, and speed independently below.")}</small></span>
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
            <div className="settings-card access-card">
              <span className="settings-icon"><ShieldCheck size={22} /></span>
              <div>
                <span className="eyebrow">{tx(locale, "РАЗРЕШЕНИЯ", "PERMISSIONS")}</span>
                <h2>{tx(locale, "Когда Nova должна спрашивать", "When Nova should ask")}</h2>
                <p>{tx(
                  locale,
                  "Выберите, насколько автономно Nova выполняет инструменты. Жёсткие системные запреты и защита проактивного режима остаются во всех вариантах.",
                  "Choose how autonomously Nova executes tools. Hard system blocks and proactive-mode safeguards remain active in every mode.",
                )}</p>
              </div>
              <div className="permission-mode-options">
                {([
                  {
                    key: "full_access" as const,
                    title: tx(locale, "Полный доступ", "Full access"),
                    description: tx(locale, "Выполняет разрешённые действия сразу, без вопросов.", "Runs allowed actions immediately without asking."),
                    badge: tx(locale, "Автономно", "Autonomous"),
                  },
                  {
                    key: "risky_only" as const,
                    title: tx(locale, "Только опасные", "Risky only"),
                    description: tx(locale, "Спрашивает перед отправкой, командами, удалением и другими рискованными действиями.", "Asks before sending, commands, deletion, and other risky actions."),
                    badge: tx(locale, "Рекомендуется", "Recommended"),
                  },
                  {
                    key: "always_ask" as const,
                    title: tx(locale, "Спрашивать всегда", "Always ask"),
                    description: tx(locale, "Запрашивает подтверждение перед каждым инструментом, даже чтением.", "Requests confirmation before every tool, including read-only actions."),
                    badge: tx(locale, "Строго", "Strict"),
                  },
                ]).map((option) => (
                  <button
                    key={option.key}
                    className={permissionMode === option.key ? "permission-mode-option active" : "permission-mode-option"}
                    onClick={() => void selectPermissionMode(option.key)}
                    disabled={permissionModePending}
                    aria-pressed={permissionMode === option.key}
                  >
                    <span><strong>{option.title}</strong><b>{option.badge}</b></span>
                    <small>{option.description}</small>
                  </button>
                ))}
              </div>
            </div>
            <div className="settings-card tts-card">
              <span className="settings-icon"><Volume2 size={22} /></span>
              <div>
                <span className="eyebrow">TEXT TO SPEECH</span>
                <h2>{tx(locale, "Выбери, как говорит Nova", "Choose how Nova speaks")}</h2>
                <p>{tx(
                  locale,
                  "Русские голоса работают локально через Silero. Английские голоса Orpheus работают через Groq API и не нагружают ноутбук моделью в памяти.",
                  "Russian voices run locally with Silero. English Orpheus voices use the Groq API and do not keep another model in laptop memory.",
                )}</p>
              </div>
              <div className="tts-language-options" aria-label={tx(locale, "Язык озвучки", "Speech language")}>
                {(["auto", "ru", "en"] as const).map((language) => (
                  <button
                    key={language}
                    className={ttsSettings.language === language ? "active" : ""}
                    onClick={() => void saveTtsSettings({ language })}
                    disabled={ttsPending}
                  >
                    <strong>{language === "auto" ? "Auto" : language.toUpperCase()}</strong>
                    <small>{language === "auto"
                      ? tx(locale, "По тексту ответа", "Detect from reply")
                      : language === "ru"
                        ? tx(locale, "Локально", "Local")
                        : "Groq API"}</small>
                  </button>
                ))}
              </div>
              <div className="tts-controls">
                <label>
                  <span><strong>{tx(locale, "Скорость речи", "Speech speed")}</strong><small>{ttsSpeedDraft.toFixed(2)}×</small></span>
                  <input
                    type="range"
                    min="0.7"
                    max="1.6"
                    step="0.05"
                    value={ttsSpeedDraft}
                    onChange={(event) => setTtsSpeedDraft(Number(event.target.value))}
                    onPointerDown={(event) => {
                      ttsSpeedDraggingRef.current = true;
                      event.currentTarget.setPointerCapture(event.pointerId);
                    }}
                    onPointerUp={(event) => {
                      ttsSpeedDraggingRef.current = false;
                      const speed = Number(event.currentTarget.value);
                      ttsSpeedCommittedRef.current = speed;
                      setTtsSettings((current) => ({ ...current, speed }));
                      void saveTtsSettings({ speed });
                    }}
                    onPointerCancel={() => {
                      ttsSpeedDraggingRef.current = false;
                      setTtsSpeedDraft(ttsSettings.speed);
                    }}
                    onBlur={(event) => {
                      if (!ttsSpeedDraggingRef.current) {
                        const speed = Number(event.currentTarget.value);
                        if (Math.abs(speed - ttsSpeedCommittedRef.current) > 0.001) {
                          ttsSpeedCommittedRef.current = speed;
                          setTtsSettings((current) => ({ ...current, speed }));
                          void saveTtsSettings({ speed });
                        }
                      }
                    }}
                  />
                </label>
                <label>
                  <span><strong>{tx(locale, "Манера английской речи", "English speaking style")}</strong><small>Orpheus</small></span>
                  <select
                    value={ttsSettings.style}
                    onChange={(event) => void saveTtsSettings({ style: event.target.value as TtsStyle })}
                  >
                    {(["neutral", "warm", "cheerful", "professional", "confident"] as const).map((style) => (
                      <option key={style} value={style}>{tx(
                        locale,
                        ({ neutral: "Обычная", warm: "Тёплая", cheerful: "Весёлая", professional: "Профессиональная", confident: "Уверенная" })[style],
                        style[0].toUpperCase() + style.slice(1),
                      )}</option>
                    ))}
                  </select>
                </label>
              </div>
              {(["ru", "en"] as const).map((language) => (
                <section className="tts-voice-section" key={language}>
                  <div className="tts-section-title">
                    <strong>{language === "ru" ? tx(locale, "Русские · Silero", "Russian · Silero") : tx(locale, "Английские · Groq Orpheus", "English · Groq Orpheus")}</strong>
                    <small>{language === "ru" ? tx(locale, "Работают без интернета", "Works offline") : tx(locale, "6 выразительных голосов", "6 expressive voices")}</small>
                  </div>
                  <div className="tts-voice-grid">
                    {ttsVoices.filter((voice) => voice.language === language).map((voice) => {
                      const selected = language === "ru"
                        ? ttsSettings.ru_voice === voice.id
                        : ttsSettings.en_voice === voice.id;
                      return (
                        <div className={selected ? "tts-voice active" : "tts-voice"} key={`${voice.engine}-${voice.id}`}>
                          <button
                            className="tts-voice-select"
                            onClick={() => void saveTtsSettings(language === "ru" ? { ru_voice: voice.id } : { en_voice: voice.id })}
                            aria-pressed={selected}
                          >
                            <span className="voice-avatar">{voice.name.slice(0, 1)}</span>
                            <span><strong>{voice.name}</strong><small>{voice.gender === "female" ? tx(locale, "Женский", "Female") : tx(locale, "Мужской", "Male")} · {voice.engine}</small></span>
                          </button>
                          <button
                            className="tts-preview"
                            onClick={() => void previewTtsVoice(voice)}
                            disabled={!voice.available || previewingVoice !== null}
                            title={!voice.available ? tx(locale, "Добавьте Groq API-ключ", "Add a Groq API key") : tx(locale, "Послушать пример", "Play sample")}
                          >
                            {previewingVoice === voice.id ? <Activity size={14} /> : <Play size={14} />}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
              <p className="tts-footnote">{tx(
                locale,
                "Groq применяет точный коэффициент. Silero использует естественные SSML-ступени: очень медленно, медленно, обычно, быстро и очень быстро — без ускорения готовой записи.",
                "Groq applies the exact multiplier. Silero uses natural SSML presets: x-slow, slow, normal, fast, and x-fast — without speeding up finished audio.",
              )}</p>
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
                    onPointerDown={(event) => {
                      wakeSensitivityDraggingRef.current = true;
                      event.currentTarget.setPointerCapture(event.pointerId);
                    }}
                    onPointerUp={(event) => {
                      wakeSensitivityDraggingRef.current = false;
                      const sensitivity = Number(event.currentTarget.value);
                      wakeSensitivityCommittedRef.current = sensitivity;
                      void setWakeWordSensitivity(sensitivity);
                    }}
                    onPointerCancel={() => { wakeSensitivityDraggingRef.current = false; }}
                    onBlur={(event) => {
                      if (!wakeSensitivityDraggingRef.current) {
                        const sensitivity = Number(event.currentTarget.value);
                        if (Math.abs(sensitivity - wakeSensitivityCommittedRef.current) > 0.001) {
                          wakeSensitivityCommittedRef.current = sensitivity;
                          void setWakeWordSensitivity(sensitivity);
                        }
                      }
                    }}
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
                <div className="provider-capacity-summary">
                  <span>{tx(locale, "Живая ёмкость роя", "Live swarm capacity")}</span>
                  <strong>{providerRuntime?.capacity.parallel_lanes ?? 0} {tx(locale, "линий", "lanes")}</strong>
                  <small>
                    {providerRuntime?.capacity.available_keys ?? providerKeys.length}/{providerRuntime?.capacity.total_keys ?? providerKeys.length} {tx(locale, "ключей доступны", "keys available")}
                    {" · "}{tx(locale, "до", "up to")} {Math.min(6, providerRuntime?.capacity.parallel_lanes ?? 0)} {tx(locale, "субагентов", "subagents")}
                    {" · "}{(providerRuntime?.capacity.parallel_lanes ?? 0) >= 2 ? tx(locale, "critic включён", "critic enabled") : tx(locale, "critic ждёт второй независимый ключ", "critic needs a second independent key")}
                  </small>
                </div>
                {providers.map((option) => {
                  const keys = providerKeys.filter((key) => key.provider === option.key);
                  const runtimeCapacity = providerRuntime?.capacity.providers[option.key];
                  return (
                    <section className="provider-group" key={option.key}>
                      <header>
                        <span>
                          <strong>{option.label}</strong>
                          <small>{option.description}</small>
                        </span>
                        <b title={tx(locale, "доступно / всего", "available / total")}>
                          {providerKeysLoading ? "…" : `${runtimeCapacity?.available ?? keys.length}/${runtimeCapacity?.total ?? keys.length}`}
                        </b>
                      </header>
                      <div className="provider-key-list">
                        {keys.length === 0 ? (
                          <p>{tx(locale, "Ключей пока нет", "No keys yet")}</p>
                        ) : keys.map((key) => (
                          <div className="provider-key" key={`${key.provider}-${key.source}-${key.index}-${key.hint}`}>
                            <span>
                              <code>{key.hint}</code>
                              <small>{key.source === "nova" ? tx(locale, "Добавлен в Nova", "Added in Nova") : tx(locale, "Системная переменная", "System environment variable")}</small>
                              <input
                                className="provider-model-input"
                                defaultValue={key.model}
                                disabled={!key.removable}
                                placeholder={option.modelPlaceholder}
                                aria-label={tx(locale, `Модель для ${key.hint}`, `Model for ${key.hint}`)}
                                title={key.removable ? tx(locale, "Своя модель для этого ключа", "Custom model for this key") : tx(locale, "Модель задана системной переменной", "Model is set by an environment variable")}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") event.currentTarget.blur();
                                }}
                                onBlur={(event) => void updateProviderModel(key, event.currentTarget.value)}
                              />
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
              <label>
                {tx(locale, "Модель для этого ключа", "Model for this key")}
                <input
                  type="text"
                  value={apiModel}
                  onChange={(event) => setApiModel(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void addProviderKey();
                  }}
                  placeholder={providers.find((option) => option.key === provider)?.modelPlaceholder}
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
            <div className="settings-card provider-card integration-card">
              <span className="settings-icon"><Bot size={22} /></span>
              <div>
                <span className="eyebrow">{tx(locale, "ИНТЕГРАЦИИ", "INTEGRATIONS")}</span>
                <h2>{tx(locale, "Telegram и веб-поиск", "Telegram and web search")}</h2>
                <p>{tx(
                  locale,
                  "Секреты хранятся локально и отображаются только в маскированном виде. Telegram использует официального Business-бота, Tavily улучшает поиск в интернете.",
                  "Secrets stay local and are only shown in masked form. Telegram uses an official connected Business bot; Tavily improves web search.",
                )}</p>
              </div>
              <div className="integration-grid">
                {([
                  {
                    service: "telegram" as const,
                    title: "Telegram Business Bot",
                    descriptionRu: "Создайте бота через @BotFather, включите Business Mode и подключите его в настройках Telegram. Nova увидит новые разрешённые диалоги после подключения.",
                    descriptionEn: "Create a bot with @BotFather, enable Business Mode, then connect it in Telegram settings. Nova sees newly observed permitted chats after connection.",
                    placeholder: "123456789:AA…",
                  },
                  {
                    service: "tavily" as const,
                    title: "Tavily Search",
                    descriptionRu: "Ключ Tavily для качественного веб-поиска. Без него Nova продолжит использовать бесплатный резервный поиск.",
                    descriptionEn: "Tavily key for higher-quality web search. Without it, Nova keeps using the free fallback search.",
                    placeholder: "tvly-…",
                  },
                ]).map((option) => {
                  const configured = serviceSecrets.find((item) => item.service === option.service);
                  return (
                    <section className="provider-group integration-service" key={option.service}>
                      <header>
                        <span>
                          <strong>{option.title}</strong>
                          <small>{tx(locale, option.descriptionRu, option.descriptionEn)}</small>
                        </span>
                        <b>{configured ? tx(locale, "ВКЛ", "ON") : tx(locale, "ВЫКЛ", "OFF")}</b>
                      </header>
                      {configured ? (
                        <div className="provider-key">
                          <span>
                            <code>{configured.hint}</code>
                            <small>{configured.source === "nova" ? tx(locale, "Добавлен в Nova", "Added in Nova") : tx(locale, "Системная переменная", "System environment variable")}</small>
                          </span>
                          {configured.removable && (
                            <button onClick={() => void removeServiceSecret(option.service)} title={tx(locale, "Отключить", "Disconnect")}>
                              <Trash2 size={13} />
                            </button>
                          )}
                        </div>
                      ) : (
                        <div className="integration-secret-row">
                          <input
                            type="password"
                            value={serviceDrafts[option.service]}
                            onChange={(event) => setServiceDrafts((current) => ({ ...current, [option.service]: event.target.value }))}
                            onKeyDown={(event) => { if (event.key === "Enter") void saveServiceSecret(option.service); }}
                            placeholder={option.placeholder}
                            autoComplete="off"
                          />
                          <button
                            className="save-settings"
                            onClick={() => void saveServiceSecret(option.service)}
                            disabled={serviceDrafts[option.service].trim().length < 12}
                          >
                            <Plus size={14} /> {tx(locale, "Подключить", "Connect")}
                          </button>
                        </div>
                      )}
                    </section>
                  );
                })}
              </div>
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
            <NovaMark size={96} />
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
