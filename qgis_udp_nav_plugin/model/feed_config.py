from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

CHECKSUM_POLICIES = {"lenient", "strict", "ignore"}
SYMBOL_MODES = {"vessel", "vehicle", "qgis", "icon_file", "unicode"}
QGIS_SIZE_UNITS = {"screen", "map_meters"}
GPS_LONGITUDINAL_REFERENCES = {"bow", "stern"}
SPLIT_ROUTING_MODES = {"auto", "manual"}


def _normalize_sentence_types(value: object) -> list[str]:
    if value in (None, ""):
        return []

    tokens: Iterable[str]
    if isinstance(value, str):
        tokens = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(item) for item in value]
    else:
        tokens = [str(value)]

    normalized: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        sentence_type = str(token).strip().upper()
        if not sentence_type or sentence_type in seen:
            continue
        seen.add(sentence_type)
        normalized.append(sentence_type)
    return normalized


@dataclass
class FeedConfig:
    feed_id: str
    name: str
    bind_host: str = "0.0.0.0"
    port: int = 10110
    enabled: bool = True
    checksum_policy: str = "lenient"
    icon_path: str = ""
    symbol_mode: str = "vessel"
    vessel_length_m: float = 20.0
    vessel_width_m: float = 6.0
    vessel_gps_longitudinal_reference: str = "bow"
    vessel_gps_offset_from_reference_m: float = 0.0
    vessel_gps_offset_starboard_m: float = 0.0
    split_subfeeds_enabled: bool = False
    split_routing_mode: str = "auto"
    vehicle_show_on_vessel_when_missing_position: bool = False
    vessel_track_enabled: bool = False
    vehicle_track_enabled: bool = False
    manual_vessel_sentence_types: list[str] = field(default_factory=list)
    manual_vehicle_sentence_types: list[str] = field(default_factory=list)
    vehicle_icon_path: str = ""
    vehicle_symbol_mode: str = "qgis"
    vehicle_vessel_length_m: float = 4.0
    vehicle_vessel_width_m: float = 2.0
    vehicle_vessel_gps_longitudinal_reference: str = "bow"
    vehicle_vessel_gps_offset_from_reference_m: float = 0.0
    vehicle_vessel_gps_offset_starboard_m: float = 0.0
    vehicle_qgis_symbol_name: str = "diamond"
    vehicle_qgis_symbol_width: float = 7.0
    vehicle_qgis_symbol_height: float = 7.0
    vehicle_qgis_size_unit: str = "screen"
    vehicle_unicode_symbol: str = "\u26f5"
    vehicle_unicode_font_family: str = "Noto Sans Symbols 2"
    vehicle_color_hex: str = "#00b8ff"
    qgis_symbol_name: str = "circle"
    qgis_symbol_width: float = 7.0
    qgis_symbol_height: float = 7.0
    qgis_size_unit: str = "screen"
    unicode_symbol: str = "\u2693"
    unicode_font_family: str = "Noto Sans Symbols 2"
    color_hex: str = "#ff4500"
    hipap_utm_epsg: Optional[int] = None
    reference_lat: Optional[float] = None
    reference_lon: Optional[float] = None
    reference_heading_deg: Optional[float] = None
    stale_timeout_sec: int = 5

    def validate(self) -> None:
        if not self.feed_id:
            raise ValueError("feed_id is required")
        if not self.name:
            raise ValueError("name is required")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("port must be in range 1-65535")
        if self.checksum_policy not in CHECKSUM_POLICIES:
            raise ValueError(
                f"checksum_policy must be one of {sorted(CHECKSUM_POLICIES)}"
            )
        if self.symbol_mode not in SYMBOL_MODES:
            raise ValueError(f"symbol_mode must be one of {sorted(SYMBOL_MODES)}")
        if self.vessel_length_m <= 0:
            raise ValueError("vessel_length_m must be greater than zero")
        if self.vessel_width_m <= 0:
            raise ValueError("vessel_width_m must be greater than zero")
        if self.vessel_gps_longitudinal_reference not in GPS_LONGITUDINAL_REFERENCES:
            raise ValueError(
                "vessel_gps_longitudinal_reference must be one of "
                f"{sorted(GPS_LONGITUDINAL_REFERENCES)}"
            )
        if self.vessel_gps_offset_from_reference_m < 0:
            raise ValueError("vessel_gps_offset_from_reference_m cannot be negative")
        if self.split_routing_mode not in SPLIT_ROUTING_MODES:
            raise ValueError(
                f"split_routing_mode must be one of {sorted(SPLIT_ROUTING_MODES)}"
            )
        if self.vehicle_symbol_mode not in SYMBOL_MODES:
            raise ValueError(f"vehicle_symbol_mode must be one of {sorted(SYMBOL_MODES)}")
        if self.vehicle_vessel_length_m <= 0:
            raise ValueError("vehicle_vessel_length_m must be greater than zero")
        if self.vehicle_vessel_width_m <= 0:
            raise ValueError("vehicle_vessel_width_m must be greater than zero")
        if (
            self.vehicle_vessel_gps_longitudinal_reference
            not in GPS_LONGITUDINAL_REFERENCES
        ):
            raise ValueError(
                "vehicle_vessel_gps_longitudinal_reference must be one of "
                f"{sorted(GPS_LONGITUDINAL_REFERENCES)}"
            )
        if self.vehicle_vessel_gps_offset_from_reference_m < 0:
            raise ValueError(
                "vehicle_vessel_gps_offset_from_reference_m cannot be negative"
            )
        if self.vehicle_qgis_size_unit not in QGIS_SIZE_UNITS:
            raise ValueError(
                f"vehicle_qgis_size_unit must be one of {sorted(QGIS_SIZE_UNITS)}"
            )
        if not self.vehicle_qgis_symbol_name:
            raise ValueError("vehicle_qgis_symbol_name is required")
        if self.vehicle_qgis_symbol_width <= 0:
            raise ValueError("vehicle_qgis_symbol_width must be greater than zero")
        if self.vehicle_qgis_symbol_height <= 0:
            raise ValueError("vehicle_qgis_symbol_height must be greater than zero")
        if self.vehicle_symbol_mode == "unicode" and not self.vehicle_unicode_symbol:
            raise ValueError(
                "vehicle_unicode_symbol is required when vehicle_symbol_mode is unicode"
            )
        if not self._is_valid_color(self.vehicle_color_hex):
            raise ValueError("vehicle_color_hex must be #RGB or #RRGGBB")
        if self.qgis_size_unit not in QGIS_SIZE_UNITS:
            raise ValueError(f"qgis_size_unit must be one of {sorted(QGIS_SIZE_UNITS)}")
        if not self.qgis_symbol_name:
            raise ValueError("qgis_symbol_name is required")
        if self.qgis_symbol_width <= 0:
            raise ValueError("qgis_symbol_width must be greater than zero")
        if self.qgis_symbol_height <= 0:
            raise ValueError("qgis_symbol_height must be greater than zero")
        if self.symbol_mode == "unicode" and not self.unicode_symbol:
            raise ValueError("unicode_symbol is required when symbol_mode is unicode")
        if not self._is_valid_color(self.color_hex):
            raise ValueError("color_hex must be #RGB or #RRGGBB")
        self.manual_vessel_sentence_types = _normalize_sentence_types(
            self.manual_vessel_sentence_types
        )
        self.manual_vehicle_sentence_types = _normalize_sentence_types(
            self.manual_vehicle_sentence_types
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "name": self.name,
            "bind_host": self.bind_host,
            "port": self.port,
            "enabled": self.enabled,
            "checksum_policy": self.checksum_policy,
            "icon_path": self.icon_path,
            "symbol_mode": self.symbol_mode,
            "vessel_length_m": self.vessel_length_m,
            "vessel_width_m": self.vessel_width_m,
            "vessel_gps_longitudinal_reference": self.vessel_gps_longitudinal_reference,
            "vessel_gps_offset_from_reference_m": self.vessel_gps_offset_from_reference_m,
            "vessel_gps_offset_starboard_m": self.vessel_gps_offset_starboard_m,
            "split_subfeeds_enabled": self.split_subfeeds_enabled,
            "split_routing_mode": self.split_routing_mode,
            "vehicle_show_on_vessel_when_missing_position": self.vehicle_show_on_vessel_when_missing_position,
            "vessel_track_enabled": self.vessel_track_enabled,
            "vehicle_track_enabled": self.vehicle_track_enabled,
            "manual_vessel_sentence_types": list(self.manual_vessel_sentence_types),
            "manual_vehicle_sentence_types": list(self.manual_vehicle_sentence_types),
            "vehicle_icon_path": self.vehicle_icon_path,
            "vehicle_symbol_mode": self.vehicle_symbol_mode,
            "vehicle_vessel_length_m": self.vehicle_vessel_length_m,
            "vehicle_vessel_width_m": self.vehicle_vessel_width_m,
            "vehicle_vessel_gps_longitudinal_reference": self.vehicle_vessel_gps_longitudinal_reference,
            "vehicle_vessel_gps_offset_from_reference_m": self.vehicle_vessel_gps_offset_from_reference_m,
            "vehicle_vessel_gps_offset_starboard_m": self.vehicle_vessel_gps_offset_starboard_m,
            "vehicle_qgis_symbol_name": self.vehicle_qgis_symbol_name,
            "vehicle_qgis_symbol_width": self.vehicle_qgis_symbol_width,
            "vehicle_qgis_symbol_height": self.vehicle_qgis_symbol_height,
            "vehicle_qgis_size_unit": self.vehicle_qgis_size_unit,
            "vehicle_unicode_symbol": self.vehicle_unicode_symbol,
            "vehicle_unicode_font_family": self.vehicle_unicode_font_family,
            "vehicle_color_hex": self.vehicle_color_hex,
            "qgis_symbol_name": self.qgis_symbol_name,
            "qgis_symbol_width": self.qgis_symbol_width,
            "qgis_symbol_height": self.qgis_symbol_height,
            "qgis_size_unit": self.qgis_size_unit,
            "unicode_symbol": self.unicode_symbol,
            "unicode_font_family": self.unicode_font_family,
            "color_hex": self.color_hex,
            "hipap_utm_epsg": self.hipap_utm_epsg,
            "reference_lat": self.reference_lat,
            "reference_lon": self.reference_lon,
            "reference_heading_deg": self.reference_heading_deg,
            "stale_timeout_sec": self.stale_timeout_sec,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeedConfig":
        unicode_symbol = data.get("unicode_symbol", "\u2693")
        if unicode_symbol in (None, ""):
            unicode_symbol = "\u2693"

        unicode_font_family = data.get("unicode_font_family", "Noto Sans Symbols 2")
        if unicode_font_family in (None, ""):
            unicode_font_family = "Noto Sans Symbols 2"

        vehicle_unicode_symbol = data.get("vehicle_unicode_symbol", "\u26f5")
        if vehicle_unicode_symbol in (None, ""):
            vehicle_unicode_symbol = "\u26f5"

        vehicle_unicode_font_family = data.get(
            "vehicle_unicode_font_family", "Noto Sans Symbols 2"
        )
        if vehicle_unicode_font_family in (None, ""):
            vehicle_unicode_font_family = "Noto Sans Symbols 2"

        vessel_length_m = float(data.get("vessel_length_m", 20.0))
        longitudinal_reference = str(
            data.get("vessel_gps_longitudinal_reference", "")
        ).strip().lower()

        offset_from_reference_raw = data.get("vessel_gps_offset_from_reference_m")
        if offset_from_reference_raw in (None, ""):
            legacy_forward = float(data.get("vessel_gps_offset_forward_m", 0.0))
            (
                inferred_reference,
                inferred_offset,
            ) = cls._legacy_forward_to_reference(legacy_forward, vessel_length_m)
            if longitudinal_reference not in GPS_LONGITUDINAL_REFERENCES:
                longitudinal_reference = inferred_reference
            offset_from_reference_m = inferred_offset
        else:
            if longitudinal_reference not in GPS_LONGITUDINAL_REFERENCES:
                longitudinal_reference = "bow"
            offset_from_reference_m = float(offset_from_reference_raw)

        vehicle_vessel_length_m = float(data.get("vehicle_vessel_length_m", 4.0))
        vehicle_longitudinal_reference = str(
            data.get("vehicle_vessel_gps_longitudinal_reference", "")
        ).strip().lower()

        vehicle_offset_from_reference_raw = data.get(
            "vehicle_vessel_gps_offset_from_reference_m"
        )
        if vehicle_offset_from_reference_raw in (None, ""):
            vehicle_legacy_forward = float(
                data.get("vehicle_vessel_gps_offset_forward_m", 0.0)
            )
            (
                inferred_vehicle_reference,
                inferred_vehicle_offset,
            ) = cls._legacy_forward_to_reference(
                vehicle_legacy_forward,
                vehicle_vessel_length_m,
            )
            if vehicle_longitudinal_reference not in GPS_LONGITUDINAL_REFERENCES:
                vehicle_longitudinal_reference = inferred_vehicle_reference
            vehicle_offset_from_reference_m = inferred_vehicle_offset
        else:
            if vehicle_longitudinal_reference not in GPS_LONGITUDINAL_REFERENCES:
                vehicle_longitudinal_reference = "bow"
            vehicle_offset_from_reference_m = float(vehicle_offset_from_reference_raw)

        split_routing_mode = str(data.get("split_routing_mode", "auto")).strip().lower()
        if split_routing_mode not in SPLIT_ROUTING_MODES:
            split_routing_mode = "auto"

        config = cls(
            feed_id=str(data.get("feed_id", "")).strip(),
            name=str(data.get("name", "")).strip(),
            bind_host=str(data.get("bind_host", "0.0.0.0")).strip() or "0.0.0.0",
            port=int(data.get("port", 10110)),
            enabled=bool(data.get("enabled", True)),
            checksum_policy=str(data.get("checksum_policy", "lenient")).strip().lower(),
            icon_path=str(data.get("icon_path", "")).strip(),
            symbol_mode=str(data.get("symbol_mode", "vessel")).strip().lower() or "vessel",
            vessel_length_m=vessel_length_m,
            vessel_width_m=float(data.get("vessel_width_m", 6.0)),
            vessel_gps_longitudinal_reference=longitudinal_reference,
            vessel_gps_offset_from_reference_m=offset_from_reference_m,
            vessel_gps_offset_starboard_m=float(
                data.get("vessel_gps_offset_starboard_m", 0.0)
            ),
            split_subfeeds_enabled=bool(data.get("split_subfeeds_enabled", False)),
            split_routing_mode=split_routing_mode,
            vehicle_show_on_vessel_when_missing_position=bool(
                data.get("vehicle_show_on_vessel_when_missing_position", False)
            ),
            vessel_track_enabled=bool(data.get("vessel_track_enabled", False)),
            vehicle_track_enabled=bool(data.get("vehicle_track_enabled", False)),
            manual_vessel_sentence_types=_normalize_sentence_types(
                data.get("manual_vessel_sentence_types", [])
            ),
            manual_vehicle_sentence_types=_normalize_sentence_types(
                data.get("manual_vehicle_sentence_types", [])
            ),
            vehicle_icon_path=str(data.get("vehicle_icon_path", "")).strip(),
            vehicle_symbol_mode=str(data.get("vehicle_symbol_mode", "qgis")).strip().lower()
            or "qgis",
            vehicle_vessel_length_m=vehicle_vessel_length_m,
            vehicle_vessel_width_m=float(data.get("vehicle_vessel_width_m", 2.0)),
            vehicle_vessel_gps_longitudinal_reference=vehicle_longitudinal_reference,
            vehicle_vessel_gps_offset_from_reference_m=vehicle_offset_from_reference_m,
            vehicle_vessel_gps_offset_starboard_m=float(
                data.get("vehicle_vessel_gps_offset_starboard_m", 0.0)
            ),
            vehicle_qgis_symbol_name=str(data.get("vehicle_qgis_symbol_name", "diamond")).strip()
            or "diamond",
            vehicle_qgis_symbol_width=float(data.get("vehicle_qgis_symbol_width", 7.0)),
            vehicle_qgis_symbol_height=float(data.get("vehicle_qgis_symbol_height", 7.0)),
            vehicle_qgis_size_unit=str(
                data.get("vehicle_qgis_size_unit", "screen")
            )
            .strip()
            .lower()
            or "screen",
            vehicle_unicode_symbol=str(vehicle_unicode_symbol),
            vehicle_unicode_font_family=str(vehicle_unicode_font_family).strip()
            or "Noto Sans Symbols 2",
            vehicle_color_hex=str(
                data.get(
                    "vehicle_color_hex",
                    data.get("color_hex", "#ff4500"),
                )
            ).strip()
            or str(data.get("color_hex", "#ff4500")).strip()
            or "#ff4500",
            qgis_symbol_name=str(data.get("qgis_symbol_name", "circle")).strip()
            or "circle",
            qgis_symbol_width=float(data.get("qgis_symbol_width", 7.0)),
            qgis_symbol_height=float(data.get("qgis_symbol_height", 7.0)),
            qgis_size_unit=str(data.get("qgis_size_unit", "screen")).strip().lower()
            or "screen",
            unicode_symbol=str(unicode_symbol),
            unicode_font_family=str(unicode_font_family).strip() or "Noto Sans Symbols 2",
            color_hex=str(data.get("color_hex", "#ff4500")).strip() or "#ff4500",
            hipap_utm_epsg=(
                int(data["hipap_utm_epsg"])
                if data.get("hipap_utm_epsg") not in (None, "")
                else None
            ),
            reference_lat=(
                float(data["reference_lat"])
                if data.get("reference_lat") not in (None, "")
                else None
            ),
            reference_lon=(
                float(data["reference_lon"])
                if data.get("reference_lon") not in (None, "")
                else None
            ),
            reference_heading_deg=(
                float(data["reference_heading_deg"])
                if data.get("reference_heading_deg") not in (None, "")
                else None
            ),
            stale_timeout_sec=int(data.get("stale_timeout_sec", 5)),
        )
        config.validate()
        return config

    @staticmethod
    def _is_valid_color(value: str) -> bool:
        return value.startswith("#") and len(value) in (4, 7)

    @staticmethod
    def _legacy_forward_to_reference(
        forward_from_center_m: float,
        vessel_length_m: float,
    ) -> tuple[str, float]:
        half_length = max(0.05, float(vessel_length_m)) / 2.0
        bow_offset = half_length - float(forward_from_center_m)
        stern_offset = half_length + float(forward_from_center_m)

        if bow_offset >= 0 and stern_offset >= 0:
            if bow_offset <= stern_offset:
                return "bow", bow_offset
            return "stern", stern_offset
        if bow_offset >= 0:
            return "bow", bow_offset
        return "stern", stern_offset
