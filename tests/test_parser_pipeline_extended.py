from qgis_udp_nav_plugin.model.events import FeedStatusEvent, ParseWarningEvent, PositionFixEvent
from qgis_udp_nav_plugin.model.feed_config import FeedConfig
from qgis_udp_nav_plugin.parser.core import calculate_checksum
from qgis_udp_nav_plugin.parser.pipeline import SentencePipeline


def _feed(policy: str = "lenient") -> FeedConfig:
    return FeedConfig(feed_id="feed-pipeline", name="Pipeline Feed", checksum_policy=policy)


def _sentence(body: str) -> str:
    return f"${body}*{calculate_checksum(body)}"


def test_pipeline_attaches_source_address_to_metadata_events() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")

    events = pipeline.parse_datagram(_feed(), payload, source_address="192.168.1.50")

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, PositionFixEvent)
    assert event.metadata["source_address"] == "192.168.1.50"


def test_pipeline_unknown_sentence_is_ignored_without_warnings() -> None:
    pipeline = SentencePipeline()
    payload = _sentence("GPXXX,1,2,3,4,5")

    events = pipeline.parse_datagram(_feed(), payload)

    assert events == []


def test_pipeline_parse_failure_emits_parse_warning() -> None:
    pipeline = SentencePipeline()
    bad_lat = _sentence("GPGGA,123519,9999.999,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")

    events = pipeline.parse_datagram(_feed(), bad_lat)

    assert len(events) == 1
    assert isinstance(events[0], ParseWarningEvent)
    assert "Failed to parse GGA" in events[0].message


def test_pipeline_strict_policy_rejects_checksum_mismatch() -> None:
    pipeline = SentencePipeline()
    payload = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"

    events = pipeline.parse_datagram(_feed(policy="strict"), payload)

    assert len(events) == 1
    assert isinstance(events[0], ParseWarningEvent)
    assert "Checksum rejected by strict policy" in events[0].message


def test_pipeline_ignore_policy_accepts_checksum_mismatch_without_warning() -> None:
    pipeline = SentencePipeline()
    payload = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"

    events = pipeline.parse_datagram(_feed(policy="ignore"), payload)

    assert len(events) == 1
    assert isinstance(events[0], PositionFixEvent)


def test_pipeline_mixed_payload_emits_parse_warning_and_valid_events() -> None:
    pipeline = SentencePipeline()
    payload = "\n".join(
        [
            _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"),
            "not-a-sentence",
            _sentence("PSIMSNS,123519.00,,01,01,1.0,2.0,,180.0,,1,0.4,,M121"),
        ]
    )

    events = pipeline.parse_datagram(_feed(), payload)

    assert len(events) == 3
    assert any(isinstance(event, PositionFixEvent) for event in events)
    assert any(isinstance(event, ParseWarningEvent) for event in events)
    assert any(isinstance(event, FeedStatusEvent) for event in events)
