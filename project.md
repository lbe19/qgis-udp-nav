# Project Transfer Notes (May 2026)

This file captures important technical lessons from the QGIS UDP Nav development cycle so they can be reused in a new related project.

## 1. Core Architecture Pattern

Use a clear pipeline with typed events and strict responsibility boundaries:

- Plugin shell: QGIS lifecycle, dock wiring, project transition hooks.
- Controller: orchestration, feed state, routing, status, telemetry, keep-center, persistence hooks.
- UDP worker: socket loop and datagram intake in a worker thread.
- Parser pipeline: sentence parsing and checksum policy handling.
- Layer manager: map rendering, track metrics, saved-track persistence.
- Dock UI: operator actions and live status display.

Why this worked:

- UI remained thin.
- Parsing and map rendering stayed testable without full QGIS runtime.
- Operational behavior was easier to tune without rewriting the full stack.

## 2. UDP Handling Patterns That Held Up

### 2.1 Worker-per-feed model

Run each feed in its own worker thread with:

- QUdpSocket bound per feed.
- explicit start and stop lifecycle.
- status signal path for operator feedback.

### 2.2 Binding behavior

Use share/reuse bind flags and fallback host handling:

- Accept configured host when valid.
- Fall back to AnyIPv4 or 0.0.0.0 when needed.

### 2.3 Datagram loop backpressure

Avoid starving the event loop:

- Process only a capped number of pending datagrams per cycle.
- If backlog remains, schedule next read via zero-delay timer.

This prevented stop/reload lag during bursty traffic.

### 2.4 Stale detection

Track last datagram timestamp per feed and emit warning when age exceeds stale timeout.

Key detail:

- stale timer runs periodically (for example every 1 second).
- warning should emit once per stale period, then reset when traffic resumes.

### 2.5 Source provenance

Attach source address to events and sentence logs. This was useful for multi-source debugging and operator trust.

## 3. Parser and Event Model

Typed events were a major win:

- PositionFixEvent
- HeadingEvent
- FeedStatusEvent
- ParseWarningEvent

Benefits:

- deterministic handling in controller
- reduced stringly-typed condition chains
- easier targeted tests

### 3.1 Sentence core behavior

- Normalize datagram newlines and split safely.
- Keep sentence identity talker-agnostic for standard NMEA where appropriate.
- Keep proprietary formatters intact (for example PSIMSSB and PSIMSNS).

### 3.2 Checksum policy model

Three policies worked well:

- lenient: accept and warn on mismatch
- strict: reject missing or mismatched checksum
- ignore: do not validate

This allowed practical field operation while still supporting strict validation workflows.

## 4. Kongsberg HiPAP Behavior and Signals

This section is the most important transferable behavior.

### 4.1 PSIMSSB semantics

Parse and preserve these fields in metadata:

- status
- error code
- coordinate system
- orientation
- x and y coordinate
- depth
- expected accuracy
- extra fields and transponder code

Validity rule used:

- position valid only when status is A and both coordinates are present

Status handling rules:

- status V: invalid position warning
- status A plus error code: warning but keep position if coordinates are present
- unknown status: warning
- status A with missing coordinates: explicit NO_COORD warning

Important practical rule:

- valid with warning code is not the same as invalid. Do not throw good coordinates away unnecessarily.

### 4.2 PSIMSSB error code meaning

Keep a lookup table for known codes (for example NRy, AmX, AmY, Rej, Pre, VRU, GYR).

Why:

- operators get human-readable explanations
- logs become useful for post-mission diagnosis

### 4.3 PSIMSNS semantics

PSIMSNS often carries sensor state and heading context.

Rules that worked:

- when pos_item exists: treat as normal sensor update
- when pos_item missing: treat as no-valid-position phase signal

Store telemetry metadata:

- roll
- pitch
- heave
- heading
- age
- transceiver and transducer tags

Noise control used in controller:

- info-level PSIMSNS statuses can be suppressed from UI spam while still using telemetry values (especially heading).

### 4.4 Routing rules for split vessel and vehicle

Auto routing behavior that proved useful:

- PSIMSSB and PSIMSNS to vehicle
- GLL with IN or CP talker to vehicle
- core standard NMEA navigation and heading sentences to vessel

Also support manual routing lists for sentence types.

### 4.5 Coordinate conversion model for PSIMSSB

Support coordinate systems:

- U (UTM)
- C (Cartesian offsets)
- P (Polar range and bearing)

Support orientation modes:

- N
- E
- H (head-up)

Requirements for successful conversion:

- UTM mode needs configured UTM EPSG.
- Local offset modes need reference lat and lon, or a recent vessel position.
- Head-up modes need heading (prefer live heading; fallback to configured reference heading).

Failure behavior:

- emit explicit status warnings and keep pipeline alive
- do not crash on bad/unsupported mode combinations

## 5. Position and Fallback Behavior

Vehicle fallback rule that helped field usability:

- if split mode is active and vehicle fix is stale or missing, optionally render vehicle at vessel position
- keep status explicit that fallback is active
- clear fallback state when vehicle positions return

Also useful:

- tolerate transient invalid vehicle telegrams by retaining recent valid vehicle position for a short window

## 6. Track Behavior and Metrics

### 6.1 Dimension semantics

Use operator-friendly terms:

- vessel track as x/y
- vehicle track as x/y/z

### 6.2 Length metrics

Maintain:

- raw polyline length
- smoothed polyline length

### 6.3 Toggle behavior

When a track toggle is turned off:

- auto-save track if it has enough points
- clear active track after successful save

Performance lesson:

- defer expensive saved-layer refresh (debounce) instead of doing it in the immediate toggle click path

## 7. UI Stability Lessons Under Live Feed

High-impact fixes from this cycle:

- Keep multi-select source menus open while toggling checkboxes.
- Do not rebuild combo options while popup is open.
- Stabilize card layout to avoid jumping during frequent updates.
- Batch table refresh updates (block signals, suppress repaints during rebuild).
- Prefer x/y and x/y/z labels over 2D and 3D for operators.

## 8. Testing Strategy That Paid Off

### 8.1 Deterministic unit tests

Cover:

- parser core
- NMEA parser
- Kongsberg parser
- checksum policy behavior
- settings persistence

### 8.2 Log replay tests

Use real mission-like logs and assert expected phase behavior:

- no-position phases
- valid-with-warning-code phases
- invalid bursts
- lifecycle transitions

This caught realistic edge cases that synthetic one-liners missed.

### 8.3 Long-run soak simulation

Add a synthetic UDP simulator and run accelerated multi-day and multi-week scenarios.

Goal:

- detect long-run stability issues
- detect state drift and UI churn over time

## 9. Persistence and IO Robustness

### 9.1 Saved track writing

For persistent GeoJSON writing:

- write to temp file first
- atomic replace
- if write fails due to layer lock, release/reload lock path and retry

### 9.2 Runtime logs

Write per-feed logs with UTC timestamps and category tags. This was critical for reconstructing behavior in field debugging.

## 10. Practical Handoff Checklist for New Related Project

1. Keep worker-thread UDP ingestion separate from UI.
2. Keep typed event model from parser to controller.
3. Preserve three checksum policies.
4. Implement PSIMSSB and PSIMSNS as first-class sentence families.
5. Implement robust coordinate-system conversion with explicit warnings.
6. Implement split routing with both auto and manual modes.
7. Add fallback behavior for missing vehicle position.
8. Debounce heavy map or disk operations from UI toggles.
9. Build replay tests from real logs early.
10. Add an accelerated soak sender before field deployment.

## 11. Known Product Positioning Notes

- This plugin was developed through prompt-driven iteration with agent-built code.
- Operationally useful behavior emerged by repeatedly testing against real mission patterns, not only synthetic samples.
- The best quality gains came from combining operator feedback, replay tests, and targeted performance hardening.
