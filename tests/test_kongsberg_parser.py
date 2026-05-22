from qgis_udp_nav_plugin.model.events import FeedStatusEvent, PositionFixEvent
from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.parser.core import calculate_checksum
from qgis_udp_nav_plugin.parser.pipeline import SentencePipeline


def _feed() -> FeedConfig:
    return FeedConfig(feed_id="feed-hipap", name="HiPAP Feed")


def _sentence(body: str) -> str:
    return f"${body}*{calculate_checksum(body)}"


def test_psimssb_valid_position_event() -> None:
    pipeline = SentencePipeline()
    ssb = _sentence("PSIMSSB,,B01,A,,P,H,M,111.80,63.43,48.50,0.00,N,,")

    events = pipeline.parse_datagram(_feed(), ssb)
    positions = [event for event in events if isinstance(event, PositionFixEvent)]

    assert len(positions) == 1
    assert positions[0].sentence_type == "PSIMSSB"
    assert positions[0].valid is True
    assert positions[0].metadata["tp_code"] == "B01"
    assert positions[0].metadata["coordinate_system"] == "P"
    assert positions[0].metadata["depth_m"] == 48.5


def test_psimssb_invalid_status_generates_warning() -> None:
    pipeline = SentencePipeline()
    ssb_invalid = _sentence("PSIMSSB,,B36,V,NRy,P,H,M,,,,2.70,N,,")

    events = pipeline.parse_datagram(_feed(), ssb_invalid)
    warnings = [event for event in events if isinstance(event, FeedStatusEvent)]
    positions = [event for event in events if isinstance(event, PositionFixEvent)]

    assert len(positions) == 1
    assert positions[0].valid is False
    assert any(event.code == "NRy" for event in warnings)


def test_psimsns_without_pos_item_is_informative_warning() -> None:
    pipeline = SentencePipeline()
    sns = _sentence("PSIMSNS,123519.00,,01,01,1.0,2.0,,180.0,,1,0.4,,M121")

    events = pipeline.parse_datagram(_feed(), sns)
    status_events = [event for event in events if isinstance(event, FeedStatusEvent)]

    assert len(status_events) == 1
    assert status_events[0].sentence_type == "PSIMSNS"
    assert status_events[0].level == "warning"
    assert status_events[0].code == "NO_POSITION"
    assert "no-valid-position" in status_events[0].message
