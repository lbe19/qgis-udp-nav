from qgis_udp_nav_plugin.model.events import FeedStatusEvent, PositionFixEvent
from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.parser.pipeline import SentencePipeline


def _feed() -> FeedConfig:
    return FeedConfig(feed_id="feed-log-replay", name="Log Replay")


def _parse(payload: str) -> list[object]:
    pipeline = SentencePipeline()
    return pipeline.parse_datagram(_feed(), payload)


def _positions(events: list[object], sentence_type: str = "") -> list[PositionFixEvent]:
    items = [event for event in events if isinstance(event, PositionFixEvent)]
    if sentence_type:
        wanted = str(sentence_type).strip().upper()
        return [event for event in items if event.sentence_type.upper() == wanted]
    return items


def _statuses(events: list[object], sentence_type: str = "") -> list[FeedStatusEvent]:
    items = [event for event in events if isinstance(event, FeedStatusEvent)]
    if sentence_type:
        wanted = str(sentence_type).strip().upper()
        return [event for event in items if event.sentence_type.upper() == wanted]
    return items


def test_log_replay_pre_transponder_phase_has_no_position_sns_warning() -> None:
    # Derived from 2026-05-23 07:56:24Z main feed log samples.
    payload = "\n".join(
        [
            "$GPGGA,075617.34,7002.968962,N,02938.350607,E,2,12,0.6,-0.52,M,20.34,M,7.0,0907*6F",
            "$GPGLL,7002.968962,N,02938.350607,E,075617.34,A,D*61",
            "$PSIMSNS,075617.446,,1,1,-1.27,-1.13,-0.04,250.87,,a0,0.000,,M121*59",
        ]
    )

    events = _parse(payload)
    positions = _positions(events)
    sns_statuses = _statuses(events, "PSIMSNS")

    assert len(positions) == 2
    assert all(event.valid for event in positions)
    assert {event.sentence_type for event in positions} == {"GGA", "GLL"}

    assert len(sns_statuses) == 1
    assert sns_statuses[0].level == "warning"
    assert sns_statuses[0].code == "NO_POSITION"
    assert "no-valid-position period" in sns_statuses[0].message


def test_log_replay_psimssb_valid_nry_keeps_position_but_emits_warning() -> None:
    # Derived from 2026-05-23 08:37:40Z main feed log sample.
    payload = (
        "$PSIMSSB,083733.036,M17,A,NRy,C,N,F,0.000,0.000,0.000,20.000,T,0.003731,*08"
    )

    events = _parse(payload)
    positions = _positions(events, "PSIMSSB")
    statuses = _statuses(events, "PSIMSSB")

    assert len(positions) == 1
    assert positions[0].valid is True
    assert positions[0].metadata["status"] == "A"
    assert positions[0].metadata["error_code"] == "NRy"
    assert positions[0].metadata["x_coordinate"] == 0.0
    assert positions[0].metadata["y_coordinate"] == 0.0
    assert positions[0].metadata["depth_m"] == 0.0

    assert len(statuses) == 1
    assert statuses[0].level == "warning"
    assert statuses[0].code == "NRy"
    assert "valid with code NRy" in statuses[0].message


def test_log_replay_psimssb_active_tracking_has_valid_position_without_warning() -> None:
    # Derived from 2026-05-23 08:37:40Z main feed log sample.
    payload = (
        "$PSIMSSB,083733.386,M17,A,,C,N,F,46.649,1.632,24.829,1.414,T,0.033681,*54"
    )

    events = _parse(payload)
    positions = _positions(events, "PSIMSSB")
    statuses = _statuses(events, "PSIMSSB")

    assert len(positions) == 1
    assert positions[0].valid is True
    assert positions[0].metadata["status"] == "A"
    assert positions[0].metadata["error_code"] is None
    assert positions[0].metadata["x_coordinate"] == 46.649
    assert positions[0].metadata["y_coordinate"] == 1.632
    assert positions[0].metadata["depth_m"] == 24.829

    assert len(statuses) == 0


def test_log_replay_psimssb_invalid_nry_reports_invalid_position() -> None:
    # Derived from 2026-05-23 09:45:39Z main feed log sample.
    payload = "$PSIMSSB,094532.523,M17,V,NRy,C,N,M,,,,,T,0.002245,*25"

    events = _parse(payload)
    positions = _positions(events, "PSIMSSB")
    statuses = _statuses(events, "PSIMSSB")

    assert len(positions) == 1
    assert positions[0].valid is False
    assert positions[0].metadata["status"] == "V"
    assert positions[0].metadata["error_code"] == "NRy"
    assert positions[0].metadata["x_coordinate"] is None
    assert positions[0].metadata["y_coordinate"] is None

    assert len(statuses) == 1
    assert statuses[0].level == "warning"
    assert statuses[0].code == "NRy"
    assert "PSIMSSB invalid" in statuses[0].message


def test_log_replay_vehicle_lifecycle_sequence_matches_observed_pattern() -> None:
    # Replay of observed phases from 2026-05-23 logs:
    # 1) no-valid-position period, 2) activation with NRy noise,
    # 3) stable valid updates, 4) invalid/no-reply bursts, 5) valid again.
    payload = "\n".join(
        [
            "$PSIMSNS,075617.446,,1,1,-1.27,-1.13,-0.04,250.87,,a0,0.000,,M121*59",
            "$PSIMSSB,083733.036,M17,A,NRy,C,N,F,0.000,0.000,0.000,20.000,T,0.003731,*08",
            "$PSIMSSB,083733.386,M17,A,,C,N,F,46.649,1.632,24.829,1.414,T,0.033681,*54",
            "$PSIMSSB,094532.523,M17,V,NRy,C,N,M,,,,,T,0.002245,*25",
            "$PSIMSSB,093933.055,M17,A,NRy,C,N,F,13.281,-1.978,0.422,2.236,T,0.008391,*27",
        ]
    )

    events = _parse(payload)
    ssb_positions = _positions(events, "PSIMSSB")
    status_events = _statuses(events)

    assert [event.valid for event in ssb_positions] == [True, True, False, True]

    sns_events = [event for event in status_events if event.sentence_type == "PSIMSNS"]
    ssb_warning_events = [event for event in status_events if event.sentence_type == "PSIMSSB"]

    assert len(sns_events) == 1
    assert sns_events[0].code == "NO_POSITION"

    assert len(ssb_warning_events) == 3
    assert [event.code for event in ssb_warning_events] == ["NRy", "NRy", "NRy"]
    assert "valid with code NRy" in ssb_warning_events[0].message
    assert "PSIMSSB invalid" in ssb_warning_events[1].message
    assert "valid with code NRy" in ssb_warning_events[2].message