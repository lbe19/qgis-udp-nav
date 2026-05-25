# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Fixed

- Plugin toolbar visibility resilience on long-running sessions:
  - added a bundled plugin icon,
  - set the QAction icon explicitly,
  - re-register toolbar/menu action when QGIS regains focus after OS lock/unlock.
- Live layer lifecycle hardening:
  - reuse existing plugin layers after cache resets,
  - tag plugin layers with stable feed/role identity,
  - remove duplicate stale ephemeral layers during cleanup.

### Changed

- Track workflow is now scratch-first:
  - toggling a track off pauses capture but keeps collected points in memory,
  - tracks persist only when the operator explicitly runs Save Tracks.
- Plugin unload now prompts when unsaved tracks exist, with Save, Discard, and Cancel options.

### Performance

- Incremental track length calculation: O(1) per new point instead of full O(n) recalculation.
- Throttled track geometry rebuild: QGIS polyline updated every 5th point instead of every fix.
- Efficient live position updates: in-place geometry/attribute change instead of delete-and-recreate.
- In-place feed table cell updates: avoids full table rebuild and flicker at 5 Hz refresh.
- Eliminated redundant datagram split in parser pipeline.
- SVG symbol cache auto-prune removes stale entries older than 7 days on startup.

### Added

- Diagnostic logging is now opt-in (default off) via `diagnostic_logging` setting.
  No log files are written unless explicitly enabled.
- Log file rotation: files older than 30 days are pruned on startup when logging is enabled.
- `stale_timeout_sec` validation (must be >= 1 second).
- Bind address fallback warning when an invalid address silently falls back to 0.0.0.0.
- `SentencePipeline.parse_lines()` method accepts pre-split lines for efficient reuse.

## 0.2.0 - 2026-05-23

### Added

- Comprehensive current-state documentation in docs/CURRENT_STATE.md.
- Long-horizon soak simulation tooling and related tests.
- Expanded parser and settings test coverage, including replay workflow tests.

### Changed

- Operator UI behavior hardening for live operation:
  - persistent Group Sources selection menu,
  - split-feed Track Live selector with per-feed role memory,
  - x/y and x/y/z track dimension labels,
  - reduced table/card UI churn under live updates.
- Track toggle workflow performance improvements with deferred saved-layer refresh.
- Saved track persistence path and write behavior tuned for reliability.

### License

- Project license set to ISC.
