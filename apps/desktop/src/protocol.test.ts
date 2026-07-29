import { describe, expect, it, vi } from "vitest";
import {
  isNovaEvent,
  makeCommand,
  NOVA_COMMAND_ACTIONS,
  NOVA_EVENT_TYPES,
} from "./protocol";

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
    expect(NOVA_COMMAND_ACTIONS).toContain("set_preference");
  });
});
