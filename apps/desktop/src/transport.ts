import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import {
  isNovaEvent,
  makeCommand,
  type JsonObject,
  type NovaCommandAction,
  type NovaEvent,
} from "./protocol";

export type ConnectionState = "connecting" | "connected" | "disconnected";
export type EventListener = (event: NovaEvent) => void;
export type ConnectionListener = (state: ConnectionState) => void;

export interface NovaTransport {
  connect(onEvent: EventListener, onConnection: ConnectionListener): Promise<() => void>;
  send(action: NovaCommandAction, payload?: JsonObject): Promise<void>;
}

export class TauriNovaTransport implements NovaTransport {
  async connect(
    onEvent: EventListener,
    onConnection: ConnectionListener,
  ): Promise<() => void> {
    onConnection("connecting");
    let unlisten: UnlistenFn;
    try {
      unlisten = await listen<unknown>("nova:event", ({ payload }) => {
        if (isNovaEvent(payload)) onEvent(payload);
      });
      const ready = await invoke<boolean>("nova_connect");
      if (!ready) {
        unlisten();
        onConnection("disconnected");
        return () => undefined;
      }
      onConnection("connected");
    } catch {
      onConnection("disconnected");
      return () => undefined;
    }

    return () => {
      unlisten();
      onConnection("disconnected");
    };
  }

  async send(action: NovaCommandAction, payload: JsonObject = {}): Promise<void> {
    await invoke("nova_send_command", {
      command: makeCommand(action, payload),
    });
  }
}

class DemoNovaTransport implements NovaTransport {
  private listener: EventListener | null = null;
  private timers = new Set<number>();
  private seeded = false;

  async connect(
    onEvent: EventListener,
    onConnection: ConnectionListener,
  ): Promise<() => void> {
    const listener = onEvent;
    this.listener = listener;
    onConnection("connected");
    if (!this.seeded) {
      this.seeded = true;
      this.push("runtime", { status: "idle", voice_enabled: true });
      this.push("preferences", { proactive_vision_enabled: true });
      this.push("processes", {
        processes: [
          {
            process_id: "demo_1",
            name: "Анализ проекта Nova",
            status: "running",
            progress: 68,
          },
        ],
      });
      this.push("proactive_suggestion", {
        title: "Похоже, тесты упали после изменения UI",
        message: "Могу сравнить traceback с последним diff и подготовить исправление.",
        suggested_request: "Найди причину падения UI-тестов и исправь её",
      });
    }

    return () => {
      if (this.listener === listener) {
        this.listener = null;
        this.timers.forEach(window.clearTimeout);
        this.timers.clear();
      }
    };
  }

  async send(action: NovaCommandAction, payload: JsonObject = {}): Promise<void> {
    if (action === "submit_user_request") {
      const text = String(payload.text ?? "");
      this.push("user_message", { text });
      this.push("request_started", { text });
      this.later(500, () =>
        this.push("tool_started", {
          tool_name: "inspect_workspace",
          description: "Проверяю проект и активные процессы",
        }),
      );
      this.later(1400, () => {
        this.push("tool_completed", {
          tool_name: "inspect_workspace",
          success: true,
          duration_ms: 843,
        });
        this.push("assistant_message", {
          text: "Нашла узкое место в UI-процессе. Могу подготовить безопасный patch и прогнать тесты.",
          success: true,
        });
      });
    }
    if (action === "new_task") {
      this.push("runtime", { status: "idle", voice_enabled: true });
    }
  }

  private push(event_type: NovaEvent["event_type"], payload: JsonObject): void {
    this.listener?.({
      event_type,
      payload,
      created_at: Date.now() / 1000,
    });
  }

  private later(delay: number, callback: () => void): void {
    const timer = window.setTimeout(() => {
      this.timers.delete(timer);
      callback();
    }, delay);
    this.timers.add(timer);
  }
}

export function createNovaTransport(): NovaTransport {
  const demoRequested =
    import.meta.env.DEV &&
    new URLSearchParams(window.location.search).get("demo") === "1";
  return demoRequested ? new DemoNovaTransport() : new TauriNovaTransport();
}
