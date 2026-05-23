# Changelog

All notable changes to this project are documented in this file.

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
