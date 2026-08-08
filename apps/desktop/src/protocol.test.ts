import { describe, expect, it, vi } from "vitest";
import {
  isNovaEvent,
  makeCommand,
  NOVA_COMMAND_ACTIONS,
  NOVA_EVENT_TYPES,
} from "./protocol";
import { eventToItem, runtimePresentation } from "./App";

describe("Nova desktop protocol", () => {
  it("accepts the same JSON event envelope as Python", () => {
    expect(
      isNovaEvent({
        event_type: "assistant_message",
        payload: { text: "Готово" },
        created_at: 123.4,
      }),
    ).toBe(true);
  });

  it("rejects unknown and malformed events", () => {
    expect(isNovaEvent({ event_type: "unknown", payload: {}, created_at: 1 })).toBe(false);
    expect(isNovaEvent({ event_type: "runtime", payload: [], created_at: 1 })).toBe(false);
  });

  it("creates Python-compatible commands", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "11111111-2222-3333-4444-555555555555" });
    const command = makeCommand("submit_user_request", { text: "Проверь тесты" });
    expect(command).toMatchObject({
      command_id: "ui_command_11111111222233334444555555555555",
      action: "submit_user_request",
      payload: { text: "Проверь тесты" },
    });
    expect(command.created_at).toEqual(expect.any(Number));
    vi.unstubAllGlobals();
  });

  it("keeps the initial contract explicit", () => {
    expect(NOVA_EVENT_TYPES).toContain("proactive_suggestion");
    expect(NOVA_EVENT_TYPES).toContain("proactive_status");
    expect(NOVA_EVENT_TYPES).toContain("proactive_confirmation_resolved");
    expect(NOVA_EVENT_TYPES).toContain("agent_progress");
    expect(NOVA_EVENT_TYPES).toContain("request_heartbeat");
    expect(NOVA_COMMAND_ACTIONS).toContain("set_preference");
    expect(NOVA_COMMAND_ACTIONS).toContain("set_tts_settings");
    expect(NOVA_COMMAND_ACTIONS).toContain("preview_tts");
    expect(NOVA_COMMAND_ACTIONS).toContain("proactive_feedback");
  });

  it("maps Core runtime state into the integrated desktop indicator", () => {
    expect(runtimePresentation("ГОВОРИТ")).toEqual({
      label: "Nova отвечает",
      working: true,
    });
    expect(runtimePresentation("СПИТ")).toEqual({
      label: "Nova готова",
      working: false,
    });
  });

  it("keeps proactive identity and one-shot visual context on the card", () => {
    const item = eventToItem({
      event_type: "proactive_suggestion",
      payload: {
        event_id: "proactive_visual_1",
        source_key: "visual:fingerprint",
        title: "Вижу ошибку",
        message: "Могу проверить.",
        suggested_request: "Разбери ошибку",
        action_label: "Разобраться",
      },
      created_at: 1,
    });

    expect(item).toMatchObject({
      action: "Разбери ошибку",
      actionLabel: "Разобраться",
      proactiveEventId: "proactive_visual_1",
      proactiveContextKey: "visual:fingerprint",
    });
  });
});
