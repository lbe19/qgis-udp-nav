# QGIS UDP Nav: Current State (0.2.0)

This document describes the plugin behavior implemented in this repository at version 0.2.0.
It is intentionally implementation-focused and mirrors the current code paths.

## 1. Purpose and Scope

QGIS UDP Nav is a QGIS plugin for live UDP navigation feed ingestion and map rendering.
It targets vessel and vehicle operations where operators need:

- concurrent feed monitoring,
- split vessel/vehicle positioning,
- live telemetry visibility,
- active track collection,
- persistent saved-track export with operator metadata.

The plugin currently focuses on operational display and recording workflows, not post-processing analysis.

## 2. Runtime and Compatibility

- Plugin package folder: qgis_udp_nav_plugin/
- Entry point: qgis_udp_nav_plugin/__init__.py (classFactory)
- Main plugin class: qgis_udp_nav_plugin/plugin.py
- Metadata compatibility range: QGIS 3.44 to 4.99
- Tested runtimes: QGIS 3.44.12 / Qt 5.15.13 and QGIS 4.2.0 / Qt 6.11.0
- Project Python requirement: >= 3.10

The explicit 4.99 maximum is retained because omitting it for a plugin with a QGIS 3 minimum
would make the repository infer a 3.99 maximum. QGIS 3.44 is the tested QGIS 3 floor.

## 3. Installation and Local Deployment (GitHub Workflow)

The project is currently intended for GitHub-hosted development and manual deployment.

### 3.1 Clone

```powershell
git clone https://github.com/lbert1858/qgis-udp-nav.git
cd qgis-udp-nav
```

### 3.2 Deploy into local QGIS profile (Windows)

```powershell
$profile = 'C:\path\to\the\active\QGIS\profile'
$target = Join-Path $profile 'python\plugins\qgis_udp_nav_plugin'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $target
Copy-Item -Recurse -Force '.\qgis_udp_nav_plugin' $target
```

Use `Settings > User Profiles > Open Active Profile Folder` to find `$profile`. Append
`python/plugins` rather than assuming a QGIS version or the `default` profile.

### 3.3 Run in QGIS

- Open QGIS.
- Enable/reload plugin.
- Open dock via Plugins > QGIS UDP Nav.

## 4. Operator Dock: Behavior and Controls

The dock combines feed management, map-follow controls, telemetry cards, and sentence inspection.

### 4.1 Feed table

Columns:

- Feed
- Port
- Checksum
- Track
- Status
- Message
- Color
- Symbol

Split feeds render as one main row plus sub-rows:

- vessel sub-row
- vehicle sub-row

### 4.2 Action controls

- Add, Edit, Remove
- Symbol, Color
- Start, Stop
- Start All, Stop All
- Save Tracks
- Track Vessel (toggle)
- Track Vehicle (toggle, split feeds)
- Log received sentences to disk (toggle with a disk/performance warning)

### 4.3 Startup mode

Configurable in dock:

- Auto Start: Off
- Auto Start: First
- Auto Start: All

Default startup mode is first.

### 4.4 Keep center controls

- Keep Vessel Center
- Keep Vehicle Center
- Keep Group Center
- Group Sources selector

Group sources menu is persistent while checking/unchecking entries (menu does not close per click).

### 4.5 Info cards

Optional cards:

- Heading
- Speed
- Depth
- Track Raw
- Track Smooth

For split feeds, a Track Live selector controls which role drives track cards:

- Vessel (x/y)
- Vehicle (x/y/z)

Track role selection is remembered per base feed while navigating the table.

### 4.6 Sentence inspector

- Live sentence stream by selected feed
- Visible throttling markers when the display rate exceeds 50 sentences/second
- Stop/Start control for selected feed
- No Scroll mode (sentence-type snapshot view)
- Clear output

No Scroll is enabled by default when the dock is created.

## 5. Feed Configuration Reference

Feed configuration is represented by FeedConfig in qgis_udp_nav_plugin/model/feed_config.py.

### 5.1 Transport and lifecycle

- feed_id: required string identifier
- name: required display name
- bind_host: default 0.0.0.0
- port: default 10110
- enabled: default true
- checksum_policy: lenient | strict | ignore (default lenient)
- stale_timeout_sec: default 5

### 5.2 Main vessel visual profile

- symbol_mode: vessel | vehicle | qgis | icon_file | unicode
- icon_path
- color_hex
- qgis_symbol_name / qgis_symbol_width / qgis_symbol_height / qgis_size_unit
- unicode_symbol / unicode_font_family
- vessel_length_m / vessel_width_m
- vessel_gps_longitudinal_reference: bow | stern
- vessel_gps_offset_from_reference_m
- vessel_gps_offset_starboard_m

### 5.3 Split vessel/vehicle operation

- split_subfeeds_enabled: default false
- split_routing_mode: auto | manual (default auto)
- vehicle_show_on_vessel_when_missing_position: default false
- vessel_track_enabled: default false
- vehicle_track_enabled: default false
- manual_vessel_sentence_types: normalized list
- manual_vehicle_sentence_types: normalized list

### 5.4 Vehicle visual profile (split role)

- vehicle_symbol_mode
- vehicle_icon_path
- vehicle_color_hex
- vehicle_qgis_symbol_name / vehicle_qgis_symbol_width / vehicle_qgis_symbol_height
- vehicle_qgis_size_unit
- vehicle_unicode_symbol / vehicle_unicode_font_family
- vehicle_vessel_length_m / vehicle_vessel_width_m
- vehicle_vessel_gps_longitudinal_reference: bow | stern
- vehicle_vessel_gps_offset_from_reference_m
- vehicle_vessel_gps_offset_starboard_m

### 5.5 Position transformation references

- hipap_utm_epsg
- reference_lat
- reference_lon
- reference_heading_deg

These are used for PSIMSSB coordinate transformations when source data requires UTM or local reference conversion.

## 6. Sentence Parsing and Routing

### 6.1 Standard NMEA support

Handled through parser/pipeline.py and parser/nmea_standard.py:

- GGA
- GLL
- RMC
- GSA
- HDT
- HDM
- HDG
- THS
- VHW

### 6.2 Kongsberg support

Handled through parser/kongsberg.py:

- PSIMSSB
- PSIMSNS

### 6.3 Checksum policies

- lenient: parse sentence and emit warning on mismatch
- strict: reject sentence when checksum missing/mismatched
- ignore: do not validate checksum

### 6.4 Split routing rules

Auto routing behavior:

- PSIMSSB/PSIMSNS and PSIMS* patterns -> vehicle
- GLL with talker IN or CP -> vehicle
- Other supported standard navigation/heading sentences -> vessel

Manual routing mode:

- sentence types in manual_vessel_sentence_types -> vessel
- sentence types in manual_vehicle_sentence_types -> vehicle

If no manual match exists, fallback defaults to vessel.

## 7. Tracks and Dimensions

Track collection is managed by controller/feed_controller.py and map/layer_manager.py.

- Vessel tracks are computed as x/y length (2D)
- Vehicle tracks are computed as x/y/z length (3D) when depth is available
- Raw and smoothed length metrics are maintained

Behavior:

- Enabling a track toggle starts collecting points for that role.
- Disabling a track toggle pauses collection and retains that role track in memory.
- Save Tracks appends the current accumulated route as a new saved feature.
- A successful save marks only the exported revision as saved. A later accepted point makes the
  retained route unsaved again.
- Plugin unload/exit offers Save or Discard for unsaved routes. Save failures offer retry or
  explicit discard because QGIS plugin unload has no reliable cancel contract.

Main row track dimension reporting:

- x/y
- x/y/z
- x/y + x/y/z when both split-role tracks are active with points

## 8. Saved Tracks Layer

Save Tracks writes to a persistent GeoJSON-backed layer:

- Layer name: UDP Nav - Saved Tracks
- File: `<active QGIS profile>/qgis_udp_nav_tracks/saved_tracks.geojson`

Each saved feature contains:

- saved_at_utc
- feed_id
- feed_name
- role
- track_layer_id
- track_dimension
- track_color_hex
- saved_color_hex
- planned_number
- actual_number
- actual_raw_m
- actual_smoothed_m
- point_count

Geometry is LineString and may be 2D or 3D depending on track dimension.

## 9. Keep-Center and Fallback Semantics

### 9.1 Keep-center

- Vessel mode centers map on the selected base feed vessel position.
- Vehicle mode centers map on selected base feed vehicle position; if vehicle is stale, existing fallback behavior may provide a vessel-derived vehicle position when enabled.
- Group mode centers on average of selected sources.

### 9.2 Vehicle fallback

When enabled and split mode is active:

- if vehicle position is stale/missing,
- vehicle can be rendered at vessel position,
- fallback heading prefers vehicle heading state, then vessel heading state,
- fallback state is surfaced via status messaging.

## 10. Persistence and Logs

### 10.1 QGIS settings keys

Stored by SettingsStore under prefix qgis_udp_nav_plugin:

- qgis_udp_nav_plugin/feeds
- qgis_udp_nav_plugin/vessel_profiles
- qgis_udp_nav_plugin/startup_mode
- qgis_udp_nav_plugin/sentence_logging
- qgis_udp_nav_plugin/diagnostic_logging

### 10.2 Runtime logs

When `Log received sentences to disk` is enabled, per-feed/subfeed logs are appended under:

- `<active QGIS profile>/qgis_udp_nav_logs`

File naming pattern:

- YYYYMMDD_<feed-id>.log

## 11. Internal Architecture

Core modules:

- qgis_udp_nav_plugin/plugin.py
- qgis_udp_nav_plugin/controller/feed_controller.py
- qgis_udp_nav_plugin/transport/udp_feed_worker.py
- qgis_udp_nav_plugin/parser/core.py
- qgis_udp_nav_plugin/parser/pipeline.py
- qgis_udp_nav_plugin/parser/nmea_standard.py
- qgis_udp_nav_plugin/parser/kongsberg.py
- qgis_udp_nav_plugin/map/layer_manager.py
- qgis_udp_nav_plugin/ui/feed_dock.py
- qgis_udp_nav_plugin/settings/store.py

Design intent:

- UI emits operator intents.
- Controller orchestrates runtime state and routing.
- Parser pipeline emits typed events.
- Layer manager applies map rendering and track persistence.
- Settings store serializes stable config to QGIS settings.

## 12. Test Coverage (Current Repository)

Current automated suite includes:

- Feed config validation and migration tests
- Parser core unit tests
- Standard NMEA parser tests
- Kongsberg parser tests
- Pipeline checksum/routing tests
- SettingsStore persistence tests
- Real-log replay workflow tests
- Long-horizon soak simulation tests

Run all tests:

```powershell
python -m pytest -q
```

Compile sanity check:

```powershell
python -m compileall -q qgis_udp_nav_plugin
```

## 13. Long-Run Soak Simulation Tool

The repository includes tools/udp_soak_simulator.py for practical long-duration feed simulation.

Example:

```powershell
python tools/udp_soak_simulator.py --host 127.0.0.1 --port 10110 --virtual-days 7 --speedup 120
```

Useful options:

- --virtual-days for mission duration
- --speedup for virtual-time acceleration

## 14. Known Constraints and Notes

- Most logic is validated through deterministic tests outside full QGIS runtime.
- Full GUI behavior still depends on running inside QGIS desktop.
- Local test execution may require fallback behavior when qgis Python module is unavailable.
- PSIMSSB Cartesian/polar fallback offsets currently use the latest GNSS fix as their local
  origin. Changing that origin to hull center, transducer, or another vessel reference is
  intentionally deferred pending domain sign-off; absolute UTM PSIMSSB positions are unaffected.
