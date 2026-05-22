from qgis_udp_nav_plugin.model.events import HeadingEvent, ParseWarningEvent, PositionFixEvent
from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.parser.core import calculate_checksum
from qgis_udp_nav_plugin.parser.pipeline import SentencePipeline


def _feed(policy: str = "lenient") -> FeedConfig:
    return FeedConfig(
        feed_id="feed-test",
        name="Test Feed",
        checksum_policy=policy,
    )


def _sentence(body: str) -> str:
    return f"${body}*{calculate_checksum(body)}"


def test_talker_agnostic_gga_parsing() -> None:
    pipeline = SentencePipeline()
    gpgga = _sentence(
        "GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
    )
    ingga = _sentence(
        "INGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
    )

    events = pipeline.parse_datagram(_feed(), f"{gpgga}\n{ingga}")
    positions = [event for event in events if isinstance(event, PositionFixEvent)]

    assert len(positions) == 2
    assert positions[0].sentence_type == "GGA"
    assert positions[1].sentence_type == "GGA"
    assert positions[0].talker == "GP"
    assert positions[1].talker == "IN"


def test_strict_checksum_rejects_sentence_without_checksum() -> None:
    pipeline = SentencePipeline()
    no_checksum = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"

    events = pipeline.parse_datagram(_feed(policy="strict"), no_checksum)

    assert any(isinstance(event, ParseWarningEvent) for event in events)
    assert not any(isinstance(event, PositionFixEvent) for event in events)


def test_lenient_checksum_warns_but_accepts_on_mismatch() -> None:
    pipeline = SentencePipeline()
    invalid_checksum = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"

    events = pipeline.parse_datagram(_feed(policy="lenient"), invalid_checksum)

    assert any(isinstance(event, ParseWarningEvent) for event in events)
    assert any(isinstance(event, PositionFixEvent) for event in events)


def test_gll_optional_mode_indicator_supported() -> None:
    pipeline = SentencePipeline()
    gll_without_mode = _sentence("GPGLL,4916.45,N,12311.12,W,225444,A")

    events = pipeline.parse_datagram(_feed(), gll_without_mode)
    positions = [event for event in events if isinstance(event, PositionFixEvent)]

    assert len(positions) == 1
    assert positions[0].sentence_type == "GLL"
    assert positions[0].valid is True
    assert positions[0].latitude is not None
    assert positions[0].longitude is not None


def test_hdt_heading_event_is_parsed() -> None:
    pipeline = SentencePipeline()
    hdt = _sentence("HEHDT,123.4,T")

    events = pipeline.parse_datagram(_feed(), hdt)
    headings = [event for event in events if isinstance(event, HeadingEvent)]

    assert len(headings) == 1
    assert headings[0].sentence_type == "HDT"
    assert headings[0].is_true_heading is True
    assert headings[0].heading_deg == 123.4


def test_hdg_uses_variation_to_resolve_true_heading() -> None:
    pipeline = SentencePipeline()
    hdg = _sentence("HEHDG,100.0,,,2.5,E")

    events = pipeline.parse_datagram(_feed(), hdg)
    headings = [event for event in events if isinstance(event, HeadingEvent)]

    assert len(headings) == 1
    assert headings[0].sentence_type == "HDG"
    assert headings[0].is_true_heading is True
    assert headings[0].heading_deg == 102.5


def test_rmc_course_is_not_interpreted_as_heading() -> None:
    pipeline = SentencePipeline()
    rmc = _sentence("GPRMC,123519,A,4807.038,N,01131.000,E,2.1,084.4,230394,,,A")

    events = pipeline.parse_datagram(_feed(), rmc)
    headings = [event for event in events if isinstance(event, HeadingEvent)]
    positions = [event for event in events if isinstance(event, PositionFixEvent)]

    assert len(positions) == 1
    assert positions[0].sentence_type == "RMC"
    assert len(headings) == 0


def test_rmc_speed_knots_is_exposed_in_metadata() -> None:
    pipeline = SentencePipeline()
    rmc = _sentence("GPRMC,123519,A,4807.038,N,01131.000,E,5.4,084.4,230394,,,A")

    events = pipeline.parse_datagram(_feed(), rmc)
    positions = [event for event in events if isinstance(event, PositionFixEvent)]

    assert len(positions) == 1
    assert positions[0].metadata["speed_knots"] == 5.4
