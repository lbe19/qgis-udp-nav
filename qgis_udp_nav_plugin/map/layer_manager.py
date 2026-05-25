from __future__ import annotations

import json
import hashlib
import html
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsFeature,
    QgsFillSymbol,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProperty,
    QgsProject,
    QgsSymbolLayer,
    QgsUnitTypes,
    QgsSvgMarkerSymbolLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..model.feed_config import FeedConfig
from ..model.events import PositionFixEvent

_OVERVIEW_ARROW_SCALE_THRESHOLD = 8189.0
_OVERVIEW_ARROW_SIZE_MM = 6.0
_ICON_STYLIZE_SCALE_THRESHOLD = 8189.0
_ICON_STYLIZE_SIZE_FACTOR = 2.8
_ICON_STYLIZE_MIN_DELTA = 1.8
_TRACK_MAX_POINTS = 8000
_TRACK_SMOOTHING_WINDOW = 5
_EARTH_RADIUS_M = 6371000.0
_TRACK_LINE_WIDTH_MM = 1.2
_SAVED_TRACK_LAYER_NAME = "UDP Nav - Saved Tracks"
_SAVED_TRACKS_FILENAME = "saved_tracks.geojson"
_SAVED_TRACK_COLOR_HEX = "#36454F"
_SAVED_TRACK_VESSEL_FALLBACK_HEX = "#8f5f3b"
_SAVED_TRACK_VEHICLE_FALLBACK_HEX = "#2f5f73"
_LAYER_TAG_KIND = "qgis_udp_nav_layer_kind"
_LAYER_TAG_FEED_ID = "qgis_udp_nav_feed_id"
_LAYER_KIND_LIVE = "live"
_LAYER_KIND_OVERVIEW = "overview"
_LAYER_KIND_TRACK = "track"


_TRACK_GEOMETRY_REBUILD_INTERVAL = 5


class LayerManager:
    def __init__(self) -> None:
        self._layers: Dict[str, QgsVectorLayer] = {}
        self._overview_layers: Dict[str, QgsVectorLayer] = {}
        self._track_layers: Dict[str, QgsVectorLayer] = {}
        self._track_points: Dict[str, List[Tuple[float, float, float]]] = {}
        self._track_lengths: Dict[str, Tuple[float, float]] = {}
        self._track_dimensions: Dict[str, str] = {}
        self._track_last_depth: Dict[str, float] = {}
        # Incremental track length state (Phase 1)
        self._track_origin: Dict[str, Tuple[float, float]] = {}
        self._track_local_xy: Dict[str, List[Tuple[float, float, float]]] = {}
        self._track_raw_length: Dict[str, float] = {}
        # Geometry rebuild throttle state (Phase 2)
        self._track_geometry_dirty: Dict[str, int] = {}
        # Speed gate: last accepted fix per feed (lat, lon, monotonic_ts)
        self._track_last_accepted: Dict[str, Tuple[float, float, float]] = {}
        # Live position feature ID cache (Phase 5)
        self._live_feature_id: Dict[str, int] = {}
        self._heading_by_feed: Dict[str, float] = {}
        self._position_by_feed: Dict[str, Tuple[float, float]] = {}
        self._saved_tracks_layer: Optional[QgsVectorLayer] = None
        self._saved_tracks_file_path: str = ""
        self._prune_svg_cache()

    @staticmethod
    def _prune_svg_cache(max_age_days: int = 7) -> None:
        cache_dir = os.path.join(tempfile.gettempdir(), "qgis_udp_nav_symbol_cache")
        if not os.path.isdir(cache_dir):
            return
        try:
            import time as _time
            cutoff = _time.time() - (max_age_days * 86400)
            for name in os.listdir(cache_dir):
                fpath = os.path.join(cache_dir, name)
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                except OSError:
                    pass
        except OSError:
            pass

    @staticmethod
    def _layer_id(layer: Optional[QgsVectorLayer]) -> str:
        if layer is None:
            return ""

        try:
            return str(layer.id() or "")
        except RuntimeError:
            return ""

    @staticmethod
    def _is_layer_alive(layer: Optional[QgsVectorLayer]) -> bool:
        layer_id = LayerManager._layer_id(layer)
        if not layer_id:
            return False

        if QgsProject.instance().mapLayer(layer_id) is None:
            return False

        try:
            return bool(layer.isValid())
        except RuntimeError:
            return False

    def _cached_layer(
        self,
        cache: Dict[str, QgsVectorLayer],
        cache_key: str,
    ) -> Optional[QgsVectorLayer]:
        layer = cache.get(cache_key)
        if self._is_layer_alive(layer):
            return layer

        cache.pop(cache_key, None)
        return None

    @staticmethod
    def _remove_layer_from_project(layer: Optional[QgsVectorLayer]) -> None:
        layer_id = LayerManager._layer_id(layer)
        if not layer_id:
            return

        project = QgsProject.instance()
        if project.mapLayer(layer_id) is None:
            return

        project.removeMapLayer(layer_id)

    def reset_project_layer_caches(self) -> None:
        self._layers.clear()
        self._overview_layers.clear()
        self._track_layers.clear()
        self._saved_tracks_layer = None

    def prune_dead_layer_caches(self) -> None:
        for cache_key in list(self._layers.keys()):
            self._cached_layer(self._layers, cache_key)

        for cache_key in list(self._overview_layers.keys()):
            self._cached_layer(self._overview_layers, cache_key)

        for cache_key in list(self._track_layers.keys()):
            self._cached_layer(self._track_layers, cache_key)

        if not self._is_layer_alive(self._saved_tracks_layer):
            self._saved_tracks_layer = None

    def upsert_position(
        self,
        feed: FeedConfig,
        event: PositionFixEvent,
        track_enabled: bool = False,
        track_use_depth_3d: bool = False,
        track_depth_m: Optional[float] = None,
    ) -> None:
        if event.latitude is None or event.longitude is None:
            return

        layer = self._ensure_layer(feed)
        provider = layer.dataProvider()

        self._position_by_feed[feed.feed_id] = (event.latitude, event.longitude)
        heading = event.metadata.get("display_heading_deg")
        heading_source = event.metadata.get("heading_source") or ""
        heading_value = float(heading) if isinstance(heading, (int, float)) else None

        if heading_value is not None:
            self._heading_by_feed[feed.feed_id] = self._normalize_heading(heading_value)

        if feed.symbol_mode in {"vessel", "vehicle"}:
            heading_for_shape = self._heading_by_feed.get(feed.feed_id, 0.0)
            if feed.symbol_mode == "vehicle":
                geometry = self._build_vehicle_geometry(
                    latitude=event.latitude,
                    longitude=event.longitude,
                    heading_deg=heading_for_shape,
                    vehicle_length_m=feed.vessel_length_m,
                    vehicle_width_m=feed.vessel_width_m,
                    gps_longitudinal_reference=feed.vessel_gps_longitudinal_reference,
                    gps_offset_from_reference_m=feed.vessel_gps_offset_from_reference_m,
                    gps_offset_starboard_m=feed.vessel_gps_offset_starboard_m,
                )
            else:
                geometry = self._build_vessel_geometry(
                    latitude=event.latitude,
                    longitude=event.longitude,
                    heading_deg=heading_for_shape,
                    vessel_length_m=feed.vessel_length_m,
                    vessel_width_m=feed.vessel_width_m,
                    gps_longitudinal_reference=feed.vessel_gps_longitudinal_reference,
                    gps_offset_from_reference_m=feed.vessel_gps_offset_from_reference_m,
                    gps_offset_starboard_m=feed.vessel_gps_offset_starboard_m,
                )
            heading_value = heading_for_shape
        else:
            geometry = QgsGeometry.fromPointXY(QgsPointXY(event.longitude, event.latitude))

        attributes = [
            feed.feed_id,
            feed.name,
            event.sentence_type,
            event.status_text,
            event.fix_time_utc or "",
            event.metadata.get("error_code") or "",
            event.received_at.isoformat(),
            heading_value,
            heading_source,
        ]

        cached_fid = self._live_feature_id.get(feed.feed_id)
        if cached_fid is not None:
            attr_map = {cached_fid: {i: v for i, v in enumerate(attributes)}}
            provider.changeGeometryValues({cached_fid: geometry})
            provider.changeAttributeValues(attr_map)
        else:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(geometry)
            feature.setAttributes(attributes)
            provider.addFeature(feature)
            self._live_feature_id[feed.feed_id] = feature.id()

        if feed.symbol_mode in {"vessel", "vehicle"}:
            overview_heading = self._heading_by_feed.get(feed.feed_id, 0.0)
            self._upsert_overview_marker(
                feed,
                event.latitude,
                event.longitude,
                overview_heading,
            )
        else:
            self._remove_overview_layer(feed.feed_id)

        if heading_value is not None and feed.symbol_mode not in {"vessel", "vehicle"}:
            self.update_heading(feed, heading_value)

        self._upsert_track(
            feed,
            event,
            track_enabled=track_enabled,
            track_use_depth_3d=track_use_depth_3d,
            track_depth_m=track_depth_m,
        )

        layer.updateExtents()
        layer.triggerRepaint()

    def update_style(self, feed: FeedConfig) -> None:
        layer = self._ensure_layer(feed)

        if feed.symbol_mode in {"vessel", "vehicle"}:
            self._refresh_vessel_geometry(feed)
            self._update_overview_style(feed)
        else:
            self._remove_overview_layer(feed.feed_id)

        layer.renderer().setSymbol(self._create_symbol(feed))
        layer.triggerRepaint()
        self._update_track_style(feed)

    def remove_feed(self, feed_id: str) -> None:
        layer = self._cached_layer(self._layers, feed_id)
        layer_name = layer.name() if layer is not None else ""
        self._layers.pop(feed_id, None)
        self._live_feature_id.pop(feed_id, None)
        self._remove_project_layers_for_feed(
            feed_id,
            _LAYER_KIND_LIVE,
            expected_name=layer_name,
        )
        self._remove_overview_layer(feed_id)
        self.clear_track(feed_id)
        self._heading_by_feed.pop(feed_id, None)
        self._position_by_feed.pop(feed_id, None)
        self._remove_layer_from_project(layer)

    def track_metrics(self, feed_id: str) -> Optional[dict]:
        lengths = self._track_lengths.get(feed_id)
        points = self._track_points.get(feed_id)
        if lengths is None or points is None:
            return None

        return {
            "raw_m": float(lengths[0]),
            "smoothed_m": float(lengths[1]),
            "dimension": self._track_dimensions.get(feed_id, "2d"),
            "point_count": len(points),
        }

    def track_snapshot(self, feed_id: str) -> Optional[dict]:
        lengths = self._track_lengths.get(feed_id)
        points = self._track_points.get(feed_id)
        if lengths is None or points is None or len(points) < 2:
            return None

        return {
            "feed_id": str(feed_id),
            "raw_m": float(lengths[0]),
            "smoothed_m": float(lengths[1]),
            "dimension": self._track_dimensions.get(feed_id, "2d"),
            "point_count": len(points),
            "points": [
                [float(latitude), float(longitude), float(depth_m)]
                for latitude, longitude, depth_m in points
            ],
        }

    def detach_track_snapshot(self, feed_id: str) -> Optional[dict]:
        layer = self._cached_layer(self._track_layers, feed_id)
        self._track_layers.pop(feed_id, None)

        points = self._track_points.pop(feed_id, None)
        lengths = self._track_lengths.pop(feed_id, None)
        dimension = self._track_dimensions.pop(feed_id, None)
        self._track_last_depth.pop(feed_id, None)
        self._track_origin.pop(feed_id, None)
        self._track_local_xy.pop(feed_id, None)
        self._track_raw_length.pop(feed_id, None)
        self._track_geometry_dirty.pop(feed_id, None)
        self._track_last_accepted.pop(feed_id, None)

        self._remove_layer_from_project(layer)

        if lengths is None or points is None or len(points) < 2:
            return None

        return {
            "feed_id": str(feed_id),
            "raw_m": float(lengths[0]),
            "smoothed_m": float(lengths[1]),
            "dimension": str(dimension or "2d"),
            "point_count": len(points),
            # Reuse existing tuples so UI toggle stays fast; conversion happens at write time.
            "points": points,
        }

    def save_tracks(
        self,
        entries: List[dict],
        planned_number: str,
        actual_number: str,
        refresh_saved_layer: bool = True,
    ) -> Tuple[int, str]:
        if not entries:
            return 0, ""

        file_path = self._saved_tracks_path()
        if not file_path:
            return 0, ""

        payload = self._load_saved_track_feature_collection(file_path)
        if payload is None:
            payload = {"type": "FeatureCollection", "features": []}

        features = payload.get("features")
        if not isinstance(features, list):
            features = []
            payload["features"] = features

        planned_text = str(planned_number or "").strip()
        actual_text = str(actual_number or "").strip()
        saved_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        added_count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            track = entry.get("track")
            if not isinstance(track, dict):
                continue

            points = track.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue

            dimension = str(track.get("dimension") or "2d").strip().lower()
            use_3d = dimension == "3d"

            coordinates: List[List[float]] = []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue

                latitude = point[0]
                longitude = point[1]
                depth_m = point[2] if len(point) > 2 else 0.0

                if not isinstance(latitude, (int, float)):
                    continue
                if not isinstance(longitude, (int, float)):
                    continue

                if use_3d and isinstance(depth_m, (int, float)):
                    coordinates.append([float(longitude), float(latitude), float(depth_m)])
                else:
                    coordinates.append([float(longitude), float(latitude)])

            if len(coordinates) < 2:
                continue

            raw_m = track.get("raw_m")
            smoothed_m = track.get("smoothed_m")
            point_count = track.get("point_count")
            role_text = str(entry.get("role") or "").strip().lower()
            base_color_hex = self._normalize_color_hex(
                str(entry.get("track_color_hex") or "").strip(),
                fallback=_SAVED_TRACK_COLOR_HEX,
            )
            saved_color_hex = self._saved_track_color_hex(base_color_hex)

            properties = {
                "saved_at_utc": saved_at_utc,
                "feed_id": str(entry.get("feed_id") or ""),
                "feed_name": str(entry.get("feed_name") or ""),
                "role": role_text,
                "track_layer_id": str(entry.get("track_layer_id") or ""),
                "track_dimension": "3d" if use_3d else "2d",
                "track_color_hex": base_color_hex,
                "saved_color_hex": saved_color_hex,
                "planned_number": planned_text,
                "actual_number": actual_text,
                "actual_raw_m": float(raw_m) if isinstance(raw_m, (int, float)) else None,
                "actual_smoothed_m": (
                    float(smoothed_m) if isinstance(smoothed_m, (int, float)) else None
                ),
                "point_count": int(point_count) if isinstance(point_count, (int, float)) else 0,
            }

            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates,
                    },
                    "properties": properties,
                }
            )
            added_count += 1

        if added_count <= 0:
            return 0, file_path

        if not self._write_saved_track_feature_collection(file_path, payload):
            # Windows can hold an exclusive lock while the OGR layer is loaded.
            self._release_saved_tracks_layer_locks(file_path)
            if not self._write_saved_track_feature_collection(file_path, payload):
                return 0, file_path

        if refresh_saved_layer:
            self._ensure_saved_tracks_layer(file_path)
        return added_count, file_path

    @staticmethod
    def _normalize_color_hex(color_hex: str, fallback: str) -> str:
        color = QColor(str(color_hex or "").strip())
        if color.isValid():
            return str(color.name())

        fallback_color = QColor(str(fallback or "").strip())
        if fallback_color.isValid():
            return str(fallback_color.name())
        return "#666666"

    @staticmethod
    def _saved_track_color_hex(base_color_hex: str) -> str:
        color = QColor(str(base_color_hex or "").strip())
        if not color.isValid():
            color = QColor(_SAVED_TRACK_COLOR_HEX)

        if color.lightnessF() <= 0.30:
            return str(color.lighter(120).name())
        return str(color.darker(145).name())

    @staticmethod
    def _is_saved_tracks_project_layer(layer: QgsVectorLayer, normalized_path: str) -> bool:
        marked = layer.customProperty("qgis_udp_nav_saved_tracks", 0)
        marked_text = str(marked).strip().lower()
        if marked_text in {"1", "true", "yes"}:
            return True

        try:
            source_path = os.path.normpath(layer.source().split("|", 1)[0])
        except Exception:
            return False
        return source_path == normalized_path

    def _release_saved_tracks_layer_locks(self, file_path: str) -> None:
        normalized_path = os.path.normpath(file_path)
        project = QgsProject.instance()
        layer_ids: List[str] = []

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not self._is_saved_tracks_project_layer(layer, normalized_path):
                continue

            layer_id = self._layer_id(layer)
            if layer_id:
                layer_ids.append(layer_id)

        for layer_id in layer_ids:
            if project.mapLayer(layer_id) is not None:
                project.removeMapLayer(layer_id)

        self._saved_tracks_layer = None

    def _saved_tracks_path(self) -> str:
        if self._saved_tracks_file_path:
            return self._saved_tracks_file_path

        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            output_dir = os.path.join(
                appdata,
                "QGIS",
                "QGIS4",
                "profiles",
                "default",
                "qgis_udp_nav_tracks",
            )
        else:
            output_dir = os.path.join(
                os.path.expanduser("~"),
                ".qgis_udp_nav_plugin",
                "saved_tracks",
            )

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError:
            return ""

        self._saved_tracks_file_path = os.path.join(output_dir, _SAVED_TRACKS_FILENAME)
        return self._saved_tracks_file_path

    @staticmethod
    def _load_saved_track_feature_collection(file_path: str) -> Optional[dict]:
        if not os.path.isfile(file_path):
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get("type") != "FeatureCollection":
            return None

        features = payload.get("features")
        if not isinstance(features, list):
            payload["features"] = []
        return payload

    @staticmethod
    def _write_saved_track_feature_collection(file_path: str, payload: dict) -> bool:
        temp_path = f"{file_path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            os.replace(temp_path, file_path)
        except OSError:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False
        return True

    def _ensure_saved_tracks_layer(self, file_path: str) -> None:
        existing = self._saved_tracks_layer
        if not self._is_layer_alive(existing):
            self._saved_tracks_layer = None
            existing = None

        if existing is not None:
            existing.reload()
            self._style_saved_tracks_layer(existing)
            existing.triggerRepaint()
            return

        normalized_path = os.path.normpath(file_path)
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            marked = layer.customProperty("qgis_udp_nav_saved_tracks", 0)
            marked_text = str(marked).strip().lower()
            if marked_text in {"1", "true", "yes"}:
                self._saved_tracks_layer = layer
                layer.reload()
                self._style_saved_tracks_layer(layer)
                layer.triggerRepaint()
                return

            try:
                source_path = os.path.normpath(layer.source().split("|", 1)[0])
            except Exception:
                continue

            if source_path == normalized_path:
                layer.setCustomProperty("qgis_udp_nav_saved_tracks", 1)
                self._saved_tracks_layer = layer
                layer.reload()
                self._style_saved_tracks_layer(layer)
                layer.triggerRepaint()
                return

        layer = QgsVectorLayer(file_path, _SAVED_TRACK_LAYER_NAME, "ogr")
        if not layer.isValid():
            return

        layer.setCustomProperty("qgis_udp_nav_saved_tracks", 1)
        project.addMapLayer(layer)
        self._saved_tracks_layer = layer
        self._style_saved_tracks_layer(layer)

    def refresh_saved_tracks_layer(self) -> None:
        file_path = self._saved_tracks_path()
        if not file_path or not os.path.isfile(file_path):
            return

        self._ensure_saved_tracks_layer(file_path)

    def _style_saved_tracks_layer(self, layer: QgsVectorLayer) -> None:
        renderer = layer.renderer()
        if renderer is None:
            return

        renderer.setSymbol(self._create_saved_track_symbol())

    def clear_track(self, feed_id: str) -> None:
        layer = self._cached_layer(self._track_layers, feed_id)
        layer_name = layer.name() if layer is not None else ""
        self._track_layers.pop(feed_id, None)
        self._track_points.pop(feed_id, None)
        self._track_lengths.pop(feed_id, None)
        self._track_dimensions.pop(feed_id, None)
        self._track_last_depth.pop(feed_id, None)
        self._track_origin.pop(feed_id, None)
        self._track_local_xy.pop(feed_id, None)
        self._track_raw_length.pop(feed_id, None)
        self._track_geometry_dirty.pop(feed_id, None)
        self._track_last_accepted.pop(feed_id, None)

        self._remove_project_layers_for_feed(
            feed_id,
            _LAYER_KIND_TRACK,
            expected_name=layer_name,
        )
        self._remove_layer_from_project(layer)

    def update_heading(self, feed: FeedConfig, heading_deg: float) -> None:
        layer = self._cached_layer(self._layers, feed.feed_id)
        normalized = self._normalize_heading(heading_deg)
        self._heading_by_feed[feed.feed_id] = normalized

        if layer is None:
            return

        if feed.symbol_mode in {"vessel", "vehicle"}:
            self._refresh_vessel_geometry(feed)
            self._update_overview_heading(feed.feed_id, normalized)
            layer.triggerRepaint()
            return

        self._apply_heading_to_layer(layer, normalized)
        layer.triggerRepaint()

    def clear(self) -> None:
        for feed_id in list(self._layers.keys()):
            self.remove_feed(feed_id)

        for feed_id in list(self._track_layers.keys()):
            self.clear_track(feed_id)

        # Remove any plugin memory layers left behind after cache resets.
        self._remove_all_plugin_ephemeral_layers()
        self._layers.clear()
        self._overview_layers.clear()
        self._track_layers.clear()
        self._track_points.clear()
        self._track_lengths.clear()
        self._track_dimensions.clear()
        self._track_last_depth.clear()
        self._track_origin.clear()
        self._track_local_xy.clear()
        self._track_raw_length.clear()
        self._track_geometry_dirty.clear()
        self._track_last_accepted.clear()
        self._live_feature_id.clear()
        self._heading_by_feed.clear()
        self._position_by_feed.clear()

    @staticmethod
    def _mark_ephemeral_layer(layer: QgsVectorLayer) -> None:
        # Prevent QGIS from prompting to save plugin-managed memory layers on exit.
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        layer.setCustomProperty("qgis_udp_nav_ephemeral", 1)

    @staticmethod
    def _tag_layer(layer: QgsVectorLayer, *, feed_id: str, layer_kind: str) -> None:
        layer.setCustomProperty(_LAYER_TAG_FEED_ID, str(feed_id or ""))
        layer.setCustomProperty(_LAYER_TAG_KIND, str(layer_kind or ""))

    @staticmethod
    def _is_plugin_ephemeral_layer(layer: QgsVectorLayer) -> bool:
        marked = layer.customProperty("qgis_udp_nav_ephemeral", 0)
        marked_text = str(marked).strip().lower()
        return marked_text in {"1", "true", "yes"}

    def _project_layers_for_feed(
        self,
        feed_id: str,
        layer_kind: str,
        expected_name: str = "",
    ) -> List[QgsVectorLayer]:
        feed_text = str(feed_id or "").strip()
        kind_text = str(layer_kind or "").strip().lower()
        expected_name_text = str(expected_name or "").strip()
        matches: List[QgsVectorLayer] = []

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            tagged_feed_id = str(layer.customProperty(_LAYER_TAG_FEED_ID, "") or "").strip()
            tagged_kind = str(layer.customProperty(_LAYER_TAG_KIND, "") or "").strip().lower()
            if tagged_feed_id == feed_text and tagged_kind == kind_text:
                matches.append(layer)
                continue

            if not expected_name_text or layer.name() != expected_name_text:
                continue
            if not self._is_plugin_ephemeral_layer(layer):
                continue
            matches.append(layer)

        return matches

    def _adopt_existing_project_layer(
        self,
        feed_id: str,
        layer_kind: str,
        expected_name: str,
    ) -> Optional[QgsVectorLayer]:
        matches = self._project_layers_for_feed(
            feed_id,
            layer_kind,
            expected_name=expected_name,
        )
        if not matches:
            return None

        adopted = matches[0]
        self._tag_layer(adopted, feed_id=feed_id, layer_kind=layer_kind)
        for duplicate in matches[1:]:
            self._remove_layer_from_project(duplicate)
        return adopted

    def _remove_project_layers_for_feed(
        self,
        feed_id: str,
        layer_kind: str,
        expected_name: str = "",
    ) -> None:
        for layer in self._project_layers_for_feed(
            feed_id,
            layer_kind,
            expected_name=expected_name,
        ):
            self._remove_layer_from_project(layer)

    def _remove_all_plugin_ephemeral_layers(self) -> None:
        for layer in list(QgsProject.instance().mapLayers().values()):
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not self._is_plugin_ephemeral_layer(layer):
                continue
            self._remove_layer_from_project(layer)

    def _ensure_layer(self, feed: FeedConfig) -> QgsVectorLayer:
        layer = self._cached_layer(self._layers, feed.feed_id)
        wants_polygon = feed.symbol_mode in {"vessel", "vehicle"}
        expected_name = f"UDP Nav - {feed.name}"

        if layer is not None:
            try:
                is_polygon = (
                    QgsWkbTypes.geometryType(layer.wkbType())
                    == QgsWkbTypes.PolygonGeometry
                )
            except RuntimeError:
                layer = None
                self._layers.pop(feed.feed_id, None)

            if layer is not None:
                if is_polygon == wants_polygon:
                    return layer

                self._remove_layer_from_project(layer)
                self._layers.pop(feed.feed_id, None)

        if layer is None:
            layer = self._adopt_existing_project_layer(
                feed.feed_id,
                _LAYER_KIND_LIVE,
                expected_name,
            )
            if layer is not None:
                try:
                    is_polygon = (
                        QgsWkbTypes.geometryType(layer.wkbType())
                        == QgsWkbTypes.PolygonGeometry
                    )
                except RuntimeError:
                    is_polygon = not wants_polygon

                if is_polygon != wants_polygon:
                    self._remove_layer_from_project(layer)
                    layer = None
                else:
                    layer.setName(expected_name)
                    layer.renderer().setSymbol(self._create_symbol(feed))
                    self._layers[feed.feed_id] = layer
                    return layer

        layer_uri = "Polygon?crs=EPSG:4326" if wants_polygon else "Point?crs=EPSG:4326"
        layer = QgsVectorLayer(layer_uri, expected_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("feed_id", QVariant.String),
                QgsField("feed_name", QVariant.String),
                QgsField("sentence", QVariant.String),
                QgsField("status", QVariant.String),
                QgsField("fix_time", QVariant.String),
                QgsField("message", QVariant.String),
                QgsField("updated_utc", QVariant.String),
                QgsField("heading_deg", QVariant.Double),
                QgsField("heading_src", QVariant.String),
            ]
        )
        layer.updateFields()

        layer.renderer().setSymbol(self._create_symbol(feed))
        self._mark_ephemeral_layer(layer)
        self._tag_layer(layer, feed_id=feed.feed_id, layer_kind=_LAYER_KIND_LIVE)
        QgsProject.instance().addMapLayer(layer)
        self._layers[feed.feed_id] = layer
        return layer

    def _create_symbol(self, feed: FeedConfig):
        if feed.symbol_mode in {"vessel", "vehicle"}:
            return QgsFillSymbol.createSimple(
                {
                    "color": feed.color_hex,
                    "outline_color": "#1f1f1f",
                    "outline_width": "0.4",
                    "outline_style": "solid",
                }
            )

        marker_name = feed.qgis_symbol_name or "circle"
        qgis_width = max(0.1, float(feed.qgis_symbol_width))
        qgis_height = max(0.1, float(feed.qgis_symbol_height))
        marker_base_size = max(qgis_width, qgis_height)
        render_unit = self._render_unit_for_feed(feed)
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": marker_name,
                "color": feed.color_hex,
                "size": f"{marker_base_size:.3f}",
                "outline_color": "#1f1f1f",
                "outline_width": "0.4",
            }
        )

        if feed.symbol_mode == "qgis":
            self._apply_qgis_marker_dimensions(
                symbol,
                qgis_width,
                qgis_height,
                render_unit=render_unit,
            )

        elif feed.symbol_mode == "icon_file":
            if feed.icon_path and feed.icon_path.lower().endswith(".svg"):
                svg_layer = QgsSvgMarkerSymbolLayer(feed.icon_path, 7.0)
                self._apply_svg_symbol_layer(
                    symbol,
                    svg_layer,
                    size=max(qgis_width, qgis_height),
                    render_unit=render_unit,
                    fill_color=feed.color_hex,
                )

        elif feed.symbol_mode == "unicode":
            unicode_svg = self._unicode_svg_path(feed)
            if unicode_svg is not None:
                svg_layer = QgsSvgMarkerSymbolLayer(unicode_svg, 7.0)
                self._apply_svg_symbol_layer(
                    symbol,
                    svg_layer,
                    size=max(qgis_width, qgis_height),
                    render_unit=render_unit,
                )

        heading = self._heading_by_feed.get(feed.feed_id)
        if heading is not None:
            self._apply_heading_to_symbol(symbol, heading)

        self._apply_marker_symbol_scaling(symbol, marker_base_size)

        return symbol

    def _ensure_overview_layer(self, feed: FeedConfig) -> QgsVectorLayer:
        layer = self._cached_layer(self._overview_layers, feed.feed_id)
        if layer is not None:
            return layer

        expected_name = f"UDP Nav - {feed.name} (overview)"
        layer = self._adopt_existing_project_layer(
            feed.feed_id,
            _LAYER_KIND_OVERVIEW,
            expected_name,
        )
        if layer is not None:
            layer.setName(expected_name)
            layer.renderer().setSymbol(self._create_overview_symbol(feed))
            self._overview_layers[feed.feed_id] = layer
            return layer

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            expected_name,
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("feed_id", QVariant.String),
                QgsField("feed_name", QVariant.String),
                QgsField("heading_deg", QVariant.Double),
            ]
        )
        layer.updateFields()

        layer.renderer().setSymbol(self._create_overview_symbol(feed))
        self._mark_ephemeral_layer(layer)
        self._tag_layer(layer, feed_id=feed.feed_id, layer_kind=_LAYER_KIND_OVERVIEW)
        QgsProject.instance().addMapLayer(layer, False)
        self._overview_layers[feed.feed_id] = layer
        return layer

    def _ensure_track_layer(self, feed: FeedConfig) -> QgsVectorLayer:
        layer = self._cached_layer(self._track_layers, feed.feed_id)
        if layer is not None:
            return layer

        expected_name = f"UDP Nav - {feed.name} (track)"
        layer = self._adopt_existing_project_layer(
            feed.feed_id,
            _LAYER_KIND_TRACK,
            expected_name,
        )
        if layer is not None:
            layer.setName(expected_name)
            layer.renderer().setSymbol(self._create_track_symbol(feed.color_hex))
            self._track_layers[feed.feed_id] = layer
            return layer

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            expected_name,
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("feed_id", QVariant.String),
                QgsField("feed_name", QVariant.String),
                QgsField("raw_m", QVariant.Double),
                QgsField("smooth_m", QVariant.Double),
                QgsField("dimension", QVariant.String),
                QgsField("point_count", QVariant.Int),
            ]
        )
        layer.updateFields()

        layer.renderer().setSymbol(self._create_track_symbol(feed.color_hex))
        self._mark_ephemeral_layer(layer)
        self._tag_layer(layer, feed_id=feed.feed_id, layer_kind=_LAYER_KIND_TRACK)
        QgsProject.instance().addMapLayer(layer)
        self._track_layers[feed.feed_id] = layer
        return layer

    def _remove_overview_layer(self, feed_id: str) -> None:
        layer = self._cached_layer(self._overview_layers, feed_id)
        layer_name = layer.name() if layer is not None else ""
        self._overview_layers.pop(feed_id, None)
        self._remove_project_layers_for_feed(
            feed_id,
            _LAYER_KIND_OVERVIEW,
            expected_name=layer_name,
        )
        self._remove_layer_from_project(layer)

    @staticmethod
    def _create_track_symbol(color_hex: str) -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple(
            {
                "color": str(color_hex or "#ff4500"),
                "width": f"{_TRACK_LINE_WIDTH_MM:.2f}",
            }
        )
        set_opacity = getattr(symbol, "setOpacity", None)
        if callable(set_opacity):
            set_opacity(0.85)
        return symbol

    @staticmethod
    def _create_saved_track_symbol() -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple(
            {
                "color": _SAVED_TRACK_COLOR_HEX,
                "width": f"{_TRACK_LINE_WIDTH_MM:.2f}",
            }
        )
        set_opacity = getattr(symbol, "setOpacity", None)
        if callable(set_opacity):
            set_opacity(0.95)

        symbol_layer = symbol.symbolLayer(0)
        set_property = getattr(symbol_layer, "setDataDefinedProperty", None)
        color_property = LayerManager._symbol_property("PropertyStrokeColor")
        if color_property is None:
            color_property = LayerManager._symbol_property("PropertyColor")
        if symbol_layer is not None and color_property is not None and callable(set_property):
            expression = (
                f'coalesce("saved_color_hex", '
                "CASE "
                f'WHEN lower("role") = \'vehicle\' THEN \'{_SAVED_TRACK_VEHICLE_FALLBACK_HEX}\' '
                f'WHEN lower("role") = \'vessel\' THEN \'{_SAVED_TRACK_VESSEL_FALLBACK_HEX}\' '
                f"ELSE '{_SAVED_TRACK_COLOR_HEX}' END)"
            )
            set_property(color_property, QgsProperty.fromExpression(expression))

        return symbol

    def _update_track_style(self, feed: FeedConfig) -> None:
        layer = self._cached_layer(self._track_layers, feed.feed_id)
        if layer is None:
            return

        layer.setName(f"UDP Nav - {feed.name} (track)")
        layer.renderer().setSymbol(self._create_track_symbol(feed.color_hex))
        layer.triggerRepaint()

    def _upsert_track(
        self,
        feed: FeedConfig,
        event: PositionFixEvent,
        track_enabled: bool,
        track_use_depth_3d: bool,
        track_depth_m: Optional[float],
    ) -> None:
        if not track_enabled:
            return

        latitude = event.latitude
        longitude = event.longitude
        if latitude is None or longitude is None:
            return

        depth_m = self._resolve_track_depth(
            feed.feed_id,
            track_use_depth_3d,
            track_depth_m,
        )

        feed_id = feed.feed_id

        # --- Speed gate: reject implausible jumps (e.g. HiPAP fallout) ---
        if not self._passes_speed_gate(feed, latitude, longitude):
            return

        points = self._track_points.setdefault(feed_id, [])
        points.append((float(latitude), float(longitude), depth_m))

        # --- Incremental local-XY and raw length (Phase 1) ---
        origin = self._track_origin.get(feed_id)
        local_xy = self._track_local_xy.setdefault(feed_id, [])

        if origin is None:
            origin = (float(latitude), float(longitude))
            self._track_origin[feed_id] = origin
            local_xy.clear()
            self._track_raw_length[feed_id] = 0.0

        z_m = float(depth_m) if track_use_depth_3d else 0.0
        x_m, y_m = self._latlon_to_local_xy(origin[0], origin[1], latitude, longitude)
        local_xy.append((x_m, y_m, z_m))

        # Add new segment length to running total
        raw_length = self._track_raw_length.get(feed_id, 0.0)
        if len(local_xy) >= 2:
            prev = local_xy[-2]
            dx = x_m - prev[0]
            dy = y_m - prev[1]
            dz = (z_m - prev[2]) if track_use_depth_3d else 0.0
            raw_length += math.sqrt(dx * dx + dy * dy + dz * dz)

        # FIFO trim - subtract removed segment from raw length
        if len(points) > _TRACK_MAX_POINTS:
            trim_count = len(points) - _TRACK_MAX_POINTS
            for i in range(trim_count):
                if len(local_xy) > 1:
                    p0 = local_xy[0]
                    p1 = local_xy[1]
                    dx = p1[0] - p0[0]
                    dy = p1[1] - p0[1]
                    dz = (p1[2] - p0[2]) if track_use_depth_3d else 0.0
                    raw_length -= math.sqrt(dx * dx + dy * dy + dz * dz)
                    raw_length = max(0.0, raw_length)
                del local_xy[0]
            del points[:trim_count]

        self._track_raw_length[feed_id] = raw_length
        self._track_last_accepted[feed_id] = (float(latitude), float(longitude), time.monotonic())

        # Smoothed length from cached local XY
        smoothed_length_m = self._compute_smoothed_length(local_xy, track_use_depth_3d)

        self._track_lengths[feed_id] = (raw_length, smoothed_length_m)
        self._track_dimensions[feed_id] = "3d" if track_use_depth_3d else "2d"

        # --- Geometry rebuild throttle (Phase 2) ---
        dirty = self._track_geometry_dirty.get(feed_id, 0) + 1
        self._track_geometry_dirty[feed_id] = dirty

        if dirty < _TRACK_GEOMETRY_REBUILD_INTERVAL and len(points) >= 10:
            return

        self._track_geometry_dirty[feed_id] = 0
        self._rebuild_track_geometry(feed, points, raw_length, smoothed_length_m)

    def _passes_speed_gate(
        self, feed: "FeedConfig", latitude: float, longitude: float
    ) -> bool:
        max_speed = feed.track_max_speed_ms
        if max_speed <= 0.0:
            return True  # Gate disabled

        feed_id = feed.feed_id
        prev = self._track_last_accepted.get(feed_id)
        if prev is None:
            # First fix — always accept
            self._track_last_accepted[feed_id] = (
                float(latitude), float(longitude), time.monotonic()
            )
            return True

        prev_lat, prev_lon, prev_ts = prev
        now = time.monotonic()
        dt = now - prev_ts
        if dt < 0.01:
            return True  # Near-simultaneous — accept

        dist_m = self._equirect_distance_m(prev_lat, prev_lon, latitude, longitude)
        speed = dist_m / dt
        return speed <= max_speed

    @staticmethod
    def _equirect_distance_m(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        mean_lat = math.radians((float(lat1) + float(lat2)) / 2.0)
        dx = (float(lon2) - float(lon1)) * 111320.0 * math.cos(mean_lat)
        dy = (float(lat2) - float(lat1)) * 111320.0
        return math.sqrt(dx * dx + dy * dy)

    def _rebuild_track_geometry(
        self,
        feed: FeedConfig,
        points: "List[Tuple[float, float, float]]",
        raw_length_m: float,
        smoothed_length_m: float,
    ) -> None:
        layer = self._ensure_track_layer(feed)
        provider = layer.dataProvider()
        existing_ids = [feature.id() for feature in layer.getFeatures()]
        if existing_ids:
            provider.deleteFeatures(existing_ids)

        if len(points) >= 2:
            feature = QgsFeature(layer.fields())
            line = [QgsPointXY(lon, lat) for lat, lon, _depth in points]
            feature.setGeometry(QgsGeometry.fromPolylineXY(line))
            feature.setAttributes(
                [
                    feed.feed_id,
                    feed.name,
                    float(raw_length_m),
                    float(smoothed_length_m),
                    self._track_dimensions.get(feed.feed_id, "2d"),
                    len(points),
                ]
            )
            provider.addFeature(feature)

        layer.updateExtents()
        layer.triggerRepaint()

    def _compute_smoothed_length(
        self,
        local_xy: "List[Tuple[float, float, float]]",
        use_depth_3d: bool,
    ) -> float:
        if len(local_xy) < 2:
            return 0.0
        smoothed = self._smooth_xyz(local_xy, _TRACK_SMOOTHING_WINDOW)
        return self._polyline_length(smoothed, use_depth_3d)

    def _resolve_track_depth(
        self,
        feed_id: str,
        use_depth_3d: bool,
        track_depth_m: Optional[float],
    ) -> float:
        if not use_depth_3d:
            return 0.0

        if isinstance(track_depth_m, (int, float)) and math.isfinite(float(track_depth_m)):
            depth_m = float(track_depth_m)
            self._track_last_depth[feed_id] = depth_m
            return depth_m

        previous_depth = self._track_last_depth.get(feed_id)
        if isinstance(previous_depth, (int, float)):
            return float(previous_depth)
        return 0.0

    @staticmethod
    def _calculate_track_lengths(
        points: List[Tuple[float, float, float]],
        use_depth_3d: bool,
    ) -> Tuple[float, float]:
        if len(points) < 2:
            return 0.0, 0.0

        lat0 = points[0][0]
        lon0 = points[0][1]
        xyz_points: List[Tuple[float, float, float]] = []
        for latitude, longitude, depth_m in points:
            x_m, y_m = LayerManager._latlon_to_local_xy(lat0, lon0, latitude, longitude)
            z_m = float(depth_m) if use_depth_3d else 0.0
            xyz_points.append((x_m, y_m, z_m))

        raw_length = LayerManager._polyline_length(xyz_points, use_depth_3d)
        smoothed_points = LayerManager._smooth_xyz(xyz_points, _TRACK_SMOOTHING_WINDOW)
        smoothed_length = LayerManager._polyline_length(smoothed_points, use_depth_3d)
        return raw_length, smoothed_length

    @staticmethod
    def _latlon_to_local_xy(
        origin_lat: float,
        origin_lon: float,
        latitude: float,
        longitude: float,
    ) -> Tuple[float, float]:
        delta_lat = math.radians(float(latitude) - float(origin_lat))
        delta_lon = math.radians(float(longitude) - float(origin_lon))
        x_m = _EARTH_RADIUS_M * delta_lon * math.cos(math.radians(float(origin_lat)))
        y_m = _EARTH_RADIUS_M * delta_lat
        return x_m, y_m

    @staticmethod
    def _polyline_length(points: List[Tuple[float, float, float]], use_depth_3d: bool) -> float:
        if len(points) < 2:
            return 0.0

        total = 0.0
        for index in range(1, len(points)):
            x0, y0, z0 = points[index - 1]
            x1, y1, z1 = points[index]
            dx = x1 - x0
            dy = y1 - y0
            dz = (z1 - z0) if use_depth_3d else 0.0
            total += math.sqrt((dx * dx) + (dy * dy) + (dz * dz))

        return total

    @staticmethod
    def _smooth_xyz(
        points: List[Tuple[float, float, float]],
        window_size: int,
    ) -> List[Tuple[float, float, float]]:
        if len(points) <= 2:
            return list(points)

        size = max(1, int(window_size))
        if size <= 1:
            return list(points)

        half_window = size // 2
        smoothed: List[Tuple[float, float, float]] = []
        for index in range(len(points)):
            start = max(0, index - half_window)
            end = min(len(points), index + half_window + 1)
            subset = points[start:end]
            count = float(len(subset))

            avg_x = sum(point[0] for point in subset) / count
            avg_y = sum(point[1] for point in subset) / count
            avg_z = sum(point[2] for point in subset) / count
            smoothed.append((avg_x, avg_y, avg_z))

        return smoothed

    def _upsert_overview_marker(
        self,
        feed: FeedConfig,
        latitude: float,
        longitude: float,
        heading_deg: float,
    ) -> None:
        layer = self._ensure_overview_layer(feed)
        provider = layer.dataProvider()

        existing_ids = [feature.id() for feature in layer.getFeatures()]
        if existing_ids:
            provider.deleteFeatures(existing_ids)

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude)))
        feature.setAttributes([feed.feed_id, feed.name, float(heading_deg)])
        provider.addFeature(feature)

        self._update_overview_heading(feed.feed_id, heading_deg)
        layer.updateExtents()
        layer.triggerRepaint()

    def _update_overview_style(self, feed: FeedConfig) -> None:
        layer = self._ensure_overview_layer(feed)
        layer.renderer().setSymbol(self._create_overview_symbol(feed))
        heading = self._heading_by_feed.get(feed.feed_id)
        if heading is not None:
            self._update_overview_heading(feed.feed_id, heading)
        layer.triggerRepaint()

    def _update_overview_heading(self, feed_id: str, heading_deg: float) -> None:
        layer = self._cached_layer(self._overview_layers, feed_id)
        if layer is None:
            return
        self._apply_heading_to_layer(layer, heading_deg)

    def _create_overview_symbol(self, feed: FeedConfig) -> QgsMarkerSymbol:
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "arrow",
                "color": feed.color_hex,
                "size": f"{_OVERVIEW_ARROW_SIZE_MM:.2f}",
                "outline_color": "#1f1f1f",
                "outline_width": "0.2",
            }
        )

        render_unit = self._render_unit("RenderMillimeters")
        set_symbol_output_unit = getattr(symbol, "setOutputUnit", None)
        if callable(set_symbol_output_unit):
            set_symbol_output_unit(render_unit)

        set_symbol_size_unit = getattr(symbol, "setSizeUnit", None)
        if callable(set_symbol_size_unit):
            set_symbol_size_unit(render_unit)

        symbol_layer = symbol.symbolLayer(0)
        if symbol_layer is not None:
            set_output_unit = getattr(symbol_layer, "setOutputUnit", None)
            if callable(set_output_unit):
                set_output_unit(render_unit)

            set_size_unit = getattr(symbol_layer, "setSizeUnit", None)
            if callable(set_size_unit):
                set_size_unit(render_unit)

            size_property = self._symbol_property("PropertySize")
            set_property = getattr(symbol_layer, "setDataDefinedProperty", None)
            if size_property is not None and callable(set_property):
                expression = (
                    "CASE "
                    f"WHEN @map_scale > {_OVERVIEW_ARROW_SCALE_THRESHOLD:.0f} "
                    f"THEN {_OVERVIEW_ARROW_SIZE_MM:.2f} "
                    "ELSE 0 "
                    "END"
                )
                set_property(size_property, QgsProperty.fromExpression(expression))

        heading = self._heading_by_feed.get(feed.feed_id)
        if heading is not None:
            self._apply_heading_to_symbol(symbol, heading)

        return symbol

    @staticmethod
    def _apply_heading_to_layer(layer: QgsVectorLayer, heading_deg: float) -> None:
        renderer = layer.renderer()
        if renderer is None:
            return

        symbol = renderer.symbol()
        if symbol is None:
            return

        LayerManager._apply_heading_to_symbol(symbol, heading_deg)

    @staticmethod
    def _apply_heading_to_symbol(symbol, heading_deg: float) -> None:
        if hasattr(symbol, "setAngle"):
            try:
                symbol.setAngle(float(heading_deg))
            except (TypeError, ValueError):
                return

    @staticmethod
    def _normalize_heading(value: float) -> float:
        heading = float(value) % 360.0
        if heading < 0:
            heading += 360.0
        return heading

    def _refresh_vessel_geometry(self, feed: FeedConfig) -> None:
        layer = self._cached_layer(self._layers, feed.feed_id)
        position = self._position_by_feed.get(feed.feed_id)
        if layer is None or position is None:
            return

        heading = self._heading_by_feed.get(feed.feed_id, 0.0)
        if feed.symbol_mode == "vehicle":
            geometry = self._build_vehicle_geometry(
                latitude=position[0],
                longitude=position[1],
                heading_deg=heading,
                vehicle_length_m=feed.vessel_length_m,
                vehicle_width_m=feed.vessel_width_m,
                gps_longitudinal_reference=feed.vessel_gps_longitudinal_reference,
                gps_offset_from_reference_m=feed.vessel_gps_offset_from_reference_m,
                gps_offset_starboard_m=feed.vessel_gps_offset_starboard_m,
            )
        else:
            geometry = self._build_vessel_geometry(
                latitude=position[0],
                longitude=position[1],
                heading_deg=heading,
                vessel_length_m=feed.vessel_length_m,
                vessel_width_m=feed.vessel_width_m,
                gps_longitudinal_reference=feed.vessel_gps_longitudinal_reference,
                gps_offset_from_reference_m=feed.vessel_gps_offset_from_reference_m,
                gps_offset_starboard_m=feed.vessel_gps_offset_starboard_m,
            )

        provider = layer.dataProvider()
        changes = {}
        for feature in layer.getFeatures():
            changes[feature.id()] = geometry

        if changes:
            provider.changeGeometryValues(changes)

    def _build_vessel_geometry(
        self,
        latitude: float,
        longitude: float,
        heading_deg: float,
        vessel_length_m: float,
        vessel_width_m: float,
        gps_longitudinal_reference: str,
        gps_offset_from_reference_m: float,
        gps_offset_starboard_m: float,
    ) -> QgsGeometry:
        length = max(0.05, float(vessel_length_m))
        width = max(0.05, float(vessel_width_m))
        gps_forward_m = self._gps_forward_from_reference(
            length,
            gps_longitudinal_reference,
            gps_offset_from_reference_m,
        )

        # Input position is the GNSS antenna location. Shift to vessel center.
        center_east_m, center_north_m = self._forward_starboard_to_offsets(
            heading_deg,
            -gps_forward_m,
            -float(gps_offset_starboard_m),
        )
        center_latitude, center_longitude = self._offset_to_wgs84(
            latitude,
            longitude,
            center_east_m,
            center_north_m,
        )

        half_length = length / 2.0
        half_width = width / 2.0

        bow_length = max(length * 0.28, min(length * 0.45, width))
        bow_base = half_length - bow_length

        local_points = [
            (-half_length, -half_width),
            (bow_base, -half_width),
            (half_length, 0.0),
            (bow_base, half_width),
            (-half_length, half_width),
            (-half_length, -half_width),
        ]

        ring = []
        for forward_m, starboard_m in local_points:
            east_m, north_m = self._forward_starboard_to_offsets(
                heading_deg,
                forward_m,
                starboard_m,
            )
            lat, lon = self._offset_to_wgs84(
                center_latitude,
                center_longitude,
                east_m,
                north_m,
            )
            ring.append(QgsPointXY(lon, lat))

        return QgsGeometry.fromPolygonXY([ring])

    def _build_vehicle_geometry(
        self,
        latitude: float,
        longitude: float,
        heading_deg: float,
        vehicle_length_m: float,
        vehicle_width_m: float,
        gps_longitudinal_reference: str,
        gps_offset_from_reference_m: float,
        gps_offset_starboard_m: float,
    ) -> QgsGeometry:
        length = max(0.05, float(vehicle_length_m))
        width = max(0.05, float(vehicle_width_m))
        gps_forward_m = self._gps_forward_from_reference(
            length,
            gps_longitudinal_reference,
            gps_offset_from_reference_m,
        )

        center_east_m, center_north_m = self._forward_starboard_to_offsets(
            heading_deg,
            -gps_forward_m,
            -float(gps_offset_starboard_m),
        )
        center_latitude, center_longitude = self._offset_to_wgs84(
            latitude,
            longitude,
            center_east_m,
            center_north_m,
        )

        half_length = length / 2.0
        half_width = width / 2.0
        local_points = [
            (-half_length, -half_width),
            (half_length, -half_width),
            (half_length, half_width),
            (-half_length, half_width),
            (-half_length, -half_width),
        ]

        ring = []
        for forward_m, starboard_m in local_points:
            east_m, north_m = self._forward_starboard_to_offsets(
                heading_deg,
                forward_m,
                starboard_m,
            )
            lat, lon = self._offset_to_wgs84(
                center_latitude,
                center_longitude,
                east_m,
                north_m,
            )
            ring.append(QgsPointXY(lon, lat))

        return QgsGeometry.fromPolygonXY([ring])

    @staticmethod
    def _gps_forward_from_reference(
        vessel_length_m: float,
        reference: str,
        offset_from_reference_m: float,
    ) -> float:
        half_length = max(0.05, float(vessel_length_m)) / 2.0
        offset = max(0.0, float(offset_from_reference_m))
        if str(reference).strip().lower() == "stern":
            return (-half_length) + offset
        return half_length - offset

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

    @staticmethod
    def _offset_to_wgs84(
        latitude: float,
        longitude: float,
        east_m: float,
        north_m: float,
    ) -> Tuple[float, float]:
        lat = latitude + (north_m / 111320.0)
        cos_lat = math.cos(math.radians(latitude))
        if abs(cos_lat) < 1e-9:
            cos_lat = 1e-9
        lon = longitude + (east_m / (111320.0 * cos_lat))
        return lat, lon

    @staticmethod
    def _apply_svg_symbol_layer(
        symbol: QgsMarkerSymbol,
        svg_layer: QgsSvgMarkerSymbolLayer,
        size: float,
        render_unit,
        fill_color: Optional[str] = None,
    ) -> None:
        if not LayerManager._svg_layer_is_usable(svg_layer):
            return

        base_size = max(0.1, float(size))

        set_size = getattr(svg_layer, "setSize", None)
        if callable(set_size):
            set_size(base_size)

        set_output_unit = getattr(svg_layer, "setOutputUnit", None)
        if callable(set_output_unit):
            set_output_unit(render_unit)

        set_size_unit = getattr(svg_layer, "setSizeUnit", None)
        if callable(set_size_unit):
            set_size_unit(render_unit)

        if fill_color:
            set_fill_color = getattr(svg_layer, "setFillColor", None)
            if callable(set_fill_color):
                try:
                    set_fill_color(QColor(fill_color))
                except (TypeError, ValueError):
                    pass

        try:
            symbol.changeSymbolLayer(0, svg_layer)
        except (TypeError, ValueError):
            return

        size_property = LayerManager._symbol_property("PropertySize")
        set_property = getattr(svg_layer, "setDataDefinedProperty", None)
        if size_property is not None and callable(set_property):
            set_property(
                size_property,
                QgsProperty.fromExpression(
                    LayerManager._stylized_size_expression(base_size)
                ),
            )

    @staticmethod
    def _svg_layer_is_usable(svg_layer: QgsSvgMarkerSymbolLayer) -> bool:
        is_valid = getattr(svg_layer, "isValid", None)
        if callable(is_valid):
            try:
                return bool(is_valid())
            except TypeError:
                return True

        # QGIS 4 builds may not expose isValid() on this class.
        return True

    @staticmethod
    def _apply_qgis_marker_dimensions(
        symbol: QgsMarkerSymbol,
        width: float,
        height: float,
        render_unit,
    ) -> None:
        set_symbol_output_unit = getattr(symbol, "setOutputUnit", None)
        if callable(set_symbol_output_unit):
            set_symbol_output_unit(render_unit)

        set_symbol_size_unit = getattr(symbol, "setSizeUnit", None)
        if callable(set_symbol_size_unit):
            set_symbol_size_unit(render_unit)

        symbol_layer = symbol.symbolLayer(0)
        if symbol_layer is None:
            return

        set_output_unit = getattr(symbol_layer, "setOutputUnit", None)
        if callable(set_output_unit):
            set_output_unit(render_unit)

        set_size_unit = getattr(symbol_layer, "setSizeUnit", None)
        if callable(set_size_unit):
            set_size_unit(render_unit)

        width_property = LayerManager._symbol_property("PropertyWidth")
        height_property = LayerManager._symbol_property("PropertyHeight")

        set_property = getattr(symbol_layer, "setDataDefinedProperty", None)
        if not callable(set_property):
            return

        width_expression = LayerManager._stylized_size_expression(float(width))
        height_expression = LayerManager._stylized_size_expression(float(height))

        if width_property is not None and height_property is not None:
            set_property(width_property, QgsProperty.fromExpression(width_expression))
            set_property(height_property, QgsProperty.fromExpression(height_expression))
            return

        size_property = LayerManager._symbol_property("PropertySize")
        if size_property is None:
            return

        fallback_size = max(float(width), float(height))
        set_property(
            size_property,
            QgsProperty.fromExpression(
                LayerManager._stylized_size_expression(fallback_size)
            ),
        )

    @staticmethod
    def _apply_marker_symbol_scaling(symbol: QgsMarkerSymbol, base_size: float) -> None:
        expression = LayerManager._stylized_size_expression(base_size)

        set_data_defined_size = getattr(symbol, "setDataDefinedSize", None)
        if callable(set_data_defined_size):
            try:
                set_data_defined_size(QgsProperty.fromExpression(expression))
                return
            except TypeError:
                pass

        symbol_layer = symbol.symbolLayer(0)
        if symbol_layer is None:
            return

        size_property = LayerManager._symbol_property("PropertySize")
        set_property = getattr(symbol_layer, "setDataDefinedProperty", None)
        if size_property is not None and callable(set_property):
            set_property(size_property, QgsProperty.fromExpression(expression))

    @staticmethod
    def _stylized_size_expression(base_size: float) -> str:
        true_size = max(0.1, float(base_size))
        stylized_size = max(
            true_size * _ICON_STYLIZE_SIZE_FACTOR,
            true_size + _ICON_STYLIZE_MIN_DELTA,
        )
        return (
            "CASE "
            f"WHEN @map_scale > {_ICON_STYLIZE_SCALE_THRESHOLD:.0f} "
            f"THEN {stylized_size:.3f} "
            f"ELSE {true_size:.3f} "
            "END"
        )

    @staticmethod
    def _render_unit_for_feed(feed: FeedConfig):
        if feed.qgis_size_unit == "map_meters":
            return LayerManager._render_unit("RenderMetersInMapUnits")
        return LayerManager._render_unit("RenderMillimeters")

    @staticmethod
    def _symbol_property(name: str):
        enum_cls = getattr(QgsSymbolLayer, "Property", None)
        if enum_cls is not None and hasattr(enum_cls, name):
            return getattr(enum_cls, name)
        return getattr(QgsSymbolLayer, name, None)

    @staticmethod
    def _render_unit(name: str):
        enum_cls = getattr(QgsUnitTypes, "RenderUnit", None)
        if enum_cls is not None and hasattr(enum_cls, name):
            return getattr(enum_cls, name)
        return getattr(QgsUnitTypes, name)

    @staticmethod
    def _unicode_svg_path(feed: FeedConfig) -> Optional[str]:
        symbol_char = feed.unicode_symbol or "\u2693"
        font_family = feed.unicode_font_family or "Noto Sans Symbols 2"

        signature = f"{symbol_char}|{font_family}|{feed.color_hex}"
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]

        cache_dir = os.path.join(tempfile.gettempdir(), "qgis_udp_nav_symbol_cache")
        os.makedirs(cache_dir, exist_ok=True)

        svg_path = os.path.join(cache_dir, f"unicode_{digest}.svg")
        if os.path.exists(svg_path):
            return svg_path

        text_value = html.escape(symbol_char)
        # Fallback font family sequence includes open fonts and common system symbol fonts.
        font_css = html.escape(
            f"{font_family}, Noto Sans Symbols 2, Noto Emoji, DejaVu Sans, Segoe UI Symbol"
        )
        color = html.escape(feed.color_hex)

        svg_content = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"128\" height=\"128\" viewBox=\"0 0 128 128\">\n"
            "  <rect x=\"0\" y=\"0\" width=\"128\" height=\"128\" fill=\"none\"/>\n"
            f"  <text x=\"64\" y=\"92\" text-anchor=\"middle\" font-size=\"92\" font-family=\"{font_css}\" fill=\"{color}\">{text_value}</text>\n"
            "</svg>\n"
        )

        try:
            with open(svg_path, "w", encoding="utf-8") as handle:
                handle.write(svg_content)
        except OSError:
            return None

        return svg_path
