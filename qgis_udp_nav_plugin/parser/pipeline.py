from __future__ import annotations

from typing import List

from ..model.events import ParseWarningEvent
from ..model.feed_config import FeedConfig
from .core import parse_sentence, split_datagram
from .kongsberg import parse_kongsberg_sentence
from .nmea_standard import parse_standard_sentence

_SUPPORTED_STANDARD = {
    "GGA",
    "GLL",
    "RMC",
    "GSA",
    "HDT",
    "HDM",
    "HDG",
    "THS",
    "VHW",
}


class SentencePipeline:
    def parse_datagram(
        self,
        feed_config: FeedConfig,
        payload: str,
        source_address: str = "",
    ) -> List[object]:
        events: List[object] = []

        for line in split_datagram(payload):
            try:
                sentence = parse_sentence(line)
            except ValueError as exc:
                events.append(
                    ParseWarningEvent(
                        feed_id=feed_config.feed_id,
                        raw_sentence=line,
                        sentence_type="UNKNOWN",
                        talker=None,
                        message=f"Cannot parse sentence: {exc}",
                    )
                )
                continue

            reject_sentence, checksum_warning = self._checksum_handling(feed_config, sentence)
            if checksum_warning:
                events.append(
                    ParseWarningEvent(
                        feed_id=feed_config.feed_id,
                        raw_sentence=sentence.raw,
                        sentence_type=sentence.sentence_type,
                        talker=sentence.talker,
                        message=checksum_warning,
                    )
                )
            if reject_sentence:
                continue

            try:
                if sentence.formatter in {"PSIMSSB", "PSIMSNS"}:
                    parsed = parse_kongsberg_sentence(feed_config.feed_id, sentence)
                elif sentence.sentence_type in _SUPPORTED_STANDARD:
                    parsed = parse_standard_sentence(feed_config.feed_id, sentence)
                else:
                    parsed = []
            except (ValueError, TypeError) as exc:
                events.append(
                    ParseWarningEvent(
                        feed_id=feed_config.feed_id,
                        raw_sentence=sentence.raw,
                        sentence_type=sentence.sentence_type,
                        talker=sentence.talker,
                        message=f"Failed to parse {sentence.sentence_type}: {exc}",
                    )
                )
                continue

            for event in parsed:
                metadata = getattr(event, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.setdefault("source_address", source_address or None)
                events.append(event)

        return events

    @staticmethod
    def _checksum_handling(feed_config: FeedConfig, sentence) -> tuple[bool, str]:
        policy = feed_config.checksum_policy

        if policy == "ignore":
            return False, ""

        if policy == "strict":
            if sentence.checksum_valid is not True:
                return (
                    True,
                    "Checksum rejected by strict policy "
                    "(missing checksum or checksum mismatch).",
                )
            return False, ""

        if sentence.checksum_valid is False:
            return False, "Checksum mismatch; sentence accepted by lenient policy."

        return False, ""
