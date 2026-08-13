# Changelog

All notable changes to Rynne are documented here.

## [1.0.1] - 2026-08-13

### Fixed

- Added an installed always-on Remote Bridge so Telegram Mini App wake requests launch the production desktop application rather than the development runtime.
- Fixed the NSIS startup shortcut used by the Remote Bridge.
- Fixed broken Russian text in the Mini App and made remote cancellation final after Core crashes or reconnects.
- Prevented late results from cancelled remote tasks from reviving stale work.
- Hardened local secret storage and high-risk execution paths.

### Known limitations

- The Windows installer is not Authenticode-signed yet, so SmartScreen may display a warning.
- Rynne Nearby, voice interaction, and third-party GUI automation remain experimental.

## [1.0.0] - 2026-08-11

The first public Rynne release: a local-first Windows agent with a React,
TypeScript and Tauri desktop shell plus a Python agent core.

### Highlights

- Goal-oriented execution with visible understand, act, verify and recover stages.
- Windows, application, file, terminal, Git, browser and MCP tools.
- Skill-first execution for common multi-step actions.
- Groq, OpenRouter and Gemini provider pools with multiple keys and custom models.
- Voice input, wake word, configurable speech output and Russian/English UI.
- Memory, durable background tasks, automations and proactive Rynne Nearby mode.
- Telegram Business tools and Telegram Remote control.
- Dynamic subagent delegation when independent provider capacity is available.
- Three permission modes and explicit confirmation for protected actions.

### Known limitations

- The Windows installer is not code-signed yet, so SmartScreen may display a warning.
- Voice recognition quality depends on the microphone, acoustic environment and the
  configured local or API speech provider.
- GUI automation can be affected by application updates, custom layouts and focus.
- Rynne Nearby is experimental and intentionally conservative.

### Links

- Website: https://rynne-web.vercel.app/
- Repository: https://github.com/KremlevLev/Rynne
- Commercial licensing: `COMMERCIAL-LICENSE.md`
