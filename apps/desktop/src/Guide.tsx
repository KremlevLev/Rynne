import {
  BookOpen,
  Bot,
  CheckCircle2,
  Code2,
  Command,
  KeyRound,
  Mic,
  Radio,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";

export type GuideLocale = "ru" | "en";

type GuideSection = {
  icon: typeof BookOpen;
  eyebrow: string;
  title: string;
  body: string;
  bullets: string[];
  examples?: string[];
};

const sections: Record<GuideLocale, GuideSection[]> = {
  ru: [
    {
      icon: Command,
      eyebrow: "БЫСТРЫЙ СТАРТ",
      title: "Ставьте цель обычными словами",
      body: "Не называйте инструменты. Опишите конечный результат и важные ограничения — Nova сама разложит задачу, найдёт tools и проверит итог.",
      bullets: [
        "Добавляйте контекст: приложение, сайт, файл или активный workspace.",
        "Составные команды можно давать одной фразой.",
        "Продолжайте коротко: «теперь там открой активность» — Nova помнит цель.",
      ],
      examples: [
        "Открой OpenRouter, зайди в Activity и сделай скрин.",
        "Найди ошибку в проекте, исправь её и запусти тесты.",
        "Открой Telegram, найди диалог с Лёшей и подготовь ответ — не отправляй.",
      ],
    },
    {
      icon: Wrench,
      eyebrow: "КАК NOVA РАБОТАЕТ",
      title: "Tools, skills и проверяемый результат",
      body: "Nova начинает с компактного набора возможностей, а затем подгружает нужные инструменты из полного локального и MCP-каталога.",
      bullets: [
        "Task ledger не позволяет закончить составную задачу после первого шага.",
        "Skills подсказывают правильную процедуру для браузера, Windows и проектов.",
        "При ошибке агент читает реальный tool result, выбирает альтернативу и продолжает.",
        "Если обязательный результат не достигнут, вы увидите честный blocker, а не ложное «готово».",
      ],
    },
    {
      icon: Mic,
      eyebrow: "ГОЛОС",
      title: "Кнопка, непрерывный режим и wake word",
      body: "Микрофон под строкой ввода переключает режим распознавания. Wake word работает локально через Vosk, после обращения полная команда распознаётся STT.",
      bullets: [
        "Wake «Нова»: дождитесь индикатора, скажите имя и после короткой паузы команду.",
        "«Слушать»: речь отправляется без ключевого слова.",
        "«Выкл.»: микрофон не используется.",
        "Во время TTS действует акустическая защита, чтобы Nova не услышала саму себя.",
      ],
      examples: ["Нова… открой календарь и покажи встречи на сегодня.", "Нова, давай — голосовое подтверждение proactive-подсказки."],
    },
    {
      icon: Radio,
      eyebrow: "NOVA РЯДОМ",
      title: "Проактивная помощь под вашим контролем",
      body: "Режим наблюдает только за активным окном, ищет видимую проблему и предлагает действие. Самостоятельно нажимать, отправлять или изменять данные он не может.",
      bullets: [
        "Включите режим в верхней панели или Settings.",
        "Для проверки откройте нужное окно и нажмите «Проверить сейчас» — снимок будет через 3 секунды.",
        "Предложение требует второго клика или голосового «Нова, давай».",
        "Банковские, платёжные, password-manager и private окна автоматически пропускаются.",
      ],
    },
    {
      icon: Code2,
      eyebrow: "СВОИ SKILLS",
      title: "Научите Nova вашему workflow",
      body: "Создайте SKILL.md — пересборка приложения не нужна. Правило загрузится по ключевым словам или пути файла и подключит необходимые tools.",
      bullets: [
        "%USERPROFILE%\\.nova\\skills — глобально.",
        "<workspace>\\.nova\\skills — только для проекта.",
        "<workspace>\\.agents\\skills — совместимый путь.",
        "Проектный skill переопределяет глобальный с тем же именем.",
      ],
      examples: ["triggers: [релиз, опубликуй версию]", "tools: [run_project_tests, git_commit]"],
    },
    {
      icon: KeyRound,
      eyebrow: "МОДЕЛИ И MCP",
      title: "Ключи, провайдеры и внешние сервисы",
      body: "В Settings можно хранить любое количество ключей Groq, OpenRouter и Gemini. Nova ротирует их и использует один общий capability registry для native и MCP tools.",
      bullets: [
        "Полный API-ключ не возвращается в React — отображаются только начало и конец.",
        "Groq: GPT OSS 120B для текста/tools, Qwen для изображений.",
        "MCP подключает файловые серверы, API и рабочие сервисы.",
        "Если tool не виден сразу, Nova может найти и подгрузить его через discover_tools.",
      ],
    },
    {
      icon: ShieldCheck,
      eyebrow: "БЕЗОПАСНОСТЬ",
      title: "Что требует подтверждения",
      body: "Чтение и безопасная диагностика выполняются сразу. Отправка сообщений, необратимые изменения и другие рискованные действия проходят policy и подтверждение.",
      bullets: [
        "Можно сказать «подготовь, но не отправляй», чтобы остановиться перед side effect.",
        "Содержимое сайтов и экрана считается недоверенным и не может переписать системные правила.",
        "Nova не должна повторять уже успешный side effect при fallback.",
        "Для отмены текущей задачи используйте квадратную кнопку Stop.",
      ],
    },
    {
      icon: Bot,
      eyebrow: "ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ",
      title: "Быстрая диагностика",
      body: "Сначала посмотрите статус Core, микрофона и текущего tool в правой панели. Затем сформулируйте наблюдаемый результат — Nova сможет проверить систему своими read-only tools.",
      bullets: [
        "«Проверь состояние Core и последние ошибки запуска».",
        "«Проверь микрофон, Vosk и STT, ничего не меняй».",
        "«Покажи активные процессы Nova и останови только зависшие после подтверждения».",
        "В dev-режиме используйте scripts/dev-desktop.ps1 вместо пересборки installer.",
      ],
    },
  ],
  en: [
    {
      icon: Command,
      eyebrow: "QUICK START",
      title: "Describe the outcome in plain language",
      body: "You do not need to name tools. State the final result and important constraints — Nova will decompose the task, find capabilities, and verify the outcome.",
      bullets: [
        "Include context: the app, website, file, or active workspace.",
        "Give multi-step tasks in one message.",
        "Continue naturally: “now open Activity there” — Nova keeps the goal in context.",
      ],
      examples: [
        "Open OpenRouter, go to Activity, and take a screenshot.",
        "Find the project error, fix it, and run the tests.",
        "Open Telegram, find Alex's chat, and draft a reply — do not send it.",
      ],
    },
    {
      icon: Wrench,
      eyebrow: "HOW NOVA WORKS",
      title: "Tools, skills, and verifiable outcomes",
      body: "Nova starts with a compact capability set, then loads the right tools from the full local and MCP catalog on demand.",
      bullets: [
        "The task ledger prevents a multi-step task from ending after one convenient action.",
        "Skills provide proven procedures for browser, Windows, and project workflows.",
        "After an error, the agent reads the real tool result, selects an alternative, and continues.",
        "If a required outcome is missing, Nova reports a concrete blocker instead of claiming success.",
      ],
    },
    {
      icon: Mic,
      eyebrow: "VOICE",
      title: "Push to talk, continuous listening, and wake word",
      body: "Controls below the composer switch recognition modes. The wake word runs locally with Vosk; the full command is then passed to STT.",
      bullets: [
        "Wake “Nova”: wait for the indicator, say the name, pause briefly, then say the command.",
        "Listen: recognize speech without a wake word.",
        "Off: do not use the microphone.",
        "An acoustic guard prevents Nova from transcribing its own TTS output.",
      ],
      examples: ["Nova… open my calendar and show today's meetings.", "Nova, go ahead — confirm a proactive suggestion by voice."],
    },
    {
      icon: Radio,
      eyebrow: "NOVA NEARBY",
      title: "Proactive help under your control",
      body: "This mode observes only the active window, detects visible problems, and suggests an action. It cannot click, submit, or modify data on its own.",
      bullets: [
        "Enable it from the top bar or Settings.",
        "Open the target window and click Check now — capture starts after three seconds.",
        "A suggestion requires a second click or the voice phrase “Nova, go ahead.”",
        "Banking, payment, password-manager, and private windows are skipped automatically.",
      ],
    },
    {
      icon: Code2,
      eyebrow: "CUSTOM SKILLS",
      title: "Teach Nova your workflow",
      body: "Create a SKILL.md file — no rebuild required. Rules load by keyword or file path and bring their required tools into the agent loop.",
      bullets: [
        "%USERPROFILE%\\.nova\\skills — global skills.",
        "<workspace>\\.nova\\skills — project skills.",
        "<workspace>\\.agents\\skills — compatible path.",
        "A project skill overrides a global skill with the same name.",
      ],
      examples: ["triggers: [release, publish version]", "tools: [run_project_tests, git_commit]"],
    },
    {
      icon: KeyRound,
      eyebrow: "MODELS AND MCP",
      title: "Keys, providers, and external services",
      body: "Settings can store any number of Groq, OpenRouter, and Gemini keys. Nova rotates them and exposes native and MCP tools through one capability registry.",
      bullets: [
        "Full API keys never return to React — only a masked prefix and suffix are shown.",
        "Groq: GPT OSS 120B for text/tools and Qwen for images.",
        "MCP connects file servers, APIs, and work services.",
        "If a capability is deferred, Nova can find and load it through discover_tools.",
      ],
    },
    {
      icon: ShieldCheck,
      eyebrow: "SAFETY",
      title: "What requires confirmation",
      body: "Reading and safe diagnostics can run immediately. Sending messages, irreversible changes, and other risky actions pass policy checks and confirmation.",
      bullets: [
        "Say “draft it, but do not send” to stop before a side effect.",
        "Web and screen content is untrusted and cannot override system rules.",
        "Fallback routes must not repeat a side effect that already succeeded.",
        "Use the square Stop button to cancel the active task.",
      ],
    },
    {
      icon: Bot,
      eyebrow: "TROUBLESHOOTING",
      title: "Fast diagnostics",
      body: "Check Core, microphone, and active-tool status in the side panel. Then describe the observed failure — Nova can inspect it with read-only tools.",
      bullets: [
        "“Check Core health and the latest startup errors.”",
        "“Check the microphone, Vosk, and STT without changing anything.”",
        "“List Nova processes and stop only stale ones after confirmation.”",
        "In development, use scripts/dev-desktop.ps1 instead of rebuilding the installer.",
      ],
    },
  ],
};

export function Guide({ locale }: { locale: GuideLocale }) {
  const isRu = locale === "ru";
  return (
    <div className="guide-view">
      <section className="guide-hero">
        <span className="guide-orb"><Sparkles size={24} /></span>
        <div>
          <span className="eyebrow">{isRu ? "ПАМЯТКА NOVA" : "NOVA HANDBOOK"}</span>
          <h2>{isRu ? "Передайте задачу, а не набор кликов" : "Delegate an outcome, not a sequence of clicks"}</h2>
          <p>{isRu
            ? "Эта памятка объясняет весь рабочий цикл: от первой команды и голоса до proactive-режима, собственных skills, MCP и безопасных подтверждений."
            : "This handbook covers the complete workflow: first commands, voice, proactive mode, custom skills, MCP, and safe confirmations."}</p>
        </div>
      </section>

      <div className="guide-grid">
        {sections[locale].map((section) => {
          const Icon = section.icon;
          return (
            <article className="guide-card" key={section.title}>
              <span className="guide-icon"><Icon size={19} /></span>
              <div>
                <span className="eyebrow">{section.eyebrow}</span>
                <h3>{section.title}</h3>
                <p>{section.body}</p>
                <ul>
                  {section.bullets.map((bullet) => (
                    <li key={bullet}><CheckCircle2 size={14} />{bullet}</li>
                  ))}
                </ul>
                {section.examples && (
                  <div className="guide-examples">
                    <strong>{isRu ? "Попробуйте" : "Try it"}</strong>
                    {section.examples.map((example) => <code key={example}>{example}</code>)}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <section className="guide-footer">
        <BookOpen size={18} />
        <p>{isRu
          ? "Совет: если Nova остановилась слишком рано, не повторяйте всю команду — скажите, какой результат ещё не достигнут. Goal ledger продолжит исходную задачу."
          : "Tip: if Nova stops too early, do not repeat the whole request — state which outcome is still missing. The goal ledger will continue the original task."}</p>
      </section>
    </div>
  );
}
