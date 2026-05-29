"""
QGIS Python Console Diagnostic Script for UDP Nav Plugin.

Paste this into QGIS Python Console (Plugins → Python Console)
to test the plugin's rendering pipeline without needing UDP data.

It simulates a position event and checks if layers appear correctly.
"""
from datetime import datetime, timezone


def run_diagnostic():
    import sys
    from qgis.core import QgsProject, QgsMessageLog, Qgis

    print("=" * 60)
    print("UDP Nav Plugin Diagnostic")
    print("=" * 60)

    # 1. Check if plugin is loaded
    try:
        from qgis_udp_nav_plugin.plugin import QgisUdpNavPlugin
        print("[OK] Plugin module importable")
    except ImportError as e:
        print(f"[FAIL] Cannot import plugin: {e}")
        return

    # 2. Check if plugin is active in QGIS
    from qgis.utils import plugins
    plugin = plugins.get("qgis_udp_nav_plugin")
    if plugin is None:
        print("[FAIL] Plugin is NOT loaded in QGIS. Enable it in Plugin Manager.")
        return
    print(f"[OK] Plugin loaded: {type(plugin).__name__}")

    # 3. Check controller
    controller = getattr(plugin, "_controller", None)
    if controller is None:
        print("[FAIL] Controller not initialized")
        return
    print(f"[OK] Controller active")

    # 4. Check feeds
    feeds = controller.feeds()
    print(f"[INFO] Feeds configured: {len(feeds)}")
    for f in feeds:
        print(f"       - {f.name} | {f.bind_host}:{f.port} | mode={f.symbol_mode}")

    # 5. Check workers (running feeds)
    workers = getattr(controller, "_workers", {})
    print(f"[INFO] Running workers: {len(workers)}")
    for fid in workers:
        feed = controller._feeds.get(fid)
        name = feed.name if feed else fid
        print(f"       - {name} (running)")

    # 6. Check project transition state
    transition = controller.project_transition_active()
    shutting_down = getattr(controller, "_shutting_down", False)
    print(f"[INFO] Project transition active: {transition}")
    print(f"[INFO] Shutting down: {shutting_down}")
    if transition:
        print("[WARNING] Project transition is ACTIVE - events are being dropped!")

    # 7. Check startup mode
    mode = controller.startup_mode()
    print(f"[INFO] Startup mode: {mode}")

    # 8. Check status
    status = getattr(controller, "_status_by_feed", {})
    for sid, s in status.items():
        print(f"[STATUS] {sid}: [{s.get('level')}] {s.get('message')}")

    # 9. Simulate a position event
    print("\n--- Simulating position event ---")
    if not feeds:
        print("[SKIP] No feeds configured, cannot simulate")
        return

    feed = feeds[0]
    from qgis_udp_nav_plugin.model.events import PositionFixEvent

    event = PositionFixEvent(
        feed_id=feed.feed_id,
        sentence_type="GGA",
        talker="GP",
        latitude=59.9139,
        longitude=10.7522,
        valid=True,
        status_text="GPS fix",
        fix_time_utc="12:00:00",
        received_at=datetime.now(timezone.utc),
        metadata={},
    )

    try:
        controller._handle_position_event(event)
        print("[OK] Position event handled without error")
    except Exception as e:
        print(f"[FAIL] Error handling position event: {e}")
        import traceback
        traceback.print_exc()
        return

    # 10. Check if layer was created
    layers = QgsProject.instance().mapLayers()
    nav_layers = [l for l in layers.values() if "UDP Nav" in l.name()]
    print(f"[INFO] UDP Nav layers in project: {len(nav_layers)}")
    for layer in nav_layers:
        print(f"       - {layer.name()} | features={layer.featureCount()} | valid={layer.isValid()}")

    if nav_layers:
        print("\n[OK] Plugin is working! Layers are created.")
        print("     If you don't see anything on the map, check:")
        print("     1. Is the layer visible in the Layers panel?")
        print("     2. Is the map zoomed to the right area? (try right-click → Zoom to Layer)")
        print("     3. Is a UDP data source sending to the configured port?")
    else:
        print("\n[FAIL] No layers created - something is wrong in the layer creation path.")

    print("=" * 60)


run_diagnostic()
