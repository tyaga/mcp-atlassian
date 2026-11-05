"""Tests for Tempo user schedule operations."""

from datetime import date

from mcp_atlassian.models.tempo import TempoUserRef
from tests.unit.tempo.conftest import make_fetcher

SCHEDULE = {
    "numberOfWorkingDays": 2,
    "requiredSeconds": 57600,
    "days": [
        {
            "date": "2026-05-01",
            "requiredSeconds": 0,
            "type": "HOLIDAY",
            "holiday": {"name": "Labour Day"},
        },
        {
            "date": "2026-05-02",
            "requiredSeconds": 0,
            "type": "HOLIDAY_AND_NON_WORKING_DAY",
            "holiday": {"name": "Sat"},
        },
        {
            "date": "2026-05-03",
            "requiredSeconds": 0,
            "type": "HOLIDAY_AND_NON_WORKING_DAY",
            "holiday": {"name": "Sun"},
        },
        {"date": "2026-05-04", "requiredSeconds": 28800, "type": "WORKING_DAY"},
        {"date": "2026-05-05", "requiredSeconds": 28800, "type": "WORKING_DAY"},
    ],
}


def test_schedule_maps_days_and_totals():
    fetcher = make_fetcher({("GET", "/rest/tempo-core/1/user/schedule"): SCHEDULE})
    user = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane Doe")

    schedule = fetcher.get_user_schedule(user, date(2026, 5, 1), date(2026, 5, 5))

    assert schedule.user is user
    assert schedule.working_days == 2
    assert schedule.required_hours == 16.0
    assert [d.type for d in schedule.days] == [
        "HOLIDAY",
        "HOLIDAY_AND_NON_WORKING_DAY",
        "HOLIDAY_AND_NON_WORKING_DAY",
        "WORKING_DAY",
        "WORKING_DAY",
    ]
    assert schedule.days[0].holiday_name == "Labour Day"
    assert fetcher.client.calls == [  # type: ignore[attr-defined]
        (
            "GET",
            "/rest/tempo-core/1/user/schedule",
            {"user": "jdoe", "from": "2026-05-01", "to": "2026-05-05"},
        )
    ]


def test_schedule_uses_key_when_username_missing():
    fetcher = make_fetcher({("GET", "/rest/tempo-core/1/user/schedule"): SCHEDULE})
    fetcher.get_user_schedule(
        TempoUserRef(key="JIRAUSER1001"), date(2026, 5, 1), date(2026, 5, 5)
    )
    assert fetcher.client.calls[0][2]["user"] == "JIRAUSER1001"  # type: ignore[attr-defined]
