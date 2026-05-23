from __future__ import annotations

import os
from typing import Dict, List, Optional, Set

from qgis.PyQt.QtCore import QEvent, QPointF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QBrush, QPainter, QPalette, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QDockWidget,
    QLineEdit,
    QMessageBox,
    QLabel,
    QInputDialog,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)


def _dialog_button(name: str):
    enum_cls = getattr(QDialogButtonBox, "StandardButton", None)
    if enum_cls is not None and hasattr(enum_cls, name):
        return getattr(enum_cls, name)
    return getattr(QDialogButtonBox, name)


def _dialog_exec(dialog: QDialog) -> int:
    exec_fn = getattr(dialog, "exec", None)
    if callable(exec_fn):
        return int(exec_fn())
    return int(dialog.exec_())


def _dialog_accepted_code() -> int:
    enum_cls = getattr(QDialog, "DialogCode", None)
    if enum_cls is not None and hasattr(enum_cls, "Accepted"):
        return int(enum_cls.Accepted)
    return int(QDialog.Accepted)


def _messagebox_yes_code() -> int:
    enum_cls = getattr(QMessageBox, "StandardButton", None)
    if enum_cls is not None and hasattr(enum_cls, "Yes"):
        return int(enum_cls.Yes)
    return int(QMessageBox.Yes)


def _select_rows_behavior():
    enum_cls = getattr(QAbstractItemView, "SelectionBehavior", None)
    if enum_cls is not None and hasattr(enum_cls, "SelectRows"):
        return enum_cls.SelectRows
    return QAbstractItemView.SelectRows


def _single_selection_mode():
    enum_cls = getattr(QAbstractItemView, "SelectionMode", None)
    if enum_cls is not None and hasattr(enum_cls, "SingleSelection"):
        return enum_cls.SingleSelection
    return QAbstractItemView.SingleSelection


def _no_edit_triggers():
    enum_cls = getattr(QAbstractItemView, "EditTrigger", None)
    if enum_cls is not None and hasattr(enum_cls, "NoEditTriggers"):
        return enum_cls.NoEditTriggers
    return QAbstractItemView.NoEditTriggers


def _header_resize_mode(name: str):
    enum_cls = getattr(QHeaderView, "ResizeMode", None)
    if enum_cls is not None and hasattr(enum_cls, name):
        return getattr(enum_cls, name)
    return getattr(QHeaderView, name)


def _vertical_orientation():
    enum_cls = getattr(Qt, "Orientation", None)
    if enum_cls is not None and hasattr(enum_cls, "Vertical"):
        return enum_cls.Vertical
    return Qt.Vertical


def _align_center_flag():
    enum_cls = getattr(Qt, "AlignmentFlag", None)
    if enum_cls is not None and hasattr(enum_cls, "AlignCenter"):
        return enum_cls.AlignCenter
    return Qt.AlignCenter


def _event_type(name: str):
    enum_cls = getattr(QEvent, "Type", None)
    if enum_cls is not None and hasattr(enum_cls, name):
        return getattr(enum_cls, name)
    return getattr(QEvent, name, None)


def _palette_role(name: str):
    enum_cls = getattr(QPalette, "ColorRole", None)
    if enum_cls is not None and hasattr(enum_cls, name):
        return getattr(enum_cls, name)
    return getattr(QPalette, name, None)


def _palette_color(palette: QPalette, role_name: str, fallback: QColor) -> QColor:
    role = _palette_role(role_name)
    if role is None:
        return QColor(fallback)
    color = palette.color(role)
    if isinstance(color, QColor) and color.isValid():
        return color
    return QColor(fallback)


def _qcolor_css(color: QColor) -> str:
    if isinstance(color, QColor) and color.isValid():
        return color.name()
    return "#000000"


QGIS_MARKER_OPTIONS = [
    "circle",
    "square",
    "triangle",
    "cross",
    "x",
    "diamond",
    "star",
    "arrow",
    "line",
]

UNICODE_OPTIONS = [
    ("Anchor", "\u2693"),
    ("Ship", "\u26f5"),
    ("Location", "\U0001f4cd"),
    ("Compass", "\u2638"),
    ("Circle", "\u25cf"),
    ("Triangle", "\u25b2"),
    ("Square", "\u25a0"),
    ("Diamond", "\u25c6"),
]


def _painter_antialiasing_hint():
    enum_cls = getattr(QPainter, "RenderHint", None)
    if enum_cls is not None and hasattr(enum_cls, "Antialiasing"):
        return enum_cls.Antialiasing
    return QPainter.Antialiasing


def _dash_line_pen_style():
    enum_cls = getattr(Qt, "PenStyle", None)
    if enum_cls is not None and hasattr(enum_cls, "DashLine"):
        return enum_cls.DashLine
    return Qt.DashLine


def _no_brush_style():
    enum_cls = getattr(Qt, "BrushStyle", None)
    if enum_cls is not None and hasattr(enum_cls, "NoBrush"):
        return enum_cls.NoBrush
    return Qt.NoBrush


class VesselPreviewWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._length_m = 20.0
        self._width_m = 6.0
        self._gps_longitudinal_reference = "bow"
        self._gps_offset_from_reference_m = 0.0
        self._gps_starboard_m = 0.0
        self._body_mode = "vessel"
        self.setMinimumHeight(170)

    def set_values(
        self,
        length_m: float,
        width_m: float,
        gps_longitudinal_reference: str,
        gps_offset_from_reference_m: float,
        gps_starboard_m: float,
        body_mode: str = "vessel",
    ) -> None:
        self._length_m = max(0.05, float(length_m))
        self._width_m = max(0.05, float(width_m))
        reference = str(gps_longitudinal_reference).strip().lower()
        self._gps_longitudinal_reference = "stern" if reference == "stern" else "bow"
        self._gps_offset_from_reference_m = max(0.0, float(gps_offset_from_reference_m))
        self._gps_starboard_m = float(gps_starboard_m)
        mode = str(body_mode).strip().lower()
        self._body_mode = "vehicle" if mode == "vehicle" else "vessel"
        self.update()

    @staticmethod
    def _forward_from_reference(
        length_m: float,
        reference: str,
        offset_from_reference_m: float,
    ) -> float:
        half_length = max(0.05, float(length_m)) / 2.0
        offset = max(0.0, float(offset_from_reference_m))
        if str(reference).strip().lower() == "stern":
            return (-half_length) + offset
        return half_length - offset

    @staticmethod
    def _to_canvas(
        min_forward: float,
        min_starboard: float,
        scale: float,
        origin_x: float,
        origin_y: float,
        forward_m: float,
        starboard_m: float,
    ) -> QPointF:
        x = origin_x + ((starboard_m - min_starboard) * scale)
        y = origin_y - ((forward_m - min_forward) * scale)
        return QPointF(x, y)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(_painter_antialiasing_hint(), True)

        canvas = self.rect().adjusted(8, 8, -8, -8)
        if canvas.width() < 20 or canvas.height() < 20:
            return

        length = self._length_m
        width = self._width_m
        gps_forward_m = self._forward_from_reference(
            length,
            self._gps_longitudinal_reference,
            self._gps_offset_from_reference_m,
        )
        half_length = length / 2.0
        half_width = width / 2.0
        if self._body_mode == "vehicle":
            hull_points = [
                (-half_length, -half_width),
                (half_length, -half_width),
                (half_length, half_width),
                (-half_length, half_width),
            ]
        else:
            bow_length = max(length * 0.28, min(length * 0.45, width))
            bow_base = half_length - bow_length
            hull_points = [
                (-half_length, -half_width),
                (bow_base, -half_width),
                (half_length, 0.0),
                (bow_base, half_width),
                (-half_length, half_width),
            ]

        all_forward = [point[0] for point in hull_points] + [gps_forward_m, 0.0]
        all_starboard = [point[1] for point in hull_points] + [self._gps_starboard_m, 0.0]
        margin_m = max(1.0, length * 0.05, width * 0.1)
        min_forward = min(all_forward) - margin_m
        max_forward = max(all_forward) + margin_m
        min_starboard = min(all_starboard) - margin_m
        max_starboard = max(all_starboard) + margin_m

        forward_span = max(1e-6, max_forward - min_forward)
        starboard_span = max(1e-6, max_starboard - min_starboard)

        scale = min(
            canvas.width() / starboard_span,
            canvas.height() / forward_span,
        )

        drawing_width = starboard_span * scale
        drawing_height = forward_span * scale
        origin_x = canvas.left() + ((canvas.width() - drawing_width) / 2.0)
        origin_y = canvas.bottom() - ((canvas.height() - drawing_height) / 2.0)

        painter.fillRect(canvas, QColor("#f7fafc"))

        center_a = self._to_canvas(
            min_forward,
            min_starboard,
            scale,
            origin_x,
            origin_y,
            min_forward,
            0.0,
        )
        center_b = self._to_canvas(
            min_forward,
            min_starboard,
            scale,
            origin_x,
            origin_y,
            max_forward,
            0.0,
        )
        center_c = self._to_canvas(
            min_forward,
            min_starboard,
            scale,
            origin_x,
            origin_y,
            0.0,
            min_starboard,
        )
        center_d = self._to_canvas(
            min_forward,
            min_starboard,
            scale,
            origin_x,
            origin_y,
            0.0,
            max_starboard,
        )

        centerline_pen = QPen(QColor("#c5cdd8"))
        centerline_pen.setWidth(1)
        centerline_pen.setStyle(_dash_line_pen_style())
        painter.setPen(centerline_pen)
        painter.setBrush(_no_brush_style())
        painter.drawLine(center_a, center_b)
        painter.drawLine(center_c, center_d)

        polygon = QPolygonF(
            [
                self._to_canvas(
                    min_forward,
                    min_starboard,
                    scale,
                    origin_x,
                    origin_y,
                    forward_m,
                    starboard_m,
                )
                for forward_m, starboard_m in hull_points
            ]
        )
        painter.setPen(QPen(QColor("#1f2933"), 2))
        painter.setBrush(QBrush(QColor("#9dc3de")))
        painter.drawPolygon(polygon)

        gps_point = self._to_canvas(
            min_forward,
            min_starboard,
            scale,
            origin_x,
            origin_y,
            gps_forward_m,
            self._gps_starboard_m,
        )
        painter.setPen(QPen(QColor("#b00020"), 1))
        painter.setBrush(QBrush(QColor("#ef4444")))
        painter.drawEllipse(gps_point, 4, 4)

        bow_label = self._to_canvas(
            min_forward,
            min_starboard,
            scale,
            origin_x,
            origin_y,
            half_length,
            0.0,
        )
        painter.setPen(QPen(QColor("#334155"), 1))
        if self._body_mode == "vehicle":
            painter.drawText(bow_label + QPointF(6.0, -6.0), "Forward")
        else:
            painter.drawText(bow_label + QPointF(6.0, -6.0), "Bow")
        painter.drawText(gps_point + QPointF(6.0, 16.0), "GNSS")
        painter.setBrush(_no_brush_style())
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.drawRect(canvas)


class FeedConfigDialog(QDialog):
    def __init__(self, parent=None, initial: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Feed Configuration")
        self.setModal(True)

        initial = initial or {}

        self.name_edit = QLineEdit(initial.get("name", ""))
        self.host_edit = QLineEdit(initial.get("bind_host", "0.0.0.0"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(initial.get("port", 10110)))

        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(["lenient", "strict", "ignore"])
        self.checksum_combo.setCurrentText(initial.get("checksum_policy", "lenient"))

        self.stale_spin = QSpinBox()
        self.stale_spin.setRange(1, 120)
        self.stale_spin.setValue(int(initial.get("stale_timeout_sec", 5)))

        self.utm_epsg_edit = QLineEdit(self._fmt_optional(initial.get("hipap_utm_epsg")))
        self.ref_lat_edit = QLineEdit(self._fmt_optional(initial.get("reference_lat")))
        self.ref_lon_edit = QLineEdit(self._fmt_optional(initial.get("reference_lon")))
        self.ref_heading_edit = QLineEdit(
            self._fmt_optional(initial.get("reference_heading_deg"))
        )

        self.enabled_combo = QComboBox()
        self.enabled_combo.addItems(["Enabled", "Disabled"])
        if not bool(initial.get("enabled", True)):
            self.enabled_combo.setCurrentText("Disabled")

        self.split_combo = QComboBox()
        self.split_combo.addItem("Single target", "single")
        self.split_combo.addItem("Split vessel + vehicle", "split")
        if bool(initial.get("split_subfeeds_enabled", False)):
            self.split_combo.setCurrentIndex(1)

        self.routing_combo = QComboBox()
        self.routing_combo.addItem("Auto (GPS->vessel, Kongsberg->vehicle)", "auto")
        self.routing_combo.addItem("Manual sentence routing", "manual")
        initial_routing = str(initial.get("split_routing_mode", "auto")).strip().lower()
        self.routing_combo.setCurrentIndex(
            max(0, self.routing_combo.findData(initial_routing or "auto"))
        )

        self.vehicle_fallback_combo = QComboBox()
        self.vehicle_fallback_combo.addItem("Disabled", False)
        self.vehicle_fallback_combo.addItem("Enabled", True)
        if bool(initial.get("vehicle_show_on_vessel_when_missing_position", False)):
            self.vehicle_fallback_combo.setCurrentIndex(1)

        self.vessel_track_check = QCheckBox("Draw vessel track")
        self.vessel_track_check.setChecked(bool(initial.get("vessel_track_enabled", False)))

        self.vehicle_track_check = QCheckBox("Draw vehicle track")
        self.vehicle_track_check.setChecked(bool(initial.get("vehicle_track_enabled", False)))

        self.manual_vessel_edit = QLineEdit(
            self._sentence_types_to_text(initial.get("manual_vessel_sentence_types", []))
        )
        self.manual_vessel_edit.setPlaceholderText("GGA,GLL,RMC,HDT")

        self.manual_vehicle_edit = QLineEdit(
            self._sentence_types_to_text(initial.get("manual_vehicle_sentence_types", []))
        )
        self.manual_vehicle_edit.setPlaceholderText("PSIMSSB,PSIMSNS")

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Bind Host", self.host_edit)
        form.addRow("UDP Port", self.port_spin)
        form.addRow("Checksum Policy", self.checksum_combo)
        form.addRow("Target Mode", self.split_combo)
        form.addRow("Split Routing", self.routing_combo)
        form.addRow("Vehicle Fallback To Vessel", self.vehicle_fallback_combo)
        form.addRow("Vessel Track", self.vessel_track_check)
        form.addRow("Vehicle Track", self.vehicle_track_check)
        form.addRow("Manual Vessel Sentence Types", self.manual_vessel_edit)
        form.addRow("Manual Vehicle Sentence Types", self.manual_vehicle_edit)
        form.addRow("Stale Timeout (s)", self.stale_spin)
        form.addRow("HiPAP UTM EPSG", self.utm_epsg_edit)
        form.addRow("Reference Latitude", self.ref_lat_edit)
        form.addRow("Reference Longitude", self.ref_lon_edit)
        form.addRow("Reference Heading", self.ref_heading_edit)
        form.addRow("State", self.enabled_combo)

        self._routing_label = form.labelForField(self.routing_combo)
        self._vehicle_fallback_label = form.labelForField(self.vehicle_fallback_combo)
        self._vessel_track_label = form.labelForField(self.vessel_track_check)
        self._vehicle_track_label = form.labelForField(self.vehicle_track_check)
        self._manual_vessel_label = form.labelForField(self.manual_vessel_edit)
        self._manual_vehicle_label = form.labelForField(self.manual_vehicle_edit)

        buttons = QDialogButtonBox(_dialog_button("Ok") | _dialog_button("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self.split_combo.currentIndexChanged.connect(self._refresh_split_fields)
        self.routing_combo.currentIndexChanged.connect(self._refresh_split_fields)
        self._refresh_split_fields()

    def payload(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "bind_host": self.host_edit.text().strip() or "0.0.0.0",
            "port": int(self.port_spin.value()),
            "checksum_policy": self.checksum_combo.currentText().strip(),
            "split_subfeeds_enabled": bool(self.split_combo.currentData() == "split"),
            "split_routing_mode": str(self.routing_combo.currentData() or "auto"),
            "vehicle_show_on_vessel_when_missing_position": bool(
                self.vehicle_fallback_combo.currentData()
            ),
            "vessel_track_enabled": bool(self.vessel_track_check.isChecked()),
            "vehicle_track_enabled": bool(self.vehicle_track_check.isChecked()),
            "manual_vessel_sentence_types": self._parse_sentence_types(
                self.manual_vessel_edit.text()
            ),
            "manual_vehicle_sentence_types": self._parse_sentence_types(
                self.manual_vehicle_edit.text()
            ),
            "stale_timeout_sec": int(self.stale_spin.value()),
            "hipap_utm_epsg": self._to_optional_int(self.utm_epsg_edit.text()),
            "reference_lat": self._to_optional_float(self.ref_lat_edit.text()),
            "reference_lon": self._to_optional_float(self.ref_lon_edit.text()),
            "reference_heading_deg": self._to_optional_float(self.ref_heading_edit.text()),
            "enabled": self.enabled_combo.currentText() == "Enabled",
        }

    def _refresh_split_fields(self) -> None:
        split_enabled = bool(self.split_combo.currentData() == "split")
        manual_mode = bool(self.routing_combo.currentData() == "manual")

        self._routing_label.setVisible(split_enabled)
        self.routing_combo.setVisible(split_enabled)
        self._vehicle_fallback_label.setVisible(split_enabled)
        self.vehicle_fallback_combo.setVisible(split_enabled)
        self._vehicle_track_label.setVisible(split_enabled)
        self.vehicle_track_check.setVisible(split_enabled)

        self._vessel_track_label.setVisible(True)
        self.vessel_track_check.setVisible(True)

        show_manual = split_enabled and manual_mode
        self._manual_vessel_label.setVisible(show_manual)
        self.manual_vessel_edit.setVisible(show_manual)
        self._manual_vehicle_label.setVisible(show_manual)
        self.manual_vehicle_edit.setVisible(show_manual)

    @staticmethod
    def _fmt_optional(value) -> str:
        if value in (None, ""):
            return ""
        return str(value)

    @staticmethod
    def _to_optional_float(value: str):
        text = value.strip()
        if not text:
            return None
        return float(text)

    @staticmethod
    def _to_optional_int(value: str):
        text = value.strip()
        if not text:
            return None
        return int(text)

    @staticmethod
    def _sentence_types_to_text(value: object) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple, set)):
            return ",".join(str(item).strip().upper() for item in value if str(item).strip())
        return str(value)

    @staticmethod
    def _parse_sentence_types(value: str) -> list[str]:
        parts = value.replace(";", ",").split(",")
        parsed: list[str] = []
        seen: set[str] = set()
        for part in parts:
            sentence_type = part.strip().upper()
            if not sentence_type or sentence_type in seen:
                continue
            seen.add(sentence_type)
            parsed.append(sentence_type)
        return parsed


class SymbolPickerDialog(QDialog):
    def __init__(
        self,
        parent=None,
        initial: Optional[dict] = None,
        vessel_profiles: Optional[dict[str, dict]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Feed Symbol")
        self.setModal(True)

        initial = initial or {}
        self._vessel_profiles: dict[str, dict] = {
            str(name): dict(payload)
            for name, payload in (vessel_profiles or {}).items()
            if str(name).strip() and isinstance(payload, dict)
        }
        self._profiles_changed = False
        current_mode = str(initial.get("symbol_mode", "vessel"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Vessel Hull (scaled)", "vessel")
        self.mode_combo.addItem("Vehicle Rectangle (scaled)", "vehicle")
        self.mode_combo.addItem("QGIS Marker", "qgis")
        self.mode_combo.addItem("Unicode Symbol", "unicode")
        self.mode_combo.addItem("SVG Icon File", "icon_file")
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(current_mode)))

        self.vessel_length_spin = QDoubleSpinBox()
        self.vessel_length_spin.setDecimals(3)
        self.vessel_length_spin.setRange(0.05, 1000.0)
        self.vessel_length_spin.setSingleStep(0.5)
        self.vessel_length_spin.setSuffix(" m")
        self.vessel_length_spin.setValue(float(initial.get("vessel_length_m", 20.0)))

        self.vessel_width_spin = QDoubleSpinBox()
        self.vessel_width_spin.setDecimals(3)
        self.vessel_width_spin.setRange(0.05, 300.0)
        self.vessel_width_spin.setSingleStep(0.5)
        self.vessel_width_spin.setSuffix(" m")
        self.vessel_width_spin.setValue(float(initial.get("vessel_width_m", 6.0)))

        legacy_forward_offset = float(initial.get("vessel_gps_offset_forward_m", 0.0))
        (
            inferred_reference,
            inferred_offset_from_reference,
        ) = self._reference_offset_from_forward(
            length_m=float(self.vessel_length_spin.value()),
            forward_from_center_m=legacy_forward_offset,
        )

        reference_value = str(
            initial.get("vessel_gps_longitudinal_reference", inferred_reference)
        ).strip().lower()
        if reference_value not in {"bow", "stern"}:
            reference_value = inferred_reference

        offset_from_reference_m = float(
            initial.get(
                "vessel_gps_offset_from_reference_m",
                inferred_offset_from_reference,
            )
        )

        self.vessel_gps_reference_button = QPushButton(self)
        self.vessel_gps_reference_button.setCheckable(True)
        self._set_gps_reference(reference_value)

        self.vessel_gps_offset_ref_spin = QDoubleSpinBox()
        self.vessel_gps_offset_ref_spin.setDecimals(3)
        self.vessel_gps_offset_ref_spin.setRange(0.0, 2000.0)
        self.vessel_gps_offset_ref_spin.setSingleStep(0.5)
        self.vessel_gps_offset_ref_spin.setSuffix(" m")
        self.vessel_gps_offset_ref_spin.setValue(max(0.0, offset_from_reference_m))

        self.vessel_gps_starboard_spin = QDoubleSpinBox()
        self.vessel_gps_starboard_spin.setDecimals(3)
        self.vessel_gps_starboard_spin.setRange(-500.0, 500.0)
        self.vessel_gps_starboard_spin.setSingleStep(0.5)
        self.vessel_gps_starboard_spin.setSuffix(" m")
        self.vessel_gps_starboard_spin.setValue(
            float(initial.get("vessel_gps_offset_starboard_m", 0.0))
        )

        self.qgis_combo = QComboBox()
        self.qgis_combo.addItems(QGIS_MARKER_OPTIONS)
        qgis_marker = str(initial.get("qgis_symbol_name", "circle"))
        self.qgis_combo.setCurrentIndex(max(0, self.qgis_combo.findText(qgis_marker)))

        self.qgis_width_spin = QDoubleSpinBox()
        self.qgis_width_spin.setDecimals(3)
        self.qgis_width_spin.setRange(0.5, 200.0)
        self.qgis_width_spin.setSingleStep(0.5)
        self.qgis_width_spin.setValue(float(initial.get("qgis_symbol_width", 7.0)))

        self.qgis_height_spin = QDoubleSpinBox()
        self.qgis_height_spin.setDecimals(3)
        self.qgis_height_spin.setRange(0.5, 200.0)
        self.qgis_height_spin.setSingleStep(0.5)
        self.qgis_height_spin.setValue(float(initial.get("qgis_symbol_height", 7.0)))

        self.qgis_unit_combo = QComboBox()
        self.qgis_unit_combo.addItem("Screen millimeters", "screen")
        self.qgis_unit_combo.addItem("Map meters", "map_meters")
        qgis_size_unit = str(initial.get("qgis_size_unit", "screen"))
        self.qgis_unit_combo.setCurrentIndex(max(0, self.qgis_unit_combo.findData(qgis_size_unit)))

        self.unicode_combo = QComboBox()
        for label, char in UNICODE_OPTIONS:
            self.unicode_combo.addItem(f"{char}  {label}", char)
        desired_unicode = str(initial.get("unicode_symbol", "\u2693"))
        unicode_index = self.unicode_combo.findData(desired_unicode)
        self.unicode_combo.setCurrentIndex(max(0, unicode_index))

        self.font_edit = QLineEdit(
            str(initial.get("unicode_font_family", "Noto Sans Symbols 2"))
            or "Noto Sans Symbols 2"
        )

        self.icon_path_edit = QLineEdit(str(initial.get("icon_path", "")))
        self.icon_pick_button = QPushButton("Browse...")
        self.icon_pick_button.clicked.connect(self._browse_icon)

        file_widget = QWidget(self)
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.addWidget(self.icon_path_edit)
        file_layout.addWidget(self.icon_pick_button)

        self.color_edit = QLineEdit(str(initial.get("color_hex", "#ff4500")).strip() or "#ff4500")
        self.color_pick_button = QPushButton("Pick...")
        self.color_pick_button.clicked.connect(self._browse_color)

        color_widget = QWidget(self)
        color_layout = QHBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.addWidget(self.color_edit)
        color_layout.addWidget(self.color_pick_button)

        self.profile_combo = QComboBox()
        self.profile_load_button = QPushButton("Load")
        self.profile_save_button = QPushButton("Save As")

        profile_widget = QWidget(self)
        profile_layout = QHBoxLayout(profile_widget)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self.profile_combo)
        profile_layout.addWidget(self.profile_load_button)
        profile_layout.addWidget(self.profile_save_button)
        self._refresh_profile_combo()
        self.profile_load_button.clicked.connect(self._on_load_profile_clicked)
        self.profile_save_button.clicked.connect(self._on_save_profile_clicked)

        form = QFormLayout()
        form.addRow("Source", self.mode_combo)
        form.addRow("Vessel Profile", profile_widget)
        form.addRow("Vessel Length", self.vessel_length_spin)
        form.addRow("Vessel Width", self.vessel_width_spin)
        form.addRow("GPS Longitudinal Reference", self.vessel_gps_reference_button)
        form.addRow("GPS Offset From Reference", self.vessel_gps_offset_ref_spin)
        form.addRow("GPS Offset Starboard (+/- from centerline)", self.vessel_gps_starboard_spin)
        form.addRow("QGIS Marker", self.qgis_combo)
        form.addRow("QGIS Width", self.qgis_width_spin)
        form.addRow("QGIS Height", self.qgis_height_spin)
        form.addRow("QGIS Units", self.qgis_unit_combo)
        form.addRow("Unicode Symbol", self.unicode_combo)
        form.addRow("Unicode Font", self.font_edit)
        form.addRow("SVG Path", file_widget)
        form.addRow("Color", color_widget)

        self._qgis_label = form.labelForField(self.qgis_combo)
        self._vessel_length_label = form.labelForField(self.vessel_length_spin)
        self._vessel_width_label = form.labelForField(self.vessel_width_spin)
        self._vessel_gps_reference_label = form.labelForField(self.vessel_gps_reference_button)
        self._vessel_gps_offset_ref_label = form.labelForField(self.vessel_gps_offset_ref_spin)
        self._vessel_gps_starboard_label = form.labelForField(self.vessel_gps_starboard_spin)
        self._qgis_width_label = form.labelForField(self.qgis_width_spin)
        self._qgis_height_label = form.labelForField(self.qgis_height_spin)
        self._qgis_unit_label = form.labelForField(self.qgis_unit_combo)
        self._unicode_label = form.labelForField(self.unicode_combo)
        self._font_label = form.labelForField(self.font_edit)
        self._file_label = form.labelForField(file_widget)
        self._file_widget = file_widget

        preview_hint = QLabel("Preview: top view (bow up, starboard right, red dot = GNSS)")
        self._preview_widget = VesselPreviewWidget(self)

        buttons = QDialogButtonBox(_dialog_button("Ok") | _dialog_button("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(preview_hint)
        layout.addWidget(self._preview_widget)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self._preview_hint = preview_hint

        self.mode_combo.currentIndexChanged.connect(self._refresh_visibility)
        self.vessel_length_spin.valueChanged.connect(self._update_vessel_preview)
        self.vessel_width_spin.valueChanged.connect(self._update_vessel_preview)
        self.vessel_gps_reference_button.toggled.connect(self._on_gps_reference_toggled)
        self.vessel_gps_offset_ref_spin.valueChanged.connect(self._update_vessel_preview)
        self.vessel_gps_starboard_spin.valueChanged.connect(self._update_vessel_preview)
        self._update_vessel_preview()
        self._refresh_visibility()

    def payload(self) -> dict:
        symbol_mode = str(self.mode_combo.currentData() or "vessel")
        unicode_char = str(self.unicode_combo.currentData() or "\u2693")

        return {
            "symbol_mode": symbol_mode,
            "vessel_length_m": float(self.vessel_length_spin.value()),
            "vessel_width_m": float(self.vessel_width_spin.value()),
            "vessel_gps_longitudinal_reference": self._current_gps_reference(),
            "vessel_gps_offset_from_reference_m": float(self.vessel_gps_offset_ref_spin.value()),
            "vessel_gps_offset_starboard_m": float(self.vessel_gps_starboard_spin.value()),
            "qgis_symbol_name": self.qgis_combo.currentText().strip() or "circle",
            "qgis_symbol_width": float(self.qgis_width_spin.value()),
            "qgis_symbol_height": float(self.qgis_height_spin.value()),
            "qgis_size_unit": str(self.qgis_unit_combo.currentData() or "screen"),
            "unicode_symbol": unicode_char,
            "unicode_font_family": self.font_edit.text().strip() or "Noto Sans Symbols 2",
            "icon_path": self.icon_path_edit.text().strip(),
            "color_hex": self.color_edit.text().strip() or "#ff4500",
        }

    def _refresh_visibility(self) -> None:
        mode = str(self.mode_combo.currentData() or "vessel")

        show_vessel = mode in {"vessel", "vehicle"}
        show_qgis = mode == "qgis"
        show_unicode = mode == "unicode"
        show_file = mode == "icon_file"

        self._vessel_length_label.setVisible(show_vessel)
        self.vessel_length_spin.setVisible(show_vessel)
        self._vessel_width_label.setVisible(show_vessel)
        self.vessel_width_spin.setVisible(show_vessel)
        self._vessel_gps_reference_label.setVisible(show_vessel)
        self.vessel_gps_reference_button.setVisible(show_vessel)
        self._vessel_gps_offset_ref_label.setVisible(show_vessel)
        self.vessel_gps_offset_ref_spin.setVisible(show_vessel)
        self._vessel_gps_starboard_label.setVisible(show_vessel)
        self.vessel_gps_starboard_spin.setVisible(show_vessel)

        self._qgis_label.setVisible(show_qgis)
        self.qgis_combo.setVisible(show_qgis)
        self._qgis_width_label.setVisible(show_qgis)
        self.qgis_width_spin.setVisible(show_qgis)
        self._qgis_height_label.setVisible(show_qgis)
        self.qgis_height_spin.setVisible(show_qgis)
        self._qgis_unit_label.setVisible(show_qgis)
        self.qgis_unit_combo.setVisible(show_qgis)

        self._unicode_label.setVisible(show_unicode)
        self.unicode_combo.setVisible(show_unicode)
        self._font_label.setVisible(show_unicode)
        self.font_edit.setVisible(show_unicode)

        self._file_label.setVisible(show_file)
        self._file_widget.setVisible(show_file)

        self._preview_hint.setVisible(show_vessel)
        self._preview_widget.setVisible(show_vessel)
        self._update_preview_hint(mode)
        self._update_vessel_preview()

    def _update_vessel_preview(self, *_args) -> None:
        mode = str(self.mode_combo.currentData() or "vessel")
        self._preview_widget.set_values(
            length_m=float(self.vessel_length_spin.value()),
            width_m=float(self.vessel_width_spin.value()),
            gps_longitudinal_reference=self._current_gps_reference(),
            gps_offset_from_reference_m=float(self.vessel_gps_offset_ref_spin.value()),
            gps_starboard_m=float(self.vessel_gps_starboard_spin.value()),
            body_mode=mode,
        )

    def _update_preview_hint(self, mode: str) -> None:
        if mode == "vehicle":
            self._preview_hint.setText(
                "Preview: top view rectangle (forward up, starboard right, red dot = GNSS)"
            )
            return
        self._preview_hint.setText(
            "Preview: top view (bow up, starboard right, red dot = GNSS)"
        )

    def _current_gps_reference(self) -> str:
        return "stern" if self.vessel_gps_reference_button.isChecked() else "bow"

    def _set_gps_reference(self, reference: str) -> None:
        self.vessel_gps_reference_button.setChecked(
            str(reference).strip().lower() == "stern"
        )
        self._update_gps_reference_button_text()

    def _on_gps_reference_toggled(self, _checked: bool) -> None:
        self._update_gps_reference_button_text()
        self._update_vessel_preview()

    def _update_gps_reference_button_text(self) -> None:
        if self.vessel_gps_reference_button.isChecked():
            self.vessel_gps_reference_button.setText("Stern")
            self.vessel_gps_reference_button.setToolTip(
                "Longitudinal offset is measured from stern toward bow."
            )
        else:
            self.vessel_gps_reference_button.setText("Bow")
            self.vessel_gps_reference_button.setToolTip(
                "Longitudinal offset is measured from bow toward stern."
            )

    @staticmethod
    def _reference_offset_from_forward(
        length_m: float,
        forward_from_center_m: float,
    ) -> tuple[str, float]:
        half_length = max(0.05, float(length_m)) / 2.0
        bow_offset = half_length - float(forward_from_center_m)
        stern_offset = half_length + float(forward_from_center_m)
        if bow_offset >= 0 and stern_offset >= 0:
            if bow_offset <= stern_offset:
                return "bow", bow_offset
            return "stern", stern_offset
        if bow_offset >= 0:
            return "bow", bow_offset
        return "stern", stern_offset

    def profiles_changed(self) -> bool:
        return bool(self._profiles_changed)

    def updated_profiles(self) -> dict[str, dict]:
        return {
            str(name): dict(profile)
            for name, profile in self._vessel_profiles.items()
            if str(name).strip() and isinstance(profile, dict)
        }

    def _refresh_profile_combo(self, selected_name: Optional[str] = None) -> None:
        self.profile_combo.clear()
        names = sorted(self._vessel_profiles.keys(), key=lambda value: value.lower())
        for name in names:
            self.profile_combo.addItem(name, name)

        if not names:
            self.profile_combo.addItem("(No saved profiles)", "")
            self.profile_load_button.setEnabled(False)
            return

        self.profile_load_button.setEnabled(True)
        if selected_name:
            index = self.profile_combo.findData(selected_name)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)

    def _on_load_profile_clicked(self) -> None:
        profile_name = str(self.profile_combo.currentData() or "").strip()
        if not profile_name:
            return

        profile = self._vessel_profiles.get(profile_name)
        if not isinstance(profile, dict):
            return

        self._apply_profile(profile)

    def _on_save_profile_clicked(self) -> None:
        profile_name, ok = QInputDialog.getText(
            self,
            "Save Vessel Profile",
            "Profile name:",
        )
        if not ok:
            return

        name = str(profile_name).strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Profile name cannot be empty.")
            return

        if name in self._vessel_profiles:
            confirm = QMessageBox.question(
                self,
                "Overwrite Profile",
                f"Profile '{name}' already exists. Overwrite it?",
            )
            if int(confirm) != _messagebox_yes_code():
                return

        self._vessel_profiles[name] = self._profile_payload()
        self._profiles_changed = True
        self._refresh_profile_combo(selected_name=name)

    def _apply_profile(self, profile: dict) -> None:
        symbol_mode = str(profile.get("symbol_mode", self.mode_combo.currentData() or "vessel"))
        mode_index = self.mode_combo.findData(symbol_mode)
        if mode_index >= 0:
            self.mode_combo.setCurrentIndex(mode_index)

        self.vessel_length_spin.setValue(float(profile.get("vessel_length_m", self.vessel_length_spin.value())))
        self.vessel_width_spin.setValue(float(profile.get("vessel_width_m", self.vessel_width_spin.value())))
        self._set_gps_reference(
            str(
                profile.get(
                    "vessel_gps_longitudinal_reference",
                    self._current_gps_reference(),
                )
            )
        )
        self.vessel_gps_offset_ref_spin.setValue(
            float(
                profile.get(
                    "vessel_gps_offset_from_reference_m",
                    self.vessel_gps_offset_ref_spin.value(),
                )
            )
        )
        self.vessel_gps_starboard_spin.setValue(
            float(
                profile.get(
                    "vessel_gps_offset_starboard_m",
                    self.vessel_gps_starboard_spin.value(),
                )
            )
        )

        qgis_symbol_name = str(profile.get("qgis_symbol_name", self.qgis_combo.currentText()))
        qgis_symbol_index = self.qgis_combo.findText(qgis_symbol_name)
        if qgis_symbol_index >= 0:
            self.qgis_combo.setCurrentIndex(qgis_symbol_index)

        self.qgis_width_spin.setValue(float(profile.get("qgis_symbol_width", self.qgis_width_spin.value())))
        self.qgis_height_spin.setValue(float(profile.get("qgis_symbol_height", self.qgis_height_spin.value())))

        qgis_unit = str(profile.get("qgis_size_unit", self.qgis_unit_combo.currentData() or "screen"))
        qgis_unit_index = self.qgis_unit_combo.findData(qgis_unit)
        if qgis_unit_index >= 0:
            self.qgis_unit_combo.setCurrentIndex(qgis_unit_index)

        unicode_symbol = str(profile.get("unicode_symbol", self.unicode_combo.currentData() or "\u2693"))
        unicode_index = self.unicode_combo.findData(unicode_symbol)
        if unicode_index >= 0:
            self.unicode_combo.setCurrentIndex(unicode_index)

        self.font_edit.setText(
            str(profile.get("unicode_font_family", self.font_edit.text()))
            or "Noto Sans Symbols 2"
        )
        self.icon_path_edit.setText(str(profile.get("icon_path", self.icon_path_edit.text())).strip())
        self.color_edit.setText(
            str(profile.get("color_hex", self.color_edit.text())).strip() or "#ff4500"
        )

        self._refresh_visibility()
        self._update_vessel_preview()

    def _profile_payload(self) -> dict:
        return {
            "symbol_mode": str(self.mode_combo.currentData() or "vessel"),
            "vessel_length_m": float(self.vessel_length_spin.value()),
            "vessel_width_m": float(self.vessel_width_spin.value()),
            "vessel_gps_longitudinal_reference": self._current_gps_reference(),
            "vessel_gps_offset_from_reference_m": float(self.vessel_gps_offset_ref_spin.value()),
            "vessel_gps_offset_starboard_m": float(self.vessel_gps_starboard_spin.value()),
            "qgis_symbol_name": self.qgis_combo.currentText().strip() or "circle",
            "qgis_symbol_width": float(self.qgis_width_spin.value()),
            "qgis_symbol_height": float(self.qgis_height_spin.value()),
            "qgis_size_unit": str(self.qgis_unit_combo.currentData() or "screen"),
            "unicode_symbol": str(self.unicode_combo.currentData() or "\u2693"),
            "unicode_font_family": self.font_edit.text().strip() or "Noto Sans Symbols 2",
            "icon_path": self.icon_path_edit.text().strip(),
            "color_hex": self.color_edit.text().strip() or "#ff4500",
        }

    def _browse_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pick SVG Icon",
            "",
            "SVG Images (*.svg)",
        )
        if path:
            self.icon_path_edit.setText(path)

    def _browse_color(self) -> None:
        current_hex = self.color_edit.text().strip() or "#ff4500"
        color = QColorDialog.getColor(QColor(current_hex), self, "Pick Symbol Color")
        if color.isValid():
            self.color_edit.setText(color.name())


class FeedDockWidget(QDockWidget):
    feed_added = pyqtSignal(dict)
    feed_updated = pyqtSignal(str, dict)
    feed_removed = pyqtSignal(str)
    feed_start_requested = pyqtSignal(str)
    feed_stop_requested = pyqtSignal(str)
    keep_center_requested = pyqtSignal(str, str, bool, list)
    start_all_requested = pyqtSignal()
    stop_all_requested = pyqtSignal()
    save_tracks_requested = pyqtSignal(str, str, str)
    track_toggle_requested = pyqtSignal(str, str, bool)
    color_changed = pyqtSignal(str, str, str)
    symbol_changed = pyqtSignal(str, dict)
    vessel_profiles_updated = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__("QGIS UDP Nav", parent)
        self.setObjectName("QgisUdpNavDock")
        self.setMinimumWidth(320)
        self.resize(420, 760)

        self._rows_by_feed: Dict[str, dict] = {}
        self._sentence_logs: Dict[str, list[str]] = {}
        self._sentence_snapshots: Dict[str, Dict[str, str]] = {}
        self._active_debug_feed_id: Optional[str] = None
        self._vessel_profiles: Dict[str, dict] = {}
        self._keep_center_enabled = False
        self._keep_center_feed_id = ""
        self._keep_center_role = "vessel"
        self._group_source_ids: Set[str] = set()
        self._max_log_lines = 600

        root = QWidget(self)
        root_layout = QVBoxLayout(root)

        button_grid = QGridLayout()
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.setHorizontalSpacing(4)
        button_grid.setVerticalSpacing(4)

        self._add_button = QPushButton("Add")
        self._edit_button = QPushButton("Edit")
        self._remove_button = QPushButton("Remove")
        self._symbol_button = QPushButton("Symbol")
        self._color_button = QPushButton("Color")
        self._start_button = QPushButton("Start")
        self._stop_button = QPushButton("Stop")
        self._start_all_button = QPushButton("Start All")
        self._stop_all_button = QPushButton("Stop All")
        self._keep_vessel_center_button = QPushButton("Keep Vessel Center")
        self._keep_vessel_center_button.setCheckable(True)
        self._keep_vehicle_center_button = QPushButton("Keep Vehicle Center")
        self._keep_vehicle_center_button.setCheckable(True)
        self._keep_group_center_button = QPushButton("Keep Group Center")
        self._keep_group_center_button.setCheckable(True)
        self._track_vessel_button = QPushButton("Track Vessel")
        self._track_vessel_button.setCheckable(True)
        self._track_vehicle_button = QPushButton("Track Vehicle")
        self._track_vehicle_button.setCheckable(True)
        self._group_options_button = QPushButton("Group Sources")
        self._save_tracks_button = QPushButton("Save Tracks")
        self._info_cards_button = QPushButton("Info Cards")
        self._info_cards_button.setCheckable(True)
        self._group_menu = QMenu(self)
        self._group_options_button.setMenu(self._group_menu)
        self._group_options_button.setToolTip(
            "Choose which live sources are included in Group center."
        )

        self._keep_vessel_center_button.setToolTip(
            "Continuously center map on vessel position for selected feed."
        )
        self._keep_vehicle_center_button.setToolTip(
            "Continuously center map on vehicle position for selected feed."
        )
        self._keep_group_center_button.setToolTip(
            "Continuously center map on the average of selected Group sources."
        )
        self._track_vessel_button.setToolTip(
            "Enable/disable vessel track drawing for selected feed."
        )
        self._track_vehicle_button.setToolTip(
            "Enable/disable vehicle track drawing for selected feed (split mode)."
        )
        self._save_tracks_button.setToolTip(
            "Save active vessel/vehicle tracks to the persistent saved-tracks layer."
        )
        self._track_vessel_button.setEnabled(False)
        self._track_vehicle_button.setEnabled(False)
        self._save_tracks_button.setEnabled(False)

        button_grid.addWidget(self._add_button, 0, 0)
        button_grid.addWidget(self._edit_button, 0, 1)
        button_grid.addWidget(self._remove_button, 0, 2)
        button_grid.addWidget(self._symbol_button, 1, 0)
        button_grid.addWidget(self._color_button, 1, 1)
        button_grid.addWidget(self._start_button, 1, 2)
        button_grid.addWidget(self._stop_button, 2, 0)
        button_grid.addWidget(self._start_all_button, 2, 1)
        button_grid.addWidget(self._stop_all_button, 2, 2)
        button_grid.addWidget(self._keep_vessel_center_button, 3, 0)
        button_grid.addWidget(self._keep_vehicle_center_button, 3, 1)
        button_grid.addWidget(self._keep_group_center_button, 3, 2)
        button_grid.addWidget(self._group_options_button, 4, 0, 1, 2)
        button_grid.addWidget(self._info_cards_button, 4, 2)
        button_grid.addWidget(self._track_vessel_button, 5, 0)
        button_grid.addWidget(self._track_vehicle_button, 5, 1)
        button_grid.addWidget(self._save_tracks_button, 5, 2)

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            [
                "ID",
                "Name",
                "Bind",
                "Port",
                "Checksum",
                "Status",
                "Message",
                "Color",
                "Symbol",
            ]
        )
        self._table.setSelectionBehavior(_select_rows_behavior())
        self._table.setSelectionMode(_single_selection_mode())
        self._table.setEditTriggers(_no_edit_triggers())
        self._table.setWordWrap(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(1, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(2, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(3, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(4, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(5, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(6, _header_resize_mode("Stretch"))
        header.setSectionResizeMode(7, _header_resize_mode("ResizeToContents"))
        header.setSectionResizeMode(8, _header_resize_mode("ResizeToContents"))

        table_widget = QWidget(self)
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self._table)

        debug_widget = QWidget(self)
        debug_layout = QVBoxLayout(debug_widget)
        debug_layout.setContentsMargins(0, 0, 0, 0)
        debug_header = QHBoxLayout()
        debug_title = QLabel("Feed Sentence Inspector")
        self._pause_debug_button = QPushButton("Stop")
        self._pause_debug_button.setCheckable(True)
        self._pause_debug_button.setToolTip("Stop selected feed.")
        self._no_scroll_button = QPushButton("No Scroll: Off")
        self._no_scroll_button.setCheckable(True)
        self._no_scroll_button.setToolTip(
            "Show one live-updating entry per sentence type instead of appending each raw sentence."
        )
        self._clear_debug_button = QPushButton("Clear")
        debug_header.addWidget(debug_title)
        debug_header.addStretch(1)
        debug_header.addWidget(self._no_scroll_button)
        debug_header.addWidget(self._pause_debug_button)
        debug_header.addWidget(self._clear_debug_button)
        self._debug_output = QPlainTextEdit(self)
        self._debug_output.setReadOnly(True)
        self._debug_output.setPlaceholderText(
            "Select a feed row to inspect raw sentences received on that UDP feed."
        )
        self._debug_output.document().setMaximumBlockCount(self._max_log_lines)
        debug_layout.addLayout(debug_header)
        debug_layout.addWidget(self._debug_output)

        splitter = QSplitter(_vertical_orientation(), self)
        splitter.addWidget(table_widget)
        splitter.addWidget(debug_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)

        self._info_cards_widget = QWidget(self)
        info_layout = QHBoxLayout(self._info_cards_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)

        self._heading_card = QLabel("Heading\n--")
        self._speed_card = QLabel("Speed\n--")
        self._depth_card = QLabel("Depth\n--")
        self._track_raw_card = QLabel("Track Raw\n--")
        self._track_smooth_card = QLabel("Track Smooth\n--")
        for card in (
            self._heading_card,
            self._speed_card,
            self._depth_card,
            self._track_raw_card,
            self._track_smooth_card,
        ):
            card.setAlignment(_align_center_flag())
            card.setMinimumHeight(54)
            card.setWordWrap(True)
            info_layout.addWidget(card, 1)

        self._apply_info_cards_theme()

        self._info_cards_widget.setVisible(False)

        root_layout.addLayout(button_grid)
        root_layout.addWidget(splitter)
        root_layout.addWidget(self._info_cards_widget)

        self.setWidget(root)

        self._add_button.clicked.connect(self._on_add_clicked)
        self._edit_button.clicked.connect(self._on_edit_clicked)
        self._remove_button.clicked.connect(self._on_remove_clicked)
        self._symbol_button.clicked.connect(self._on_symbol_clicked)
        self._color_button.clicked.connect(self._on_color_clicked)
        self._start_button.clicked.connect(self._on_start_clicked)
        self._stop_button.clicked.connect(self._on_stop_clicked)
        self._keep_vessel_center_button.toggled.connect(self._on_keep_vessel_center_toggled)
        self._keep_vehicle_center_button.toggled.connect(self._on_keep_vehicle_center_toggled)
        self._keep_group_center_button.toggled.connect(
            self._on_keep_group_center_toggled
        )
        self._track_vessel_button.toggled.connect(self._on_track_vessel_toggled)
        self._track_vehicle_button.toggled.connect(self._on_track_vehicle_toggled)
        self._group_menu.aboutToShow.connect(self._refresh_group_sources)
        self._info_cards_button.toggled.connect(self._on_info_cards_toggled)
        self._save_tracks_button.clicked.connect(self._on_save_tracks_clicked)
        self._start_all_button.clicked.connect(self.start_all_requested)
        self._stop_all_button.clicked.connect(self.stop_all_requested)
        self._pause_debug_button.toggled.connect(self._on_pause_toggled)
        self._no_scroll_button.toggled.connect(self._on_no_scroll_toggled)
        self._clear_debug_button.clicked.connect(self._on_clear_debug_clicked)
        self._table.itemSelectionChanged.connect(self._refresh_debug_panel)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        palette_change = _event_type("PaletteChange")
        app_palette_change = _event_type("ApplicationPaletteChange")
        style_change = _event_type("StyleChange")
        if event.type() in {palette_change, app_palette_change, style_change}:
            self._apply_info_cards_theme()

    def set_rows(self, rows: list[dict]) -> None:
        selected_feed = self._selected_feed_id()

        self._table.setRowCount(0)
        self._rows_by_feed.clear()

        for row_data in rows:
            row_index = self._table.rowCount()
            self._table.insertRow(row_index)

            feed_id = row_data.get("feed_id", "")
            self._rows_by_feed[feed_id] = dict(row_data)

            icon_path = row_data.get("icon_path") or ""
            symbol_display = row_data.get("symbol_summary") or ""
            if not symbol_display and icon_path:
                symbol_display = os.path.basename(icon_path)

            values = [
                feed_id,
                row_data.get("name", ""),
                row_data.get("bind_host", ""),
                str(row_data.get("port", "")),
                row_data.get("checksum_policy", ""),
                row_data.get("status", ""),
                row_data.get("message", ""),
                row_data.get("color_hex", ""),
                symbol_display,
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._table.setItem(row_index, col, item)

            log_feed_id = str(row_data.get("parent_feed_id") or feed_id)
            if log_feed_id not in self._sentence_logs:
                self._sentence_logs[log_feed_id] = []
            if log_feed_id not in self._sentence_snapshots:
                self._sentence_snapshots[log_feed_id] = {}

        self._prune_group_sources_from_rows()

        if selected_feed:
            self._select_feed_row(selected_feed)
        if self._selected_feed_id() is None and self._table.rowCount() > 0:
            self._table.selectRow(0)

        self._refresh_debug_panel()

    def set_vessel_profiles(self, profiles: dict) -> None:
        safe_profiles: Dict[str, dict] = {}
        if isinstance(profiles, dict):
            for name, payload in profiles.items():
                profile_name = str(name).strip()
                if not profile_name or not isinstance(payload, dict):
                    continue
                safe_profiles[profile_name] = dict(payload)
        self._vessel_profiles = safe_profiles

    def update_status(self, feed_id: str, level: str, message: str) -> None:
        row_index = self._row_index_for_feed(feed_id)
        if row_index is None:
            return

        self._table.setItem(row_index, 5, QTableWidgetItem(level))
        self._table.setItem(row_index, 6, QTableWidgetItem(message))

        if feed_id in self._rows_by_feed:
            self._rows_by_feed[feed_id]["status"] = level
            self._rows_by_feed[feed_id]["message"] = message

        self._sync_stop_button_state_from_selected_row()

    def _row_index_for_feed(self, feed_id: str) -> Optional[int]:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text() == feed_id:
                return row
        return None

    def _selected_feed_id(self) -> Optional[str]:
        selected = self._table.selectedItems()
        if not selected:
            return None

        row = selected[0].row()
        item = self._table.item(row, 0)
        if item is None:
            return None
        return item.text()

    def _selected_row_data(self) -> Optional[dict]:
        feed_id = self._selected_feed_id()
        if not feed_id:
            return None
        return self._rows_by_feed.get(feed_id)

    def _selected_base_feed_id(self) -> Optional[str]:
        feed_id = self._selected_feed_id()
        if not feed_id:
            return None
        row_data = self._rows_by_feed.get(feed_id, {})
        parent_feed_id = str(row_data.get("parent_feed_id") or "").strip()
        return parent_feed_id or feed_id

    def _selected_subfeed_role(self) -> str:
        row_data = self._selected_row_data() or {}
        role = str(row_data.get("subfeed_role") or "").strip().lower()
        if role in {"vessel", "vehicle"}:
            return role
        return ""

    def _selected_log_feed_id(self) -> Optional[str]:
        feed_id = self._selected_feed_id()
        if not feed_id:
            return None
        row_data = self._rows_by_feed.get(feed_id, {})
        parent_feed_id = str(row_data.get("parent_feed_id") or "").strip()
        return parent_feed_id or feed_id

    def _select_feed_row(self, feed_id: str) -> None:
        row_index = self._row_index_for_feed(feed_id)
        if row_index is None:
            return
        self._table.selectRow(row_index)

    def append_sentence(self, feed_id: str, line: str) -> None:
        lines = self._sentence_logs.setdefault(feed_id, [])
        lines.append(line)
        if len(lines) > self._max_log_lines:
            del lines[: len(lines) - self._max_log_lines]

        self._update_sentence_snapshot(feed_id, line)

        if self._selected_log_feed_id() != feed_id:
            return

        scrollbar = self._debug_output.verticalScrollBar()
        follow_tail = self._should_follow_tail()
        previous_value = scrollbar.value()

        if self._no_scroll_button.isChecked():
            self._debug_output.setPlainText(self._snapshot_text_for_feed(feed_id))
        else:
            self._debug_output.appendPlainText(line)

        if follow_tail:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(previous_value, scrollbar.maximum()))

    def _refresh_debug_panel(self) -> None:
        self._sync_stop_button_state_from_selected_row()
        self._sync_keep_center_button_state()
        feed_id = self._selected_log_feed_id()
        if not feed_id:
            self._active_debug_feed_id = None
            self._debug_output.clear()
            self._debug_output.setPlaceholderText(
                "Select a feed row to inspect raw sentences received on that UDP feed."
            )
            self._refresh_info_cards()
            return

        is_feed_switch = feed_id != self._active_debug_feed_id
        scrollbar = self._debug_output.verticalScrollBar()
        follow_tail = True if is_feed_switch else self._should_follow_tail()
        previous_value = scrollbar.value()

        self._debug_output.setPlaceholderText("")
        if self._no_scroll_button.isChecked():
            self._debug_output.setPlainText(self._snapshot_text_for_feed(feed_id))
        else:
            lines = self._sentence_logs.get(feed_id, [])
            self._debug_output.setPlainText("\n".join(lines))

        if follow_tail:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(previous_value, scrollbar.maximum()))

        self._active_debug_feed_id = feed_id
        self._refresh_info_cards()

    def _on_clear_debug_clicked(self) -> None:
        feed_id = self._selected_log_feed_id()
        if not feed_id:
            return

        self._sentence_logs[feed_id] = []
        self._sentence_snapshots[feed_id] = {}
        self._refresh_debug_panel()

    def _on_save_tracks_clicked(self) -> None:
        base_feed_id = self._selected_base_feed_id()
        if not base_feed_id:
            return

        planned_number, planned_ok = QInputDialog.getText(
            self,
            "Save Tracks",
            "Planned Number:",
            text="",
        )
        if not planned_ok:
            return

        actual_number, actual_ok = QInputDialog.getText(
            self,
            "Save Tracks",
            "Actual Number:",
            text="",
        )
        if not actual_ok:
            return

        self.save_tracks_requested.emit(
            base_feed_id,
            str(planned_number or "").strip(),
            str(actual_number or "").strip(),
        )

    def _on_pause_toggled(self, paused: bool) -> None:
        feed_id = self._selected_base_feed_id()
        if not feed_id:
            blocker = self._pause_debug_button.blockSignals(True)
            self._pause_debug_button.setChecked(False)
            self._pause_debug_button.blockSignals(blocker)
            self._sync_stop_button_state_from_selected_row()
            return

        if bool(paused):
            self.feed_stop_requested.emit(feed_id)
            self._pause_debug_button.setText("Start")
            self._pause_debug_button.setToolTip("Start selected feed.")
            return

        self.feed_start_requested.emit(feed_id)
        self._pause_debug_button.setText("Stop")
        self._pause_debug_button.setToolTip("Stop selected feed.")

    def _on_no_scroll_toggled(self, enabled: bool) -> None:
        if enabled:
            self._no_scroll_button.setText("No Scroll: On")
        else:
            self._no_scroll_button.setText("No Scroll: Off")
        self._refresh_debug_panel()

    def _on_keep_vessel_center_toggled(self, enabled: bool) -> None:
        self._on_keep_center_mode_toggled("vessel", enabled)

    def _on_keep_vehicle_center_toggled(self, enabled: bool) -> None:
        self._on_keep_center_mode_toggled("vehicle", enabled)

    def _on_keep_group_center_toggled(self, enabled: bool) -> None:
        self._on_keep_center_mode_toggled("group", enabled)

    def _on_track_vessel_toggled(self, enabled: bool) -> None:
        self._on_track_mode_toggled("vessel", enabled)

    def _on_track_vehicle_toggled(self, enabled: bool) -> None:
        self._on_track_mode_toggled("vehicle", enabled)

    def _on_track_mode_toggled(self, mode: str, enabled: bool) -> None:
        base_feed_id = self._selected_base_feed_id()
        if not base_feed_id:
            self._set_track_mode_button_checked(mode, False)
            self._sync_keep_center_button_state()
            return

        base_row = self._rows_by_feed.get(base_feed_id, {})
        split_enabled = bool(base_row.get("split_subfeeds_enabled", False))
        if mode == "vehicle" and not split_enabled:
            self._set_track_mode_button_checked("vehicle", False)
            self._sync_keep_center_button_state()
            return

        self.track_toggle_requested.emit(base_feed_id, mode, bool(enabled))

    def _on_keep_center_mode_toggled(self, mode: str, enabled: bool) -> None:
        if not enabled:
            if self._keep_center_enabled and self._keep_center_role == mode:
                disable_feed_id = self._keep_center_feed_id if mode in {"vessel", "vehicle"} else ""
                self.keep_center_requested.emit(
                    disable_feed_id,
                    mode,
                    False,
                    self._group_selected_sources_payload(),
                )
                self._keep_center_enabled = False
                self._keep_center_feed_id = ""
                self._keep_center_role = "vessel"
            self._sync_keep_center_button_state()
            return

        if mode in {"vessel", "vehicle"}:
            base_feed_id = self._selected_base_feed_id()
            if not base_feed_id:
                self._set_keep_center_mode_button_checked(mode, False)
                self._sync_keep_center_button_state()
                return

            self._keep_center_enabled = True
            self._keep_center_feed_id = base_feed_id
            self._keep_center_role = mode
            self.keep_center_requested.emit(base_feed_id, mode, True, [])
            self._sync_keep_center_button_state()
            return

        selected_sources = self._group_selected_sources_payload()
        if not selected_sources:
            QMessageBox.information(
                self,
                "Group Sources",
                "Select at least one group source before enabling center tracking.",
            )
            self._set_keep_center_mode_button_checked("group", False)
            self._sync_keep_center_button_state()
            return

        self._keep_center_enabled = True
        self._keep_center_feed_id = ""
        self._keep_center_role = "group"
        self.keep_center_requested.emit("", "group", True, selected_sources)
        self._sync_keep_center_button_state()

    def _on_group_source_toggled(self, source_id: str, checked: bool) -> None:
        previous_selected = set(self._group_source_ids)
        if checked:
            self._group_source_ids.add(source_id)
        else:
            self._group_source_ids.discard(source_id)
        self._handle_group_sources_changed(previous_selected)

    def _set_all_group_sources(self, checked: bool) -> None:
        previous_selected = set(self._group_source_ids)
        source_ids = {source_id for source_id, _ in self._group_candidates()}
        if checked:
            self._group_source_ids = set(source_ids)
        else:
            self._group_source_ids.clear()

        for action in self._group_menu.actions():
            source_id = action.data()
            if not isinstance(source_id, str) or not source_id:
                continue
            blocker = action.blockSignals(True)
            action.setChecked(source_id in self._group_source_ids)
            action.blockSignals(blocker)

        self._handle_group_sources_changed(previous_selected)

    def _prune_group_sources_from_rows(self) -> None:
        available_ids = {source_id for source_id, _ in self._group_candidates()}
        previous_selected = set(self._group_source_ids)
        self._group_source_ids = {
            source_id for source_id in self._group_source_ids if source_id in available_ids
        }

        if previous_selected != self._group_source_ids:
            self._handle_group_sources_changed(previous_selected)
            return

        # Keep button enabled/disabled state in sync with changing rows without
        # rebuilding the popup menu while live data is streaming.
        self._sync_keep_center_button_state()

    def _refresh_group_sources(self) -> None:
        candidates = self._group_candidates()
        available_ids = {source_id for source_id, _ in candidates}
        previous_selected = set(self._group_source_ids)
        self._group_source_ids = {
            source_id for source_id in self._group_source_ids if source_id in available_ids
        }

        self._group_menu.clear()
        if not candidates:
            empty_action = self._group_menu.addAction("No sources available")
            empty_action.setEnabled(False)
            self._handle_group_sources_changed(previous_selected)
            return

        select_all_action = self._group_menu.addAction("Select All")
        select_all_action.triggered.connect(
            lambda _checked=False: self._set_all_group_sources(True)
        )
        clear_all_action = self._group_menu.addAction("Clear All")
        clear_all_action.triggered.connect(
            lambda _checked=False: self._set_all_group_sources(False)
        )
        self._group_menu.addSeparator()

        for source_id, label in candidates:
            action = self._group_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(source_id in self._group_source_ids)
            action.setData(source_id)
            action.toggled.connect(
                lambda checked, sid=source_id: self._on_group_source_toggled(sid, checked)
            )

        self._handle_group_sources_changed(previous_selected)

    def _handle_group_sources_changed(self, previous_selected: Set[str]) -> None:
        self._update_group_options_button_text()

        if self._keep_center_enabled and self._keep_center_role == "group":
            selected_sources = self._group_selected_sources_payload()
            if selected_sources:
                if previous_selected != self._group_source_ids:
                    self.keep_center_requested.emit("", "group", True, selected_sources)
            else:
                self.keep_center_requested.emit("", "group", False, [])
                self._keep_center_enabled = False
                self._keep_center_feed_id = ""
                self._keep_center_role = "vessel"

        self._sync_keep_center_button_state()

    def _update_group_options_button_text(self) -> None:
        total = len(self._group_candidates())
        selected = len(self._group_source_ids)
        if total <= 0:
            self._group_options_button.setText("Group Sources")
            return
        self._group_options_button.setText(f"Group Sources ({selected}/{total})")

    def _group_candidates(self) -> List[tuple[str, str]]:
        candidates: List[tuple[str, str]] = []
        for source_id, row_data in self._rows_by_feed.items():
            row_kind = str(row_data.get("row_kind") or "").strip().lower()
            include = False
            if row_kind == "subfeed":
                include = True
            elif row_kind == "feed" and not bool(row_data.get("split_subfeeds_enabled", False)):
                include = True

            if not include:
                continue

            if row_kind == "subfeed":
                parent_id = str(row_data.get("parent_feed_id") or "").strip()
                parent_name = str(
                    self._rows_by_feed.get(parent_id, {}).get("name") or parent_id or source_id
                ).strip()
                role = str(row_data.get("subfeed_role") or "source").strip().capitalize()
                label = f"{parent_name} - {role}"
            else:
                label = str(row_data.get("name") or source_id).strip()

            candidates.append((source_id, label))

        candidates.sort(key=lambda item: (item[1].lower(), item[0]))
        return candidates

    def _group_selected_sources_payload(self) -> list[str]:
        return sorted(self._group_source_ids)

    def _set_keep_center_mode_button_checked(self, mode: str, checked: bool) -> None:
        button_map = {
            "vessel": self._keep_vessel_center_button,
            "vehicle": self._keep_vehicle_center_button,
            "group": self._keep_group_center_button,
        }
        button = button_map.get(mode)
        if button is None:
            return
        blocker = button.blockSignals(True)
        button.setChecked(bool(checked))
        button.blockSignals(blocker)

    def _set_track_mode_button_checked(self, mode: str, checked: bool) -> None:
        button_map = {
            "vessel": self._track_vessel_button,
            "vehicle": self._track_vehicle_button,
        }
        button = button_map.get(mode)
        if button is None:
            return

        blocker = button.blockSignals(True)
        button.setChecked(bool(checked))
        button.blockSignals(blocker)

    def _on_info_cards_toggled(self, enabled: bool) -> None:
        self._info_cards_widget.setVisible(bool(enabled))
        if enabled:
            self._info_cards_button.setText("Info Cards: On")
        else:
            self._info_cards_button.setText("Info Cards")
        self._apply_info_cards_theme()
        self._refresh_info_cards()

    def _apply_info_cards_theme(self) -> None:
        palette = self.palette()

        window_color = _palette_color(palette, "Window", QColor("#ffffff"))
        base_color = _palette_color(palette, "Base", window_color)
        text_color = _palette_color(palette, "Text", QColor("#111827"))
        border_color = _palette_color(palette, "Mid", text_color)

        if window_color.lightnessF() < 0.5:
            card_background = base_color.lighter(112)
            card_border = border_color.lighter(118)
        else:
            card_background = base_color.darker(102)
            card_border = border_color.darker(105)

        card_style = (
            "QLabel {"
            f"border: 1px solid {_qcolor_css(card_border)};"
            "border-radius: 4px;"
            f"background-color: {_qcolor_css(card_background)};"
            f"color: {_qcolor_css(text_color)};"
            "padding: 4px 8px;"
            "font-weight: 600;"
            "font-size: 11px;"
            "}"
        )

        for card in (
            self._heading_card,
            self._speed_card,
            self._depth_card,
            self._track_raw_card,
            self._track_smooth_card,
        ):
            card.setStyleSheet(card_style)

    def _refresh_info_cards(self) -> None:
        if not self._info_cards_widget.isVisible():
            return

        row_data = self._selected_row_data() or {}
        role = str(row_data.get("subfeed_role") or "").strip().lower()

        heading = row_data.get("heading_deg")
        heading_source = str(row_data.get("heading_source") or "").strip()
        speed_knots = row_data.get("speed_knots")
        depth_m = row_data.get("depth_m")
        track_enabled = bool(row_data.get("track_enabled", False))
        track_dimension = str(row_data.get("track_dimension") or "2d").strip().lower()
        track_raw_m = row_data.get("track_raw_m")
        track_smoothed_m = row_data.get("track_smoothed_m")

        if isinstance(heading, (int, float)):
            heading_text = f"Heading\n{float(heading):.1f} deg"
            if heading_source:
                heading_text += f"\n{heading_source}"
        else:
            heading_text = "Heading\n--"

        if isinstance(speed_knots, (int, float)):
            speed_text = f"Speed\n{float(speed_knots):.2f} kn"
        else:
            speed_text = "Speed\n--"

        if role == "vehicle":
            if isinstance(depth_m, (int, float)):
                depth_text = f"Depth\n{float(depth_m):.2f} m"
            else:
                depth_text = "Depth\n--"
        else:
            if isinstance(depth_m, (int, float)):
                depth_text = f"Depth\n{float(depth_m):.2f} m"
            else:
                depth_text = "Depth\nn/a"

        track_suffix = "3D" if track_dimension == "3d" else "2D"
        if not track_enabled:
            track_raw_text = f"Track Raw {track_suffix}\noff"
            track_smooth_text = f"Track Smooth {track_suffix}\noff"
        else:
            if isinstance(track_raw_m, (int, float)):
                track_raw_text = f"Track Raw {track_suffix}\n{float(track_raw_m):.1f} m"
            else:
                track_raw_text = f"Track Raw {track_suffix}\n--"

            if isinstance(track_smoothed_m, (int, float)):
                track_smooth_text = (
                    f"Track Smooth {track_suffix}\n{float(track_smoothed_m):.1f} m"
                )
            else:
                track_smooth_text = f"Track Smooth {track_suffix}\n--"

        self._heading_card.setText(heading_text)
        self._speed_card.setText(speed_text)
        self._depth_card.setText(depth_text)
        self._track_raw_card.setText(track_raw_text)
        self._track_smooth_card.setText(track_smooth_text)

    def _sync_keep_center_button_state(self) -> None:
        base_feed_id = self._selected_base_feed_id()
        has_base_feed = bool(base_feed_id)
        has_group_sources = len(self._group_candidates()) > 0
        base_row = self._rows_by_feed.get(base_feed_id, {}) if has_base_feed else {}

        split_enabled = bool(base_row.get("split_subfeeds_enabled", False))
        vessel_track_enabled = bool(base_row.get("vessel_track_enabled", False))
        vehicle_track_enabled = bool(base_row.get("vehicle_track_enabled", False)) and split_enabled

        self._keep_vessel_center_button.setEnabled(has_base_feed)
        self._keep_vehicle_center_button.setEnabled(has_base_feed)
        self._keep_group_center_button.setEnabled(has_group_sources)
        self._track_vessel_button.setEnabled(has_base_feed)
        self._track_vehicle_button.setEnabled(has_base_feed and split_enabled)
        self._save_tracks_button.setEnabled(has_base_feed)

        self._set_track_mode_button_checked("vessel", vessel_track_enabled)
        self._set_track_mode_button_checked("vehicle", vehicle_track_enabled)
        self._track_vessel_button.setText(
            "Track Vessel: On" if vessel_track_enabled else "Track Vessel"
        )
        self._track_vehicle_button.setText(
            "Track Vehicle: On" if vehicle_track_enabled else "Track Vehicle"
        )

        vessel_active = (
            self._keep_center_enabled
            and self._keep_center_role == "vessel"
            and has_base_feed
            and self._keep_center_feed_id == base_feed_id
        )
        vehicle_active = (
            self._keep_center_enabled
            and self._keep_center_role == "vehicle"
            and has_base_feed
            and self._keep_center_feed_id == base_feed_id
        )
        group_active = self._keep_center_enabled and self._keep_center_role == "group"

        self._set_keep_center_mode_button_checked("vessel", vessel_active)
        self._set_keep_center_mode_button_checked("vehicle", vehicle_active)
        self._set_keep_center_mode_button_checked("group", group_active)

        self._keep_vessel_center_button.setText(
            "Centering Vessel" if vessel_active else "Keep Vessel Center"
        )
        self._keep_vehicle_center_button.setText(
            "Centering Vehicle" if vehicle_active else "Keep Vehicle Center"
        )
        self._keep_group_center_button.setText(
            "Centering Group"
            if group_active
            else "Keep Group Center"
        )
        self._update_group_options_button_text()

    def _sync_stop_button_state_from_selected_row(self) -> None:
        base_feed_id = self._selected_base_feed_id()
        if not base_feed_id:
            self._pause_debug_button.setEnabled(False)
            return

        self._pause_debug_button.setEnabled(True)
        row = self._rows_by_feed.get(base_feed_id, {})
        status = str(row.get("status", "")).strip().lower()
        message = str(row.get("message", "")).strip().lower()
        is_stopped = status == "idle" and (not message or "stopped" in message)

        blocker = self._pause_debug_button.blockSignals(True)
        self._pause_debug_button.setChecked(is_stopped)
        self._pause_debug_button.blockSignals(blocker)
        if is_stopped:
            self._pause_debug_button.setText("Start")
            self._pause_debug_button.setToolTip("Start selected feed.")
        else:
            self._pause_debug_button.setText("Stop")
            self._pause_debug_button.setToolTip("Stop selected feed.")

    def _should_follow_tail(self) -> bool:
        scrollbar = self._debug_output.verticalScrollBar()
        # Keep auto-follow only if the user is already at the tail.
        return scrollbar.value() >= (scrollbar.maximum() - 2)

    def _update_sentence_snapshot(self, feed_id: str, line: str) -> None:
        sentence = self._extract_sentence_part(line)
        if not sentence:
            return

        sentence_id = self._sentence_identifier(sentence)
        if not sentence_id:
            return

        snapshots = self._sentence_snapshots.setdefault(feed_id, {})
        snapshots[sentence_id] = line

    @staticmethod
    def _extract_sentence_part(line: str) -> str:
        marker = "] "
        marker_idx = line.find(marker)
        if marker_idx >= 0:
            return line[marker_idx + len(marker):].strip()
        return line.strip()

    @staticmethod
    def _sentence_identifier(sentence: str) -> str:
        text = sentence.strip()
        if not text:
            return ""
        if text[0] in {"$", "!"}:
            text = text[1:]
        head = text.split(",", 1)[0]
        head = head.split("*", 1)[0]
        return head.strip().upper()

    def _snapshot_text_for_feed(self, feed_id: str) -> str:
        snapshots = self._sentence_snapshots.get(feed_id, {})
        if not snapshots:
            return "Waiting for sentences..."

        return "\n".join(snapshots.values())

    def _on_add_clicked(self) -> None:
        dialog = FeedConfigDialog(self)
        if _dialog_exec(dialog) != _dialog_accepted_code():
            return

        try:
            payload = dialog.payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Feed", str(exc))
            return

        self.feed_added.emit(payload)

    def _on_edit_clicked(self) -> None:
        feed_id = self._selected_base_feed_id()
        if not feed_id:
            return

        initial = self._rows_by_feed.get(feed_id, {})
        dialog = FeedConfigDialog(self, initial=initial)
        if _dialog_exec(dialog) != _dialog_accepted_code():
            return

        try:
            payload = dialog.payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Feed", str(exc))
            return

        self.feed_updated.emit(feed_id, payload)

    def _on_remove_clicked(self) -> None:
        feed_id = self._selected_base_feed_id()
        if not feed_id:
            return

        confirm = QMessageBox.question(
            self,
            "Remove Feed",
            f"Remove feed {feed_id}?",
        )
        if int(confirm) == _messagebox_yes_code():
            self._sentence_logs.pop(feed_id, None)
            self._sentence_snapshots.pop(feed_id, None)
            if self._keep_center_enabled and self._keep_center_feed_id == feed_id:
                self.keep_center_requested.emit(
                    self._keep_center_feed_id,
                    self._keep_center_role,
                    False,
                    self._group_selected_sources_payload(),
                )
                self._keep_center_enabled = False
                self._keep_center_feed_id = ""
                self._keep_center_role = "vessel"
            self.feed_removed.emit(feed_id)

    def _on_symbol_clicked(self) -> None:
        selected_feed_id = self._selected_feed_id()
        base_feed_id = self._selected_base_feed_id()
        if not selected_feed_id or not base_feed_id:
            return

        selected_row = self._rows_by_feed.get(selected_feed_id, {})
        base_row = self._rows_by_feed.get(base_feed_id, selected_row)

        target_role = self._selected_subfeed_role() or "vessel"
        if not self._selected_subfeed_role() and bool(base_row.get("split_subfeeds_enabled", False)):
            role_text, ok = QInputDialog.getItem(
                self,
                "Select Subfeed",
                "Configure symbol for:",
                ["Vessel", "Vehicle"],
                0,
                False,
            )
            if not ok:
                return
            target_role = "vehicle" if role_text == "Vehicle" else "vessel"

        dialog = SymbolPickerDialog(
            self,
            initial=self._symbol_initial_for_role(base_row, target_role),
            vessel_profiles=self._vessel_profiles,
        )
        if _dialog_exec(dialog) != _dialog_accepted_code():
            return

        payload = dialog.payload()
        payload["symbol_target_role"] = target_role
        self.symbol_changed.emit(base_feed_id, payload)

        if dialog.profiles_changed():
            updated_profiles = dialog.updated_profiles()
            self._vessel_profiles = updated_profiles
            self.vessel_profiles_updated.emit(updated_profiles)

    @staticmethod
    def _symbol_initial_for_role(row_data: dict, role: str) -> dict:
        initial = dict(row_data)
        if role != "vehicle":
            return initial

        initial["symbol_mode"] = row_data.get("vehicle_symbol_mode", row_data.get("symbol_mode", "qgis"))
        initial["icon_path"] = row_data.get("vehicle_icon_path", row_data.get("icon_path", ""))
        initial["vessel_length_m"] = row_data.get(
            "vehicle_vessel_length_m",
            row_data.get("vessel_length_m", 4.0),
        )
        initial["vessel_width_m"] = row_data.get(
            "vehicle_vessel_width_m",
            row_data.get("vessel_width_m", 2.0),
        )
        initial["vessel_gps_longitudinal_reference"] = row_data.get(
            "vehicle_vessel_gps_longitudinal_reference",
            row_data.get("vessel_gps_longitudinal_reference", "bow"),
        )
        initial["vessel_gps_offset_from_reference_m"] = row_data.get(
            "vehicle_vessel_gps_offset_from_reference_m",
            row_data.get("vessel_gps_offset_from_reference_m", 0.0),
        )
        initial["vessel_gps_offset_starboard_m"] = row_data.get(
            "vehicle_vessel_gps_offset_starboard_m",
            row_data.get("vessel_gps_offset_starboard_m", 0.0),
        )
        initial["qgis_symbol_name"] = row_data.get(
            "vehicle_qgis_symbol_name",
            row_data.get("qgis_symbol_name", "diamond"),
        )
        initial["qgis_symbol_width"] = row_data.get(
            "vehicle_qgis_symbol_width",
            row_data.get("qgis_symbol_width", 7.0),
        )
        initial["qgis_symbol_height"] = row_data.get(
            "vehicle_qgis_symbol_height",
            row_data.get("qgis_symbol_height", 7.0),
        )
        initial["qgis_size_unit"] = row_data.get(
            "vehicle_qgis_size_unit",
            row_data.get("qgis_size_unit", "screen"),
        )
        initial["unicode_symbol"] = row_data.get(
            "vehicle_unicode_symbol",
            row_data.get("unicode_symbol", "\u26f5"),
        )
        initial["unicode_font_family"] = row_data.get(
            "vehicle_unicode_font_family",
            row_data.get("unicode_font_family", "Noto Sans Symbols 2"),
        )
        initial["color_hex"] = row_data.get(
            "vehicle_color_hex",
            row_data.get("color_hex", "#00b8ff"),
        )
        return initial

    def _on_color_clicked(self) -> None:
        selected_feed_id = self._selected_feed_id()
        base_feed_id = self._selected_base_feed_id()
        if not selected_feed_id or not base_feed_id:
            return

        selected_row = self._rows_by_feed.get(selected_feed_id, {})
        base_row = self._rows_by_feed.get(base_feed_id, selected_row)

        selected_role = self._selected_subfeed_role()
        target_role = selected_role or "vessel"
        if not selected_role and bool(base_row.get("split_subfeeds_enabled", False)):
            role_text, ok = QInputDialog.getItem(
                self,
                "Select Subfeed",
                "Set color for:",
                ["Vessel", "Vehicle"],
                0,
                False,
            )
            if not ok:
                return
            target_role = "vehicle" if role_text == "Vehicle" else "vessel"

        if target_role == "vehicle":
            current_hex = (
                str(base_row.get("vehicle_color_hex", "")).strip()
                or str(selected_row.get("color_hex", "")).strip()
                or "#00b8ff"
            )
            title = "Pick Vehicle Color"
        else:
            current_hex = str(base_row.get("color_hex", "#ff4500")).strip() or "#ff4500"
            title = "Pick Vessel Color"

        color = QColorDialog.getColor(QColor(current_hex), self, title)
        if not color.isValid():
            return

        self.color_changed.emit(base_feed_id, target_role, color.name())

    def _on_start_clicked(self) -> None:
        feed_id = self._selected_base_feed_id()
        if feed_id:
            self.feed_start_requested.emit(feed_id)

    def _on_stop_clicked(self) -> None:
        feed_id = self._selected_base_feed_id()
        if feed_id:
            self.feed_stop_requested.emit(feed_id)
