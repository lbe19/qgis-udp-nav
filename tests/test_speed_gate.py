"""Tests for track speed gate (outlier rejection)."""

from __future__ import annotations

import math
import sys
import os
import time
from unittest.mock import MagicMock

_qgis_mock = MagicMock()
sys.modules["qgis"] = _qgis_mock
sys.modules["qgis.PyQt"] = _qgis_mock
sys.modules["qgis.PyQt.QtCore"] = _qgis_mock
sys.modules["qgis.PyQt.QtGui"] = _qgis_mock
sys.modules["qgis.core"] = _qgis_mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qgis_udp_nav_plugin.map.layer_manager import LayerManager
from qgis_udp_nav_plugin.model.feed_config import FeedConfig


def _feed(max_speed: float = 3.0) -> FeedConfig:
    return FeedConfig(
        feed_id="test-vehicle",
        name="Test Vehicle",
        track_max_speed_ms=max_speed,
    )


class TestSpeedGate:
    def test_first_fix_always_accepted(self):
        lm = LayerManager()
        feed = _feed(3.0)
        assert lm._passes_speed_gate(feed, 60.0, 5.0) is True

    def test_fast_movement_rejected(self):
        lm = LayerManager()
        feed = _feed(3.0)
        lm._passes_speed_gate(feed, 60.0, 5.0)
        # 0.0001 deg lat is ~11m. Pin elapsed time because Windows timer
        # resolution can report no monotonic advance after a 10ms sleep.
        lm._track_last_accepted["test-vehicle"] = (
            60.0,
            5.0,
            time.monotonic() - 0.1,
        )
        assert lm._passes_speed_gate(feed, 60.0001, 5.0) is False

    def test_slow_movement_accepted(self):
        lm = LayerManager()
        feed = _feed(3.0)
        lm._passes_speed_gate(feed, 60.0, 5.0)
        # 11m in 10 seconds = 1.1 m/s -- accept
        lm._track_last_accepted["test-vehicle"] = (60.0, 5.0, time.monotonic() - 10.0)
        assert lm._passes_speed_gate(feed, 60.0001, 5.0) is True

    def test_large_jump_rejected(self):
        lm = LayerManager()
        feed = _feed(3.0)
        lm._passes_speed_gate(feed, 60.0, 5.0)
        # 111m in 1 second = 111 m/s -- reject
        lm._track_last_accepted["test-vehicle"] = (60.0, 5.0, time.monotonic() - 1.0)
        assert lm._passes_speed_gate(feed, 60.001, 5.0) is False

    def test_gate_disabled_when_zero(self):
        lm = LayerManager()
        feed = _feed(0.0)
        lm._passes_speed_gate(feed, 60.0, 5.0)
        lm._track_last_accepted["test-vehicle"] = (60.0, 5.0, time.monotonic() - 0.1)
        # Huge jump should pass when gate is disabled
        assert lm._passes_speed_gate(feed, 61.0, 5.0) is True

    def test_equirect_distance_sanity(self):
        dist = LayerManager._equirect_distance_m(60.0, 5.0, 61.0, 5.0)
        assert 110000 < dist < 112000
        assert LayerManager._equirect_distance_m(60.0, 5.0, 60.0, 5.0) == 0.0

    def test_near_simultaneous_fixes_accepted(self):
        lm = LayerManager()
        feed = _feed(3.0)
        lm._passes_speed_gate(feed, 60.0, 5.0)
        lm._track_last_accepted["test-vehicle"] = (60.0, 5.0, time.monotonic())
        # dt ~ 0 so speed calc skipped -- accept
        assert lm._passes_speed_gate(feed, 60.01, 5.0) is True

    def test_config_roundtrip(self):
        feed = _feed(3.5)
        data = feed.to_dict()
        assert data["track_max_speed_ms"] == 3.5
        restored = FeedConfig.from_dict(data)
        assert restored.track_max_speed_ms == 3.5

    def test_config_default_disabled(self):
        feed = FeedConfig(feed_id="x", name="X")
        assert feed.track_max_speed_ms == 0.0
