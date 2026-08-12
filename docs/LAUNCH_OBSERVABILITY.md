# Rynne launch observability

Rynne diagnostics are opt-in. Enable them with `RYNNE_TELEMETRY_ENABLED=true` only after the user has agreed.

## Collected

- app version, device online state and uptime;
- Rynne process CPU and memory usage;
- configured provider count, provider/model names and stable error codes;
- task status, tool names, durations and whether verification succeeded;
- crash component and a short redacted technical message.

## Never collected

- prompts, assistant replies or Telegram messages;
- screenshots or file contents;
- API keys, bot tokens, device tokens, cookies or environment variables;
- terminal command arguments or clipboard contents.

## Launch funnel

Measure these only as aggregate counters after explicit consent:

1. installer started and completed;
2. Core reached ready state;
3. at least one provider was configured;
4. first task was submitted;
5. first task completed and passed verification;
6. the user returned after one and seven days.

Do not use stars or raw downloads as the primary activation metric. The useful metric is `first verified task / completed installations`.

## Failure triage

Group failures by stable code and component. Fix them in this order:

1. startup and Core connection;
2. tasks that remain active beyond the hard deadline;
3. provider timeouts and exhausted keys;
4. wrong tool selection or invalid parameters;
5. tools reporting success without verification;
6. voice recognition and TTS latency;
7. cosmetic UI failures.

Ask testers for the task ID, approximate time, visible final status and a diagnostics ZIP created from Settings. Never ask them to paste `.env`.
