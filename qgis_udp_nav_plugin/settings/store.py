from __future__ import annotations

import json
from typing import Dict, List

try:
    from qgis.core import QgsSettings
except ImportError:  # pragma: no cover - fallback for local non-QGIS test runs.
    from PyQt5.QtCore import QSettings as QgsSettings  # type: ignore

from ..model.feed_config import FeedConfig


class SettingsStore:
    PREFIX = "qgis_udp_nav_plugin"
    FEEDS_KEY = f"{PREFIX}/feeds"
    VESSEL_PROFILES_KEY = f"{PREFIX}/vessel_profiles"

    def __init__(self) -> None:
        self._settings = QgsSettings()

    def load_feeds(self) -> List[FeedConfig]:
        raw = self._settings.value(self.FEEDS_KEY, "")
        if not raw:
            return [self._default_feed()]

        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return [self._default_feed()]

        feeds: List[FeedConfig] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                try:
                    feeds.append(FeedConfig.from_dict(item))
                except (TypeError, ValueError):
                    continue

        if not feeds:
            feeds = [self._default_feed()]

        return feeds

    def save_feeds(self, feeds: List[FeedConfig]) -> None:
        payload = [feed.to_dict() for feed in feeds]
        self._settings.setValue(self.FEEDS_KEY, json.dumps(payload))

    def load_vessel_profiles(self) -> Dict[str, dict]:
        raw = self._settings.value(self.VESSEL_PROFILES_KEY, "")
        if not raw:
            return {}

        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

        if not isinstance(payload, dict):
            return {}

        profiles: Dict[str, dict] = {}
        for name, profile in payload.items():
            profile_name = str(name).strip()
            if not profile_name or not isinstance(profile, dict):
                continue
            profiles[profile_name] = dict(profile)
        return profiles

    def save_vessel_profiles(self, profiles: Dict[str, dict]) -> None:
        safe_profiles: Dict[str, dict] = {}
        for name, profile in profiles.items():
            profile_name = str(name).strip()
            if not profile_name or not isinstance(profile, dict):
                continue
            safe_profiles[profile_name] = dict(profile)

        self._settings.setValue(self.VESSEL_PROFILES_KEY, json.dumps(safe_profiles))

    @staticmethod
    def _default_feed() -> FeedConfig:
        return FeedConfig(
            feed_id="feed-1",
            name="Feed 1",
            bind_host="0.0.0.0",
            port=10110,
            checksum_policy="lenient",
            symbol_mode="vessel",
            vessel_length_m=20.0,
            vessel_width_m=6.0,
            vessel_gps_longitudinal_reference="bow",
            vessel_gps_offset_from_reference_m=0.0,
            vessel_gps_offset_starboard_m=0.0,
            split_subfeeds_enabled=False,
            split_routing_mode="auto",
            vehicle_show_on_vessel_when_missing_position=False,
            manual_vessel_sentence_types=[],
            manual_vehicle_sentence_types=[],
            vehicle_icon_path="",
            vehicle_symbol_mode="qgis",
            vehicle_vessel_length_m=4.0,
            vehicle_vessel_width_m=2.0,
            vehicle_vessel_gps_longitudinal_reference="bow",
            vehicle_vessel_gps_offset_from_reference_m=0.0,
            vehicle_vessel_gps_offset_starboard_m=0.0,
            vehicle_qgis_symbol_name="diamond",
            vehicle_qgis_symbol_width=7.0,
            vehicle_qgis_symbol_height=7.0,
            vehicle_qgis_size_unit="screen",
            vehicle_unicode_symbol="\u26f5",
            vehicle_unicode_font_family="Noto Sans Symbols 2",
            vehicle_color_hex="#00b8ff",
            qgis_symbol_name="circle",
            qgis_symbol_width=7.0,
            qgis_symbol_height=7.0,
            qgis_size_unit="screen",
            unicode_symbol="\u2693",
            unicode_font_family="Noto Sans Symbols 2",
            color_hex="#ff4500",
        )
