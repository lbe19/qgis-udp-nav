from __future__ import annotations

import hashlib
import html
import math
import os
import tempfile
from typing import Dict, Optional, Tuple

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsFeature,
    QgsFillSymbol,
    QgsField,
    QgsGeometry,
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


class LayerManager:
    def __init__(self) -> None:
        self._layers: Dict[str, QgsVectorLayer] = {}
        self._overview_layers: Dict[str, QgsVectorLayer] = {}
        self._heading_by_feed: Dict[str, float] = {}
        self._position_by_feed: Dict[str, Tuple[float, float]] = {}

    def upsert_position(self, feed: FeedConfig, event: PositionFixEvent) -> None:
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

    def remove_feed(self, feed_id: str) -> None:
        layer = self._layers.pop(feed_id, None)
        self._remove_overview_layer(feed_id)
        self._heading_by_feed.pop(feed_id, None)
        self._position_by_feed.pop(feed_id, None)
        if layer is None:
            return
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
        QgsProject.instance().addMapLayer(layer, False)
        self._overview_layers[feed.feed_id] = layer
        return layer

    def _remove_overview_layer(self, feed_id: str) -> None:
        layer = self._overview_layers.pop(feed_id, None)
        if layer is None:
            return
        QgsProject.instance().removeMapLayer(layer.id())

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
