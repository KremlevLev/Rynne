import { describe, expect, it, vi } from "vitest";
import {
  eventToItem,
  scrollConversationToBottom,
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
