from qgis_udp_nav_plugin.model.events import FeedStatusEvent, PositionFixEvent
from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.parser.core import calculate_checksum
from qgis_udp_nav_plugin.parser.pipeline import SentencePipeline


def _feed() -> FeedConfig:
    return FeedConfig(feed_id="feed-hipap-extended", name="HiPAP Extended")


def _sentence(body: str) -> str:
    return f"${body}*{calculate_checksum(body)}"


def test_psimssb_status_a_without_coordinates_emits_no_coord_warning() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("PSIMSSB,083733.036,M17,A,,C,N,F,,,,20.000,T,0.003731,")

    events = pipeline.parse_datagram(_feed(), payload)
    positions = [event for event in events if isinstance(event, PositionFixEvent)]
    statuses = [event for event in events if isinstance(event, FeedStatusEvent)]

    assert len(positions) == 1
    assert positions[0].valid is False

    assert len(statuses) == 1
    assert statuses[0].code == "NO_COORD"
    assert "coordinates are missing" in statuses[0].message


def test_psimssb_unknown_status_emits_status_warning() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("PSIMSSB,083733.036,M17,X,,C,N,F,1.0,2.0,3.0,20.000,T,0.003731,")

    events = pipeline.parse_datagram(_feed(), payload)
    statuses = [event for event in events if isinstance(event, FeedStatusEvent)]

    assert len(statuses) == 1
    assert statuses[0].code == "STATUS"
    assert "unknown status field" in statuses[0].message


def test_psimssb_valid_with_unknown_error_code_uses_generic_warning_message() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("PSIMSSB,083733.036,M17,A,ZZZ,C,N,F,1.0,2.0,3.0,20.000,T,0.003731,")

    events = pipeline.parse_datagram(_feed(), payload)
    statuses = [event for event in events if isinstance(event, FeedStatusEvent)]

    assert len(statuses) == 1
    assert statuses[0].code == "ZZZ"
    assert "valid with code ZZZ" in statuses[0].message


def test_psimsns_with_position_item_is_info_status() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("PSIMSNS,123519.00,42,01,01,1.0,2.0,0.3,180.0,,1,0.4,,M121")

    events = pipeline.parse_datagram(_feed(), payload)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, FeedStatusEvent)
    assert event.level == "info"
    assert event.code == "SNS"
    assert "item 42" in event.message


def test_psimsns_metadata_contains_telemetry_fields() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("PSIMSNS,123519.00,42,02,03,1.2,-0.8,0.4,179.6,,a0,0.9,,M121")

    events = pipeline.parse_datagram(_feed(), payload)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, FeedStatusEvent)
    assert event.metadata["clock"] == "123519.00"
    assert event.metadata["pos_item"] == "42"
    assert event.metadata["transceiver"] == "02"
    assert event.metadata["transducer"] == "03"
    assert event.metadata["roll_deg"] == 1.2
    assert event.metadata["pitch_deg"] == -0.8
    assert event.metadata["heave_m"] == 0.4
    assert event.metadata["heading_deg"] == 179.6
    assert event.metadata["time_age_s"] == 0.9
