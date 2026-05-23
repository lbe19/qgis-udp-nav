from __future__ import annotations

from collections import Counter

from qgis_udp_nav_plugin.model.events import FeedStatusEvent, ParseWarningEvent, PositionFixEvent
from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.parser.core import calculate_checksum
from qgis_udp_nav_plugin.parser.pipeline import SentencePipeline


def _feed() -> FeedConfig:
    return FeedConfig(feed_id="feed-soak", name="Soak Feed")


def _sentence(body: str) -> str:
    return f"${body}*{calculate_checksum(body)}"


def _hhmmss(day_minute: int) -> str:
    hour = (int(day_minute) // 60) % 24
    minute = int(day_minute) % 60
    return f"{hour:02d}{minute:02d}00.00"


def _simulate_virtual_operations(days: int, minute_step: int) -> tuple[Counter, Counter]:
    pipeline = SentencePipeline()
    feed = _feed()

    expected: Counter = Counter()
    observed: Counter = Counter()

    total_minutes = int(days) * 24 * 60
    for minute_index in range(0, total_minutes, int(minute_step)):
        day_minute = minute_index % (24 * 60)
        clock = _hhmmss(day_minute)

        lines: list[str] = [
            _sentence(
                f"GPGGA,{clock},7002.968962,N,02938.350607,E,2,12,0.6,-0.52,M,20.34,M,7.0,0907"
            ),
            _sentence(f"GPGLL,7002.968962,N,02938.350607,E,{clock},A,D"),
        ]
        expected["vessel_valid_positions"] += 2

        if day_minute < 180:
            pos_item = ""
            expected["sns_no_position"] += 1
        elif day_minute < 720:
            pos_item = "42"
            expected["sns_info"] += 1

            has_nry_warning = (minute_index % 11) == 0
            error_code = "NRy" if has_nry_warning else ""
            x_value = 46.0 + ((minute_index // max(1, minute_step)) % 10) * 0.1
            y_value = 1.5 + ((minute_index // max(1, minute_step)) % 5) * 0.01
            depth_m = 24.0 + ((minute_index // max(1, minute_step)) % 7) * 0.5

            lines.append(
                _sentence(
                    "PSIMSSB,"
                    f"{clock},M17,A,{error_code},C,N,F,"
                    f"{x_value:.3f},{y_value:.3f},{depth_m:.3f},1.414,T,0.033681,"
                )
            )
            expected["ssb_valid_positions"] += 1
            if has_nry_warning:
                expected["ssb_nry_warnings"] += 1
        else:
            pos_item = ""
            expected["sns_no_position"] += 1

            if (minute_index % 3) == 0:
                lines.append(
                    _sentence(
                        f"PSIMSSB,{clock},M17,V,NRy,C,N,M,,,,,T,0.002245,"
                    )
                )
                expected["ssb_invalid_positions"] += 1
                expected["ssb_nry_warnings"] += 1

        lines.append(
            _sentence(
                "PSIMSNS,"
                f"{clock},{pos_item},1,1,-1.27,-1.13,-0.04,250.87,,a0,0.000,,M121"
            )
        )

        payload = "\n".join(lines)
        events = pipeline.parse_datagram(feed, payload, source_address="192.168.1.150")

        for event in events:
            metadata = getattr(event, "metadata", None)
            if isinstance(metadata, dict):
                observed["metadata_source_address"] += int(
                    metadata.get("source_address") == "192.168.1.150"
                )

            if isinstance(event, ParseWarningEvent):
                observed["parse_warnings"] += 1
                continue

            if isinstance(event, PositionFixEvent):
                if event.sentence_type in {"GGA", "GLL"} and event.valid:
                    observed["vessel_valid_positions"] += 1
                elif event.sentence_type == "PSIMSSB":
                    if event.valid:
                        observed["ssb_valid_positions"] += 1
                    else:
                        observed["ssb_invalid_positions"] += 1
                continue

            if isinstance(event, FeedStatusEvent):
                if event.sentence_type == "PSIMSNS":
                    if event.code == "NO_POSITION":
                        observed["sns_no_position"] += 1
                    else:
                        observed["sns_info"] += 1
                elif event.sentence_type == "PSIMSSB" and event.code == "NRy":
                    observed["ssb_nry_warnings"] += 1

    return observed, expected


def _assert_simulation_counts(observed: Counter, expected: Counter) -> None:
    assert observed["parse_warnings"] == 0

    for key in (
        "vessel_valid_positions",
        "ssb_valid_positions",
        "ssb_invalid_positions",
        "sns_no_position",
        "sns_info",
        "ssb_nry_warnings",
    ):
        assert observed[key] == expected[key], f"mismatch for {key}"

    assert observed["metadata_source_address"] > 0


def test_virtual_three_day_timeline_matches_expected_operational_phases() -> None:
    observed, expected = _simulate_virtual_operations(days=3, minute_step=1)

    _assert_simulation_counts(observed, expected)
    assert observed["ssb_valid_positions"] > 0
    assert observed["ssb_invalid_positions"] > 0
    assert observed["sns_no_position"] > observed["sns_info"]


def test_virtual_four_week_soak_remains_stable_at_coarse_resolution() -> None:
    observed, expected = _simulate_virtual_operations(days=28, minute_step=5)

    _assert_simulation_counts(observed, expected)
    assert observed["ssb_nry_warnings"] >= observed["ssb_invalid_positions"]
