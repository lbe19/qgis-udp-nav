from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BaseEvent:
    feed_id: str
    raw_sentence: str
    sentence_type: str
    talker: Optional[str]
    received_at: datetime = field(default_factory=utc_now)


@dataclass
class PositionFixEvent(BaseEvent):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    valid: bool = False
    status_text: str = ""
    source: str = ""
    fix_time_utc: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedStatusEvent(BaseEvent):
    level: str = "info"
    message: str = ""
    code: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseWarningEvent(BaseEvent):
    message: str = ""


@dataclass
class HeadingEvent(BaseEvent):
    heading_deg: Optional[float] = None
    is_true_heading: bool = False
    valid: bool = True
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
