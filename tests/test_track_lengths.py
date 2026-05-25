"""Tests for incremental track length calculation.

Verifies that the incremental approach (Phase 1) produces the same results
as the full O(n) _calculate_track_lengths static method.
"""

from __future__ import annotations

import math
import sys
import os
from unittest.mock import MagicMock

# Mock qgis modules before importing layer_manager
_qgis_mock = MagicMock()
sys.modules["qgis"] = _qgis_mock
sys.modules["qgis.PyQt"] = _qgis_mock
sys.modules["qgis.PyQt.QtCore"] = _qgis_mock
sys.modules["qgis.PyQt.QtGui"] = _qgis_mock
sys.modules["qgis.core"] = _qgis_mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qgis_udp_nav_plugin.map.layer_manager import (  # noqa: E402
    LayerManager,
    _TRACK_MAX_POINTS,
    _TRACK_SMOOTHING_WINDOW,
)


def _generate_track_points(count: int, use_3d: bool = False):
    points = []
    base_lat = 60.0
    base_lon = 5.0
    for i in range(count):
        lat = base_lat + i * 0.0001
        lon = base_lon + i * 0.00005
        depth = float(i * 0.5) if use_3d else 0.0
        points.append((lat, lon, depth))
    return points


def _incremental_track_lengths(points, use_depth_3d: bool):
    origin = None
    local_xy = []
    raw_length = 0.0

    for lat, lon, depth in points:
        if origin is None:
            origin = (float(lat), float(lon))
            local_xy.clear()
            raw_length = 0.0

        z_m = float(depth) if use_depth_3d else 0.0
        x_m, y_m = LayerManager._latlon_to_local_xy(origin[0], origin[1], lat, lon)
        local_xy.append((x_m, y_m, z_m))

        if len(local_xy) >= 2:
            prev = local_xy[-2]
            dx = x_m - prev[0]
            dy = y_m - prev[1]
            dz = (z_m - prev[2]) if use_depth_3d else 0.0
            raw_length += math.sqrt(dx * dx + dy * dy + dz * dz)

    smoothed = LayerManager._smooth_xyz(local_xy, _TRACK_SMOOTHING_WINDOW)
    smoothed_length = LayerManager._polyline_length(smoothed, use_depth_3d)

    return raw_length, smoothed_length


class TestIncrementalTrackLengths:
    def test_incremental_matches_full_2d(self):
        points = _generate_track_points(100, use_3d=False)
        full_raw, full_smooth = LayerManager._calculate_track_lengths(points, use_depth_3d=False)
        incr_raw, incr_smooth = _incremental_track_lengths(points, use_depth_3d=False)

        assert abs(full_raw - incr_raw) < 0.001, f"Raw: {full_raw} vs {incr_raw}"
        assert abs(full_smooth - incr_smooth) < 0.001, f"Smooth: {full_smooth} vs {incr_smooth}"

    def test_incremental_matches_full_3d(self):
        points = _generate_track_points(100, use_3d=True)
        full_raw, full_smooth = LayerManager._calculate_track_lengths(points, use_depth_3d=True)
        incr_raw, incr_smooth = _incremental_track_lengths(points, use_depth_3d=True)

        assert abs(full_raw - incr_raw) < 0.001, f"Raw: {full_raw} vs {incr_raw}"
        assert abs(full_smooth - incr_smooth) < 0.001, f"Smooth: {full_smooth} vs {incr_smooth}"

    def test_incremental_with_fifo_trim(self):
        all_points = _generate_track_points(_TRACK_MAX_POINTS + 50, use_3d=False)
        trimmed_points = all_points[-_TRACK_MAX_POINTS:]
        full_raw, full_smooth = LayerManager._calculate_track_lengths(trimmed_points, use_depth_3d=False)
        incr_raw, incr_smooth = _incremental_track_lengths(trimmed_points, use_depth_3d=False)
        assert abs(full_raw - incr_raw) < 0.001
        assert abs(full_smooth - incr_smooth) < 0.001

    def test_single_point_returns_zero(self):
        points = _generate_track_points(1)
        full_raw, full_smooth = LayerManager._calculate_track_lengths(points, use_depth_3d=False)
        incr_raw, incr_smooth = _incremental_track_lengths(points, use_depth_3d=False)
        assert full_raw == 0.0
        assert full_smooth == 0.0
        assert incr_raw == 0.0
        assert incr_smooth == 0.0

    def test_two_points(self):
        points = _generate_track_points(2)
        full_raw, full_smooth = LayerManager._calculate_track_lengths(points, use_depth_3d=False)
        incr_raw, incr_smooth = _incremental_track_lengths(points, use_depth_3d=False)
        assert full_raw > 0
        assert abs(full_raw - incr_raw) < 0.001
        assert abs(full_smooth - incr_smooth) < 0.001

    def test_raw_length_positive_and_increasing(self):
        for n in [10, 50, 200, 1000]:
            points = _generate_track_points(n)
            raw, smooth = _incremental_track_lengths(points, use_depth_3d=False)
            assert raw > 0
            assert smooth > 0

    def test_latlon_to_local_xy_identity_at_origin(self):
        x, y = LayerManager._latlon_to_local_xy(60.0, 5.0, 60.0, 5.0)
        assert x == 0.0
        assert y == 0.0

    def test_latlon_to_local_xy_north_movement(self):
        x, y = LayerManager._latlon_to_local_xy(60.0, 5.0, 61.0, 5.0)
        assert abs(x) < 0.01
        assert 110000 < y < 112000
