from __future__ import annotations

from datetime import datetime, timezone
import math
import os
import shutil
import time
import uuid
from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)

from ..map.layer_manager import LayerManager
from ..model.events import FeedStatusEvent, HeadingEvent, ParseWarningEvent, PositionFixEvent
from ..model.feed_config import FeedConfig
from ..parser.pipeline import SentencePipeline
from ..settings.store import SettingsStore
from ..transport.udp_feed_worker import UdpFeedWorker

_AUTO_VESSEL_SENTENCE_TYPES = {
    "GGA",
    "GLL",
    "RMC",
    "GSA",
    "HDT",
    "HDM",
    "HDG",
    "THS",
    "VHW",
}
_AUTO_VEHICLE_SENTENCE_TYPES = {"PSIMSSB", "PSIMSNS"}
_AUTO_VEHICLE_GLL_TALKERS = {"IN", "CP"}
_SUBFEED_ROLES = {"vessel", "vehicle"}
_KEEP_CENTER_MODES = {"vessel", "vehicle", "group"}
_GROUP_DEFAULT_MAX_AGE_SEC = 15
_LIVE_SNAPSHOT_MIN_INTERVAL_SEC = 0.2
_AUTO_SAVE_LAYER_REFRESH_DEBOUNCE_MS = 300


def _queued_connection_type():
    connection_enum = getattr(Qt, "ConnectionType", None)
    if connection_enum is not None and hasattr(connection_enum, "QueuedConnection"):
        return connection_enum.QueuedConnection
    return Qt.QueuedConnection


class FeedController(QObject):
    snapshot_changed = pyqtSignal(list)
    status_changed = pyqtSignal(str, str, str)
    sentence_streamed = pyqtSignal(str, str)
    vessel_profiles_changed = pyqtSignal(dict)

    def __init__(self, iface) -> None:
        super().__init__()
        self._iface = iface
        self._settings = SettingsStore()
        self._pipeline = SentencePipeline()
        self._layer_manager = LayerManager()

        self._feeds: Dict[str, FeedConfig] = {
            feed.feed_id: feed for feed in self._settings.load_feeds()
        }
        self._vessel_profiles: Dict[str, dict] = self._settings.load_vessel_profiles()
        self._status_by_feed: Dict[str, Dict[str, str]] = {}
        self._latest_heading: Dict[str, Dict[str, object]] = {}
        self._telemetry_by_layer: Dict[str, Dict[str, object]] = {}
        self._last_position_by_layer: Dict[str, Tuple[float, float, datetime]] = {}
        self._last_vehicle_fix_by_feed: Dict[str, datetime] = {}
        self._vehicle_fallback_active_by_feed: Dict[str, bool] = {}
        self._workers: Dict[str, UdpFeedWorker] = {}
        self._threads: Dict[str, QThread] = {}
        self._shutting_down = False
        self._project_transition_active = False
        self._project_transition_resume_feed_ids: List[str] = []
        self._last_live_snapshot_monotonic = 0.0
        self._keep_center_enabled = False
        self._keep_center_feed_id = ""
        self._keep_center_role = "vessel"
        self._keep_center_source_ids: List[str] = []
        self._saved_tracks_refresh_timer = QTimer(self)
        self._saved_tracks_refresh_timer.setSingleShot(True)
        self._saved_tracks_refresh_timer.setInterval(_AUTO_SAVE_LAYER_REFRESH_DEBOUNCE_MS)
        self._saved_tracks_refresh_timer.timeout.connect(self._refresh_saved_tracks_layer)
        self._log_dir = self._initialize_log_dir()
        self._startup_mode = self._settings.load_startup_mode()

        for feed in self._feeds.values():
            self._sync_status_slots(feed)

        self._emit_snapshot()
        self._emit_profiles()

    def feeds(self) -> List[FeedConfig]:
        return sorted(self._feeds.values(), key=lambda f: f.name.lower())

    def vessel_profiles(self) -> Dict[str, dict]:
        return {name: dict(profile) for name, profile in self._vessel_profiles.items()}

    def startup_mode(self) -> str:
        return str(self._startup_mode)

    def set_startup_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in {"off", "first", "all"}:
            normalized = "first"

        if normalized == self._startup_mode:
            return

        self._startup_mode = normalized
        self._settings.save_startup_mode(normalized)

    def project_transition_active(self) -> bool:
        return bool(self._project_transition_active)

    def project_transition_started(self) -> None:
        if self._shutting_down:
            return

        if self._project_transition_active:
            self._layer_manager.reset_project_layer_caches()
            self._last_position_by_layer.clear()
            return

        self._project_transition_active = True
        self._project_transition_resume_feed_ids = list(self._workers.keys())
        self._layer_manager.reset_project_layer_caches()
        self._last_position_by_layer.clear()

        if self._project_transition_resume_feed_ids:
            self.stop_all(force=True)

    def project_transition_completed(self) -> None:
        if self._shutting_down:
            return
        if not self._project_transition_active:
            return

        self._project_transition_active = False
        self._layer_manager.reset_project_layer_caches()
        self._last_position_by_layer.clear()

        resume_ids = [
            feed_id
            for feed_id in self._project_transition_resume_feed_ids
            if feed_id in self._feeds and bool(self._feeds[feed_id].enabled)
        ]
        self._project_transition_resume_feed_ids = []

        for feed_id in resume_ids:
            self.start_feed(feed_id)

        self._emit_snapshot()

    def set_vessel_profiles(self, profiles: dict) -> None:
        safe_profiles: Dict[str, dict] = {}
        if isinstance(profiles, dict):
            for name, profile in profiles.items():
                profile_name = str(name).strip()
                if not profile_name or not isinstance(profile, dict):
                    continue
                safe_profiles[profile_name] = dict(profile)

        self._vessel_profiles = safe_profiles
        self._settings.save_vessel_profiles(self._vessel_profiles)
        self._emit_profiles()

    def add_feed(self, payload: dict) -> None:
        feed_id = f"feed-{uuid.uuid4().hex[:8]}"
        merged = {
            "feed_id": feed_id,
            "name": payload.get("name") or feed_id,
            "bind_host": payload.get("bind_host", "0.0.0.0"),
            "port": payload.get("port", 10110),
            "checksum_policy": payload.get("checksum_policy", "lenient"),
            "color_hex": payload.get("color_hex", "#ff4500"),
            "icon_path": payload.get("icon_path", ""),
            "symbol_mode": payload.get("symbol_mode", "vessel"),
            "vessel_length_m": payload.get("vessel_length_m", 20.0),
            "vessel_width_m": payload.get("vessel_width_m", 6.0),
            "vessel_gps_longitudinal_reference": payload.get(
                "vessel_gps_longitudinal_reference",
                "bow",
            ),
            "vessel_gps_offset_from_reference_m": payload.get(
                "vessel_gps_offset_from_reference_m",
                0.0,
            ),
            "vessel_gps_offset_starboard_m": payload.get(
                "vessel_gps_offset_starboard_m",
                0.0,
            ),
            "split_subfeeds_enabled": payload.get("split_subfeeds_enabled", False),
            "split_routing_mode": payload.get("split_routing_mode", "auto"),
            "vehicle_show_on_vessel_when_missing_position": payload.get(
                "vehicle_show_on_vessel_when_missing_position",
                False,
            ),
            "vessel_track_enabled": payload.get("vessel_track_enabled", False),
            "vehicle_track_enabled": payload.get("vehicle_track_enabled", False),
            "manual_vessel_sentence_types": payload.get("manual_vessel_sentence_types", []),
            "manual_vehicle_sentence_types": payload.get("manual_vehicle_sentence_types", []),
            "vehicle_icon_path": payload.get("vehicle_icon_path", ""),
            "vehicle_symbol_mode": payload.get("vehicle_symbol_mode", "qgis"),
            "vehicle_vessel_length_m": payload.get("vehicle_vessel_length_m", 4.0),
            "vehicle_vessel_width_m": payload.get("vehicle_vessel_width_m", 2.0),
            "vehicle_vessel_gps_longitudinal_reference": payload.get(
                "vehicle_vessel_gps_longitudinal_reference",
                "bow",
            ),
            "vehicle_vessel_gps_offset_from_reference_m": payload.get(
                "vehicle_vessel_gps_offset_from_reference_m",
                0.0,
            ),
            "vehicle_vessel_gps_offset_starboard_m": payload.get(
                "vehicle_vessel_gps_offset_starboard_m",
                0.0,
            ),
            "vehicle_qgis_symbol_name": payload.get("vehicle_qgis_symbol_name", "diamond"),
            "vehicle_qgis_symbol_width": payload.get("vehicle_qgis_symbol_width", 7.0),
            "vehicle_qgis_symbol_height": payload.get("vehicle_qgis_symbol_height", 7.0),
            "vehicle_qgis_size_unit": payload.get("vehicle_qgis_size_unit", "screen"),
            "vehicle_unicode_symbol": payload.get("vehicle_unicode_symbol", "\u26f5"),
            "vehicle_unicode_font_family": payload.get(
                "vehicle_unicode_font_family",
                "Noto Sans Symbols 2",
            ),
            "vehicle_color_hex": payload.get(
                "vehicle_color_hex",
                payload.get("color_hex", "#ff4500"),
            ),
            "qgis_symbol_name": payload.get("qgis_symbol_name", "circle"),
            "qgis_symbol_width": payload.get("qgis_symbol_width", 7.0),
            "qgis_symbol_height": payload.get("qgis_symbol_height", 7.0),
            "qgis_size_unit": payload.get("qgis_size_unit", "screen"),
            "unicode_symbol": payload.get("unicode_symbol", "\u2693"),
            "unicode_font_family": payload.get(
                "unicode_font_family",
                "Noto Sans Symbols 2",
            ),
            "hipap_utm_epsg": payload.get("hipap_utm_epsg"),
            "reference_lat": payload.get("reference_lat"),
            "reference_lon": payload.get("reference_lon"),
            "reference_heading_deg": payload.get("reference_heading_deg"),
            "stale_timeout_sec": payload.get("stale_timeout_sec", 5),
            "enabled": bool(payload.get("enabled", True)),
        }
        feed = FeedConfig.from_dict(merged)

        self._feeds[feed.feed_id] = feed
        self._sync_status_slots(feed)
        self._persist()
        self._emit_snapshot()

    def update_feed(self, feed_id: str, payload: dict) -> None:
        current = self._feeds.get(feed_id)
        if current is None:
            return

        was_running = feed_id in self._workers
        if was_running:
            self.stop_feed(feed_id)

        self._clear_render_state(feed_id)

        merged = current.to_dict()
        merged.update(payload)
        merged["feed_id"] = feed_id
        merged["name"] = payload.get("name", current.name)

        feed = FeedConfig.from_dict(merged)
        self._feeds[feed_id] = feed
        self._sync_status_slots(feed)
        self._persist()
        self._emit_snapshot()

        if was_running:
            self.start_feed(feed_id)

    def remove_feed(self, feed_id: str) -> None:
        if feed_id not in self._feeds:
            return

        self.stop_feed(feed_id)
        self._feeds.pop(feed_id, None)
        self._remove_status_slots(feed_id)
        self._clear_render_state(feed_id)
        if self._keep_center_role == "group":
            prefix = f"{feed_id}:"
            self._keep_center_source_ids = [
                source_id
                for source_id in self._keep_center_source_ids
                if source_id != feed_id and not source_id.startswith(prefix)
            ]
            if not self._keep_center_source_ids:
                self._keep_center_enabled = False
                self._keep_center_feed_id = ""
                self._keep_center_role = "vessel"
        elif self._keep_center_feed_id == feed_id:
            self._keep_center_enabled = False
            self._keep_center_feed_id = ""
            self._keep_center_role = "vessel"

        self._persist()
        self._emit_snapshot()

    def set_feed_color(self, feed_id: str, role: str, color_hex: str) -> None:
        feed = self._feeds.get(feed_id)
        if feed is None:
            return

        selected_role = str(role or "vessel").strip().lower()
        if selected_role not in _SUBFEED_ROLES:
            selected_role = "vessel"

        if selected_role == "vehicle":
            previous_color = feed.vehicle_color_hex
            feed.vehicle_color_hex = color_hex
        else:
            previous_color = feed.color_hex
            feed.color_hex = color_hex

        try:
            feed.validate()
        except ValueError:
            if selected_role == "vehicle":
                feed.vehicle_color_hex = previous_color
            else:
                feed.color_hex = previous_color
            self._on_worker_status(feed_id, "error", f"Invalid color value: {color_hex}")
            return

        if selected_role == "vehicle":
            if feed.split_subfeeds_enabled:
                self._layer_manager.update_style(self._render_feed(feed, "vehicle"))
        else:
            self._layer_manager.update_style(self._render_feed(feed, "vessel"))

        self._persist()
        self._emit_snapshot()

    def set_feed_icon(self, feed_id: str, icon_path: str) -> None:
        self.set_feed_symbol(
            feed_id,
            {
                "symbol_mode": "icon_file",
                "icon_path": icon_path,
                "symbol_target_role": "vessel",
            },
        )

    def set_feed_symbol(self, feed_id: str, payload: dict) -> None:
        feed = self._feeds.get(feed_id)
        if feed is None:
            return

        previous = feed.to_dict()
        role = str(payload.get("symbol_target_role", "vessel")).strip().lower()
        if role not in _SUBFEED_ROLES:
            role = "vessel"

        try:
            self._apply_symbol_payload(feed, payload, role)
            feed.validate()
        except (TypeError, ValueError) as exc:
            restored = FeedConfig.from_dict(previous)
            self._feeds[feed_id] = restored
            self._on_worker_status(feed_id, "error", str(exc))
            return

        self._layer_manager.update_style(self._render_feed(feed, role))
        self._persist()
        self._emit_snapshot()

    def start_all(self) -> None:
        for feed in self.feeds():
            if feed.enabled:
                self.start_feed(feed.feed_id)

    def stop_all(self, force: bool = False) -> None:
        for feed_id in list(self._workers.keys()):
            self.stop_feed(feed_id, force=force)

    def save_tracks(self, feed_id: str, planned_number: str, actual_number: str) -> None:
        base_feed_id = str(feed_id or "").strip()
        if not base_feed_id:
            return

        feed = self._feeds.get(base_feed_id)
        if feed is None:
            return

        entries: List[dict] = []
        if feed.split_subfeeds_enabled:
            for role in ("vessel", "vehicle"):
                layer_id = self._subfeed_layer_id(base_feed_id, role)
                track = self._layer_manager.track_snapshot(layer_id)
                if track is None:
                    continue

                entries.append(
                    {
                        "feed_id": base_feed_id,
                        "feed_name": feed.name,
                        "role": role,
                        "track_layer_id": layer_id,
                        "track_color_hex": self._track_color_for_role(feed, role),
                        "track": track,
                    }
                )
        else:
            track = self._layer_manager.track_snapshot(base_feed_id)
            if track is not None:
                entries.append(
                    {
                        "feed_id": base_feed_id,
                        "feed_name": feed.name,
                        "role": "vessel",
                        "track_layer_id": base_feed_id,
                        "track_color_hex": self._track_color_for_role(feed, "vessel"),
                        "track": track,
                    }
                )

        if not entries:
            self._on_worker_status(base_feed_id, "warning", "No active tracks available to save")
            return

        saved_count, file_path = self._layer_manager.save_tracks(
            entries,
            planned_number=str(planned_number or "").strip(),
            actual_number=str(actual_number or "").strip(),
        )
        if saved_count <= 0:
            self._on_worker_status(base_feed_id, "error", "Failed to save tracks")
            return

        output_name = os.path.basename(file_path) if file_path else "saved_tracks.geojson"
        self._on_worker_status(
            base_feed_id,
            "info",
            f"Saved {saved_count} track(s) to UDP Nav - Saved Tracks ({output_name})",
        )

    def set_track_enabled(self, feed_id: str, role: str, enabled: bool) -> None:
        base_feed_id = str(feed_id or "").strip()
        if not base_feed_id:
            return

        feed = self._feeds.get(base_feed_id)
        if feed is None:
            return

        selected_role = str(role or "vessel").strip().lower()
        if selected_role not in _SUBFEED_ROLES:
            selected_role = "vessel"

        requested_enabled = bool(enabled)
        if selected_role == "vehicle":
            if not feed.split_subfeeds_enabled:
                self._on_worker_status(
                    base_feed_id,
                    "warning",
                    "Vehicle track requires split mode",
                )
                self._emit_snapshot()
                return

            current_enabled = bool(feed.vehicle_track_enabled)
            track_layer_id = self._subfeed_layer_id(base_feed_id, "vehicle")
        else:
            current_enabled = bool(feed.vessel_track_enabled)
            if feed.split_subfeeds_enabled:
                track_layer_id = self._subfeed_layer_id(base_feed_id, "vessel")
            else:
                track_layer_id = base_feed_id

        changed = False

        if not requested_enabled:
            auto_saved_output = ""
            track_snapshot = self._layer_manager.track_snapshot(track_layer_id)
            if track_snapshot is not None:
                saved_count, file_path = self._layer_manager.save_tracks(
                    [
                        {
                            "feed_id": base_feed_id,
                            "feed_name": feed.name,
                            "role": selected_role,
                            "track_layer_id": track_layer_id,
                            "track_color_hex": self._track_color_for_role(feed, selected_role),
                            "track": track_snapshot,
                        }
                    ],
                    planned_number="",
                    actual_number="",
                    refresh_saved_layer=False,
                )
                if saved_count <= 0:
                    self._on_worker_status(
                        base_feed_id,
                        "error",
                        f"Failed to auto-save {selected_role} track; track remains active",
                    )
                    self._emit_snapshot()
                    return

                auto_saved_output = (
                    os.path.basename(file_path) if file_path else "saved_tracks.geojson"
                )
                self._schedule_saved_tracks_refresh()

            self._layer_manager.clear_track(track_layer_id)

            if current_enabled:
                if selected_role == "vehicle":
                    feed.vehicle_track_enabled = False
                else:
                    feed.vessel_track_enabled = False
                changed = True

            if changed:
                self._persist()

            if auto_saved_output:
                message = (
                    f"{selected_role.capitalize()} track disabled "
                    f"(auto-saved to {auto_saved_output})"
                )
            else:
                message = f"{selected_role.capitalize()} track disabled"

            self._on_worker_status(base_feed_id, "info", message)
            self._emit_snapshot()
            return

        if not current_enabled:
            if selected_role == "vehicle":
                feed.vehicle_track_enabled = True
            else:
                feed.vessel_track_enabled = True
            changed = True

        if changed:
            self._persist()

        self._on_worker_status(
            base_feed_id,
            "info",
            f"{selected_role.capitalize()} track enabled",
        )
        self._emit_snapshot()

    def _schedule_saved_tracks_refresh(self) -> None:
        if self._saved_tracks_refresh_timer.isActive():
            self._saved_tracks_refresh_timer.stop()
        self._saved_tracks_refresh_timer.start()

    def _refresh_saved_tracks_layer(self) -> None:
        self._layer_manager.refresh_saved_tracks_layer()

    def start_feed(self, feed_id: str) -> None:
        if self._shutting_down or self._project_transition_active:
            return

        if feed_id in self._workers:
            return

        feed = self._feeds.get(feed_id)
        if feed is None:
            return

        thread = QThread(self)
        worker = UdpFeedWorker(feed, self._pipeline)
        worker.moveToThread(thread)

        thread.started.connect(worker.start)
        connection_type = _queued_connection_type()
        worker.event_received.connect(self._on_worker_event, connection_type)
        worker.sentence_received.connect(self._on_worker_sentence, connection_type)
        worker.status.connect(self._on_worker_status, connection_type)
        worker.stopped.connect(self._on_worker_stopped, connection_type)
        thread.finished.connect(worker.deleteLater)

        self._threads[feed_id] = thread
        self._workers[feed_id] = worker

        thread.start()
        self._on_worker_status(feed_id, "info", "Starting feed")

    def stop_feed(self, feed_id: str, force: bool = False) -> None:
        worker = self._workers.pop(feed_id, None)
        thread = self._threads.pop(feed_id, None)

        if thread is not None:
            thread.requestInterruption()

        if worker is not None:
            QMetaObject.invokeMethod(worker, "stop", _queued_connection_type())

        if thread is not None:
            thread.quit()
            stopped = thread.wait(2500)
            if force and not stopped:
                thread.terminate()
                thread.wait(1000)
            thread.deleteLater()

        self._on_worker_status(feed_id, "idle", "Stopped")

    def set_keep_center_target(
        self,
        feed_id: str,
        role: str,
        enabled: bool,
        source_ids: Optional[List[str]] = None,
    ) -> None:
        selected_role = str(role or "vessel").strip().lower()
        if selected_role not in _KEEP_CENTER_MODES:
            selected_role = "vessel"

        normalized_source_ids: List[str] = []
        if isinstance(source_ids, list):
            for source_id in source_ids:
                text = str(source_id).strip()
                if text and text not in normalized_source_ids:
                    normalized_source_ids.append(text)

        if not enabled:
            if selected_role == "group":
                if self._keep_center_enabled and self._keep_center_role == "group":
                    self._keep_center_enabled = False
                    self._keep_center_feed_id = ""
                    self._keep_center_role = "vessel"
                    self._keep_center_source_ids = []
                return

            if (
                self._keep_center_enabled
                and self._keep_center_feed_id == feed_id
                and self._keep_center_role == selected_role
            ):
                self._keep_center_enabled = False
                self._keep_center_feed_id = ""
                self._keep_center_role = "vessel"
            return

        if selected_role == "group":
            if not normalized_source_ids:
                return

            self._keep_center_enabled = True
            self._keep_center_feed_id = ""
            self._keep_center_role = "group"
            self._keep_center_source_ids = normalized_source_ids

            center = self._resolve_group_center(datetime.now(timezone.utc))
            if center is not None:
                self._center_map_on(center[0], center[1])
            return

        feed = self._feeds.get(feed_id)
        if feed is None:
            return

        self._keep_center_enabled = True
        self._keep_center_feed_id = feed_id
        self._keep_center_role = selected_role
        self._keep_center_source_ids = []
        self._apply_keep_center_for_feed(feed, datetime.now(timezone.utc))

    def shutdown(self) -> None:
        self._shutting_down = True
        self._project_transition_active = False
        self._project_transition_resume_feed_ids = []
        self.stop_all(force=True)
        self._layer_manager.clear()
        self._latest_heading.clear()
        self._telemetry_by_layer.clear()
        self._last_position_by_layer.clear()
        self._last_vehicle_fix_by_feed.clear()
        self._vehicle_fallback_active_by_feed.clear()
        self._keep_center_enabled = False
        self._keep_center_feed_id = ""
        self._keep_center_role = "vessel"
        self._keep_center_source_ids = []
        self._persist()

    def log_directory(self) -> str:
        return self._log_dir

    def _persist(self) -> None:
        self._settings.save_feeds(self.feeds())

    def _initialize_log_dir(self) -> str:
        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            profile_root = os.path.join(
                appdata,
                "QGIS",
                "QGIS4",
                "profiles",
                "default",
            )
            log_dir = os.path.join(profile_root, "qgis_udp_nav_logs")
            legacy_log_dir = os.path.join(
                profile_root,
                "python",
                "plugins",
                "qgis_udp_nav_plugin",
                "logs",
            )
        else:
            log_dir = os.path.join(
                os.path.expanduser("~"),
                ".qgis_udp_nav_plugin",
                "logs",
            )
            legacy_log_dir = ""

        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            return ""

        if legacy_log_dir and os.path.isdir(legacy_log_dir):
            try:
                for name in os.listdir(legacy_log_dir):
                    if not name.lower().endswith(".log"):
                        continue
                    source_path = os.path.join(legacy_log_dir, name)
                    target_path = os.path.join(log_dir, name)
                    if os.path.exists(target_path):
                        continue
                    shutil.copy2(source_path, target_path)
            except OSError:
                pass

        return log_dir

    @staticmethod
    def _safe_file_component(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "unknown"
        safe_chars = []
        for char in text:
            if char.isalnum() or char in {"-", "_", "."}:
                safe_chars.append(char)
            else:
                safe_chars.append("_")
        return "".join(safe_chars)

    def _append_log_line(self, feed_id: str, category: str, message: str) -> None:
        if not self._log_dir:
            return

        date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
        feed_part = self._safe_file_component(feed_id)
        file_path = os.path.join(self._log_dir, f"{date_part}_{feed_part}.log")

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        category_text = str(category or "INFO").strip().upper() or "INFO"
        line = f"{stamp} [{category_text}] {message}\n"

        try:
            with open(file_path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            return

    def _emit_profiles(self) -> None:
        self.vessel_profiles_changed.emit(self.vessel_profiles())

    def snapshot_rows(self) -> List[dict]:
        rows: List[dict] = []
        for feed in self.feeds():
            self._sync_status_slots(feed)

            base_status = self._status_for_id(feed.feed_id)
            base_row = feed.to_dict()
            base_row.update(
                {
                    "feed_id": feed.feed_id,
                    "parent_feed_id": "",
                    "subfeed_role": "",
                    "row_kind": "feed",
                    "name": feed.name,
                    "bind_host": feed.bind_host,
                    "port": feed.port,
                    "checksum_policy": feed.checksum_policy,
                    "status": base_status["level"],
                    "message": base_status["message"],
                    "icon_path": feed.icon_path,
                    "symbol_summary": self._main_row_summary(feed),
                    "heading_deg": self._heading_deg_for_main_row(feed),
                    "heading_source": self._heading_source_for_main_row(feed),
                    "speed_knots": self._speed_knots_for_main_row(feed),
                    "depth_m": self._depth_m_for_main_row(feed),
                    "track_enabled": self._track_enabled_for_main_row(feed),
                    "track_dimension": self._track_dimension_for_main_row(feed),
                    "track_raw_m": self._track_raw_m_for_main_row(feed),
                    "track_smoothed_m": self._track_smoothed_m_for_main_row(feed),
                }
            )
            rows.append(base_row)

            if feed.split_subfeeds_enabled:
                rows.append(self._subfeed_row(feed, "vessel", "  |- Vessel"))
                rows.append(self._subfeed_row(feed, "vehicle", "  \\- Vehicle"))

        return rows

    def _emit_snapshot(self) -> None:
        self.snapshot_changed.emit(self.snapshot_rows())

    def _emit_live_snapshot(self) -> None:
        now = time.monotonic()
        if (now - self._last_live_snapshot_monotonic) < _LIVE_SNAPSHOT_MIN_INTERVAL_SEC:
            return

        self._last_live_snapshot_monotonic = now
        self._emit_snapshot()

    @pyqtSlot(str)
    def _on_worker_stopped(self, feed_id: str) -> None:
        thread = self._threads.pop(feed_id, None)
        self._workers.pop(feed_id, None)

        if thread is not None:
            thread.quit()
            thread.wait(2000)
            thread.deleteLater()

        if not self._shutting_down:
            self._on_worker_status(feed_id, "idle", "Stopped")

    @pyqtSlot(str, str, str)
    def _on_worker_status(self, feed_id: str, level: str, message: str) -> None:
        if self._shutting_down:
            return

        self._set_status(feed_id, level, message)

    def _on_subfeed_status(self, feed: FeedConfig, role: str, level: str, message: str) -> None:
        if feed.split_subfeeds_enabled:
            status_id = self._subfeed_layer_id(feed.feed_id, role)
        else:
            status_id = feed.feed_id
        self._set_status(status_id, level, message)

    def _set_status(self, status_id: str, level: str, message: str) -> None:
        normalized_level = str(level or "info").strip().lower() or "info"
        normalized_message = str(message or "").strip()
        previous = self._status_by_feed.get(status_id)
        if (
            previous is not None
            and previous.get("level") == normalized_level
            and previous.get("message") == normalized_message
        ):
            return

        self._status_by_feed[status_id] = {
            "level": normalized_level,
            "message": normalized_message,
        }
        self.status_changed.emit(status_id, normalized_level, normalized_message)
        self._append_log_line(
            status_id,
            "STATUS",
            f"{normalized_level}: {normalized_message}",
        )
        self._emit_snapshot()

    @pyqtSlot(object)
    def _on_worker_event(self, event: object) -> None:
        if self._shutting_down or self._project_transition_active:
            return

        feed = self._feeds.get(getattr(event, "feed_id", ""))
        if feed is None:
            return

        if isinstance(event, ParseWarningEvent):
            role = self._route_role(feed, event.sentence_type, talker=event.talker)
            self._on_subfeed_status(
                feed,
                role,
                "warning",
                self._role_prefix(feed, role) + event.message,
            )
            return

        if isinstance(event, FeedStatusEvent):
            role = self._route_role(feed, event.sentence_type, talker=event.talker)
            heading = event.metadata.get("heading_deg") if isinstance(event.metadata, dict) else None
            if isinstance(heading, (int, float)):
                heading_value = self._normalize_heading(float(heading))
                self._set_heading(
                    event.feed_id,
                    role,
                    heading_value,
                    source=event.sentence_type,
                    is_true=bool(event.metadata.get("heading_is_true", False)),
                )

            adjusted_level = self._adjust_status_level(
                role=role,
                level=event.level,
                code=event.code,
                message=event.message,
            )

            if event.sentence_type.upper() == "PSIMSNS" and adjusted_level == "info":
                return

            self._on_subfeed_status(
                feed,
                role,
                adjusted_level,
                self._role_prefix(feed, role) + event.message,
            )
            return

        if isinstance(event, HeadingEvent):
            if event.valid and isinstance(event.heading_deg, (int, float)):
                heading_value = self._normalize_heading(float(event.heading_deg))
                role = self._route_role(feed, event.sentence_type, talker=event.talker)
                self._set_heading(
                    event.feed_id,
                    role,
                    heading_value,
                    source=event.sentence_type,
                    is_true=event.is_true_heading,
                )
            return

        if isinstance(event, PositionFixEvent):
            self._handle_position_event(event)

    @pyqtSlot(str, str, str)
    def _on_worker_sentence(self, feed_id: str, source_address: str, sentence: str) -> None:
        if self._shutting_down or self._project_transition_active:
            return

        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        source = source_address or "-"
        line = f"{stamp}Z [{source}] {sentence}"
        self.sentence_streamed.emit(feed_id, line)
        self._append_log_line(feed_id, "SENTENCE", line)

    def _handle_position_event(self, event: PositionFixEvent) -> None:
        feed = self._feeds.get(event.feed_id)
        if feed is None:
            return

        role = self._route_role(feed, event.sentence_type, talker=event.talker)
        render_feed = self._render_feed(feed, role)

        def _finish() -> None:
            self._apply_keep_center_for_feed(feed, event.received_at)
            self._emit_live_snapshot()

        if event.sentence_type == "PSIMSSB":
            resolved = self._resolve_psimssb_position(
                feed,
                event,
                render_feed.feed_id,
                status_role=role,
            )
            if resolved is None:
                if event.valid:
                    self._on_subfeed_status(
                        feed,
                        role,
                        "warning",
                        self._role_prefix(feed, role)
                        + "PSIMSSB is valid but could not be transformed to map coordinates",
                    )
                self._update_telemetry_from_position_event(render_feed.feed_id, event)
                _finish()
                return
            event.latitude, event.longitude = resolved

        self._update_telemetry_from_position_event(render_feed.feed_id, event)

        heading_info = self._latest_heading.get(render_feed.feed_id)
        if heading_info is not None:
            event.metadata["display_heading_deg"] = heading_info["heading_deg"]
            event.metadata["heading_source"] = heading_info["source"]
            event.metadata["heading_true"] = heading_info["is_true"]

        if event.valid and event.latitude is not None and event.longitude is not None:
            track_enabled = self._track_enabled_for_role(feed, role)
            track_use_depth_3d = role == "vehicle"
            track_depth_m: Optional[float] = None
            if track_use_depth_3d:
                telemetry = self._telemetry_by_layer.get(render_feed.feed_id, {})
                depth_value = telemetry.get("depth_m")
                if isinstance(depth_value, (int, float)):
                    track_depth_m = float(depth_value)

            self._layer_manager.upsert_position(
                render_feed,
                event,
                track_enabled=track_enabled,
                track_use_depth_3d=track_use_depth_3d,
                track_depth_m=track_depth_m,
            )
            self._remember_position(
                render_feed.feed_id,
                event.latitude,
                event.longitude,
                event.received_at,
            )

            if role == "vehicle":
                self._last_vehicle_fix_by_feed[feed.feed_id] = event.received_at
                was_fallback = self._vehicle_fallback_active_by_feed.get(feed.feed_id, False)
                self._vehicle_fallback_active_by_feed[feed.feed_id] = False
                if was_fallback:
                    status_message = (
                        self._role_prefix(feed, role)
                        + "Vehicle position restored; using vehicle coordinates"
                    )
                else:
                    status_message = self._role_prefix(feed, role) + "Position updated"
            else:
                status_message = self._role_prefix(feed, role) + "Position updated"

            self._on_subfeed_status(
                feed,
                role,
                "info",
                status_message,
            )

            if role == "vessel":
                self._apply_vehicle_fallback_if_needed(feed, event)
            _finish()
            return

        if role == "vehicle":
            # Keep last valid vehicle position during transient invalid telegrams.
            if self._vehicle_position_recent(feed, event.received_at):
                _finish()
                return

            if self._apply_vehicle_fallback(feed, vessel_event=None):
                _finish()
                return

        invalid_level = self._position_invalid_level(role, event)
        self._on_subfeed_status(
            feed,
            role,
            invalid_level,
            self._role_prefix(feed, role)
            + f"{event.sentence_type} did not contain a valid position",
        )
        _finish()

    def _resolve_psimssb_position(
        self,
        feed: FeedConfig,
        event: PositionFixEvent,
        heading_feed_id: str,
        status_role: str,
    ) -> Optional[Tuple[float, float]]:
        metadata = event.metadata
        x = metadata.get("x_coordinate")
        y = metadata.get("y_coordinate")
        coordinate_system = str(metadata.get("coordinate_system") or "").upper()
        orientation = str(metadata.get("orientation") or "").upper()

        if x is None or y is None:
            return None

        if coordinate_system == "U":
            if orientation == "N":
                northing = float(x)
                easting = float(y)
            elif orientation == "E":
                easting = float(x)
                northing = float(y)
            else:
                self._on_subfeed_status(
                    feed,
                    status_role,
                    "warning",
                    self._role_prefix(feed, status_role)
                    + f"Unsupported PSIMSSB UTM orientation '{orientation or '<empty>'}'",
                )
                return None
            return self._utm_to_wgs84(feed, easting, northing, status_role)

        if coordinate_system == "C":
            offsets = self._cartesian_offsets(
                feed,
                float(x),
                float(y),
                orientation,
                heading_feed_id,
                status_role,
            )
            if offsets is None:
                return None
            return self._offset_to_wgs84(feed, offsets[0], offsets[1], status_role)

        if coordinate_system == "P":
            offsets = self._polar_offsets(
                feed,
                float(x),
                float(y),
                orientation,
                heading_feed_id,
                status_role,
            )
            if offsets is None:
                return None
            return self._offset_to_wgs84(feed, offsets[0], offsets[1], status_role)

        self._on_subfeed_status(
            feed,
            status_role,
            "warning",
            self._role_prefix(feed, status_role)
            + f"Unsupported PSIMSSB coordinate system '{coordinate_system or '<empty>'}'",
        )
        return None

    def _utm_to_wgs84(
        self,
        feed: FeedConfig,
        easting: float,
        northing: float,
        status_role: str,
    ) -> Optional[Tuple[float, float]]:
        if not feed.hipap_utm_epsg:
            self._on_subfeed_status(
                feed,
                status_role,
                "warning",
                self._role_prefix(feed, status_role)
                + "PSIMSSB UTM coordinates received but feed has no UTM EPSG configured",
            )
            return None

        source_crs = QgsCoordinateReferenceSystem(f"EPSG:{feed.hipap_utm_epsg}")
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        if not source_crs.isValid():
            self._on_subfeed_status(
                feed,
                status_role,
                "error",
                self._role_prefix(feed, status_role)
                + f"Configured UTM EPSG is invalid: {feed.hipap_utm_epsg}",
            )
            return None

        try:
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            point = transform.transform(QgsPointXY(easting, northing))
            return point.y(), point.x()
        except Exception as exc:  # pragma: no cover - depends on QGIS runtime.
            self._on_subfeed_status(
                feed,
                status_role,
                "error",
                self._role_prefix(feed, status_role)
                + f"Failed to transform PSIMSSB UTM coordinates: {exc}",
            )
            return None

    def _cartesian_offsets(
        self,
        feed: FeedConfig,
        x_value: float,
        y_value: float,
        orientation: str,
        heading_feed_id: str,
        status_role: str,
    ) -> Optional[Tuple[float, float]]:
        if orientation == "N":
            north = x_value
            east = y_value
            return east, north

        if orientation == "E":
            east = x_value
            north = y_value
            return east, north

        if orientation == "H":
            heading = self._heading_for_feed(feed, heading_feed_id)
            if heading is None:
                self._on_subfeed_status(
                    feed,
                    status_role,
                    "warning",
                    self._role_prefix(feed, status_role)
                    + "PSIMSSB head-up coordinates require heading (PSIMSNS, vessel heading, or feed config)",
                )
                return None
            return self._forward_starboard_to_offsets(heading, forward_m=y_value, starboard_m=x_value)

        self._on_subfeed_status(
            feed,
            status_role,
            "warning",
            self._role_prefix(feed, status_role)
            + f"Unsupported PSIMSSB Cartesian orientation '{orientation or '<empty>'}'",
        )
        return None

    def _polar_offsets(
        self,
        feed: FeedConfig,
        range_m: float,
        bearing_deg: float,
        orientation: str,
        heading_feed_id: str,
        status_role: str,
    ) -> Optional[Tuple[float, float]]:
        if orientation == "N":
            radians = math.radians(bearing_deg)
            east = range_m * math.sin(radians)
            north = range_m * math.cos(radians)
            return east, north

        if orientation == "E":
            radians = math.radians(bearing_deg)
            east = range_m * math.cos(radians)
            north = range_m * math.sin(radians)
            return east, north

        if orientation == "H":
            heading = self._heading_for_feed(feed, heading_feed_id)
            if heading is None:
                self._on_subfeed_status(
                    feed,
                    status_role,
                    "warning",
                    self._role_prefix(feed, status_role)
                    + "PSIMSSB head-up polar coordinates require heading (PSIMSNS, vessel heading, or feed config)",
                )
                return None

            radians = math.radians(bearing_deg)
            forward = range_m * math.cos(radians)
            starboard = range_m * math.sin(radians)
            return self._forward_starboard_to_offsets(heading, forward, starboard)

        self._on_subfeed_status(
            feed,
            status_role,
            "warning",
            self._role_prefix(feed, status_role)
            + f"Unsupported PSIMSSB polar orientation '{orientation or '<empty>'}'",
        )
        return None

    @staticmethod
    def _forward_starboard_to_offsets(
        heading_deg: float,
        forward_m: float,
        starboard_m: float,
    ) -> Tuple[float, float]:
        heading = math.radians(heading_deg)

        east = (math.sin(heading) * forward_m) + (math.cos(heading) * starboard_m)
        north = (math.cos(heading) * forward_m) - (math.sin(heading) * starboard_m)
        return east, north

    def _offset_to_wgs84(
        self,
        feed: FeedConfig,
        east_m: float,
        north_m: float,
        status_role: str,
    ) -> Optional[Tuple[float, float]]:
        reference = self._reference_lat_lon_for_local_offsets(feed)
        if reference is None:
            self._on_subfeed_status(
                feed,
                status_role,
                "warning",
                self._role_prefix(feed, status_role)
                + "PSIMSSB local coordinates require reference lat/lon configuration or live vessel position",
            )
            return None

        lat0 = reference[0]
        lon0 = reference[1]

        lat = lat0 + (north_m / 111320.0)
        cos_lat = math.cos(math.radians(lat0))
        if abs(cos_lat) < 1e-9:
            self._on_subfeed_status(
                feed,
                status_role,
                "error",
                self._role_prefix(feed, status_role)
                + "Reference latitude too close to poles for local conversion",
            )
            return None

        lon = lon0 + (east_m / (111320.0 * cos_lat))
        return lat, lon

    def _reference_lat_lon_for_local_offsets(self, feed: FeedConfig) -> Optional[Tuple[float, float]]:
        if isinstance(feed.reference_lat, (int, float)) and isinstance(feed.reference_lon, (int, float)):
            latitude = float(feed.reference_lat)
            longitude = float(feed.reference_lon)
            if math.isfinite(latitude) and math.isfinite(longitude):
                return latitude, longitude

        candidate_layer_ids: List[str] = []
        if feed.split_subfeeds_enabled:
            candidate_layer_ids.append(self._subfeed_layer_id(feed.feed_id, "vessel"))
        candidate_layer_ids.append(feed.feed_id)

        for candidate_layer_id in candidate_layer_ids:
            latest = self._last_position_by_layer.get(candidate_layer_id)
            if latest is None:
                continue

            latitude = float(latest[0])
            longitude = float(latest[1])
            if math.isfinite(latitude) and math.isfinite(longitude):
                return latitude, longitude

        return None

    def _heading_for_feed(self, feed: FeedConfig, heading_feed_id: str) -> Optional[float]:
        candidate_ids: List[str] = []

        def _add_candidate(candidate_id: str) -> None:
            text = str(candidate_id or "").strip()
            if text and text not in candidate_ids:
                candidate_ids.append(text)

        _add_candidate(heading_feed_id)
        _add_candidate(feed.feed_id)

        if feed.split_subfeeds_enabled:
            vessel_id = self._subfeed_layer_id(feed.feed_id, "vessel")
            vehicle_id = self._subfeed_layer_id(feed.feed_id, "vehicle")

            if heading_feed_id == vehicle_id:
                _add_candidate(vessel_id)
            elif heading_feed_id == vessel_id:
                _add_candidate(vehicle_id)
            else:
                _add_candidate(vessel_id)
                _add_candidate(vehicle_id)

        for candidate_id in candidate_ids:
            heading_state = self._latest_heading.get(candidate_id)
            if heading_state is None:
                continue
            heading = heading_state.get("heading_deg")
            if isinstance(heading, (int, float)):
                return float(heading)

        if isinstance(feed.reference_heading_deg, (int, float)):
            return float(feed.reference_heading_deg)
        return None

    def _set_heading(
        self,
        base_feed_id: str,
        role: str,
        heading_deg: float,
        source: str,
        is_true: bool,
    ) -> None:
        feed = self._feeds.get(base_feed_id)
        if feed is None:
            return

        heading_value = self._normalize_heading(heading_deg)
        render_feed = self._render_feed(feed, role)
        self._latest_heading[render_feed.feed_id] = {
            "heading_deg": heading_value,
            "source": source,
            "is_true": bool(is_true),
        }
        telemetry = self._telemetry_by_layer.setdefault(render_feed.feed_id, {})
        telemetry["heading_deg"] = heading_value
        telemetry["heading_source"] = source
        self._layer_manager.update_heading(render_feed, heading_value)

    @staticmethod
    def _normalize_heading(value: float) -> float:
        heading = value % 360.0
        if heading < 0:
            heading += 360.0
        return heading

    def _route_role(
        self,
        feed: FeedConfig,
        sentence_type: str,
        talker: Optional[str] = None,
    ) -> str:
        if not feed.split_subfeeds_enabled:
            return "vessel"

        sentence = str(sentence_type or "").strip().upper()
        talker_id = str(talker or "").strip().upper()
        if feed.split_routing_mode == "manual":
            if sentence in feed.manual_vessel_sentence_types:
                return "vessel"
            if sentence in feed.manual_vehicle_sentence_types:
                return "vehicle"

        if sentence == "GLL" and talker_id in _AUTO_VEHICLE_GLL_TALKERS:
            return "vehicle"

        if sentence in _AUTO_VEHICLE_SENTENCE_TYPES or sentence.startswith("PSIMS"):
            return "vehicle"
        if sentence in _AUTO_VESSEL_SENTENCE_TYPES:
            return "vessel"
        return "vessel"

    def _render_feed(self, feed: FeedConfig, role: str) -> FeedConfig:
        selected_role = str(role).strip().lower()
        if selected_role not in _SUBFEED_ROLES:
            selected_role = "vessel"

        data = feed.to_dict()
        if feed.split_subfeeds_enabled:
            data["feed_id"] = self._subfeed_layer_id(feed.feed_id, selected_role)
            data["name"] = f"{feed.name} ({selected_role})"

        if selected_role == "vehicle":
            data["symbol_mode"] = feed.vehicle_symbol_mode
            data["icon_path"] = feed.vehicle_icon_path
            data["color_hex"] = feed.vehicle_color_hex
            data["vessel_length_m"] = feed.vehicle_vessel_length_m
            data["vessel_width_m"] = feed.vehicle_vessel_width_m
            data["vessel_gps_longitudinal_reference"] = (
                feed.vehicle_vessel_gps_longitudinal_reference
            )
            data["vessel_gps_offset_from_reference_m"] = (
                feed.vehicle_vessel_gps_offset_from_reference_m
            )
            data["vessel_gps_offset_starboard_m"] = feed.vehicle_vessel_gps_offset_starboard_m
            data["qgis_symbol_name"] = feed.vehicle_qgis_symbol_name
            data["qgis_symbol_width"] = feed.vehicle_qgis_symbol_width
            data["qgis_symbol_height"] = feed.vehicle_qgis_symbol_height
            data["qgis_size_unit"] = feed.vehicle_qgis_size_unit
            data["unicode_symbol"] = feed.vehicle_unicode_symbol
            data["unicode_font_family"] = feed.vehicle_unicode_font_family

        return FeedConfig.from_dict(data)

    @staticmethod
    def _subfeed_layer_id(feed_id: str, role: str) -> str:
        return f"{feed_id}:{role}"

    def _clear_render_state(self, feed_id: str) -> None:
        for layer_id in (
            feed_id,
            self._subfeed_layer_id(feed_id, "vessel"),
            self._subfeed_layer_id(feed_id, "vehicle"),
        ):
            self._layer_manager.remove_feed(layer_id)
            self._latest_heading.pop(layer_id, None)
            self._telemetry_by_layer.pop(layer_id, None)
            self._last_position_by_layer.pop(layer_id, None)

        self._last_vehicle_fix_by_feed.pop(feed_id, None)
        self._vehicle_fallback_active_by_feed.pop(feed_id, None)

    def _sync_status_slots(self, feed: FeedConfig) -> None:
        self._status_by_feed.setdefault(feed.feed_id, self._default_status())
        vessel_id = self._subfeed_layer_id(feed.feed_id, "vessel")
        vehicle_id = self._subfeed_layer_id(feed.feed_id, "vehicle")

        if feed.split_subfeeds_enabled:
            self._status_by_feed.setdefault(vessel_id, self._default_status())
            self._status_by_feed.setdefault(vehicle_id, self._default_status())
        else:
            self._status_by_feed.pop(vessel_id, None)
            self._status_by_feed.pop(vehicle_id, None)

    def _remove_status_slots(self, feed_id: str) -> None:
        self._status_by_feed.pop(feed_id, None)
        self._status_by_feed.pop(self._subfeed_layer_id(feed_id, "vessel"), None)
        self._status_by_feed.pop(self._subfeed_layer_id(feed_id, "vehicle"), None)

    def _status_for_id(self, status_id: str) -> Dict[str, str]:
        return self._status_by_feed.get(status_id, self._default_status())

    @staticmethod
    def _default_status() -> Dict[str, str]:
        return {"level": "idle", "message": "Stopped"}

    def _subfeed_row(self, feed: FeedConfig, role: str, display_name: str) -> dict:
        row = feed.to_dict()
        row_id = self._subfeed_layer_id(feed.feed_id, role)
        status = self._status_for_id(row_id)

        if role == "vehicle":
            row["icon_path"] = feed.vehicle_icon_path
            row["symbol_mode"] = feed.vehicle_symbol_mode
            row["color_hex"] = feed.vehicle_color_hex

        row.update(
            {
                "feed_id": row_id,
                "parent_feed_id": feed.feed_id,
                "subfeed_role": role,
                "row_kind": "subfeed",
                "name": display_name,
                "bind_host": "",
                "port": "",
                "checksum_policy": "",
                "status": status["level"],
                "message": status["message"],
                "symbol_summary": self._symbol_summary_for_role(feed, role),
                "heading_deg": self._heading_deg_by_id(row_id),
                "heading_source": self._heading_source_by_id(row_id),
                "speed_knots": self._speed_knots_by_id(row_id),
                "depth_m": self._depth_m_by_id(row_id),
                "track_enabled": self._track_enabled_for_role(feed, role),
                "track_dimension": self._track_dimension_for_role(role),
                "track_raw_m": self._track_raw_m_by_id(row_id),
                "track_smoothed_m": self._track_smoothed_m_by_id(row_id),
            }
        )
        return row

    def _heading_deg_for_main_row(self, feed: FeedConfig) -> Optional[float]:
        if feed.split_subfeeds_enabled:
            vessel_heading = self._heading_deg_by_id(self._subfeed_layer_id(feed.feed_id, "vessel"))
            if vessel_heading is not None:
                return vessel_heading
            return self._heading_deg_by_id(self._subfeed_layer_id(feed.feed_id, "vehicle"))
        return self._heading_deg_by_id(feed.feed_id)

    def _heading_source_for_main_row(self, feed: FeedConfig) -> str:
        if feed.split_subfeeds_enabled:
            vessel_source = self._heading_source_by_id(self._subfeed_layer_id(feed.feed_id, "vessel"))
            if vessel_source:
                return vessel_source
            return self._heading_source_by_id(self._subfeed_layer_id(feed.feed_id, "vehicle"))
        return self._heading_source_by_id(feed.feed_id)

    def _heading_deg_by_id(self, feed_id: str) -> Optional[float]:
        state = self._latest_heading.get(feed_id)
        if state is None:
            return None
        heading = state.get("heading_deg")
        if isinstance(heading, (int, float)):
            return float(heading)
        return None

    def _heading_source_by_id(self, feed_id: str) -> str:
        state = self._latest_heading.get(feed_id)
        if state is None:
            return ""
        source = state.get("source")
        return str(source) if source is not None else ""

    def _speed_knots_for_main_row(self, feed: FeedConfig) -> Optional[float]:
        if feed.split_subfeeds_enabled:
            vessel_speed = self._speed_knots_by_id(self._subfeed_layer_id(feed.feed_id, "vessel"))
            if vessel_speed is not None:
                return vessel_speed
            return self._speed_knots_by_id(self._subfeed_layer_id(feed.feed_id, "vehicle"))
        return self._speed_knots_by_id(feed.feed_id)

    def _depth_m_for_main_row(self, feed: FeedConfig) -> Optional[float]:
        if feed.split_subfeeds_enabled:
            vehicle_depth = self._depth_m_by_id(self._subfeed_layer_id(feed.feed_id, "vehicle"))
            if vehicle_depth is not None:
                return vehicle_depth
            return self._depth_m_by_id(self._subfeed_layer_id(feed.feed_id, "vessel"))
        return self._depth_m_by_id(feed.feed_id)

    def _speed_knots_by_id(self, feed_id: str) -> Optional[float]:
        telemetry = self._telemetry_by_layer.get(feed_id)
        if telemetry is None:
            return None
        value = telemetry.get("speed_knots")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _depth_m_by_id(self, feed_id: str) -> Optional[float]:
        telemetry = self._telemetry_by_layer.get(feed_id)
        if telemetry is None:
            return None
        value = telemetry.get("depth_m")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _track_enabled_for_main_row(self, feed: FeedConfig) -> bool:
        if feed.split_subfeeds_enabled:
            return bool(feed.vessel_track_enabled or feed.vehicle_track_enabled)
        return bool(feed.vessel_track_enabled)

    def _track_dimension_for_main_row(self, feed: FeedConfig) -> str:
        if feed.split_subfeeds_enabled and feed.vessel_track_enabled and feed.vehicle_track_enabled:
            vessel_id = self._subfeed_layer_id(feed.feed_id, "vessel")
            vehicle_id = self._subfeed_layer_id(feed.feed_id, "vehicle")
            if self._track_has_points(vessel_id) and self._track_has_points(vehicle_id):
                return "2d+3d"

        track_id = self._track_id_for_main_row(feed)
        if track_id.endswith(":vehicle"):
            return "3d"
        if track_id.endswith(":vessel"):
            return "2d"

        if feed.split_subfeeds_enabled and not feed.vessel_track_enabled and feed.vehicle_track_enabled:
            return "3d"
        return "2d"

    def _track_raw_m_for_main_row(self, feed: FeedConfig) -> Optional[float]:
        track_id = self._track_id_for_main_row(feed)
        if not track_id:
            return None
        return self._track_raw_m_by_id(track_id)

    def _track_smoothed_m_for_main_row(self, feed: FeedConfig) -> Optional[float]:
        track_id = self._track_id_for_main_row(feed)
        if not track_id:
            return None
        return self._track_smoothed_m_by_id(track_id)

    def _track_id_for_main_row(self, feed: FeedConfig) -> str:
        candidate_ids: List[str] = []

        if feed.split_subfeeds_enabled:
            if feed.vessel_track_enabled:
                candidate_ids.append(self._subfeed_layer_id(feed.feed_id, "vessel"))
            if feed.vehicle_track_enabled:
                candidate_ids.append(self._subfeed_layer_id(feed.feed_id, "vehicle"))
        elif feed.vessel_track_enabled:
            candidate_ids.append(feed.feed_id)

        if not candidate_ids:
            return ""

        for candidate_id in candidate_ids:
            if self._track_has_points(candidate_id):
                return candidate_id

        return candidate_ids[0]

    def _track_has_points(self, feed_id: str) -> bool:
        metrics = self._layer_manager.track_metrics(feed_id)
        if not isinstance(metrics, dict):
            return False
        return int(metrics.get("point_count") or 0) >= 2

    def _track_enabled_for_role(self, feed: FeedConfig, role: str) -> bool:
        if role == "vehicle":
            return bool(feed.split_subfeeds_enabled and feed.vehicle_track_enabled)
        return bool(feed.vessel_track_enabled)

    @staticmethod
    def _track_color_for_role(feed: FeedConfig, role: str) -> str:
        if role == "vehicle" and feed.split_subfeeds_enabled:
            return str(feed.vehicle_color_hex or feed.color_hex)
        return str(feed.color_hex)

    @staticmethod
    def _track_dimension_for_role(role: str) -> str:
        return "3d" if role == "vehicle" else "2d"

    def _track_raw_m_by_id(self, feed_id: str) -> Optional[float]:
        metrics = self._layer_manager.track_metrics(feed_id)
        if not isinstance(metrics, dict):
            return None
        value = metrics.get("raw_m")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _track_smoothed_m_by_id(self, feed_id: str) -> Optional[float]:
        metrics = self._layer_manager.track_metrics(feed_id)
        if not isinstance(metrics, dict):
            return None
        value = metrics.get("smoothed_m")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _main_row_summary(self, feed: FeedConfig) -> str:
        if not feed.split_subfeeds_enabled:
            return self._symbol_summary_for_role(feed, "vessel")

        routing = "manual" if feed.split_routing_mode == "manual" else "auto"
        fallback = (
            "vehicle fallback on"
            if feed.vehicle_show_on_vessel_when_missing_position
            else "vehicle fallback off"
        )
        return f"Split feed ({routing}, {fallback})"

    @staticmethod
    def _symbol_summary_for_role(feed: FeedConfig, role: str) -> str:
        if role == "vehicle":
            symbol_mode = feed.vehicle_symbol_mode
            icon_path = feed.vehicle_icon_path
            vessel_length = feed.vehicle_vessel_length_m
            vessel_width = feed.vehicle_vessel_width_m
            reference = feed.vehicle_vessel_gps_longitudinal_reference
            offset_from_reference = feed.vehicle_vessel_gps_offset_from_reference_m
            starboard = feed.vehicle_vessel_gps_offset_starboard_m
            qgis_symbol = feed.vehicle_qgis_symbol_name
            qgis_width = feed.vehicle_qgis_symbol_width
            qgis_height = feed.vehicle_qgis_symbol_height
            qgis_unit = feed.vehicle_qgis_size_unit
            unicode_symbol = feed.vehicle_unicode_symbol
            role_prefix = "Vehicle "
        else:
            symbol_mode = feed.symbol_mode
            icon_path = feed.icon_path
            vessel_length = feed.vessel_length_m
            vessel_width = feed.vessel_width_m
            reference = feed.vessel_gps_longitudinal_reference
            offset_from_reference = feed.vessel_gps_offset_from_reference_m
            starboard = feed.vessel_gps_offset_starboard_m
            qgis_symbol = feed.qgis_symbol_name
            qgis_width = feed.qgis_symbol_width
            qgis_height = feed.qgis_symbol_height
            qgis_unit = feed.qgis_size_unit
            unicode_symbol = feed.unicode_symbol
            role_prefix = ""

        if symbol_mode == "vessel":
            reference_label = "Bow" if reference == "bow" else "Stern"
            return (
                f"{role_prefix}hull {vessel_length:.3f}x{vessel_width:.3f}m, "
                f"GPS {reference_label} {offset_from_reference:.3f}m, "
                f"S{starboard:+.3f}m"
            )

        if symbol_mode == "vehicle":
            reference_label = "Bow" if reference == "bow" else "Stern"
            return (
                f"{role_prefix}rectangle {vessel_length:.3f}x{vessel_width:.3f}m, "
                f"GPS {reference_label} {offset_from_reference:.3f}m, "
                f"S{starboard:+.3f}m"
            )

        if symbol_mode == "icon_file":
            if icon_path:
                return f"{role_prefix}icon {os.path.basename(icon_path)}"
            return f"{role_prefix}icon not set"

        if symbol_mode == "unicode":
            symbol = unicode_symbol or "?"
            return f"{role_prefix}unicode {symbol}"

        unit_label = "m" if qgis_unit == "map_meters" else "mm"
        return f"{role_prefix}marker {qgis_symbol} ({qgis_width:.3f}x{qgis_height:.3f} {unit_label})"

    def _apply_symbol_payload(self, feed: FeedConfig, payload: dict, role: str) -> None:
        if role == "vehicle":
            feed.vehicle_symbol_mode = (
                str(payload.get("symbol_mode", feed.vehicle_symbol_mode)).strip().lower()
            )
            feed.vehicle_vessel_length_m = float(
                payload.get("vessel_length_m", feed.vehicle_vessel_length_m)
            )
            feed.vehicle_vessel_width_m = float(
                payload.get("vessel_width_m", feed.vehicle_vessel_width_m)
            )
            feed.vehicle_vessel_gps_longitudinal_reference = (
                str(
                    payload.get(
                        "vessel_gps_longitudinal_reference",
                        feed.vehicle_vessel_gps_longitudinal_reference,
                    )
                )
                .strip()
                .lower()
            )
            feed.vehicle_vessel_gps_offset_from_reference_m = float(
                payload.get(
                    "vessel_gps_offset_from_reference_m",
                    feed.vehicle_vessel_gps_offset_from_reference_m,
                )
            )
            feed.vehicle_vessel_gps_offset_starboard_m = float(
                payload.get(
                    "vessel_gps_offset_starboard_m",
                    feed.vehicle_vessel_gps_offset_starboard_m,
                )
            )
            feed.vehicle_qgis_symbol_name = (
                str(payload.get("qgis_symbol_name", feed.vehicle_qgis_symbol_name)).strip()
                or feed.vehicle_qgis_symbol_name
            )
            feed.vehicle_qgis_symbol_width = float(
                payload.get("qgis_symbol_width", feed.vehicle_qgis_symbol_width)
            )
            feed.vehicle_qgis_symbol_height = float(
                payload.get("qgis_symbol_height", feed.vehicle_qgis_symbol_height)
            )
            feed.vehicle_qgis_size_unit = (
                str(payload.get("qgis_size_unit", feed.vehicle_qgis_size_unit)).strip().lower()
                or feed.vehicle_qgis_size_unit
            )
            feed.vehicle_unicode_symbol = str(
                payload.get("unicode_symbol", feed.vehicle_unicode_symbol)
            )
            feed.vehicle_unicode_font_family = (
                str(
                    payload.get(
                        "unicode_font_family",
                        feed.vehicle_unicode_font_family,
                    )
                )
                .strip()
                or feed.vehicle_unicode_font_family
            )
            feed.vehicle_color_hex = (
                str(payload.get("color_hex", feed.vehicle_color_hex)).strip()
                or feed.vehicle_color_hex
            )
            feed.vehicle_icon_path = str(payload.get("icon_path", feed.vehicle_icon_path)).strip()
            return

        feed.symbol_mode = str(payload.get("symbol_mode", feed.symbol_mode)).strip().lower()
        feed.vessel_length_m = float(payload.get("vessel_length_m", feed.vessel_length_m))
        feed.vessel_width_m = float(payload.get("vessel_width_m", feed.vessel_width_m))
        feed.vessel_gps_longitudinal_reference = (
            str(
                payload.get(
                    "vessel_gps_longitudinal_reference",
                    feed.vessel_gps_longitudinal_reference,
                )
            )
            .strip()
            .lower()
        )
        feed.vessel_gps_offset_from_reference_m = float(
            payload.get(
                "vessel_gps_offset_from_reference_m",
                feed.vessel_gps_offset_from_reference_m,
            )
        )
        feed.vessel_gps_offset_starboard_m = float(
            payload.get(
                "vessel_gps_offset_starboard_m",
                feed.vessel_gps_offset_starboard_m,
            )
        )
        feed.qgis_symbol_name = (
            str(payload.get("qgis_symbol_name", feed.qgis_symbol_name)).strip()
            or feed.qgis_symbol_name
        )
        feed.qgis_symbol_width = float(payload.get("qgis_symbol_width", feed.qgis_symbol_width))
        feed.qgis_symbol_height = float(payload.get("qgis_symbol_height", feed.qgis_symbol_height))
        feed.qgis_size_unit = (
            str(payload.get("qgis_size_unit", feed.qgis_size_unit)).strip().lower()
            or feed.qgis_size_unit
        )
        feed.unicode_symbol = str(payload.get("unicode_symbol", feed.unicode_symbol))
        feed.unicode_font_family = (
            str(payload.get("unicode_font_family", feed.unicode_font_family)).strip()
            or feed.unicode_font_family
        )
        feed.icon_path = str(payload.get("icon_path", feed.icon_path)).strip()

    @staticmethod
    def _role_prefix(feed: FeedConfig, role: str) -> str:
        if not feed.split_subfeeds_enabled:
            return ""
        if role == "vehicle":
            return "[Vehicle] "
        return "[Vessel] "

    @staticmethod
    def _adjust_status_level(role: str, level: str, code: str, message: str) -> str:
        normalized = str(level or "info").strip().lower() or "info"
        if role != "vehicle":
            return normalized

        code_upper = str(code or "").strip().upper()
        message_lower = str(message or "").lower()
        if (
            code_upper in {"NO_POSITION", "NRY", "PRE"}
            or "no-valid-position" in message_lower
            or "no position" in message_lower
            or "no reply is received" in message_lower
        ):
            if normalized in {"warning", "error"}:
                return "info"
        return normalized

    @staticmethod
    def _position_invalid_level(role: str, event: PositionFixEvent) -> str:
        if role != "vehicle":
            return "warning"

        code = str(event.metadata.get("error_code") or "").strip().upper()
        if code in {"NRY", "PRE"}:
            return "info"
        return "warning"

    def _remember_position(
        self,
        layer_id: str,
        latitude: float,
        longitude: float,
        received_at: datetime,
    ) -> None:
        self._last_position_by_layer[layer_id] = (
            float(latitude),
            float(longitude),
            received_at,
        )

    def _update_telemetry_from_position_event(
        self,
        layer_id: str,
        event: PositionFixEvent,
    ) -> None:
        telemetry = self._telemetry_by_layer.setdefault(layer_id, {})
        metadata = event.metadata if isinstance(event.metadata, dict) else {}

        speed_knots = metadata.get("speed_knots")
        if isinstance(speed_knots, (int, float)):
            telemetry["speed_knots"] = float(speed_knots)

        depth_m = metadata.get("depth_m")
        if isinstance(depth_m, (int, float)):
            telemetry["depth_m"] = float(depth_m)
        elif event.sentence_type.upper() in {"PSIMSSB", "PSIMSNS"}:
            telemetry.pop("depth_m", None)

        heading_deg = metadata.get("display_heading_deg")
        if isinstance(heading_deg, (int, float)):
            telemetry["heading_deg"] = float(heading_deg)

        heading_source = metadata.get("heading_source")
        if isinstance(heading_source, str) and heading_source.strip():
            telemetry["heading_source"] = heading_source.strip()

    def _apply_keep_center_for_feed(self, feed: FeedConfig, now: datetime) -> None:
        if self._project_transition_active:
            return

        coordinates = self._resolve_keep_center_coordinates(feed, now)
        if coordinates is None:
            return
        self._center_map_on(coordinates[0], coordinates[1])

    def _resolve_keep_center_coordinates(
        self,
        feed: FeedConfig,
        now: datetime,
    ) -> Optional[Tuple[float, float]]:
        if not self._keep_center_enabled:
            return None
        if self._keep_center_role == "group":
            return self._resolve_group_center(now)
        if self._keep_center_feed_id != feed.feed_id:
            return None

        vessel_id = (
            self._subfeed_layer_id(feed.feed_id, "vessel")
            if feed.split_subfeeds_enabled
            else feed.feed_id
        )
        vehicle_id = (
            self._subfeed_layer_id(feed.feed_id, "vehicle")
            if feed.split_subfeeds_enabled
            else feed.feed_id
        )

        if self._keep_center_role == "vehicle" and feed.split_subfeeds_enabled:
            if self._vehicle_position_recent(feed, now):
                vehicle_position = self._last_position_by_layer.get(vehicle_id)
                if vehicle_position is not None:
                    return vehicle_position[0], vehicle_position[1]

            vessel_position = self._last_position_by_layer.get(vessel_id)
            if vessel_position is not None:
                return vessel_position[0], vessel_position[1]

            vehicle_position = self._last_position_by_layer.get(vehicle_id)
            if vehicle_position is not None:
                return vehicle_position[0], vehicle_position[1]
            return None

        target_id = vessel_id if self._keep_center_role == "vessel" else vehicle_id
        target_position = self._last_position_by_layer.get(target_id)
        if target_position is None:
            return None
        return target_position[0], target_position[1]

    def _resolve_group_center(self, now: datetime) -> Optional[Tuple[float, float]]:
        if not self._keep_center_source_ids:
            return None

        points: List[Tuple[float, float]] = []
        for source_id in self._keep_center_source_ids:
            latest = self._last_position_by_layer.get(source_id)
            if latest is None:
                continue

            latitude, longitude, received_at = latest
            if not self._keep_center_source_recent(source_id, received_at, now):
                continue
            if not math.isfinite(latitude) or not math.isfinite(longitude):
                continue

            points.append((float(latitude), float(longitude)))

        if not points:
            return None

        latitude = sum(point[0] for point in points) / len(points)
        longitude = sum(point[1] for point in points) / len(points)
        return latitude, longitude

    def _keep_center_source_recent(
        self,
        source_id: str,
        received_at: datetime,
        now: datetime,
    ) -> bool:
        base_feed_id = str(source_id or "").split(":", 1)[0]
        feed = self._feeds.get(base_feed_id)
        max_age_sec = _GROUP_DEFAULT_MAX_AGE_SEC
        if feed is not None:
            max_age_sec = max(2, int(feed.stale_timeout_sec))

        age_sec = (now - received_at).total_seconds()
        return age_sec <= max_age_sec

    def _center_map_on(self, latitude: float, longitude: float) -> None:
        map_canvas_getter = getattr(self._iface, "mapCanvas", None)
        if not callable(map_canvas_getter):
            return

        canvas = map_canvas_getter()
        if canvas is None:
            return

        try:
            point = self._point_in_canvas_crs(canvas, float(longitude), float(latitude))
            if point is None:
                return
            canvas.setCenter(point)
            refresh = getattr(canvas, "refresh", None)
            if callable(refresh):
                refresh()
        except Exception:  # pragma: no cover - depends on QGIS runtime.
            return

    def _point_in_canvas_crs(
        self,
        canvas,
        longitude: float,
        latitude: float,
    ) -> Optional[QgsPointXY]:
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            return None

        source_point = QgsPointXY(longitude, latitude)
        source_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        target_crs = None
        map_settings_getter = getattr(canvas, "mapSettings", None)
        if callable(map_settings_getter):
            map_settings = map_settings_getter()
            destination_crs_getter = getattr(map_settings, "destinationCrs", None)
            if callable(destination_crs_getter):
                target_crs = destination_crs_getter()

        if target_crs is None:
            destination_crs_getter = getattr(canvas, "destinationCrs", None)
            if callable(destination_crs_getter):
                target_crs = destination_crs_getter()

        if target_crs is None or not target_crs.isValid():
            return source_point

        if target_crs.authid() == source_crs.authid():
            return source_point

        try:
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            transformed = transform.transform(source_point)
        except Exception:  # pragma: no cover - depends on QGIS runtime.
            return None

        if not math.isfinite(transformed.x()) or not math.isfinite(transformed.y()):
            return None
        return QgsPointXY(float(transformed.x()), float(transformed.y()))

    def _apply_vehicle_fallback_if_needed(
        self,
        feed: FeedConfig,
        vessel_event: PositionFixEvent,
    ) -> bool:
        if not feed.split_subfeeds_enabled:
            return False
        if not feed.vehicle_show_on_vessel_when_missing_position:
            return False
        if self._vehicle_position_recent(feed, vessel_event.received_at):
            return False
        return self._apply_vehicle_fallback(feed, vessel_event)

    def _vehicle_position_recent(self, feed: FeedConfig, now: datetime) -> bool:
        vehicle_ts = self._last_vehicle_fix_by_feed.get(feed.feed_id)
        if vehicle_ts is None:
            return False
        age_sec = (now - vehicle_ts).total_seconds()
        return age_sec <= max(1, feed.stale_timeout_sec)

    def _apply_vehicle_fallback(
        self,
        feed: FeedConfig,
        vessel_event: Optional[PositionFixEvent],
    ) -> bool:
        if not feed.split_subfeeds_enabled:
            return False
        if not feed.vehicle_show_on_vessel_when_missing_position:
            return False

        latitude: Optional[float] = None
        longitude: Optional[float] = None
        if (
            vessel_event is not None
            and vessel_event.valid
            and vessel_event.latitude is not None
            and vessel_event.longitude is not None
        ):
            latitude = float(vessel_event.latitude)
            longitude = float(vessel_event.longitude)
        else:
            vessel_layer_id = self._subfeed_layer_id(feed.feed_id, "vessel")
            position = self._last_position_by_layer.get(vessel_layer_id)
            if position is None:
                return False
            latitude, longitude = position[0], position[1]

        vehicle_render = self._render_feed(feed, "vehicle")
        fallback_event = PositionFixEvent(
            feed_id=feed.feed_id,
            raw_sentence=(vessel_event.raw_sentence if vessel_event is not None else "$FALLBACK"),
            sentence_type="FALLBACK",
            talker=None,
            latitude=latitude,
            longitude=longitude,
            valid=True,
            status_text="Fallback to vessel position",
            source="INTERNAL-FALLBACK",
            fix_time_utc=(vessel_event.fix_time_utc if vessel_event is not None else None),
        )

        heading_info = self._latest_heading.get(vehicle_render.feed_id)
        if heading_info is None:
            heading_info = self._latest_heading.get(self._subfeed_layer_id(feed.feed_id, "vessel"))
        if heading_info is not None:
            fallback_event.metadata["display_heading_deg"] = heading_info.get("heading_deg")
            fallback_event.metadata["heading_source"] = heading_info.get("source")
            fallback_event.metadata["heading_true"] = heading_info.get("is_true")

        track_depth_m: Optional[float] = None
        telemetry = self._telemetry_by_layer.get(vehicle_render.feed_id, {})
        depth_value = telemetry.get("depth_m")
        if isinstance(depth_value, (int, float)):
            track_depth_m = float(depth_value)

        self._layer_manager.upsert_position(
            vehicle_render,
            fallback_event,
            track_enabled=self._track_enabled_for_role(feed, "vehicle"),
            track_use_depth_3d=True,
            track_depth_m=track_depth_m,
        )
        self._remember_position(vehicle_render.feed_id, latitude, longitude, fallback_event.received_at)

        if not self._vehicle_fallback_active_by_feed.get(feed.feed_id, False):
            self._on_subfeed_status(
                feed,
                "vehicle",
                "info",
                self._role_prefix(feed, "vehicle")
                + "No vehicle position; showing vehicle at vessel position",
            )

        self._vehicle_fallback_active_by_feed[feed.feed_id] = True
        return True
