"""Prediction-accuracy pairing core (#56).

Pure date/number logic -- no Home Assistant imports -- so the pairing
rules are unit-testable offline. The sensor layer feeds this module two
daily series built from recorder long-term statistics:

- ``forecast_by_day``: {date: value} where the value for day D is the
  *last* state of the "Tomorrow's Forecast" sensor on day D. Gas Wizard
  publishes the next day's forecast during the evening of D, so the
  last value of day D is the prediction *for D+1*.
- ``actual_by_day``: {date: value} where the value for day D is the
  last state of the "Today's Price" sensor on day D (the price that
  actually ruled on D; it is stable through the day once published).

A pair for target day T therefore joins ``forecast_by_day[T - 1]`` with
``actual_by_day[T]``. A pair is a hit when the absolute error is at
most ``tolerance`` cents per litre (default 1.0, per the issue spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_WINDOW_DAYS = 30
DEFAULT_TOLERANCE = 1.0


@dataclass(frozen=True)
class AccuracyPair:
    """One forecast/actual pair for a target day."""

    target_day: date
    forecast: float
    actual: float

    @property
    def error(self) -> float:
        return abs(self.forecast - self.actual)


@dataclass(frozen=True)
class AccuracyResult:
    """Aggregate over the pairs inside the window."""

    pairs: tuple[AccuracyPair, ...]
    hits: int
    tolerance: float

    @property
    def pair_count(self) -> int:
        return len(self.pairs)

    @property
    def hit_rate(self) -> float | None:
        """Percentage of pairs within tolerance; None when no pairs."""
        if not self.pairs:
            return None
        return round(100.0 * self.hits / len(self.pairs), 1)

    @property
    def mean_abs_error(self) -> float | None:
        """Mean absolute error in c/L; None when no pairs."""
        if not self.pairs:
            return None
        return round(sum(p.error for p in self.pairs) / len(self.pairs), 2)


def daily_series_from_rows(rows, tz) -> dict[date, float]:
    """Build a {local date: value} series from day-period statistics rows.

    ``rows`` are ``statistics_during_period(..., "day", ...)`` rows for
    one statistic id; ``tz`` is the local timezone the recorder bucketed
    the days in (Home Assistant's default timezone). Prefers the row's
    ``state`` -- the last recorded value of the day, which for the
    forecast sensor is the evening-published prediction for tomorrow --
    and falls back to ``mean``. Rows without a usable value are skipped.
    """
    from datetime import datetime, timezone

    series: dict[date, float] = {}
    for row in rows or []:
        value = row.get("state")
        if value is None:
            value = row.get("mean")
        start = row.get("start")
        if value is None or start is None:
            continue
        if isinstance(start, datetime):
            moment = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        else:
            moment = datetime.fromtimestamp(start, tz=timezone.utc)
        series[moment.astimezone(tz).date()] = float(value)
    return series


def compute_accuracy(
    forecast_by_day: dict[date, float],
    actual_by_day: dict[date, float],
    *,
    today: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> AccuracyResult:
    """Pair forecasts with next-day actuals over a rolling window.

    The window covers target days in ``(today - window_days, today]``:
    today's pair is included once today's actual is known; a forecast
    made yesterday for today pairs even though the forecast day itself
    falls just outside the window. Days missing on either side are
    skipped silently -- gaps (HA downtime, source outages) shrink the
    pair count instead of fabricating a verdict, and the pair count is
    reported alongside the rate so a thin sample is self-qualifying.
    """
    earliest = today - timedelta(days=window_days)
    pairs: list[AccuracyPair] = []
    for target_day in sorted(actual_by_day):
        if not (earliest < target_day <= today):
            continue
        forecast = forecast_by_day.get(target_day - timedelta(days=1))
        if forecast is None:
            continue
        pairs.append(
            AccuracyPair(
                target_day=target_day,
                forecast=forecast,
                actual=actual_by_day[target_day],
            )
        )
    hits = sum(1 for p in pairs if p.error <= tolerance)
    return AccuracyResult(pairs=tuple(pairs), hits=hits, tolerance=tolerance)
