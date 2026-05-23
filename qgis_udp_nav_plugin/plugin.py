from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from .controller import FeedController
from .ui import FeedDockWidget


def _right_dock_area():
    dock_area_enum = getattr(Qt, "DockWidgetArea", None)
    if dock_area_enum is not None and hasattr(dock_area_enum, "RightDockWidgetArea"):
        return dock_area_enum.RightDockWidgetArea
    return Qt.RightDockWidgetArea


class QgisUdpNavPlugin:
    def __init__(self, iface) -> None:
        self.iface = iface
        self._action: Optional[QAction] = None
        self._dock: Optional[FeedDockWidget] = None
        self._controller: Optional[FeedController] = None

    def initGui(self) -> None:
        self._action = QAction("QGIS UDP Nav", self.iface.mainWindow())
        self._action.triggered.connect(self.show_dock)

        self.iface.addPluginToMenu("&QGIS UDP Nav", self._action)
        self.iface.addToolBarIcon(self._action)

        self._ensure_initialized()

    def unload(self) -> None:
        if self._controller is not None:
            self._controller.shutdown()

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
            self._controller = FeedController(self.iface)

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
        self._dock.color_changed.connect(self._controller.set_feed_color)
        self._dock.symbol_changed.connect(self._controller.set_feed_symbol)
        self._dock.vessel_profiles_updated.connect(self._controller.set_vessel_profiles)

        self._controller.snapshot_changed.connect(self._dock.set_rows)
        self._controller.status_changed.connect(self._dock.update_status)
        self._controller.sentence_streamed.connect(self._dock.append_sentence)
        self._controller.vessel_profiles_changed.connect(self._dock.set_vessel_profiles)

        self._dock.set_rows(self._controller.snapshot_rows())
        self._dock.set_vessel_profiles(self._controller.vessel_profiles())

        self._dock.hide()
