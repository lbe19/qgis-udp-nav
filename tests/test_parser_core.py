import re

import pytest

from qgis_udp_nav_plugin.parser.core import calculate_checksum, parse_sentence, split_datagram


def test_split_datagram_handles_mixed_newlines_and_whitespace() -> None:
    payload = "\r\n  $GPGLL,1,2,3,4,5,A*00 \r$GPGGA,1,2,3,4,5,1*00\n\n  \n$PSIMSSB,1,2,A,,C,N,F,1,2,3,4,T,0.1,*00"

    lines = list(split_datagram(payload))

    assert lines == [
        "$GPGLL,1,2,3,4,5,A*00",
        "$GPGGA,1,2,3,4,5,1*00",
        "$PSIMSSB,1,2,A,,C,N,F,1,2,3,4,T,0.1,*00",
    ]


def test_calculate_checksum_known_vector() -> None:
    assert calculate_checksum("GPGLL,4916.45,N,12311.12,W,225444,A") == "31"


def test_parse_sentence_derives_standard_sentence_type_and_talker() -> None:
    sentence = parse_sentence("$INGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*7D")

    assert sentence.formatter == "INGGA"
    assert sentence.sentence_type == "GGA"
    assert sentence.talker == "IN"


def test_parse_sentence_derives_proprietary_sentence_identity() -> None:
    sentence = parse_sentence(
        "$PSIMSSB,083733.386,M17,A,,C,N,F,46.649,1.632,24.829,1.414,T,0.033681,*54"
    )

    assert sentence.sentence_type == "PSIMSSB"
    assert sentence.talker is None


def test_parse_sentence_valid_checksum_sets_flags() -> None:
    sentence = parse_sentence("$GPGLL,4916.45,N,12311.12,W,225444,A*31")

    assert sentence.checksum_delimiter_present is True
    assert sentence.checksum_provided is True
    assert sentence.checksum_value == "31"
    assert sentence.checksum_valid is True


def test_parse_sentence_without_checksum_sets_none_state() -> None:
    sentence = parse_sentence("$GPGLL,4916.45,N,12311.12,W,225444,A")

    assert sentence.checksum_delimiter_present is False
    assert sentence.checksum_provided is False
    assert sentence.checksum_value is None
    assert sentence.checksum_valid is None


def test_parse_sentence_with_non_hex_checksum_treated_as_missing() -> None:
    sentence = parse_sentence("$GPGLL,4916.45,N,12311.12,W,225444,A*ZZ")

    assert sentence.checksum_delimiter_present is True
    assert sentence.checksum_provided is False
    assert sentence.checksum_value is None
    assert sentence.checksum_valid is None


@pytest.mark.parametrize(
    "raw_sentence, expected_message",
    [
        ("", "Sentence is empty"),
        ("GPGLL,4916.45,N,12311.12,W,225444,A*31", "Sentence must start with '$'"),
        ("$", "Sentence payload is empty"),
        ("$12,1,2,3*00", "Unsupported sentence formatter"),
    ],
)
def test_parse_sentence_rejects_invalid_input(raw_sentence: str, expected_message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(expected_message)):
        parse_sentence(raw_sentence)
