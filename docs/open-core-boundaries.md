# Rynne open-core and private-service boundaries

This document defines which parts of Rynne should remain in the public desktop repository and which parts can become separate private services. The goal is to keep the public edition useful and verifiable while protecting the infrastructure that makes a managed Rynne subscription convenient, reliable, and difficult to clone.

## Product rule

The public edition must remain a complete local-first Windows agent. It must not become a non-functional demo whose essential safety or execution logic exists only in the cloud.

The commercial product should sell managed infrastructure and convenience:

- no provider API-key setup;
- reliable model routing and capacity;
- remote access and device coordination;
- encrypted synchronization and recovery;
- curated premium integrations;
- managed updates, support, and organization controls.

## Public repository: `rynne`

The public repository should contain:

- React, TypeScript, and Tauri desktop UI;
- Rynne Core request pipeline and local orchestrator;
- local permission enforcement and confirmation modes;
- Windows, browser, file, Git, terminal, voice, and application tools;
- BYOK providers for Groq, OpenRouter, Gemini, and Tavily;
- public MCP protocol support and community integrations;
- local Vosk, Whisper adapters, Silero TTS, and voice settings;
- skill format, SDK, examples, and a useful community skill catalog;
- local memory, task ledger, recovery, and audit trail;
- installer and update client;
- deterministic tests, acceptance harness, and public security tests;
- public cloud API schemas and a replaceable `CloudGateway` interface.

Security decisions must stay local. A response received from any model or Rynne Cloud must still pass through the local tool registry, permission manager, argument validation, and execution ledger.

## Private repository: `rynne-cloud`

The managed backend should be a separate private repository. It can contain:

- user accounts, organizations, sessions, and device enrollment;
- billing, subscriptions, entitlements, quotas, and usage metering;
- encrypted provider credentials and server-side model access;
- model routing, failover, load balancing, budgets, and capacity policy;
- short-lived desktop access tokens and device revocation;
- remote task broker for Telegram, web, and future mobile clients;
- encrypted settings and automation synchronization;
- update channels, staged rollout policy, and premium entitlements;
- abuse prevention, operational telemetry, alerts, and support tooling;
- server-side feature flags and experiment configuration.

The desktop application must never contain Rynne Cloud master provider keys. It should receive only short-lived, scoped credentials or send model requests through an authenticated gateway.

## Optional private repository: `rynne-premium-skills`

High-maintenance or commercially valuable integrations can be distributed as signed skill bundles:

- enterprise mail, calendar, CRM, and document connectors;
- managed Telegram remote-control workflows;
- organization-specific automations;
- maintained application adapters with compatibility guarantees;
- premium templates and verified workflow packs.

The public skill SDK and signature verification must remain public. Only the premium implementations and distribution service need to be private.

## Optional private repository: `rynne-evals-private`

The test runner and basic scenarios should remain public. A private evaluation repository may contain:

- anonymized production failures;
- adversarial prompts and abuse cases;
- unreleased application compatibility scenarios;
- model-routing benchmarks and provider quality history;
- regression cases that reveal planned commercial features.

This data can become an important product advantage without hiding the public verification framework.

## Optional private repository: `rynne-ops`

Deployment and operational material should normally remain private:

- production infrastructure as code;
- secret layout and key rotation procedures;
- monitoring rules and incident runbooks;
- database migrations and backup operations;
- anti-abuse thresholds and provider capacity configuration.

## Trust and privacy boundary

Rynne Cloud should receive the minimum information required for the selected feature.

- Local execution remains the default.
- Raw screenshots, microphone audio, file contents, and message history are not retained by default.
- Cloud processing is explicit in the UI.
- Sensitive payloads use transport encryption and short retention periods.
- Users can continue with BYOK when Rynne Cloud is unavailable or disabled.
- Remote commands are authenticated, recorded locally, and subject to the selected local permission mode.
- The cloud cannot silently bypass local confirmation or execute Windows tools directly.

## Stable public interfaces

Keep the boundary replaceable and documented:

```text
Rynne Desktop
  -> CloudGateway interface
      -> managed inference
      -> account and entitlement API
      -> remote task stream
      -> encrypted sync API

Rynne Desktop
  -> local ToolRegistry
      -> PermissionManager
      -> local execution
      -> verification and audit ledger
```

The public client should define versioned request and event schemas. Rynne Cloud implements those schemas, but the proprietary routing, billing, and operational logic stays server-side.

## Suggested extraction order

1. Introduce a public `CloudGateway` interface without changing BYOK behavior.
2. Move account, billing, quotas, and managed provider access into `rynne-cloud`.
3. Add device enrollment and short-lived scoped tokens.
4. Add an encrypted remote task stream for Telegram and web clients.
5. Introduce signed premium skill manifests and entitlement checks.
6. Add opt-in synchronization only after local export, deletion, and recovery are reliable.
7. Keep a complete offline/BYOK acceptance suite to prevent accidental cloud lock-in.

## Licensing boundary

- Covered public Rynne versions use `FSL-1.1-ALv2` and receive Apache 2.0 after two years.
- Earlier Apache 2.0 releases retain their original license.
- Private services are not automatically distributed with the public desktop repository.
- Third-party components remain under their own licenses and notices.
- Commercial permissions for competing products, hosting, OEM distribution, or white-label use are described in [`../COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

Before accepting substantial external contributions, Rynne should adopt a contributor agreement or another explicit mechanism that preserves the ability to offer alternative commercial terms.

