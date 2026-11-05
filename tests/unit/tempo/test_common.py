"""Tests for Tempo date-window and bucket helpers."""

from datetime import date

import pytest

from mcp_atlassian.tempo.common import (
    absence_pattern,
    day_buckets,
    iso_week_buckets,
    parse_window,
    total_bucket,
)


class TestParseWindow:
    def test_parse_window_ok(self):
        assert parse_window("2026-03-01", "2026-03-31") == (
            date(2026, 3, 1),
            date(2026, 3, 31),
        )

    def test_parse_window_rejects_reversed(self):
        with pytest.raises(ValueError, match="date_from"):
            parse_window("2026-03-31", "2026-03-01")

    def test_parse_window_rejects_bad_format(self):
        with pytest.raises(ValueError, match="date_to"):
            parse_window("2026-03-01", "31.03.2026")

    def test_parse_window_rejects_long_window(self):
        with pytest.raises(ValueError, match="92"):
            parse_window("2026-01-01", "2026-04-03")

    def test_parse_window_accepts_max_window(self):
        parse_window("2026-01-01", "2026-04-02")

    def test_parse_window_limit_from_env(self, monkeypatch):
        monkeypatch.setenv("TEMPO_MAX_WINDOW_DAYS", "7")
        with pytest.raises(ValueError, match="7"):
            parse_window("2026-01-01", "2026-01-08")


class TestBuckets:
    def test_iso_week_buckets_clips_to_window(self):
        buckets = iso_week_buckets(date(2026, 10, 29), date(2026, 11, 3))
        assert [b[0] for b in buckets] == ["2026-W44", "2026-W45"]
        assert buckets[0][1:] == (date(2026, 10, 29), date(2026, 11, 1))
        assert buckets[1][1:] == (date(2026, 11, 2), date(2026, 11, 3))

    def test_day_buckets(self):
        buckets = day_buckets(date(2026, 1, 30), date(2026, 2, 1))
        assert [b[0] for b in buckets] == ["2026-01-30", "2026-01-31", "2026-02-01"]
        assert buckets[0][1] == buckets[0][2] == date(2026, 1, 30)

    def test_total_bucket(self):
        assert total_bucket(date(2026, 1, 1), date(2026, 1, 31)) == [
            ("total", date(2026, 1, 1), date(2026, 1, 31))
        ]


class TestAbsencePattern:
    def test_default_pattern_matches_vacation(self):
        assert absence_pattern().search("Annual VACATION 1-14 July")
        assert absence_pattern().search("Отпуск 5-12 октября")
        assert not absence_pattern().search("Write unit tests")

    def test_absence_pattern_env_override(self, monkeypatch):
        monkeypatch.setenv("TEMPO_ABSENCE_PATTERN", "offsite")
        assert absence_pattern().search("Team offsite")
        assert not absence_pattern().search("vacation")
