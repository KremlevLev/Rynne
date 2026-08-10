# Repository routing

Use this file before every commit. Its purpose is to prevent proprietary service code from accidentally landing in the public desktop repository.

## `KremlevLev/rynne` — public

Commit code here when it is required to build and audit the local BYOK desktop product:

- React/Tauri desktop UI;
- local Rynne Core and tool execution;
- permission enforcement and audit records;
- public skills, MCP protocol adapters, and provider adapters;
- public client contracts for optional cloud services;
- installer, documentation, and deterministic tests.

Never commit provider master keys, production credentials, customer data, private evaluation data, billing logic, or production infrastructure here.

## `KremlevLev/rynne-cloud` — private, start here

Commit server-side commercial infrastructure here:

- account, organization, device, and session services;
- managed inference routing and provider capacity policy;
- quotas, usage metering, plans, billing, and entitlements;
- remote task transport and encrypted synchronization;
- server-side feature flags, abuse prevention, and support tooling.

This repository is proprietary. The public desktop client talks to it only through versioned contracts and must keep working in BYOK mode without it.

## `KremlevLev/rynne-web` — public website

Commit the marketing and download surface here:

- public product pages and interactive demos;
- GitHub Release download links;
- search, social preview, analytics, and future account entry points;
- Vercel deployment configuration.

The website must not contain provider keys, cloud business logic, customer data, or a second copy of the local execution runtime.

## Later private repositories

- `KremlevLev/rynne-premium-skills`: signed maintained integrations and commercial workflow packs.
- `KremlevLev/rynne-evals-private`: anonymized failures, adversarial scenarios, and routing benchmarks.
- `KremlevLev/rynne-ops`: deployment configuration, monitoring, migrations, backup, and incident procedures.

Do not create these repositories until they contain a real independent lifecycle. Until then their code belongs in `rynne-cloud` under clearly separated packages.

## Commit rule

Before committing, answer one question: can a user build and safely run the local BYOK agent without this code?

- If no, it belongs in public `rynne`.
- If yes, and the code implements managed infrastructure or a paid maintained integration, it belongs in a private repository.
- If it contains secrets or customer data, it belongs in neither Git repository.
