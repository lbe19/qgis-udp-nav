from __future__ import annotations

import json
import hashlib
import html
import math
import os
import tempfile
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

_OVERVIEW_ARROW_SCALE_THRESHOLD = 25000.0
_OVERVIEW_ARROW_SIZE_MM = 4.0
_TRACK_MAX_POINTS = 8000
_TRACK_SMOOTHING_WINDOW = 5
_EARTH_RADIUS_M = 6371000.0
_SAVED_TRACK_LAYER_NAME = "UDP Nav - Saved Tracks"
_SAVED_TRACKS_FILENAME = "saved_tracks.geojson"


class LayerManager:
    def __init__(self) -> None:
        self._layers: Dict[str, QgsVectorLayer] = {}
        self._overview_layers: Dict[str, QgsVectorLayer] = {}
        self._track_layers: Dict[str, QgsVectorLayer] = {}
        self._track_points: Dict[str, List[Tuple[float, float, float]]] = {}
        self._track_lengths: Dict[str, Tuple[float, float]] = {}
        self._track_dimensions: Dict[str, str] = {}
        self._track_last_depth: Dict[str, float] = {}
        self._heading_by_feed: Dict[str, float] = {}
        self._position_by_feed: Dict[str, Tuple[float, float]] = {}
        self._saved_tracks_layer: Optional[QgsVectorLayer] = None
        self._saved_tracks_file_path: str = ""

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

        existing_ids = [feature.id() for feature in layer.getFeatures()]
        if existing_ids:
            provider.deleteFeatures(existing_ids)

        feature = QgsFeature(layer.fields())
        self._position_by_feed[feed.feed_id] = (event.latitude, event.longitude)
        heading = event.metadata.get("display_heading_deg")
        heading_source = event.metadata.get("heading_source") or ""
        heading_value = float(heading) if isinstance(heading, (int, float)) else None

        if heading_value is not None:
            self._heading_by_feed[feed.feed_id] = self._normalize_heading(heading_value)

        if feed.symbol_mode in {"vessel", "vehicle"}:
            heading_for_shape = self._heading_by_feed.get(feed.feed_id, 0.0)
            if feed.symbol_mode == "vehicle":
                feature.setGeometry(
                    self._build_vehicle_geometry(
                        latitude=event.latitude,
                        longitude=event.longitude,
                        heading_deg=heading_for_shape,
                        vehicle_length_m=feed.vessel_length_m,
                        vehicle_width_m=feed.vessel_width_m,
                        gps_longitudinal_reference=feed.vessel_gps_longitudinal_reference,
                        gps_offset_from_reference_m=feed.vessel_gps_offset_from_reference_m,
                        gps_offset_starboard_m=feed.vessel_gps_offset_starboard_m,
                    )
                )
            else:
                feature.setGeometry(
                    self._build_vessel_geometry(
                        latitude=event.latitude,
                        longitude=event.longitude,
                        heading_deg=heading_for_shape,
                        vessel_length_m=feed.vessel_length_m,
                        vessel_width_m=feed.vessel_width_m,
                        gps_longitudinal_reference=feed.vessel_gps_longitudinal_reference,
                        gps_offset_from_reference_m=feed.vessel_gps_offset_from_reference_m,
                        gps_offset_starboard_m=feed.vessel_gps_offset_starboard_m,
                    )
                )
            heading_value = heading_for_shape
        else:
            feature.setGeometry(
                QgsGeometry.fromPointXY(QgsPointXY(event.longitude, event.latitude))
            )

        feature.setAttributes(
            [
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
        )

        provider.addFeature(feature)

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
        layer = self._layers.pop(feed_id, None)
        self._remove_overview_layer(feed_id)
        self.clear_track(feed_id)
        self._heading_by_feed.pop(feed_id, None)
        self._position_by_feed.pop(feed_id, None)
        if layer is None:
            return
        QgsProject.instance().removeMapLayer(layer.id())

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

    def save_tracks(
        self,
        entries: List[dict],
        planned_number: str,
        actual_number: str,
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

            properties = {
                "saved_at_utc": saved_at_utc,
                "feed_id": str(entry.get("feed_id") or ""),
                "feed_name": str(entry.get("feed_name") or ""),
                "role": str(entry.get("role") or ""),
                "track_layer_id": str(entry.get("track_layer_id") or ""),
                "track_dimension": "3d" if use_3d else "2d",
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
            return 0, file_path

        self._ensure_saved_tracks_layer(file_path)
        return added_count, file_path

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
                json.dump(payload, handle, ensure_ascii=True, indent=2)
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
        if existing is not None and existing.isValid():
            existing.reload()
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
                layer.triggerRepaint()
                return

        layer = QgsVectorLayer(file_path, _SAVED_TRACK_LAYER_NAME, "ogr")
        if not layer.isValid():
            return

        layer.setCustomProperty("qgis_udp_nav_saved_tracks", 1)
        project.addMapLayer(layer)
        self._saved_tracks_layer = layer

    def clear_track(self, feed_id: str) -> None:
        layer = self._track_layers.pop(feed_id, None)
        self._track_points.pop(feed_id, None)
        self._track_lengths.pop(feed_id, None)
        self._track_dimensions.pop(feed_id, None)
        self._track_last_depth.pop(feed_id, None)

        if layer is not None:
            QgsProject.instance().removeMapLayer(layer.id())

    def update_heading(self, feed: FeedConfig, heading_deg: float) -> None:
        layer = self._layers.get(feed.feed_id)
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

    @staticmethod
    def _mark_ephemeral_layer(layer: QgsVectorLayer) -> None:
        # Prevent QGIS from prompting to save plugin-managed memory layers on exit.
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        layer.setCustomProperty("qgis_udp_nav_ephemeral", 1)

    def _ensure_layer(self, feed: FeedConfig) -> QgsVectorLayer:
        layer = self._layers.get(feed.feed_id)
        wants_polygon = feed.symbol_mode in {"vessel", "vehicle"}

        if layer is not None:
            is_polygon = QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry
            if is_polygon == wants_polygon:
                return layer

            QgsProject.instance().removeMapLayer(layer.id())
            self._layers.pop(feed.feed_id, None)

        layer_uri = "Polygon?crs=EPSG:4326" if wants_polygon else "Point?crs=EPSG:4326"
        layer = QgsVectorLayer(layer_uri, f"UDP Nav - {feed.name}", "memory")
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
        render_unit = self._render_unit_for_feed(feed)
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": marker_name,
                "color": feed.color_hex,
                "size": f"{max(qgis_width, qgis_height):.3f}",
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
                self._apply_svg_symbol_layer(symbol, svg_layer, fill_color=feed.color_hex)

        elif feed.symbol_mode == "unicode":
            unicode_svg = self._unicode_svg_path(feed)
            if unicode_svg is not None:
                svg_layer = QgsSvgMarkerSymbolLayer(unicode_svg, 7.0)
                self._apply_svg_symbol_layer(symbol, svg_layer)

        heading = self._heading_by_feed.get(feed.feed_id)
        if heading is not None:
            self._apply_heading_to_symbol(symbol, heading)

        return symbol

    def _ensure_overview_layer(self, feed: FeedConfig) -> QgsVectorLayer:
        layer = self._overview_layers.get(feed.feed_id)
        if layer is not None:
            return layer

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            f"UDP Nav - {feed.name} (overview)",
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
        QgsProject.instance().addMapLayer(layer, False)
        self._overview_layers[feed.feed_id] = layer
        return layer

    def _ensure_track_layer(self, feed: FeedConfig) -> QgsVectorLayer:
        layer = self._track_layers.get(feed.feed_id)
        if layer is not None:
            return layer

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            f"UDP Nav - {feed.name} (track)",
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
        QgsProject.instance().addMapLayer(layer)
        self._track_layers[feed.feed_id] = layer
        return layer

    def _remove_overview_layer(self, feed_id: str) -> None:
        layer = self._overview_layers.pop(feed_id, None)
        if layer is None:
            return
        QgsProject.instance().removeMapLayer(layer.id())

    @staticmethod
    def _create_track_symbol(color_hex: str) -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple(
            {
                "color": str(color_hex or "#ff4500"),
                "width": "1.2",
            }
        )
        set_opacity = getattr(symbol, "setOpacity", None)
        if callable(set_opacity):
            set_opacity(0.85)
        return symbol

    def _update_track_style(self, feed: FeedConfig) -> None:
        layer = self._track_layers.get(feed.feed_id)
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
            self.clear_track(feed.feed_id)
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

        points = self._track_points.setdefault(feed.feed_id, [])
        points.append((float(latitude), float(longitude), depth_m))
        if len(points) > _TRACK_MAX_POINTS:
            del points[: len(points) - _TRACK_MAX_POINTS]

        raw_length_m, smoothed_length_m = self._calculate_track_lengths(
            points,
            use_depth_3d=track_use_depth_3d,
        )
        self._track_lengths[feed.feed_id] = (raw_length_m, smoothed_length_m)
        self._track_dimensions[feed.feed_id] = "3d" if track_use_depth_3d else "2d"

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
                    self._track_dimensions[feed.feed_id],
                    len(points),
                ]
            )
            provider.addFeature(feature)

        layer.updateExtents()
        layer.triggerRepaint()

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
        layer = self._overview_layers.get(feed_id)
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
                    f"WHEN @map_scale >= {_OVERVIEW_ARROW_SCALE_THRESHOLD:.0f} "
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
        layer = self._layers.get(feed.feed_id)
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
        fill_color: Optional[str] = None,
    ) -> None:
        if not LayerManager._svg_layer_is_usable(svg_layer):
            return

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
        if width_property is None or height_property is None:
            return

        set_property = getattr(symbol_layer, "setDataDefinedProperty", None)
        if not callable(set_property):
            return

        set_property(width_property, QgsProperty.fromValue(float(width)))
        set_property(height_property, QgsProperty.fromValue(float(height)))

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
