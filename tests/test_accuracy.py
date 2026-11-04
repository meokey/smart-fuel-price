"""Offline tests for the #56 accuracy pairing core.

accuracy.py has no Home Assistant imports, so it is loaded directly
from its file path -- importing the integration package would pull in
homeassistant (same reason conftest stands in for the providers).
"""

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ACCURACY_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "smart_fuel_price" / "accuracy.py"
)
_spec = importlib.util.spec_from_file_location("sfp_accuracy", _ACCURACY_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sfp_accuracy"] = _mod  # dataclasses resolve the module here
_spec.loader.exec_module(_mod)
compute_accuracy = _mod.compute_accuracy

TODAY = date(2026, 11, 3)


def _series(start: date, values: list[float]) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def test_pairs_forecast_from_previous_day_with_actual():
    # Forecast recorded on Oct 31 (for Nov 1) vs actual on Nov 1, etc.
    forecast = _series(date(2026, 10, 31), [180.0, 181.0])
    actual = _series(date(2026, 11, 1), [180.5, 185.0])
    result = compute_accuracy(forecast, actual, today=TODAY)

    assert result.pair_count == 2
    assert result.pairs[0].target_day == date(2026, 11, 1)
    assert result.pairs[0].forecast == pytest.approx(180.0)
    assert result.pairs[0].actual == pytest.approx(180.5)
    # |180.0-180.5| = 0.5 -> hit; |181.0-185.0| = 4.0 -> miss.
    assert result.hits == 1
    assert result.hit_rate == pytest.approx(50.0)
    assert result.mean_abs_error == pytest.approx(2.25)


def test_exactly_one_cent_counts_as_hit():
    forecast = {TODAY - timedelta(days=1): 170.0}
    actual = {TODAY: 171.0}
    result = compute_accuracy(forecast, actual, today=TODAY)
    assert result.hits == 1
    assert result.hit_rate == pytest.approx(100.0)


def test_missing_side_skips_pair_without_fabricating():
    # Forecast exists but no actual for the target day (and vice versa).
    forecast = {TODAY - timedelta(days=1): 170.0, TODAY: 172.0}
    actual = {TODAY - timedelta(days=2): 169.0}
    result = compute_accuracy(forecast, actual, today=TODAY)
    assert result.pair_count == 0
    assert result.hit_rate is None
    assert result.mean_abs_error is None


def test_window_excludes_old_targets_but_pairs_edge_forecast():
    # The window is (today - 30d, today]: a target 30 days ago is out;
    # a target 29 days ago is in, and its forecast (recorded 30 days
    # ago, just outside the window) still pairs.
    old_target = TODAY - timedelta(days=30)
    edge_target = TODAY - timedelta(days=29)
    forecast = {
        old_target - timedelta(days=1): 160.0,
        edge_target - timedelta(days=1): 161.0,
    }
    actual = {old_target: 160.0, edge_target: 161.5}
    result = compute_accuracy(forecast, actual, today=TODAY)
    assert [p.target_day for p in result.pairs] == [edge_target]


def test_future_actuals_ignored():
    forecast = {TODAY: 170.0}
    actual = {TODAY + timedelta(days=1): 170.0}
    result = compute_accuracy(forecast, actual, today=TODAY)
    assert result.pair_count == 0
