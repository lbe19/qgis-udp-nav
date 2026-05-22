from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Optional, Tuple

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{2}$")


@dataclass
class Sentence:
    raw: str
    formatter: str
    sentence_type: str
    talker: Optional[str]
    fields: list[str]
    checksum_delimiter_present: bool
    checksum_provided: bool
    checksum_value: Optional[str]
    checksum_calculated: str
    checksum_valid: Optional[bool]


def split_datagram(payload: str) -> Iterable[str]:
    normalized = payload.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        cleaned = line.strip()
        if cleaned:
            yield cleaned


def calculate_checksum(body: str) -> str:
    checksum = 0
    for ch in body:
        checksum ^= ord(ch)
    return f"{checksum:02X}"


def _derive_identity(formatter: str) -> Tuple[str, Optional[str]]:
    upper = formatter.upper()
    if not upper:
        raise ValueError("Sentence formatter is empty")

    if upper.startswith("P"):
        # Proprietary sentence (for example PSIMSSB).
        return upper, None

    if len(upper) >= 5 and upper[-3:].isalpha():
        # Talker agnostic identity: GPGGA, GNGGA, INGGA => GGA.
        return upper[-3:], upper[:-3] or None

    if len(upper) == 3 and upper.isalpha():
        return upper, None

    raise ValueError(f"Unsupported sentence formatter '{formatter}'")


def parse_sentence(raw_sentence: str) -> Sentence:
    text = raw_sentence.strip()
    if not text:
        raise ValueError("Sentence is empty")
    if not text.startswith("$"):
        raise ValueError("Sentence must start with '$'")

    checksum_delimiter_present = "*" in text
    checksum_provided = False
    checksum_value: Optional[str] = None

    if checksum_delimiter_present:
        payload, checksum_part = text[1:].split("*", 1)
        checksum_part = checksum_part.strip()
        if len(checksum_part) >= 2 and _HEX_RE.match(checksum_part[:2]):
            checksum_provided = True
            checksum_value = checksum_part[:2].upper()
    else:
        payload = text[1:]

    if not payload:
        raise ValueError("Sentence payload is empty")

    checksum_calculated = calculate_checksum(payload)
    if checksum_provided and checksum_value is not None:
        checksum_valid: Optional[bool] = checksum_calculated == checksum_value
    else:
        checksum_valid = None

    parts = payload.split(",")
    formatter = parts[0].upper().strip()
    fields = [field.strip() for field in parts[1:]]
    sentence_type, talker = _derive_identity(formatter)

    return Sentence(
        raw=text,
        formatter=formatter,
        sentence_type=sentence_type,
        talker=talker,
        fields=fields,
        checksum_delimiter_present=checksum_delimiter_present,
        checksum_provided=checksum_provided,
        checksum_value=checksum_value,
        checksum_calculated=checksum_calculated,
        checksum_valid=checksum_valid,
    )
