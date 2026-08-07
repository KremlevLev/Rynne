export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  | JsonPrimitive
  | JsonValue[]
  | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export const NOVA_EVENT_TYPES = [
  "runtime",
  "request_started",
  "request_cancelled",
  "request_failed",
  "user_message",
  "assistant_message",
  "proactive_suggestion",
  "proactive_status",
  "proactive_check_result",
  "proactive_confirmation_resolved",
  "tool_started",
  "tool_completed",
  "task_started",
  "task_progress",
  "task_completed",
  "task_failed",
  "task_cancelled",
  "approval_requested",
  "permissions",
  "processes",
  "memories",
  "integrations",
  "preferences",
  "voice_status",
  "voice_activity",
  "models",
  "command_result",
  "shutdown",
] as const;

export type NovaEventType = (typeof NOVA_EVENT_TYPES)[number];

export const NOVA_COMMAND_ACTIONS = [
  "retry_last",
  "set_input_mode",
  "set_preference",
  "set_tts_settings",
  "preview_tts",
  "set_wake_word_sensitivity",
  "run_proactive_check",
  "proactive_feedback",
  "refresh",
  "stop_process",
  "delete_memory",
  "clear_memories",
  "confirm_permission",
  "deny_permission",
  "submit_user_request",
  "cancel_current_request",
  "new_task",
  "toggle_voice_mode",
  "pause_task",
  "cancel_task",
  "approve_task",
  "open_artifact",
] as const;

export type NovaCommandAction = (typeof NOVA_COMMAND_ACTIONS)[number];

export interface NovaEvent<TPayload extends JsonObject = JsonObject> {
  event_type: NovaEventType;
  payload: TPayload;
  created_at: number;
}

export interface NovaCommand<TPayload extends JsonObject = JsonObject> {
  command_id: string;
  action: NovaCommandAction;
  payload: TPayload;
  created_at: number;
}

const eventTypes = new Set<string>(NOVA_EVENT_TYPES);

export function isNovaEvent(value: unknown): value is NovaEvent {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.event_type === "string" &&
    eventTypes.has(candidate.event_type) &&
    typeof candidate.created_at === "number" &&
    !!candidate.payload &&
    typeof candidate.payload === "object" &&
    !Array.isArray(candidate.payload)
  );
}

export function makeCommand<TPayload extends JsonObject>(
  action: NovaCommandAction,
  payload: TPayload,
): NovaCommand<TPayload> {
  return {
    command_id: `ui_command_${crypto.randomUUID().replaceAll("-", "")}`,
    action,
    payload,
    created_at: Date.now() / 1000,
  };
}
