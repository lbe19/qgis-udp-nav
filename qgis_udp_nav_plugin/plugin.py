from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication
from qgis.core import Qgis, QgsMessageLog, QgsProject

from .controller import FeedController
from .diag import (
    DIAG_LOG_PATH,
    diag,
    diagnostic_logging_enabled,
    set_diagnostic_logging_enabled,
)
from .settings import SettingsStore
from .ui import FeedDockWidget


def _right_dock_area():
    dock_area_enum = getattr(Qt, "DockWidgetArea", None)
    if dock_area_enum is not None and hasattr(dock_area_enum, "RightDockWidgetArea"):
        return dock_area_enum.RightDockWidgetArea
    return Qt.RightDockWidgetArea


def _plugin_icon_path() -> str:
    return str(Path(__file__).resolve().parent / "icons" / "udp_nav.svg")


class QgisUdpNavPlugin:
    def __init__(self, iface) -> None:
        self.iface = iface
        self._action: Optional[QAction] = None
        self._dock: Optional[FeedDockWidget] = None
        self._controller: Optional[FeedController] = None
        self._project_signal_connections: List[Tuple[object, object]] = []
        self._ui_signal_connections: List[Tuple[object, object]] = []
        self._pending_initial_autostart = False
        self._initial_project_transition_pending = False
        self._project_transition_watchdog_token = 0

    def initGui(self) -> None:
        set_diagnostic_logging_enabled(
            diagnostic_logging_enabled()
            or SettingsStore().load_diagnostic_logging()
        )
        if diagnostic_logging_enabled():
            try:
                with open(DIAG_LOG_PATH, "w", encoding="utf-8") as f:
                    f.write(
                        "=== UDP Nav Plugin Startup "
                        f"{datetime.now(timezone.utc).isoformat()} ===\n"
                    )
            except OSError:
                pass
        diag("initGui called")

        self._action = QAction(QIcon(_plugin_icon_path()), "QGIS UDP Nav", self.iface.mainWindow())
        self._action.setObjectName("qgis_udp_nav_action")
        self._action.setToolTip("Open QGIS UDP Nav")
        self._action.triggered.connect(self.show_dock)

        self.iface.addPluginToMenu("&QGIS UDP Nav", self._action)
        self.iface.addToolBarIcon(self._action)
        self._connect_ui_lifecycle_signals()

        self._ensure_initialized()

    def unload(self) -> None:
        if self._controller is not None:
            try:
                self._controller.prompt_save_tracks_before_shutdown(self.iface.mainWindow())
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"[UDP Nav] Save-tracks prompt failed: {exc!r}\n{traceback.format_exc()}",
                    "UDP Nav",
                    Qgis.MessageLevel.Critical,
                )

        self._disconnect_ui_lifecycle_signals()
        self._disconnect_project_lifecycle_signals()
        self._pending_initial_autostart = False
        self._initial_project_transition_pending = False
        self._project_transition_watchdog_token = 0

        if self._controller is not None:
            self._controller.shutdown()
            self._controller = None

        if self._dock is not None:
            self.iface.removeDockWidget(self._dock)
            self._dock.deleteLater()
            self._dock = None

        if self._action is not None:
            self.iface.removePluginMenu("&QGIS UDP Nav", self._action)
            self.iface.removeToolBarIcon(self._action)
            self._action.deleteLater()
            self._action = None

    def show_dock(self) -> None:
        self._ensure_initialized()
        if self._dock is None:
            return

        self._dock.show()
        self._dock.raise_()

    def _ensure_initialized(self) -> None:
        if self._controller is None:
            diag("Creating FeedController")
            self._controller = FeedController(self.iface)
            diag(f"Controller created. Feeds: {len(self._controller.feeds())}")
            self._connect_project_lifecycle_signals()
            self._begin_initial_project_transition_guard()

        if self._dock is not None:
            return

        self._dock = FeedDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(_right_dock_area(), self._dock)

        self._dock.feed_added.connect(self._controller.add_feed)
        self._dock.feed_updated.connect(self._controller.update_feed)
        self._dock.feed_removed.connect(self._controller.remove_feed)
        self._dock.feed_start_requested.connect(self._controller.start_feed)
        self._dock.feed_stop_requested.connect(self._controller.stop_feed)
        self._dock.save_tracks_requested.connect(self._controller.save_tracks)
        self._dock.track_toggle_requested.connect(self._controller.set_track_enabled)
        self._dock.keep_center_requested.connect(self._controller.set_keep_center_target)
        self._dock.start_all_requested.connect(self._controller.start_all)
        self._dock.stop_all_requested.connect(self._controller.stop_all)
        self._dock.startup_mode_changed.connect(self._controller.set_startup_mode)
        self._dock.sentence_logging_changed.connect(self._on_sentence_logging_changed)
        self._dock.color_changed.connect(self._controller.set_feed_color)
        self._dock.symbol_changed.connect(self._controller.set_feed_symbol)
        self._dock.vessel_profiles_updated.connect(self._controller.set_vessel_profiles)

        self._controller.snapshot_changed.connect(self._dock.set_rows)
        self._controller.status_changed.connect(self._dock.update_status)
        self._controller.sentence_streamed.connect(self._dock.append_sentence)
        self._controller.vessel_profiles_changed.connect(self._dock.set_vessel_profiles)

        self._dock.set_rows(self._controller.snapshot_rows())
        self._dock.set_vessel_profiles(self._controller.vessel_profiles())
        self._dock.set_startup_mode(self._controller.startup_mode())
        self._dock.set_sentence_logging_enabled(
            self._controller.sentence_logging_enabled()
        )
        self._pending_initial_autostart = True
        QTimer.singleShot(250, self._auto_start_initial_feed)

        self._dock.hide()

    def _auto_start_initial_feed(self) -> None:
        if self._controller is None or not self._pending_initial_autostart:
            diag("_auto_start_initial_feed: controller=None or no pending autostart")
            return

        if self._controller.project_transition_active():
            diag("_auto_start_initial_feed: project_transition_active, retrying in 500ms")
            QTimer.singleShot(500, self._auto_start_initial_feed)
            return

        if not self._qgis_ui_ready_for_autostart():
            diag("_auto_start_initial_feed: UI not ready, retrying in 500ms")
            QTimer.singleShot(500, self._auto_start_initial_feed)
            return

        startup_mode = str(self._controller.startup_mode() or "first").strip().lower()
        diag(f"_auto_start_initial_feed: mode={startup_mode}, feeds={len(self._controller.feeds())}")
        QgsMessageLog.logMessage(
            f"[UDP Nav] Autostart: mode={startup_mode}, feeds={len(self._controller.feeds())}",
            "UDP Nav",
            Qgis.MessageLevel.Info,
        )
        if startup_mode == "off":
            self._pending_initial_autostart = False
            return
        if startup_mode == "all":
            self._controller.start_all()
            self._pending_initial_autostart = False
            return

        feeds = self._controller.feeds()
        if not feeds:
            self._pending_initial_autostart = False
            return

        selected_feed = next((feed for feed in feeds if bool(getattr(feed, "enabled", True))), None)
        if selected_feed is None:
            selected_feed = feeds[0]

        self._controller.start_feed(selected_feed.feed_id)
        self._pending_initial_autostart = False

    def _connect_ui_lifecycle_signals(self) -> None:
        if self._ui_signal_connections:
            return

        app = QApplication.instance()
        if app is None:
            return

        self._connect_ui_signal(app, "applicationStateChanged", self._on_application_state_changed)

    def _disconnect_ui_lifecycle_signals(self) -> None:
        for signal, handler in self._ui_signal_connections:
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                pass

        self._ui_signal_connections = []

    def _connect_ui_signal(self, source, signal_name: str, handler) -> None:
        signal = getattr(source, signal_name, None)
        connect = getattr(signal, "connect", None)
        if not callable(connect):
            return

        try:
            connect(handler)
        except TypeError:
            return

        self._ui_signal_connections.append((signal, handler))

    def _on_application_state_changed(self, state) -> None:
        active_state = getattr(Qt, "ApplicationActive", None)
        if active_state is None:
            app_state_enum = getattr(Qt, "ApplicationState", None)
            active_state = getattr(app_state_enum, "ApplicationActive", None)

        if active_state is not None and state != active_state:
            return

        # Some Windows lock/unlock transitions are asynchronous in Qt; restore twice.
        self._schedule_action_restore(0)
        self._schedule_action_restore(900)

    def _schedule_action_restore(self, delay_ms: int) -> None:
        QTimer.singleShot(max(0, int(delay_ms)), self._restore_plugin_action)

    def _restore_plugin_action(self) -> None:
        action = self._action
        if action is None:
            return

        if action.icon().isNull():
            action.setIcon(QIcon(_plugin_icon_path()))

    def _connect_project_lifecycle_signals(self) -> None:
        if self._project_signal_connections:
            return

        project = QgsProject.instance()
        self._connect_project_signal(project, "readProject", self._on_project_transition_started)
        self._connect_project_signal(project, "cleared", self._on_project_transition_started)
        self._connect_project_signal(self.iface, "projectRead", self._on_project_transition_completed)
        self._connect_project_signal(
            self.iface,
            "newProjectCreated",
            self._on_project_transition_completed,
        )

    def _disconnect_project_lifecycle_signals(self) -> None:
        for signal, handler in self._project_signal_connections:
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                pass

        self._project_signal_connections = []

    def _connect_project_signal(self, project, signal_name: str, handler) -> bool:
        signal = getattr(project, signal_name, None)
        connect = getattr(signal, "connect", None)
        if not callable(connect):
            return False

        try:
            connect(handler)
        except TypeError:
            return False

        self._project_signal_connections.append((signal, handler))
        return True

    def _begin_initial_project_transition_guard(self) -> None:
        if self._controller is None:
            return
        if self._initial_project_transition_pending:
            return

        self._initial_project_transition_pending = True
        self._controller.project_transition_started()
        QTimer.singleShot(2500, self._finish_initial_project_transition_guard)

    def _finish_initial_project_transition_guard(self) -> None:
        if not self._initial_project_transition_pending:
            return

        self._initial_project_transition_pending = False
        if self._controller is None:
            return

        self._controller.project_transition_completed()

    def _on_project_transition_started(self, *_args) -> None:
        if self._controller is None:
            return
        # Ignore project signals during initial startup guard
        if self._initial_project_transition_pending:
            return

        self._controller.project_transition_started()
        self._project_transition_watchdog_token += 1
        token = int(self._project_transition_watchdog_token)
        QTimer.singleShot(6000, lambda token_value=token: self._project_transition_watchdog(token_value))

    def _on_project_transition_completed(self, *_args) -> None:
        self._project_transition_watchdog_token += 1
        self._initial_project_transition_pending = False
        if self._controller is None:
            return

        QTimer.singleShot(0, self._controller.project_transition_completed)
        if self._pending_initial_autostart:
            QTimer.singleShot(0, self._auto_start_initial_feed)

    def _project_transition_watchdog(self, token_value: int) -> None:
        if token_value != self._project_transition_watchdog_token:
            return
        if self._controller is None:
            return
        if not self._controller.project_transition_active():
            return

        self._controller.project_transition_completed()
        if self._pending_initial_autostart:
            QTimer.singleShot(0, self._auto_start_initial_feed)

    def _qgis_ui_ready_for_autostart(self) -> bool:
        main_window = self.iface.mainWindow()
        if main_window is None or not main_window.isVisible():
            return False

        map_canvas_getter = getattr(self.iface, "mapCanvas", None)
        if callable(map_canvas_getter):
            canvas = map_canvas_getter()
            if canvas is None:
                return False

        return True

    def _on_sentence_logging_changed(self, enabled: bool) -> None:
        if self._controller is None or self._dock is None:
            return

        self._controller.set_sentence_logging_enabled(
            bool(enabled),
            self.iface.mainWindow(),
        )
        self._dock.set_sentence_logging_enabled(
            self._controller.sentence_logging_enabled()
        )
