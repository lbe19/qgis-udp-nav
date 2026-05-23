from qgis_udp_nav_plugin.model.events import FeedStatusEvent, HeadingEvent, PositionFixEvent
from qgis_udp_nav_plugin.parser.core import calculate_checksum, parse_sentence
from qgis_udp_nav_plugin.parser.nmea_standard import parse_standard_sentence


def _sentence(body: str):
    return parse_sentence(f"${body}*{calculate_checksum(body)}")


def test_parse_gga_quality_zero_marks_position_invalid() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,0,04,2.5,10.0,M,0.0,M,,")

    events = parse_standard_sentence("feed-test", sentence)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, PositionFixEvent)
    assert event.valid is False
    assert event.status_text == "No fix"


def test_parse_gga_quality_two_is_valid_dgps_fix() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,2,09,0.8,12.3,M,0.0,M,,")

    event = parse_standard_sentence("feed-test", sentence)[0]

    assert isinstance(event, PositionFixEvent)
    assert event.valid is True
    assert event.status_text == "DGPS fix"
    assert event.metadata["satellites"] == 9
    assert event.metadata["hdop"] == 0.8


def test_parse_rmc_invalid_status_is_not_valid_position() -> None:
    sentence = _sentence("GPRMC,123519,V,4807.038,N,01131.000,E,2.1,084.4,230394,,,A")

    event = parse_standard_sentence("feed-test", sentence)[0]

    assert isinstance(event, PositionFixEvent)
    assert event.valid is False
    assert event.metadata["status"] == "V"
    assert event.metadata["speed_knots"] == 2.1


def test_parse_gsa_fix_type_one_emits_warning_level_status() -> None:
    sentence = _sentence("GPGSA,A,1,,,,,,,,,,,,,2.5,1.3,2.1")

    event = parse_standard_sentence("feed-test", sentence)[0]

    assert isinstance(event, FeedStatusEvent)
    assert event.level == "warning"
    assert event.code == "1"
    assert "No fix" in event.message


def test_parse_hdm_normalizes_heading_to_0_360_range() -> None:
    sentence = _sentence("HEHDM,361.2,M")

    event = parse_standard_sentence("feed-test", sentence)[0]

    assert isinstance(event, HeadingEvent)
    assert event.is_true_heading is False
    assert event.heading_deg == 1.1999999999999886


def test_parse_hdg_west_variation_resolves_true_heading() -> None:
    sentence = _sentence("HEHDG,100.0,,,2.5,W")

    event = parse_standard_sentence("feed-test", sentence)[0]

    assert isinstance(event, HeadingEvent)
    assert event.is_true_heading is True
    assert event.heading_deg == 97.5
    assert event.metadata["heading_kind"] == "true"


def test_parse_ths_invalid_status_emits_heading_and_warning() -> None:
    sentence = _sentence("HETHS,245.2,V")

    events = parse_standard_sentence("feed-test", sentence)

    assert len(events) == 2
    heading_event = next(event for event in events if isinstance(event, HeadingEvent))
    status_event = next(event for event in events if isinstance(event, FeedStatusEvent))

    assert heading_event.valid is False
    assert status_event.level == "warning"
    assert status_event.code == "THS_STATUS"


def test_parse_vhw_prefers_true_heading_when_available() -> None:
    sentence = _sentence("VWVHW,123.4,T,111.1,M,5.5,N,10.2,K")

    events = parse_standard_sentence("feed-test", sentence)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, HeadingEvent)
    assert event.is_true_heading is True
    assert event.heading_deg == 123.4


def test_parse_vhw_falls_back_to_magnetic_heading() -> None:
    sentence = _sentence("VWVHW,,T,111.1,M,5.5,N,10.2,K")

    events = parse_standard_sentence("feed-test", sentence)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, HeadingEvent)
    assert event.is_true_heading is False
    assert event.heading_deg == 111.1


def test_parse_vhw_without_heading_returns_no_events() -> None:
    sentence = _sentence("VWVHW,,T,,M,5.5,N,10.2,K")

    events = parse_standard_sentence("feed-test", sentence)

    assert events == []


def test_parse_standard_sentence_returns_empty_for_unsupported_id() -> None:
    sentence = _sentence("GPZDA,075617.34,23,05,2026,,")

    events = parse_standard_sentence("feed-test", sentence)

    assert events == []
