from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from types import SimpleNamespace

from qgis_udp_nav_plugin.controller import feed_controller as controller_module
from qgis_udp_nav_plugin.controller.feed_controller import FeedController
from qgis_udp_nav_plugin import diag as diag_module
from qgis_udp_nav_plugin.map.layer_manager import LayerManager
from qgis_udp_nav_plugin.plugin import QgisUdpNavPlugin
from qgis_udp_nav_plugin import plugin as plugin_module


def _track_manager(revision: int = 1) -> LayerManager:
    manager = LayerManager()
    manager._track_points["feed-1"] = deque(
        [(59.0, 10.0, 0.0), (59.0001, 10.0001, 0.0)]
    )
    manager._track_lengths["feed-1"] = (12.0, 11.5)
    manager._track_dimensions["feed-1"] = "2d"
    manager._track_revisions["feed-1"] = revision
    return manager


def test_track_revision_transitions_dirty_saved_dirty() -> None:
    manager = _track_manager()

    assert manager.unsaved_track_snapshot("feed-1")["revision"] == 1

    manager.mark_track_saved("feed-1", 1)
    assert manager.unsaved_track_snapshot("feed-1") is None

    manager._track_points["feed-1"].append((59.0002, 10.0002, 0.0))
    manager._track_revisions["feed-1"] = 2
    assert manager.unsaved_track_snapshot("feed-1")["revision"] == 2


def test_marking_exported_revision_does_not_mark_later_points_saved() -> None:
    manager = _track_manager(revision=4)
    exported = manager.unsaved_track_snapshot("feed-1")

    manager._track_points["feed-1"].append((59.0002, 10.0002, 0.0))
    manager._track_revisions["feed-1"] = 5

    controller = FeedController.__new__(FeedController)
    controller._layer_manager = manager
    controller._mark_track_entries_saved(
        [{"track_layer_id": "feed-1", "track": exported}]
    )

    assert manager._saved_track_revisions["feed-1"] == 4
    assert manager.unsaved_track_snapshot("feed-1")["revision"] == 5


def test_successful_controller_save_marks_only_exported_revision(
    monkeypatch,
) -> None:
    manager = _track_manager(revision=4)
    exported = manager.unsaved_track_snapshot("feed-1")
    entries = [{"track_layer_id": "feed-1", "track": exported}]
    manager._track_points["feed-1"].append((59.0002, 10.0002, 0.0))
    manager._track_revisions["feed-1"] = 5
    monkeypatch.setattr(
        manager,
        "save_tracks",
        lambda *_args, **_kwargs: (1, "saved_tracks.geojson"),
    )

    controller = FeedController.__new__(FeedController)
    controller._feeds = {"feed-1": object()}
    controller._layer_manager = manager
    monkeypatch.setattr(controller, "_collect_track_entries", lambda _ids: entries)
    monkeypatch.setattr(controller, "_on_worker_status", lambda *_args: None)

    controller.save_tracks("feed-1", "planned", "actual")

    assert manager._saved_track_revisions["feed-1"] == 4
    assert manager.unsaved_track_snapshot("feed-1")["revision"] == 5


def test_shutdown_prompt_saves_without_refreshing_project_layer(
    monkeypatch,
) -> None:
    class FakeMessageBox:
        def __init__(self, _parent=None) -> None:
            pass

        def setIcon(self, _icon) -> None:
            pass

        def setWindowTitle(self, _title: str) -> None:
            pass

        def setText(self, _text: str) -> None:
            pass

        def setInformativeText(self, _text: str) -> None:
            pass

        def setStandardButtons(self, _buttons) -> None:
            pass

        def setDefaultButton(self, _button) -> None:
            pass

    entries = [
        {
            "feed_id": "feed-1",
            "track_layer_id": "feed-1",
            "track": {"revision": 4},
        }
    ]
    save_calls = []
    saved_revisions = []

    def save_tracks(*args, **kwargs):
        save_calls.append((args, kwargs))
        return 1, "saved_tracks.geojson"

    controller = FeedController.__new__(FeedController)
    controller._shutting_down = False
    controller._layer_manager = SimpleNamespace(
        save_tracks=save_tracks,
        mark_track_saved=lambda feed_id, revision: saved_revisions.append(
            (feed_id, revision)
        ),
    )
    controller._collect_track_entries = lambda: entries
    controller._on_worker_status = lambda *_args: None

    monkeypatch.setattr(controller_module, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(
        controller_module,
        "_messagebox_button",
        lambda name: {"Save": 1, "Discard": 2}[name],
    )
    monkeypatch.setattr(controller_module, "_messagebox_icon", lambda _name: 3)
    monkeypatch.setattr(controller_module, "_messagebox_exec", lambda _dialog: 1)

    assert controller.prompt_save_tracks_before_shutdown() is True
    assert save_calls[0][1]["refresh_saved_layer"] is False
    assert saved_revisions == [("feed-1", 4)]


def test_messagebox_helpers_prefer_scoped_enums(monkeypatch) -> None:
    class ScopedMessageBox:
        class Icon:
            Warning = 11

        class StandardButton:
            Save = 22

    monkeypatch.setattr(controller_module, "QMessageBox", ScopedMessageBox)

    assert controller_module._messagebox_icon("Warning") == 11
    assert controller_module._messagebox_button("Save") == 22


def test_messagebox_helpers_fall_back_to_qt5_names(monkeypatch) -> None:
    class LegacyMessageBox:
        Warning = 11
        Save = 22

    monkeypatch.setattr(controller_module, "QMessageBox", LegacyMessageBox)

    assert controller_module._messagebox_icon("Warning") == 11
    assert controller_module._messagebox_button("Save") == 22


def test_messagebox_exec_supports_both_bindings() -> None:
    modern = SimpleNamespace(exec=lambda: 7)
    legacy = SimpleNamespace(exec_=lambda: 8)

    assert controller_module._messagebox_exec(modern) == 7
    assert controller_module._messagebox_exec(legacy) == 8


class _Signal:
    def __init__(self) -> None:
        self.handlers = []

    def connect(self, handler) -> None:
        self.handlers.append(handler)

    def disconnect(self, handler) -> None:
        self.handlers.remove(handler)


def test_project_lifecycle_uses_cross_version_signals(monkeypatch) -> None:
    project = SimpleNamespace(readProject=_Signal(), cleared=_Signal())
    iface = SimpleNamespace(projectRead=_Signal(), newProjectCreated=_Signal())
    monkeypatch.setattr(
        plugin_module,
        "QgsProject",
        SimpleNamespace(instance=lambda: project),
    )
    plugin = QgisUdpNavPlugin(iface)

    plugin._connect_project_lifecycle_signals()

    assert project.readProject.handlers == [plugin._on_project_transition_started]
    assert project.cleared.handlers == [plugin._on_project_transition_started]
    assert iface.projectRead.handlers == [plugin._on_project_transition_completed]
    assert iface.newProjectCreated.handlers == [
        plugin._on_project_transition_completed
    ]

    plugin._disconnect_project_lifecycle_signals()
    assert plugin._project_signal_connections == []


def test_project_transition_clears_cached_runtime_state() -> None:
    controller = FeedController.__new__(FeedController)
    cache_names = (
        "_latest_heading",
        "_reference_heading_by_layer",
        "_telemetry_by_layer",
        "_last_position_by_layer",
        "_last_vehicle_fix_by_feed",
        "_vehicle_fallback_active_by_feed",
    )
    for name in cache_names:
        setattr(controller, name, {"stale": object()})

    controller._clear_project_runtime_state()

    assert all(getattr(controller, name) == {} for name in cache_names)


def test_saved_track_refresh_can_skip_adding_missing_layer(
    tmp_path,
    monkeypatch,
) -> None:
    saved_path = tmp_path / "saved_tracks.geojson"
    saved_path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    manager = LayerManager()
    calls = []
    monkeypatch.setattr(manager, "_saved_tracks_path", lambda: str(saved_path))
    monkeypatch.setattr(
        manager,
        "_ensure_saved_tracks_layer",
        lambda file_path, add_if_missing=True: calls.append(
            (file_path, add_if_missing)
        ),
    )

    manager.refresh_saved_tracks_layer(add_if_missing=False)

    assert calls == [(str(saved_path), False)]


def test_sentence_stream_throttling_emits_visible_marker(monkeypatch) -> None:
    controller = FeedController.__new__(FeedController)
    controller_module.QObject.__init__(controller)
    controller._shutting_down = False
    controller._project_transition_active = False
    controller._sentence_diag_done = True
    controller._sentence_counter = 0
    controller._sentence_rate = 0
    controller._sentence_rate_window_start = 0.0
    controller._sentence_logging_enabled = False
    controller._feeds = {}
    timestamps = iter([0.5] * 59 + [1.1])
    monkeypatch.setattr(controller_module.time, "monotonic", lambda: next(timestamps))
    streamed = []
    controller.sentence_streamed.connect(
        lambda feed_id, line: streamed.append((feed_id, line))
    )

    for index in range(60):
        controller._on_worker_sentence("feed-1", "127.0.0.1", f"$TEST,{index}")

    markers = [line for _, line in streamed if "[throttled:" in line]
    assert len(markers) == 1
    assert "60 sentences/sec" in markers[0]
    assert "display limited to 50/sec" in markers[0]


def test_diagnostic_file_logging_defaults_to_disabled(tmp_path, monkeypatch) -> None:
    path = tmp_path / "udp_nav_diag.log"
    monkeypatch.setattr(diag_module, "DIAG_LOG_PATH", str(path))
    diag_module.set_diagnostic_logging_enabled(False)

    diag_module.diag("disabled")
    assert not path.exists()

    try:
        diag_module.set_diagnostic_logging_enabled(True)
        diag_module.diag("enabled")
        assert "enabled" in path.read_text(encoding="utf-8")
    finally:
        diag_module.set_diagnostic_logging_enabled(False)


def test_no_direct_unscoped_qmessagebox_enums() -> None:
    forbidden = re.compile(
        r"QMessageBox\.(Warning|Critical|Information|Question|"
        r"Ok|Cancel|Save|Discard|Yes|No|Close|Apply|Reset)\b"
    )
    plugin_root = Path(__file__).resolve().parents[1] / "qgis_udp_nav_plugin"
    offenders = []
    for path in plugin_root.rglob("*.py"):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if forbidden.search(line):
                offenders.append(f"{path.name}:{line_number}: {line.strip()}")

    assert not offenders, (
        "Unscoped Qt5 QMessageBox enums break under PyQt6:\n"
        + "\n".join(offenders)
    )
