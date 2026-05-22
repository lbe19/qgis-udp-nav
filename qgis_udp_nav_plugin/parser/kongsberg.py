from __future__ import annotations

from typing import List, Optional

from ..model.events import FeedStatusEvent, PositionFixEvent
from .core import Sentence

_SSB_ERROR_CODES = {
    "NRy": "No reply is received. No position is calculated.",
    "AmX": "Ambiguity error in X direction. No position is calculated.",
    "AmY": "Ambiguity error in Y direction. No position is calculated.",
    "Rej": "Position measured but rejected by software filter.",
    "Mi2": "Second pulse from transponder reply is missing.",
    "Mi3": "Third pulse from transponder reply is missing.",
    "Pre": "No position measured. Position predicted by filter.",
    "VRU": "VRU reported error. Roll/pitch compensation may be invalid.",
    "GYR": "Gyro reported error. Heading compensation may be invalid.",
    "ATT": "Attitude sensor reported error.",
    "ExD": "External depth used in position calculation.",
    "ExM": "External depth wanted but not received.",
    "???": "Unknown system error reported.",
}


def _field(fields: list[str], index: int) -> str:
    if index < len(fields):
        return fields[index]
    return ""


def _optional_float(value: str) -> Optional[float]:
    if value == "":
        return None
    return float(value)


def parse_kongsberg_sentence(feed_id: str, sentence: Sentence) -> List[object]:
    if sentence.formatter == "PSIMSSB":
        return parse_psimssb(feed_id, sentence)
    if sentence.formatter == "PSIMSNS":
        return parse_psimsns(feed_id, sentence)
    return []


def parse_psimssb(feed_id: str, sentence: Sentence) -> List[object]:
    fields = sentence.fields

    utc_time = _field(fields, 0)
    tp_code = _field(fields, 1)
    status = _field(fields, 2).upper()
    error_code = _field(fields, 3)
    coordinate_system = _field(fields, 4).upper()
    orientation = _field(fields, 5).upper()
    sw_filter = _field(fields, 6).upper()
    x_coordinate = _optional_float(_field(fields, 7))
    y_coordinate = _optional_float(_field(fields, 8))
    depth_m = _optional_float(_field(fields, 9))
    expected_accuracy_m = _optional_float(_field(fields, 10))
    additional_info = _field(fields, 11).upper()
    first_additional = _field(fields, 12)
    second_additional = _field(fields, 13)

    description = _SSB_ERROR_CODES.get(error_code, "")

    valid_position = status == "A" and x_coordinate is not None and y_coordinate is not None
    status_text = "Valid" if valid_position else "Invalid or missing position"

    events: List[object] = [
        PositionFixEvent(
            feed_id=feed_id,
            raw_sentence=sentence.raw,
            sentence_type=sentence.sentence_type,
            talker=sentence.talker,
            latitude=None,
            longitude=None,
            valid=valid_position,
            status_text=status_text,
            source="KONGSBERG-PSIMSSB",
            fix_time_utc=utc_time or None,
            metadata={
                "tp_code": tp_code or None,
                "status": status or None,
                "error_code": error_code or None,
                "coordinate_system": coordinate_system or None,
                "orientation": orientation or None,
                "sw_filter": sw_filter or None,
                "x_coordinate": x_coordinate,
                "y_coordinate": y_coordinate,
                "depth_m": depth_m,
                "expected_accuracy_m": expected_accuracy_m,
                "additional_info": additional_info or None,
                "first_additional": first_additional or None,
                "second_additional": second_additional or None,
            },
        )
    ]

    if status == "V":
        reason = description or "Position reported as invalid by HiPAP"
        events.append(
            FeedStatusEvent(
                feed_id=feed_id,
                raw_sentence=sentence.raw,
                sentence_type=sentence.sentence_type,
                talker=sentence.talker,
                level="warning",
                code=error_code,
                message=f"PSIMSSB invalid ({error_code or 'no code'}): {reason}",
                metadata={
                    "tp_code": tp_code or None,
                },
            )
        )
    elif status == "A" and error_code:
        reason = description or "Position marked valid but includes warning/error code"
        events.append(
            FeedStatusEvent(
                feed_id=feed_id,
                raw_sentence=sentence.raw,
                sentence_type=sentence.sentence_type,
                talker=sentence.talker,
                level="warning",
                code=error_code,
                message=f"PSIMSSB valid with code {error_code}: {reason}",
                metadata={
                    "tp_code": tp_code or None,
                },
            )
        )
    elif status not in ("A", "V"):
        events.append(
            FeedStatusEvent(
                feed_id=feed_id,
                raw_sentence=sentence.raw,
                sentence_type=sentence.sentence_type,
                talker=sentence.talker,
                level="warning",
                code="STATUS",
                message=f"PSIMSSB has unknown status field '{status or '<empty>'}'",
                metadata={
                    "tp_code": tp_code or None,
                },
            )
        )

    if status == "A" and not valid_position:
        events.append(
            FeedStatusEvent(
                feed_id=feed_id,
                raw_sentence=sentence.raw,
                sentence_type=sentence.sentence_type,
                talker=sentence.talker,
                level="warning",
                code="NO_COORD",
                message="PSIMSSB status is A but coordinates are missing",
                metadata={
                    "tp_code": tp_code or None,
                },
            )
        )

    return events


def parse_psimsns(feed_id: str, sentence: Sentence) -> List[object]:
    fields = sentence.fields

    utc_time = _field(fields, 0)
    pos_item = _field(fields, 1)
    transceiver = _field(fields, 2)
    transducer = _field(fields, 3)
    roll = _optional_float(_field(fields, 4))
    pitch = _optional_float(_field(fields, 5))
    heave = _optional_float(_field(fields, 6))
    heading = _optional_float(_field(fields, 7))
    tag = _field(fields, 8)
    parameters = _field(fields, 9)
    time_age_s = _optional_float(_field(fields, 10))
    master_slave = _field(fields, 12)

    has_position_association = bool(pos_item)

    if has_position_association:
        level = "info"
        message = f"PSIMSNS sensor update for item {pos_item}"
    else:
        level = "warning"
        message = (
            "PSIMSNS sensor update received without associated position item "
            "(HiPAP no-valid-position period)."
        )

    return [
        FeedStatusEvent(
            feed_id=feed_id,
            raw_sentence=sentence.raw,
            sentence_type=sentence.sentence_type,
            talker=sentence.talker,
            level=level,
            code="NO_POSITION" if not has_position_association else "SNS",
            message=message,
            metadata={
                "clock": utc_time or None,
                "pos_item": pos_item or None,
                "transceiver": transceiver or None,
                "transducer": transducer or None,
                "roll_deg": roll,
                "pitch_deg": pitch,
                "heave_m": heave,
                "heading_deg": heading,
                "heading_kind": "gyro",
                "heading_is_true": False,
                "tag": tag or None,
                "parameters": parameters or None,
                "time_age_s": time_age_s,
                "master_slave": master_slave or None,
            },
        )
    ]
