import { describe, expect, it, vi } from "vitest";
import {
  eventToItem,
  isConversationNearBottom,
  normalizeUiMode,
  normalizeUiLocale,
  pendingPermissionFromEvent,
  readUiLocale,
  readUiMode,
  scrollConversationToBottom,
  UI_MODE_OPTIONS,
  uiModeOptions,
  PROVIDER_OPTIONS,
  writeUiMode,
  writeUiLocale,
} from "./App";

describe("eventToItem", () => {
  it("renders the Core assistant display_text payload", () => {
    const item = eventToItem({
      event_type: "assistant_message",
      payload: {
        display_text: "Привет! Чем помочь?",
        speech_text: "Привет! Чем помочь?",
        success: true,
      },
      created_at: 1,
    });

    expect(item?.kind).toBe("assistant");
    expect(item?.body).toBe("Привет! Чем помочь?");
  });

  it("renders request failures instead of an empty card", () => {
    const item = eventToItem({
      event_type: "request_failed",
      payload: {
        error: "Провайдер временно недоступен.",
      },
      created_at: 2,
    });

    expect(item?.body).toBe("Провайдер временно недоступен.");
    expect(item?.status).toBe("error");
  });

  it("renders an explicit cancellation result", () => {
    const item = eventToItem({
      event_type: "request_cancelled",
      payload: { request_id: "req-1" },
      created_at: 3,
    });

    expect(item?.body).toBe("Задача остановлена.");
    expect(item?.status).toBe("error");
  });

  it("renders detailed agent stages and long-running heartbeats", () => {
    const stage = eventToItem({
      event_type: "agent_progress",
      payload: {
        phase: "model",
        progress: 30,
      },
      created_at: 4,
    });
    const heartbeat = eventToItem({
      event_type: "request_heartbeat",
      payload: { elapsed_seconds: 44, alive: true },
      created_at: 5,
    });

    expect(stage).toMatchObject({
      kind: "progress",
      title: "Модель строит следующий шаг",
      progress: 30,
      status: "working",
    });
    expect(heartbeat?.body).toContain("44 сек");
  });

  it("shows concrete selected tools and safe argument names", () => {
    const stage = eventToItem({
      event_type: "agent_progress",
      payload: {
        phase: "executing",
        progress: 50,
        proposed_tools: 2,
        tool_names: ["open_application", "write_in_application"],
      },
      created_at: 6,
    });
    const tool = eventToItem({
      event_type: "tool_started",
      payload: {
        tool_name: "write_in_application",
        description: "Пишу текст в Obsidian",
        argument_names: ["application", "text"],
        risk: "low",
      },
      created_at: 7,
    });

    expect(stage?.body).toContain("open_application, write_in_application");
    expect(tool?.body).toContain("application, text");
  });

  it("shows deterministic Telegram fast-path stages", () => {
    const resolving = eventToItem({
      event_type: "agent_progress",
      payload: { phase: "telegram_resolving", progress: 30 },
      created_at: 8,
    });
    const sending = eventToItem({
      event_type: "agent_progress",
      payload: { phase: "telegram_sending", progress: 60 },
      created_at: 9,
    });

    expect(resolving?.title).toBe("Ищу получателя в Telegram");
    expect(sending?.title).toBe("Отправляю сообщение в Telegram");
  });

  it("shows wake capture before the command reaches the model", () => {
    const detected = eventToItem({
      event_type: "voice_activity",
      payload: { source: "wake_word", phase: "wake_detected", level: 0.8 },
      created_at: 8,
    });
    const captured = eventToItem({
      event_type: "voice_status",
      payload: {
        status: "wake_word_detected",
        message: "Фраза записана за 2.1 сек. Распознаю команду…",
      },
      created_at: 9,
    });

    expect(detected?.title).toBe("Услышала «Рин»");
    expect(captured?.body).toContain("2.1 сек");
    expect(captured?.status).toBe("working");
  });

  it("scrolls only the conversation container", () => {
    const scrollTo = vi.fn();

    scrollConversationToBottom({
      scrollHeight: 2048,
      scrollTo,
    });

    expect(scrollTo).toHaveBeenCalledWith({
      top: 2048,
      behavior: "auto",
    });
  });

  it("does not force new events over a user reading older messages", () => {
    expect(isConversationNearBottom({
      scrollHeight: 2400,
      scrollTop: 700,
      clientHeight: 600,
    })).toBe(false);
    expect(isConversationNearBottom({
      scrollHeight: 2400,
      scrollTop: 1740,
      clientHeight: 600,
    })).toBe(true);
  });
});

describe("permission bridge", () => {
  it("turns a Core permission snapshot into a visible approval", () => {
    const permission = pendingPermissionFromEvent({
      event_type: "permissions",
      payload: {
        items: [{
          operation_id: "op_1",
          tool_name: "run_terminal_command",
          risk: "execute",
          message: "Run tests?",
          arguments: { command: "pytest -q" },
          expires_at: 123,
        }],
      },
      created_at: 1,
    });

    expect(permission?.operationId).toBe("op_1");
    expect(permission?.arguments.command).toBe("pytest -q");
  });

  it("shows an immediate approval event without waiting for a snapshot", () => {
    const permission = pendingPermissionFromEvent({
      event_type: "approval_requested",
      payload: {
        operation_id: "op_fast",
        tool_name: "run_terminal_command",
        risk: "execute",
        message: "Run the command?",
        arguments: { command: "npm test" },
        expires_at: 456,
      },
      created_at: 3,
    });

    expect(permission?.operationId).toBe("op_fast");
  });

  it("clears the approval when Core has no pending permissions", () => {
    expect(pendingPermissionFromEvent({
      event_type: "permissions",
      payload: { items: [] },
      created_at: 2,
    })).toBeNull();
  });
});

describe("UI modes", () => {
  it("offers full, balanced and console layouts", () => {
    expect(UI_MODE_OPTIONS.map((option) => option.key)).toEqual([
      "aura",
      "focus",
      "console",
    ]);
    expect(normalizeUiMode("console")).toBe("console");
    expect(normalizeUiMode("broken")).toBe("aura");
    expect(UI_MODE_OPTIONS.map((option) => option.shortLabel)).toEqual([
      "Красивый",
      "Средний",
      "Лёгкий",
    ]);
  });

  it("persists the selected presentation without involving Core", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };

    writeUiMode(storage, "focus");

    expect(readUiMode(storage)).toBe("focus");
  });
});

describe("UI language", () => {
  it("offers a complete English presentation copy", () => {
    expect(normalizeUiLocale("en")).toBe("en");
    expect(normalizeUiLocale("unknown")).toBe("ru");
    expect(uiModeOptions("en").map((option) => option.shortLabel)).toEqual([
      "Beautiful",
      "Balanced",
      "Light",
    ]);
    expect(eventToItem({
      event_type: "request_failed",
      payload: {},
      created_at: 3,
    }, "en")?.body).toBe("The request could not be completed.");
  });

  it("persists locale without involving Rynne Core", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };

    writeUiLocale(storage, "en");

    expect(readUiLocale(storage)).toBe("en");
  });
});

describe("provider key pools", () => {
  it("offers every supported cloud provider", () => {
    expect(PROVIDER_OPTIONS.map((option) => option.key)).toEqual([
      "groq",
      "openrouter",
      "gemini",
      "openai",
      "anthropic",
    ]);
  });
});
