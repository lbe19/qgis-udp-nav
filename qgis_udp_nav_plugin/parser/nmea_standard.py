from __future__ import annotations

from typing import List, Optional, Tuple

from ..model.events import FeedStatusEvent, HeadingEvent, PositionFixEvent
from .core import Sentence

_GGA_QUALITY = {
    0: "No fix",
    1: "GPS fix",
    2: "DGPS fix",
    4: "RTK fixed",
    5: "RTK float",
    6: "Estimated",
}

_GSA_FIX_TYPE = {
    "1": "No fix",
    "2": "2D fix",
    "3": "3D fix",
}


def _field(fields: list[str], index: int) -> str:
    if index < len(fields):
        return fields[index]
    return ""


def _optional_float(value: str) -> Optional[float]:
    if value == "":
        return None
    return float(value)


def _optional_int(value: str) -> Optional[int]:
    if value == "":
        return None
    return int(value)


def _parse_dm(value: str, hemi: str, is_lat: bool) -> float:
    if not value or not hemi:
        raise ValueError("Missing coordinate component")

    if "." in value:
        left, right = value.split(".", 1)
        whole = left
        frac = right
    else:
        whole = value
        frac = ""

    degree_digits = 2 if is_lat else 3
    if len(whole) <= degree_digits:
        raise ValueError(f"Coordinate '{value}' does not contain minutes")

    degrees = int(whole[:degree_digits])
    minute_str = whole[degree_digits:] + (f".{frac}" if frac else "")
    minutes = float(minute_str)

    if minutes < 0 or minutes >= 60:
        raise ValueError(f"Coordinate minutes out of range in '{value}'")

    decimal = degrees + (minutes / 60.0)

    hemi = hemi.upper()
    if hemi in ("S", "W"):
        decimal *= -1
    elif hemi not in ("N", "E"):
        raise ValueError(f"Invalid hemisphere '{hemi}'")

    if is_lat and abs(decimal) > 90:
        raise ValueError(f"Latitude out of range in '{value}{hemi}'")
    if not is_lat and abs(decimal) > 180:
        raise ValueError(f"Longitude out of range in '{value}{hemi}'")

    return decimal


def _parse_lat_lon(
    lat_text: str,
    lat_hemi: str,
    lon_text: str,
    lon_hemi: str,
) -> Tuple[Optional[float], Optional[float]]:
    if not lat_text and not lon_text:
        return None, None
    if not lat_text or not lon_text:
        raise ValueError("Latitude/longitude pair is incomplete")

    lat = _parse_dm(lat_text, lat_hemi, is_lat=True)
    lon = _parse_dm(lon_text, lon_hemi, is_lat=False)
    return lat, lon


def _normalize_heading(value: float) -> float:
    heading = value % 360.0
    if heading < 0:
        heading += 360.0
    return heading


def parse_standard_sentence(feed_id: str, sentence: Sentence) -> List[object]:
    sentence_id = sentence.sentence_type

    if sentence_id == "GGA":
        return [parse_gga(feed_id, sentence)]
    if sentence_id == "GLL":
        return [parse_gll(feed_id, sentence)]
    if sentence_id == "RMC":
        return [parse_rmc(feed_id, sentence)]
    if sentence_id == "GSA":
        return [parse_gsa(feed_id, sentence)]
    if sentence_id == "HDT":
        return [parse_hdt(feed_id, sentence)]
    if sentence_id == "HDM":
        return [parse_hdm(feed_id, sentence)]
    if sentence_id == "HDG":
        return [parse_hdg(feed_id, sentence)]
    if sentence_id == "THS":
        return parse_ths(feed_id, sentence)
    if sentence_id == "VHW":
        return parse_vhw(feed_id, sentence)

    return []


def parse_gga(feed_id: str, sentence: Sentence) -> PositionFixEvent:
    fields = sentence.fields
    utc_time = _field(fields, 0)
    lat, lon = _parse_lat_lon(
        _field(fields, 1),
        _field(fields, 2),
        _field(fields, 3),
        _field(fields, 4),
    )

    quality = _optional_int(_field(fields, 5)) or 0
    satellites = _optional_int(_field(fields, 6))
    hdop = _optional_float(_field(fields, 7))
    altitude = _optional_float(_field(fields, 8))

    valid = quality > 0 and lat is not None and lon is not None
    status_text = _GGA_QUALITY.get(quality, "Unknown fix state")

    return PositionFixEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        latitude=lat,
        longitude=lon,
        valid=valid,
        status_text=status_text,
        source="NMEA-GGA",
        fix_time_utc=utc_time or None,
        metadata={
            "fix_quality": quality,
            "satellites": satellites,
            "hdop": hdop,
            "altitude_m": altitude,
        },
    )


def parse_gll(feed_id: str, sentence: Sentence) -> PositionFixEvent:
    fields = sentence.fields
    lat, lon = _parse_lat_lon(
        _field(fields, 0),
        _field(fields, 1),
        _field(fields, 2),
        _field(fields, 3),
    )
    utc_time = _field(fields, 4)
    status = _field(fields, 5).upper()
    mode_indicator = _field(fields, 6)

    valid = status == "A" and lat is not None and lon is not None
    status_text = "Valid" if status == "A" else "Invalid"

    return PositionFixEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        latitude=lat,
        longitude=lon,
        valid=valid,
        status_text=status_text,
        source="NMEA-GLL",
        fix_time_utc=utc_time or None,
        metadata={
            "status": status,
            "mode_indicator": mode_indicator or None,
        },
    )


def parse_rmc(feed_id: str, sentence: Sentence) -> PositionFixEvent:
    fields = sentence.fields
    utc_time = _field(fields, 0)
    status = _field(fields, 1).upper()
    lat, lon = _parse_lat_lon(
        _field(fields, 2),
        _field(fields, 3),
        _field(fields, 4),
        _field(fields, 5),
    )
    speed_knots = _optional_float(_field(fields, 6))
    course_deg = _optional_float(_field(fields, 7))
    utc_date = _field(fields, 8)
    mode_indicator = _field(fields, 11)

    valid = status == "A" and lat is not None and lon is not None
    status_text = "Valid" if status == "A" else "Invalid"

    return PositionFixEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        latitude=lat,
        longitude=lon,
        valid=valid,
        status_text=status_text,
        source="NMEA-RMC",
        fix_time_utc=utc_time or None,
        metadata={
            "status": status,
            "date": utc_date or None,
            "speed_knots": speed_knots,
            "course_deg": course_deg,
            "mode_indicator": mode_indicator or None,
        },
    )


def parse_gsa(feed_id: str, sentence: Sentence) -> FeedStatusEvent:
    fields = sentence.fields
    mode = _field(fields, 0)
    fix_type = _field(fields, 1)
    pdop = _optional_float(_field(fields, 14))
    hdop = _optional_float(_field(fields, 15))
    vdop = _optional_float(_field(fields, 16))

    level = "warning" if fix_type == "1" else "info"
    message = _GSA_FIX_TYPE.get(fix_type, "Unknown fix type")

    return FeedStatusEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        level=level,
        message=f"GSA fix type: {message}",
        code=fix_type,
        metadata={
            "mode": mode or None,
            "pdop": pdop,
            "hdop": hdop,
            "vdop": vdop,
        },
    )


def parse_hdt(feed_id: str, sentence: Sentence) -> HeadingEvent:
    fields = sentence.fields
    heading = _optional_float(_field(fields, 0))
    if heading is None:
        raise ValueError("HDT sentence missing heading field")

    normalized = _normalize_heading(heading)
    return HeadingEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        heading_deg=normalized,
        is_true_heading=True,
        valid=True,
        source="NMEA-HDT",
        metadata={
            "heading_true_deg": normalized,
            "heading_kind": "true",
        },
    )


def parse_hdm(feed_id: str, sentence: Sentence) -> HeadingEvent:
    fields = sentence.fields
    heading = _optional_float(_field(fields, 0))
    if heading is None:
        raise ValueError("HDM sentence missing heading field")

    normalized = _normalize_heading(heading)
    return HeadingEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        heading_deg=normalized,
        is_true_heading=False,
        valid=True,
        source="NMEA-HDM",
        metadata={
            "heading_magnetic_deg": normalized,
            "heading_kind": "magnetic",
        },
    )


def parse_hdg(feed_id: str, sentence: Sentence) -> HeadingEvent:
    fields = sentence.fields
    magnetic = _optional_float(_field(fields, 0))
    if magnetic is None:
        raise ValueError("HDG sentence missing heading field")

    magnetic = _normalize_heading(magnetic)
    variation = _optional_float(_field(fields, 3))
    variation_dir = _field(fields, 4).upper()

    true_heading: Optional[float] = None
    if variation is not None and variation_dir in ("E", "W"):
        if variation_dir == "E":
            true_heading = _normalize_heading(magnetic + variation)
        else:
            true_heading = _normalize_heading(magnetic - variation)

    resolved_heading = true_heading if true_heading is not None else magnetic
    return HeadingEvent(
        feed_id=feed_id,
        raw_sentence=sentence.raw,
        sentence_type=sentence.sentence_type,
        talker=sentence.talker,
        heading_deg=resolved_heading,
        is_true_heading=true_heading is not None,
        valid=True,
        source="NMEA-HDG",
        metadata={
            "heading_true_deg": true_heading,
            "heading_magnetic_deg": magnetic,
            "variation_deg": variation,
            "variation_dir": variation_dir or None,
            "heading_kind": "true" if true_heading is not None else "magnetic",
        },
    )


def parse_ths(feed_id: str, sentence: Sentence) -> List[object]:
    fields = sentence.fields
    heading = _optional_float(_field(fields, 0))
    status = _field(fields, 1).upper()

    if heading is None:
        raise ValueError("THS sentence missing heading field")

    normalized = _normalize_heading(heading)
    is_valid = status in ("", "A")

    events: List[object] = [
        HeadingEvent(
            feed_id=feed_id,
            raw_sentence=sentence.raw,
            sentence_type=sentence.sentence_type,
            talker=sentence.talker,
            heading_deg=normalized,
            is_true_heading=True,
            valid=is_valid,
            source="NMEA-THS",
            metadata={
                "status": status or None,
                "heading_kind": "true",
            },
        )
    ]

    if not is_valid:
        events.append(
            FeedStatusEvent(
                feed_id=feed_id,
                raw_sentence=sentence.raw,
                sentence_type=sentence.sentence_type,
                talker=sentence.talker,
                level="warning",
                code="THS_STATUS",
                message=f"THS heading status is '{status}', heading ignored for orientation",
                metadata={"status": status or None},
            )
        )

    return events


def parse_vhw(feed_id: str, sentence: Sentence) -> List[object]:
    fields = sentence.fields
    true_heading = _optional_float(_field(fields, 0))
    magnetic_heading = _optional_float(_field(fields, 2))

    if true_heading is None and magnetic_heading is None:
        return []

    is_true = true_heading is not None
    resolved = _normalize_heading(true_heading if true_heading is not None else magnetic_heading)
    return [
        HeadingEvent(
            feed_id=feed_id,
            raw_sentence=sentence.raw,
            sentence_type=sentence.sentence_type,
            talker=sentence.talker,
            heading_deg=resolved,
            is_true_heading=is_true,
            valid=True,
            source="NMEA-VHW",
            metadata={
                "heading_true_deg": _normalize_heading(true_heading)
                if true_heading is not None
                else None,
                "heading_magnetic_deg": _normalize_heading(magnetic_heading)
                if magnetic_heading is not None
                else None,
                "heading_kind": "true" if is_true else "magnetic",
            },
        )
    ]
