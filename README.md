# QGIS UDP Nav

QGIS UDP Nav is ~~slopware~~ *an agentically developed* QGIS plugin for receiving multiple concurrent UDP navigation feeds and visualizing vessel and subsea vehicle positions in real time.

Developed using Github Copilot by a non-programmer - use at your own risk.

Currently the plugin supports standard NMEA 0183 and Kongsberg HiPAP sentences. The plugin only targets UDP data streams, as QGIS natively supports receiving GPS signals via serial, and you will most likely be using a UDP stream over a physical serial cable for HiPAP signals anyway.

The plugin includes split vessel/vehicle routing, keep-center map tracking, live telemetry cards (work in progress, might be annoying to use), track recording (x/y and x/y/z, with averaged-out smoothing for a more relevant track distance), and persistent saved-track export with operator metadata.

## Install (From GitHub)

This plugin is currently installed manually from this GitHub repository (not from the QGIS official plugin directory).

### Quick Install (Windows)

1. Clone this repository (or download and extract the ZIP).
2. Copy the `qgis_udp_nav_plugin` folder into your QGIS profile plugins directory.
3. Restart QGIS.
4. Open `Plugins > Manage and Install Plugins...` and enable `QGIS UDP Nav`.

PowerShell example:

```powershell
git clone https://github.com/lbert1858/qgis-udp-nav.git
cd qgis-udp-nav
$profile = 'C:\path\to\the\active\QGIS\profile'
$target = Join-Path $profile 'python\plugins\qgis_udp_nav_plugin'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $target
Copy-Item -Recurse -Force '.\qgis_udp_nav_plugin' $target
```

### Plugin Folder Location By OS

Use `Settings > User Profiles > Open Active Profile Folder` in QGIS, then append
`python/plugins/qgis_udp_nav_plugin`. The profile root is version- and profile-specific; for
example, Windows commonly uses `%APPDATA%\QGIS\QGIS3\profiles\<profile>` for QGIS 3 and
`%APPDATA%\QGIS\QGIS4\profiles\<profile>` for QGIS 4.

### Update To New Version

From your local clone:

```powershell
git pull
$profile = 'C:\path\to\the\active\QGIS\profile'
$target = Join-Path $profile 'python\plugins\qgis_udp_nav_plugin'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $target
Copy-Item -Recurse -Force '.\qgis_udp_nav_plugin' $target
```

Then restart QGIS.

### Uninstall

Delete the plugin folder from your QGIS profile plugins directory, then restart QGIS.

## Documentation Index

- Full plugin documentation (current state): docs/CURRENT_STATE.md
- Release notes: CHANGELOG.md
- License: LICENSE

## Version and Compatibility

- Plugin name: QGIS UDP Nav
- Plugin version: 0.2.0
- QGIS compatibility: 3.44 to 4.99
- Tested runtimes: QGIS 3.44.12 / Qt 5.15.13 and QGIS 4.2.0 / Qt 6.11.0
- Python requirement in project metadata: >= 3.10

## Feature Overview

### Core Feed Handling

- Multiple UDP feeds can run at the same time.
- Per-feed bind host, port, and checksum policy.
- Checksum policies:
  - lenient: accepts checksum mismatches with warning
  - strict: rejects missing/mismatched checksums
  - ignore: does not validate checksums

### Sentence Support

- Standard NMEA parsing:
  - GGA, GLL, RMC (position)
  - GSA (fix status)
  - HDT, HDM, HDG, THS, VHW (heading/speed related)
- Kongsberg parsing:
  - PSIMSSB (position/depth/status metadata)
  - PSIMSNS (sensor/heading/status metadata)

### Split Vessel and Vehicle Mode

- Each feed can run as:
  - single target
  - split vessel + vehicle
- Split routing modes:
  - auto routing
    - GGA/GLL/RMC and heading-related standard NMEA default to vessel
    - Kongsberg PSIMS* and HiPAP transponder GLL talkers (INGLL/CPGLL) route to vehicle
  - manual sentence-type routing
- Optional fallback can show vehicle on vessel position when vehicle position is missing/stale.

### Map Rendering

- Symbol modes:
  - vessel hull (scaled polygon)
  - vehicle rectangle (scaled polygon)
  - QGIS marker
  - Unicode symbol
  - SVG icon file
- Separate vessel and vehicle symbol/color settings in split mode.
- Zoomed-out overview arrows for vessel/vehicle visibility at large scales.

### Keep-Center Modes

- Keep Vessel Center
- Keep Vehicle Center
  - if recent vehicle fix is unavailable, center falls back to vessel position
- Keep Group Center
  - averages selected source positions
  - configurable source selection via Group Sources menu

### Telemetry and Operator UI

- Feed Sentence Inspector with live sentence stream.
- Optional `Log received sentences to disk` control, with a warning before enabling.
- No Scroll mode for field-wise sentence snapshot view (enabled by default on startup).
- Startup mode selector in dock: Off / First / All auto-start behavior.
- Group Sources selection menu stays open while toggling checkboxes.
- Optional Info Cards:
  - Heading
  - Speed
  - Depth
  - Track Raw length
  - Track Smooth length
- Track Live selector (split feeds):
  - Vessel (x/y)
  - Vehicle (x/y/z)
  - per-feed selection memory while navigating rows

### Track Collection and Metrics

- Direct dock toggles:
  - Track Vessel
  - Track Vehicle
- Track behavior:
  - vessel track length is 2D
  - vehicle track length is 3D using depth as Z
- Length estimates:
  - raw polyline length
  - smoothed length (moving-average based path smoothing)
- Turning a track toggle off pauses capture for that role and retains the collected track in memory.
- Tracks are saved only when Save Tracks is triggered.

### Persistent Saved Tracks

- Save Tracks button exports current active tracks into one persistent saved layer.
- For split feeds, vessel and vehicle are saved as separate features in the same layer.
- A successful save retains the accumulated in-memory route and marks that exact snapshot saved.
  New accepted points make the route unsaved again; each later save appends the current full route
  as another feature.
- On plugin unload/exit, unsaved in-memory tracks trigger a Save/Discard prompt. QGIS plugin
  unload cannot be reliably canceled, so a failed save offers retry or explicit discard.
- Prompted metadata on save:
  - planned number
  - actual number

Saved track attributes per feature include:

- saved_at_utc
- feed_id
- feed_name
- role
- track_layer_id
- track_dimension (2d or 3d)
- planned_number
- actual_number
- actual_raw_m
- actual_smoothed_m
- point_count

## Layer and Persistence Model

### Runtime Layers (Ephemeral)

The plugin creates runtime memory layers for live rendering:

- live position layers
- overview arrow layers
- active track layers

These runtime layers are marked as plugin-ephemeral so QGIS does not repeatedly prompt to save scratch layers on exit.

### Persistent Saved Tracks Layer

- Layer name: UDP Nav - Saved Tracks
- Backing file: GeoJSON
- Default location: `<active QGIS profile>/qgis_udp_nav_tracks/saved_tracks.geojson`

- Appends new features on each save operation.

### Other Persistent Data

- Feed and profile configuration is stored via QGIS settings.
- When sentence logging is enabled, per-feed/subfeed logs are stored under
  `<active QGIS profile>/qgis_udp_nav_logs`.

## Dock Workflow

Typical operator flow:

1. Add feed with host/port and target mode.
2. Feed starts automatically according to selected startup mode (or start manually if mode is Off).
3. Optional: configure symbol and color for vessel/vehicle roles.
4. Optional: enable keep-center mode.
5. Optional: enable Track Vessel and/or Track Vehicle.
6. Monitor Info Cards and Sentence Inspector.
7. Use Save Tracks to persist tracks with planned/actual metadata.

## Feed Configuration Fields

The feed dialog supports, among others:

- Name, Bind Host, UDP Port
- Checksum Policy
- Target Mode (single or split)
- Split Routing (auto/manual)
- Vehicle Fallback to Vessel
- Vessel Track toggle
- Vehicle Track toggle
- Manual vessel/vehicle sentence type lists
- Stale timeout
- HiPAP UTM EPSG
- Reference latitude/longitude/heading
- Feed enabled state

## Architecture Summary

Main components:

- plugin.py
  - plugin lifecycle and signal wiring
- controller/feed_controller.py
  - orchestration, routing, telemetry, status, keep-center, persistence hooks
- transport/udp_feed_worker.py
  - UDP receive loop and worker thread processing
- parser/pipeline.py
  - sentence parsing pipeline and checksum handling
- parser/nmea_standard.py
  - standard NMEA event parsing
- parser/kongsberg.py
  - Kongsberg PSIMSSB/PSIMSNS parsing
- map/layer_manager.py
  - live layers, overview layers, active tracks, saved track export
- ui/feed_dock.py
  - dock UI, operator actions, info cards, sentence inspector
- settings/store.py
  - QGIS settings persistence

## Development

### Repository Layout

- qgis_udp_nav_plugin/: plugin source
- tests/: pytest test suite
- specdocs/: reference docs and sentence notes

### Test and Validation

Current automated coverage includes parser core behavior, standard NMEA parsing, Kongsberg parsing,
pipeline checksum/routing behavior, settings storage, realistic log-replay workflows, and long-horizon
virtual soak scenarios.

Run tests:

```powershell
python -m pytest -q
```

Run only long-horizon simulation tests:

```powershell
python -m pytest -q tests/test_soak_simulation.py
```

Run compile sanity check:

```powershell
python -m compileall -q qgis_udp_nav_plugin
```

### Long-Run Practical Soak

If you want practical unattended runtime validation with QGIS open, run the UDP soak simulator
in another terminal to replay a synthetic mission cycle repeatedly (pre-deploy -> transponder on ->
tracking -> recovery -> delayed transponder-off behavior):

```powershell
python tools/udp_soak_simulator.py --host 127.0.0.1 --port 10110 --virtual-days 7 --speedup 120
```

Notes:

- Increase `--virtual-days` for week-scale replay (for example 14 or 28).
- `--speedup` controls how fast virtual time advances relative to wall-clock.
- Keep QGIS/plugin running while the simulator sends UDP traffic.

### Developer Redeploy To Local QGIS Profile (Windows)

Example copy-deploy command:

```powershell
$profile = 'C:\path\to\the\active\QGIS\profile'
$target = Join-Path $profile 'python\plugins\qgis_udp_nav_plugin'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $target
Copy-Item -Recurse -Force '.\qgis_udp_nav_plugin' $target
```

## Troubleshooting

- Track Vehicle button disabled:
  - select a feed row
  - enable split mode for that feed
- Save Tracks reports no active tracks:
  - ensure Track Vessel or Track Vehicle is enabled
  - wait for at least two position updates
- Vehicle keep-center behavior:
  - vehicle mode can fall back to vessel when vehicle fix is stale/unavailable
- No sentence output:
  - confirm a row is selected in the feed table
  - verify incoming UDP and correct port/bind

## Current Scope

This plugin is focused on live operational navigation display and recording workflows in QGIS, with practical operator controls for split vessel/vehicle tracking and metadata-tagged track archival.

## License

This project is licensed under the ISC License. See LICENSE.
