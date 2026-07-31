import { describe, expect, it, vi } from "vitest";
import {
  eventToItem,
  normalizeUiMode,
  readUiMode,
  scrollConversationToBottom,
  UI_MODE_OPTIONS,
  PROVIDER_OPTIONS,
  writeUiMode,
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

  it("scrolls only the conversation container", () => {
    const scrollTo = vi.fn();

    scrollConversationToBottom({
      scrollHeight: 2048,
      scrollTo,
    });

    expect(scrollTo).toHaveBeenCalledWith({
      top: 2048,
      behavior: "smooth",
    });
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

describe("provider key pools", () => {
  it("offers every supported cloud provider", () => {
    expect(PROVIDER_OPTIONS.map((option) => option.key)).toEqual([
      "groq",
      "openrouter",
      "gemini",
    ]);
  });
});
