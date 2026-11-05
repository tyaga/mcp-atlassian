"""Date windows, period buckets and the absence pattern for Tempo tools."""

from __future__ import annotations

import re
from datetime import date, timedelta

from mcp_atlassian.models.tempo.common import seconds_to_hours
from mcp_atlassian.utils.env import get_int_env, get_regex_env

DEFAULT_MAX_WINDOW_DAYS = 92
DEFAULT_ABSENCE_PATTERN = r"отпуск|больничн|отгул|vacation|sick leave|day off|time off"

Bucket = tuple[str, date, date]

__all__ = [
    "Bucket",
    "absence_pattern",
    "buckets_for",
    "day_buckets",
    "iso_week_buckets",
    "max_window_days",
    "parse_window",
    "seconds_to_hours",
    "total_bucket",
]


def max_window_days() -> int:
    """Maximum inclusive span of a date window, from ``TEMPO_MAX_WINDOW_DAYS``."""
    return get_int_env("TEMPO_MAX_WINDOW_DAYS", DEFAULT_MAX_WINDOW_DAYS)


def _parse_iso(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a YYYY-MM-DD date, got {value!r}") from exc


def parse_window(date_from: str, date_to: str) -> tuple[date, date]:
    """Parse an inclusive date window and enforce the maximum span."""
    start = _parse_iso(date_from, "date_from")
    end = _parse_iso(date_to, "date_to")
    if start > end:
        raise ValueError(
            f"date_from ({date_from}) must not be after date_to ({date_to})"
        )
    limit = max_window_days()
    span = (end - start).days + 1
    if span > limit:
        raise ValueError(
            f"Date window spans {span} days; the maximum is {limit} "
            "(TEMPO_MAX_WINDOW_DAYS). Split the request into smaller windows."
        )
    return start, end


def absence_pattern() -> re.Pattern[str]:
    """Compiled, case-insensitive regex that marks plan items as absences."""
    return re.compile(
        get_regex_env("TEMPO_ABSENCE_PATTERN", DEFAULT_ABSENCE_PATTERN),
        re.IGNORECASE,
    )


def day_buckets(date_from: date, date_to: date) -> list[Bucket]:
    """One bucket per calendar day, labelled with the ISO date."""
    buckets: list[Bucket] = []
    current = date_from
    while current <= date_to:
        buckets.append((current.isoformat(), current, current))
        current += timedelta(days=1)
    return buckets


def iso_week_buckets(date_from: date, date_to: date) -> list[Bucket]:
    """One bucket per ISO week (``YYYY-Www``), clipped to the window."""
    buckets: list[Bucket] = []
    current = date_from
    while current <= date_to:
        week_end = min(current + timedelta(days=6 - current.weekday()), date_to)
        iso_year, iso_week, _ = current.isocalendar()
        buckets.append((f"{iso_year}-W{iso_week:02d}", current, week_end))
        current = week_end + timedelta(days=1)
    return buckets


def total_bucket(date_from: date, date_to: date) -> list[Bucket]:
    """A single bucket covering the whole window."""
    return [("total", date_from, date_to)]


def buckets_for(granularity: str, date_from: date, date_to: date) -> list[Bucket]:
    """Buckets for ``granularity`` ∈ {day, week, total}."""
    if granularity == "day":
        return day_buckets(date_from, date_to)
    if granularity == "week":
        return iso_week_buckets(date_from, date_to)
    if granularity == "total":
        return total_bucket(date_from, date_to)
    raise ValueError(
        f"granularity must be one of 'day', 'week', 'total', got {granularity!r}"
    )
