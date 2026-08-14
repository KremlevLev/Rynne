# Rynne 1.0.1

This maintenance release makes Rynne Remote reliable enough for early public testing.

## Fixed in 1.0.1

- the installed desktop reliably discovers and starts its bundled Core even when the Core build version differs from the shell version;
- the packaged Core no longer exits during startup because a security-disabled tool handler has no published schema;
- packaged Telegram integrations now start through the bundled Core executable instead of looking for development source files;
- FastMCP runtime data is bundled and validated so Telegram tools cannot silently disappear only after installation;
- Rynne Remote starts the installed production desktop application instead of the slow Vite/Cargo development runtime;
- the installer includes a lightweight always-on Remote Bridge and registers it in Windows startup;
- Mini App Russian labels use valid UTF-8 again;
- cancelling a remote task is final even if Core crashed or disconnected;
- late results from an old Core process cannot revive a cancelled task;
- local secrets are encrypted with Windows DPAPI and high-risk execution paths were hardened.

Rynne is a local AI agent for Windows that goes beyond chat. Give it a goal in plain language: it selects tools, performs the work, verifies the outcome, and shows every step in the desktop interface.

## What's included

- Windows, application, file, terminal, Git, and browser automation;
- voice input, wake word detection, Russian and English UI, and configurable TTS;
- Groq, OpenRouter, Gemini, OpenAI, and Anthropic support with multiple keys and custom models;
- reusable skills, memory, background tasks, automations, MCP integrations, and recovery paths;
- Telegram integrations and remote control through a Telegram bot and Mini App;
- three permission modes with approval gates for protected actions;
- experimental proactive assistance through Rynne Nearby;
- parallel subagents when multiple independent API keys are available;
- detailed live execution logs and result verification.

## Installation

1. Download `Rynne_1.0.1_x64-setup.exe` from the assets below.
2. Run the installer.
3. Add a model provider key in Rynne Settings, or use an available managed trial route.
4. Give Rynne a task in plain language or enable voice control.

The installer is not Authenticode-signed yet, so Windows SmartScreen may display a warning. Verify the accompanying SHA-256 checksum if needed.

## Try these commands

- "Open Obsidian, create a note with a poem about space, and verify that it was saved."
- "Open OpenRouter Activity in the browser and take a screenshot."
- "Find the error in this project, fix it, and run the tests."
- "Send this message to a Telegram contact after resolving the correct recipient."

## Important notes

Rynne 1.0.1 is an early public release. Voice interaction, third-party application automation, and proactive assistance still need broader real-world testing. Please report reproducible failures and include the redacted support bundle whenever possible.

- [Website](https://rynne-web.vercel.app/)
- [English documentation](https://github.com/KremlevLev/Rynne#readme)
- [Russian documentation](https://github.com/KremlevLev/Rynne/blob/main/README.ru.md)
- [Full changelog](https://github.com/KremlevLev/Rynne/blob/main/CHANGELOG.md)
