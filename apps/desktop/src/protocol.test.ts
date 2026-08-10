import { describe, expect, it, vi } from "vitest";
import {
  isRynneEvent,
  makeCommand,
  RYNNE_COMMAND_ACTIONS,
  RYNNE_EVENT_TYPES,
} from "./protocol";
import { eventToItem, runtimePresentation } from "./App";

describe("Rynne desktop protocol", () => {
  it("accepts the same JSON event envelope as Python", () => {
    expect(
      isRynneEvent({
        event_type: "assistant_message",
        payload: { text: "Готово" },
        created_at: 123.4,
      }),
    ).toBe(true);
  });

  it("rejects unknown and malformed events", () => {
    expect(isRynneEvent({ event_type: "unknown", payload: {}, created_at: 1 })).toBe(false);
    expect(isRynneEvent({ event_type: "runtime", payload: [], created_at: 1 })).toBe(false);
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
    expect(RYNNE_EVENT_TYPES).toContain("proactive_suggestion");
    expect(RYNNE_EVENT_TYPES).toContain("proactive_status");
    expect(RYNNE_EVENT_TYPES).toContain("proactive_confirmation_resolved");
    expect(RYNNE_EVENT_TYPES).toContain("agent_progress");
    expect(RYNNE_EVENT_TYPES).toContain("request_heartbeat");
    expect(RYNNE_COMMAND_ACTIONS).toContain("set_preference");
    expect(RYNNE_COMMAND_ACTIONS).toContain("set_tts_settings");
    expect(RYNNE_COMMAND_ACTIONS).toContain("preview_tts");
    expect(RYNNE_COMMAND_ACTIONS).toContain("proactive_feedback");
  });

  it("maps Core runtime state into the integrated desktop indicator", () => {
    expect(runtimePresentation("ГОВОРИТ")).toEqual({
      label: "Rynne отвечает",
      working: true,
    });
    expect(runtimePresentation("СПИТ")).toEqual({
      label: "Rynne готова",
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
