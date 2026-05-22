from __future__ import annotations

from qgis_udp_nav_plugin.model.feed_config import FeedConfig


def test_feed_config_accepts_bow_stern_reference_fields() -> None:
    config = FeedConfig.from_dict(
        {
            "feed_id": "feed-a",
            "name": "Feed A",
            "vessel_length_m": 30.0,
            "vessel_gps_longitudinal_reference": "stern",
            "vessel_gps_offset_from_reference_m": 2.5,
            "vessel_gps_offset_starboard_m": -1.25,
        }
    )

    assert config.vessel_gps_longitudinal_reference == "stern"
    assert config.vessel_gps_offset_from_reference_m == 2.5
    assert config.vessel_gps_offset_starboard_m == -1.25

    payload = config.to_dict()
    assert payload["vessel_gps_longitudinal_reference"] == "stern"
    assert payload["vessel_gps_offset_from_reference_m"] == 2.5


def test_feed_config_migrates_legacy_forward_offset_to_bow_reference() -> None:
    config = FeedConfig.from_dict(
        {
            "feed_id": "feed-b",
            "name": "Feed B",
            "vessel_length_m": 20.0,
            "vessel_gps_offset_forward_m": 4.0,
        }
    )

    assert config.vessel_gps_longitudinal_reference == "bow"
    assert config.vessel_gps_offset_from_reference_m == 6.0


def test_feed_config_migrates_legacy_forward_offset_to_stern_reference() -> None:
    config = FeedConfig.from_dict(
        {
            "feed_id": "feed-c",
            "name": "Feed C",
            "vessel_length_m": 20.0,
            "vessel_gps_offset_forward_m": -3.0,
        }
    )

    assert config.vessel_gps_longitudinal_reference == "stern"
    assert config.vessel_gps_offset_from_reference_m == 7.0


def test_feed_config_supports_split_subfeed_and_vehicle_symbol_fields() -> None:
    config = FeedConfig.from_dict(
        {
            "feed_id": "feed-d",
            "name": "Feed D",
            "split_subfeeds_enabled": True,
            "split_routing_mode": "manual",
            "vehicle_show_on_vessel_when_missing_position": True,
            "manual_vessel_sentence_types": [" gga ", "hdt", "GGA"],
            "manual_vehicle_sentence_types": "psimssb, psimsns",
            "vehicle_symbol_mode": "unicode",
            "vehicle_unicode_symbol": "\u26f5",
            "vehicle_qgis_symbol_name": "triangle",
        }
    )

    assert config.split_subfeeds_enabled is True
    assert config.split_routing_mode == "manual"
    assert config.vehicle_show_on_vessel_when_missing_position is True
    assert config.manual_vessel_sentence_types == ["GGA", "HDT"]
    assert config.manual_vehicle_sentence_types == ["PSIMSSB", "PSIMSNS"]
    assert config.vehicle_symbol_mode == "unicode"
    assert config.vehicle_unicode_symbol == "\u26f5"

    payload = config.to_dict()
    assert payload["vehicle_show_on_vessel_when_missing_position"] is True
    assert payload["manual_vessel_sentence_types"] == ["GGA", "HDT"]
    assert payload["manual_vehicle_sentence_types"] == ["PSIMSSB", "PSIMSNS"]


def test_feed_config_supports_vehicle_rectangle_mode_and_color() -> None:
    config = FeedConfig.from_dict(
        {
            "feed_id": "feed-e",
            "name": "Feed E",
            "vehicle_symbol_mode": "vehicle",
            "vehicle_vessel_length_m": 3.5,
            "vehicle_vessel_width_m": 1.7,
            "vehicle_color_hex": "#00b8ff",
        }
    )

    assert config.vehicle_symbol_mode == "vehicle"
    assert config.vehicle_vessel_length_m == 3.5
    assert config.vehicle_vessel_width_m == 1.7
    assert config.vehicle_color_hex == "#00b8ff"

    payload = config.to_dict()
    assert payload["vehicle_symbol_mode"] == "vehicle"
    assert payload["vehicle_color_hex"] == "#00b8ff"


def test_feed_config_allows_sub_meter_vessel_and_vehicle_dimensions() -> None:
    config = FeedConfig.from_dict(
        {
            "feed_id": "feed-f",
            "name": "Feed F",
            "vessel_length_m": 0.25,
            "vessel_width_m": 0.12,
            "vehicle_vessel_length_m": 0.35,
            "vehicle_vessel_width_m": 0.08,
        }
    )

    assert config.vessel_length_m == 0.25
    assert config.vessel_width_m == 0.12
    assert config.vehicle_vessel_length_m == 0.35
    assert config.vehicle_vessel_width_m == 0.08
