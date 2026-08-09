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
export type ProviderName = "groq" | "openrouter" | "gemini";
export type ServiceName = "telegram" | "tavily";
export interface ProviderKeySummary {
  provider: ProviderName;
  index: number;
  hint: string;
  source: "nova" | "environment";
  removable: boolean;
  model: string;
}
export interface ServiceSecretSummary {
  service: ServiceName;
  hint: string;
  source: "nova" | "environment";
  removable: boolean;
}

export interface NovaTransport {
  connect(onEvent: EventListener, onConnection: ConnectionListener): Promise<() => void>;
  send(action: NovaCommandAction, payload?: JsonObject): Promise<void>;
  listProviderKeys(): Promise<ProviderKeySummary[]>;
  addProviderKey(provider: ProviderName, apiKey: string, model?: string): Promise<void>;
  updateProviderKeyModel(provider: ProviderName, index: number, model: string): Promise<void>;
  removeProviderKey(provider: ProviderName, index: number): Promise<void>;
  listServiceSecrets(): Promise<ServiceSecretSummary[]>;
  setServiceSecret(service: ServiceName, secret: string): Promise<void>;
  removeServiceSecret(service: ServiceName): Promise<void>;
}

export class TauriNovaTransport implements NovaTransport {
  async connect(
    onEvent: EventListener,
    onConnection: ConnectionListener,
  ): Promise<() => void> {
    onConnection("connecting");
    let unlisten: UnlistenFn;
    let unlistenConnection: UnlistenFn;
    let disposed = false;
    let polling = false;

    const wait = (delay: number) =>
      new Promise((resolve) => window.setTimeout(resolve, delay));

    const pollConnection = async () => {
      if (polling || disposed) return;
      polling = true;
      let failedAttempts = 0;

      while (!disposed) {
        let ready = false;
        try {
          ready = await invoke<boolean>("nova_connect");
        } catch {
          ready = false;
        }

        if (ready) {
          failedAttempts = 0;
          onConnection("connected");
          await wait(2_000);
          continue;
        }

        failedAttempts += 1;
        onConnection(failedAttempts < 120 ? "connecting" : "disconnected");
        await wait(failedAttempts < 120 ? 250 : 2_000);
      }

      polling = false;
    };

    try {
      unlisten = await listen<unknown>("nova:event", ({ payload }) => {
        if (isNovaEvent(payload)) onEvent(payload);
      });
      unlistenConnection = await listen<boolean>("nova:connection", ({ payload }) => {
        if (payload) {
          onConnection("connected");
        } else {
          onConnection("connecting");
        }
      });
      void pollConnection();
    } catch {
      onConnection("disconnected");
      return () => undefined;
    }

    return () => {
      disposed = true;
      unlisten();
      unlistenConnection();
      onConnection("disconnected");
    };
  }

  async send(action: NovaCommandAction, payload: JsonObject = {}): Promise<void> {
    await invoke("nova_send_command", {
      command: makeCommand(action, payload),
    });
  }

  async listProviderKeys(): Promise<ProviderKeySummary[]> {
    return invoke<ProviderKeySummary[]>("nova_list_provider_keys");
  }

  async addProviderKey(provider: ProviderName, apiKey: string, model = ""): Promise<void> {
    await invoke("nova_add_provider_key", {
      provider,
      apiKey,
      model,
    });
  }

  async updateProviderKeyModel(
    provider: ProviderName,
    index: number,
    model: string,
  ): Promise<void> {
    await invoke("nova_update_provider_key_model", { provider, index, model });
  }

  async removeProviderKey(provider: ProviderName, index: number): Promise<void> {
    await invoke("nova_remove_provider_key", {
      provider,
      index,
    });
  }

  async listServiceSecrets(): Promise<ServiceSecretSummary[]> {
    return invoke<ServiceSecretSummary[]>("nova_list_service_secrets");
  }

  async setServiceSecret(service: ServiceName, secret: string): Promise<void> {
    await invoke("nova_set_service_secret", { service, secret });
  }

  async removeServiceSecret(service: ServiceName): Promise<void> {
    await invoke("nova_remove_service_secret", { service });
  }
}

class DemoNovaTransport implements NovaTransport {
  private listener: EventListener | null = null;
  private timers = new Set<number>();
  private seeded = false;
  private voiceActive = false;
  private inputMode = "sleep";

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
      this.push("preferences", {
        proactive_vision_enabled: true,
        input_mode: this.inputMode,
        wake_word_available: true,
        wake_word: "Нова",
        wake_word_sensitivity: 0.78,
        tts_settings: {
          language: "auto",
          ru_voice: "baya",
          en_voice: "autumn",
          speed: 1,
          style: "neutral",
        },
        tts_catalog: {
          languages: ["auto", "ru", "en"],
          styles: ["neutral", "warm", "cheerful", "professional", "confident"],
          voices: [
            ...[
              ["aidar", "Aidar", "male"], ["baya", "Baya", "female"],
              ["kseniya", "Kseniya", "female"], ["xenia", "Xenia", "female"],
              ["eugene", "Eugene", "male"],
            ].map(([id, name, gender]) => ({ id, name, gender, language: "ru", engine: "silero", model: "v5_ru", online: false, available: true })),
            ...[
              ["autumn", "Autumn", "female"], ["diana", "Diana", "female"],
              ["hannah", "Hannah", "female"], ["austin", "Austin", "male"],
              ["daniel", "Daniel", "male"], ["troy", "Troy", "male"],
            ].map(([id, name, gender]) => ({ id, name, gender, language: "en", engine: "groq", model: "canopylabs/orpheus-v1-english", online: true, available: true })),
          ],
        },
      });
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
    if (action === "toggle_voice_mode") {
      this.voiceActive = !this.voiceActive;
      this.inputMode = this.voiceActive ? "continuous" : "sleep";
      this.push("preferences", {
        proactive_vision_enabled: true,
        input_mode: this.inputMode,
        wake_word_available: true,
        wake_word: "Нова",
        wake_word_sensitivity: 0.78,
      });
      this.push("voice_status", {
        status: this.voiceActive ? "listening" : "stopped",
        message: this.voiceActive ? "Слушаю микрофон…" : "Голосовой ввод остановлен.",
      });
    }
    if (action === "set_input_mode") {
      this.inputMode = String(payload.input_mode ?? "sleep");
      this.voiceActive = this.inputMode === "continuous";
      this.push("preferences", {
        proactive_vision_enabled: true,
        input_mode: this.inputMode,
        wake_word_available: true,
        wake_word: "Нова",
        wake_word_sensitivity: 0.78,
      });
      this.push("voice_status", {
        status: this.inputMode === "wake_word" ? "waiting_wake_word" : this.inputMode,
        message: this.inputMode === "wake_word" ? "Жду «Нова»…" : "Режим микрофона изменён.",
      });
    }
    if (action === "set_wake_word_sensitivity") {
      this.push("preferences", {
        proactive_vision_enabled: true,
        input_mode: this.inputMode,
        wake_word_available: true,
        wake_word: "Нова",
        wake_word_sensitivity: Number(payload.value ?? 0.78),
      });
    }
    if (action === "run_proactive_check") {
      this.push("proactive_status", { phase: "scanning", message: "Проверяю активное окно…" });
      this.later(650, () => this.push("proactive_status", {
        phase: "checked",
        message: "Проверено — всё спокойно",
        suggestions: 0,
      }));
    }
  }

  async listProviderKeys(): Promise<ProviderKeySummary[]> {
    return [];
  }

  async addProviderKey(): Promise<void> {
    return Promise.resolve();
  }

  async updateProviderKeyModel(): Promise<void> {
    return Promise.resolve();
  }

  async removeProviderKey(): Promise<void> {
    return Promise.resolve();
  }

  async listServiceSecrets(): Promise<ServiceSecretSummary[]> {
    return [];
  }

  async setServiceSecret(): Promise<void> {
    return Promise.resolve();
  }

  async removeServiceSecret(): Promise<void> {
    return Promise.resolve();
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
