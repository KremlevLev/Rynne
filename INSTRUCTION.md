# UI Architecture & Orchestrator Documentation for Rynne

## Overview

Rynne — a local Windows AI agent with a PySide6 desktop UI. The UI runs in a **separate process** spawned by `multiprocessing` (spawn context) and communicates with the backend via **two multiprocessing queues** (`event_queue` for backend→UI, `command_queue` for UI→backend).

## Architecture: Process Model & Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  MAIN PROCESS (main.py)                                          │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ DesktopService │──│ CoreDesktopBridge │──│ AgentService   │       │
│  │ (spawn child)  │    │ (publishes     │    │ (LLM, tools,   │       │
│  │                │    │  events)       │    │  planning)     │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │ event_queue (backend→UI)                                │
│         │ command_queue (UI→backend)                              │
│         ▼                                                        │
│  ┌──────────────────────────────────────┐                       │
│  │  UI PROCESS (premium_desktop.py)      │                       │
│  │  QApplication + AppShell + event loop │                       │
│  └──────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Role |
|------|------|
| `main.py` | Entry point. Creates `DesktopService`, `CoreDesktopBridge`, `AgentService`, etc. |
| `modules/ui/desktop_service.py` | Spawns UI process via `multiprocessing.spawn`. Creates `event_queue` and `command_queue`. |
| `modules/ui/desktop_protocol.py` | Event/command protocol: `make_event()`, `make_command()`, `validate_command()`, `make_serializable()`. |
| `modules/ui/core_bridge.py` | Backend→UI bridge. `CoreDesktopBridge.run()` polls every 500ms, calls `publish_snapshots()` which publishes events to `event_queue`. |
| `modules/ui/premium_desktop.py` | **NEW UI entry point**. Creates `AppShell`, `ChatView`, `Composer`, `TaskView`, `CommandPalette`, `VoiceOverlay`. Runs `QTimer` (50ms) to poll `event_queue` and dispatch to `_handle_event()`. |
| `modules/ui/desktop.py` | **OLD UI** (fallback). Simple tabbed interface. |
| `modules/ui/shell.py` | `AppShell` (QMainWindow), `Sidebar`, `SidebarItem`, `ContextPanel`. |
| `modules/ui/chat.py` | `ChatMessage`, `ChatView`, `Composer`, `ToolActivityCard`, `ErrorCard`, `ArtifactCard`. |
| `modules/ui/orb.py` | `RynneOrb` (animated orb), `VoiceOverlay`. |
| `modules/ui/task_view.py` | `TaskView`, `PlanView`, `PlanStep`, `TimelineView`, `TimelineEvent`. |
| `modules/ui/command_palette.py` | `CommandPalette`, `Command`. |
| `modules/ui/primitives.py` | `Button`, `IconButton`, `Input`, `Card`, `Badge`, `StatusIndicator`, `AnimationLayer`, etc. |
| `modules/ui/theme.py` | Design tokens: `Theme` class, `DARK_COLORS`, `RADIUS`, `SPACING`, `DURATIONS`, etc. |

## Event Flow: Backend → UI

1. **`CoreDesktopBridge.run()`** (in `core_bridge.py`) runs an async loop every 500ms.
2. **`publish_snapshots()`** collects data and publishes events to `event_queue`:
   - `runtime` — state (SLEEPING, LISTENING, THINKING, WORKING, SPEAKING, ERROR), active flag
   - `processes` — list of background processes
   - `memories` — list of memory entries
   - `permissions` — pending permission requests
   - `models` — provider health data (from `RynneLLM.provider_health()`)
   - `preferences` — user preferences
   - `user_message` — user's message text
   - `assistant_message` — Rynne's response (display_text, success, etc.)
   - `tool_started` — tool name, description
   - `tool_completed` — tool result, duration
   - `task_started` — task title, task_id, plan steps
   - `task_progress` — plan step statuses, description
   - `task_completed` — task completion
   - `task_failed` — error message
   - `approval_requested` — description, details
   - `command_result` — UI command results
   - `shutdown` — shutdown signal

3. **`_run_event_loop()`** in `premium_desktop.py` has a `QTimer` (50ms) that polls `event_queue` and dispatches each event to `_handle_event()`.

## Event Flow: UI → Backend

1. UI calls `_send_command(command_queue, action, payload)` which creates a command via `make_command()`.
2. `CoreDesktopBridge.run()` reads commands from `command_queue` and dispatches via `handle_command()`.
3. Supported commands: `submit_user_request`, `cancel_current_request`, `set_input_mode`, `stop_process`, `delete_memory`, `clear_memories`, `confirm_permission`, `deny_permission`, `refresh`, `pause_task`, `cancel_task`, `approve_task`, `toggle_voice_mode`, `new_task`, `open_settings`, `switch_model`, `open_mcp_manager`, `open_diagnostics`.

## Problems Found & Fixed

### 1. QTimer without parent (CRITICAL)
**File**: `modules/ui/premium_desktop.py`, `_run_event_loop()`
**Problem**: `QTimer()` was created without a parent. In PySide6, QTimer objects without parents can be garbage collected, stopping the event loop that polls for backend events.
**Fix**: Changed to `QTimer(app)` — parented to the QApplication.

### 2. Composer not added to any layout (CRITICAL)
**File**: `modules/ui/premium_desktop.py`, `run_premium_desktop()`
**Problem**: `Composer` (the input field) was created but never added to any layout. The user could not type or send messages — "nothing is clickable."
**Fix**: Added `shell._center_layout.addWidget(composer)` and `shell._center_layout.setStretchFactor(shell.workspace, 1)` to place the composer at the bottom of the workspace.

### 3. CommandPalette not added to any layout (CRITICAL)
**File**: `modules/ui/premium_desktop.py`, `run_premium_desktop()`
**Problem**: `CommandPalette` was created but never parented or added to the shell. Ctrl+K shortcut could not show it.
**Fix**: Added `palette.setParent(shell)` and `palette.hide()`.

### 4. VoiceOverlay not added to any layout (CRITICAL)
**File**: `modules/ui/premium_desktop.py`, `run_premium_desktop()`
**Problem**: `VoiceOverlay` was created but never parented. Voice status was invisible.
**Fix**: Added `voice_overlay.setParent(shell)` and `voice_overlay.hide()`.

### 5. Missing event types in `_handle_event` (CRITICAL)
**File**: `modules/ui/premium_desktop.py`, `_handle_event()`
**Problem**: `processes`, `memories`, `permissions`, `command_result` events were not handled. The UI never received process lists, memory data, or permission requests.
**Fix**: Added handlers for all missing event types. `permissions` now shows an approval card via `task_view.show_approval()`.

### 6. RynneOrb animation property (BUG)
**File**: `modules/ui/orb.py`, `RynneOrb`
**Problem**: `QPropertyAnimation(self, b"_pulse_phase")` tried to animate a non-existent Qt property. PySide6 requires `@Property` decorator for animatable properties.
**Fix**: Added `@Property(float)` decorator for `pulse_phase` getter/setter, changed animation target to `b"pulse_phase"`, and called `self._state_anim.start()`.

### 7. VoiceOverlay stop button cursor (BUG)
**File**: `modules/ui/orb.py`, `VoiceOverlay._setup_ui()`
**Problem**: Used `cursor: pointer` in QSS, which is invalid in Qt. Qt uses cursor names like `pointing-hand`.
**Fix**: Replaced with `self._stop_btn.setCursor(Qt.PointingHandCursor)` and removed the invalid QSS property.

### 8. Sidebar collapse animation (BUG)
**File**: `modules/ui/shell.py`, `Sidebar._toggle_collapsed()`
**Problem**: `QPropertyAnimation` was created but never given start/end values. The animation did nothing.
**Fix**: Added `setStartValue()` and `setEndValue()` with proper target widths (60 collapsed, 280 expanded). Also added `maximumWidth` animation for correct resizing.

### 9. Sidebar navigation (BUG)
**File**: `modules/ui/shell.py`, `AppShell._on_sidebar_navigate()`
**Problem**: Sidebar had 7 items but workspace only had 2 screens (chat, task). Clicking items 2-6 did nothing.
**Fix**: Navigation now shows `context_panel` for non-chat/task items, with proper title setting.

### 10. ContextPanel never shown (BUG)
**File**: `modules/ui/shell.py`, `AppShell._on_sidebar_navigate()`
**Problem**: `ContextPanel` was hidden by default and no code ever called `show_panel()`.
**Fix**: Navigation now calls `self.context_panel.show_panel()` for non-primary sidebar items.

### 11. Models event handling (BUG)
**File**: `modules/ui/premium_desktop.py`, `_handle_event()`
**Problem**: Expected `active_provider` and `active_model` keys, but `RynneLLM.provider_health()` returns a different structure.
**Fix**: Added fallback logic to extract provider/model from nested `providers` dict.

## Design Tokens (theme.py)

```
Dark theme:
  bg.base:       #0b0d12  (matte black)
  bg.elevated:   #000000  (sidebar)
  bg.surface:    #11141c  (cards)
  text.primary:  #f5f7fb
  text.secondary:#a7b0c0
  accent.primary: #8b7cff  (electric violet)
  accent.secondary: #4cc9f0 (cyan)
  success: #4ade80, danger: #fb7185, warning: #fbbf24

Fonts: JetBrains Mono / Courier New (monospace only per .clinerules)
Radius: sm=8px, md=12px, lg=16px, xl=22px, pill=999px
Durations: micro=140ms, hover=160ms, panel=240ms, orbLoop=5000ms
```

## Testing

- `tests/test_ui_smoke.py` — import tests for all UI modules
- `tests/test_ui_state_mapping.py` — state-to-UI mapping tests (runtime, messages, tasks, approvals, models)
- All 41 tests pass.

## How to Run

```powershell
python -m main
```

Desktop UI starts automatically (controlled by `NOVA_DESKTOP_UI` env var). Premium UI is enabled by default (`NOVA_PREMIUM_UI=true`).

## Key Constraints (from .clinerules)

- PySide6/QSS only — no web properties (box-shadow, backdrop-filter, complex gradients)
- `border-radius: 0px` — all sharp 90-degree angles
- Separators: `border: 1px solid #2a2a2a`
- Monospace fonts only (JetBrains Mono, Courier New)
- Shadows forbidden in QSS (use `QGraphicsDropShadowEffect` if needed)
