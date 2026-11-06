"""Tests for the workload report."""

from datetime import date

import pytest

from mcp_atlassian.models.tempo import (
    TempoPlanItem,
    TempoScheduleDay,
    TempoTeam,
    TempoUserRef,
    TempoUserSchedule,
)
from mcp_atlassian.tempo import TempoScope
from mcp_atlassian.tempo.workload import build_workload
from tests.unit.tempo.conftest import make_fetcher

JANE = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane Doe")
ALEX = TempoUserRef(key="JIRAUSER1002", username="asmith", display_name="Alex Smith")

# Mon 2026-03-02 .. Sun 2026-03-08; Fri 03-06 is a public holiday.
WINDOW = (date(2026, 3, 2), date(2026, 3, 8))


def _schedule(user: TempoUserRef) -> TempoUserSchedule:
    days = []
    for offset in range(7):
        day = date(2026, 3, 2 + offset)
        if offset >= 5:
            days.append(
                TempoScheduleDay(
                    day=day.isoformat(), type="HOLIDAY_AND_NON_WORKING_DAY"
                )
            )
        elif offset == 4:
            days.append(
                TempoScheduleDay(
                    day=day.isoformat(), type="HOLIDAY", holiday_name="Day X"
                )
            )
        else:
            days.append(
                TempoScheduleDay(
                    day=day.isoformat(),
                    type="WORKING_DAY",
                    required_seconds=28800,
                    required_hours=8.0,
                )
            )
    return TempoUserSchedule(user=user, working_days=4, required_hours=32.0, days=days)


def _plan(
    user: TempoUserRef, day: str, key: str, hours: float, absence: bool = False
) -> TempoPlanItem:
    return TempoPlanItem(
        day=day,
        user=user,
        issue_key=key,
        summary=f"Summary {key}",
        planned_seconds=int(hours * 3600),
        planned_hours=hours,
        is_absence=absence,
    )


def _report(plans, users=(JANE,), granularity="day", limit=8.0, roles=None):
    schedules = {u.key: _schedule(u) for u in users}
    return build_workload(
        list(users),
        roles or {},
        schedules,
        plans,
        WINDOW[0],
        WINDOW[1],
        granularity,
        limit,
    )


def _day(report, day: str, user_index: int = 0):
    return next(p for p in report.users[user_index].periods if p.period == day)


class TestDayMath:
    def test_free_partial_full_statuses(self):
        report = _report(
            [
                _plan(JANE, "2026-03-03", "PROJ-1", 3.0),
                _plan(JANE, "2026-03-04", "PROJ-1", 4.0),
                _plan(JANE, "2026-03-04", "PROJ-2", 4.0),
            ]
        )
        assert _day(report, "2026-03-02").status == "free"
        assert _day(report, "2026-03-02").free_hours == 8.0
        partial = _day(report, "2026-03-03")
        assert (partial.status, partial.planned_hours, partial.free_hours) == (
            "partial",
            3.0,
            5.0,
        )
        full = _day(report, "2026-03-04")
        assert (full.status, full.free_hours, full.overbooked_hours) == (
            "full",
            0.0,
            0.0,
        )
        assert [(i.issue_key, i.hours) for i in full.items] == [
            ("PROJ-1", 4.0),
            ("PROJ-2", 4.0),
        ]

    def test_overbooked_on_working_day(self):
        report = _report([_plan(JANE, "2026-03-02", "PROJ-1", 10.0)])
        day = _day(report, "2026-03-02")
        assert (day.status, day.overbooked_hours, day.free_hours) == (
            "overbooked",
            2.0,
            0.0,
        )

    def test_weekend_with_plan_is_overbooked(self):
        report = _report([_plan(JANE, "2026-03-07", "PROJ-1", 2.0)])
        day = _day(report, "2026-03-07")
        assert (day.status, day.capacity_hours, day.overbooked_hours) == (
            "overbooked",
            0.0,
            2.0,
        )

    def test_holiday_without_plan_is_non_working(self):
        report = _report([])
        assert _day(report, "2026-03-06").status == "non_working"
        assert _day(report, "2026-03-08").status == "non_working"

    def test_absence_day_status_absent(self):
        report = _report([_plan(JANE, "2026-03-03", "PROJ-9", 8.0, absence=True)])
        day = _day(report, "2026-03-03")
        assert (day.status, day.absence_hours, day.planned_hours, day.free_hours) == (
            "absent",
            8.0,
            0.0,
            0.0,
        )
        assert day.items[0].is_absence is True

    def test_absence_plus_work_is_overbooked(self):
        report = _report(
            [
                _plan(JANE, "2026-03-03", "PROJ-9", 8.0, absence=True),
                _plan(JANE, "2026-03-03", "PROJ-1", 2.0),
            ]
        )
        assert _day(report, "2026-03-03").status == "overbooked"

    def test_daily_limit_lowers_capacity(self):
        report = _report([_plan(JANE, "2026-03-02", "PROJ-1", 7.0)], limit=6.0)
        day = _day(report, "2026-03-02")
        assert (day.capacity_hours, day.overbooked_hours, day.status) == (
            6.0,
            1.0,
            "overbooked",
        )

    def test_missing_schedule_day_means_zero_capacity(self):
        schedules = {JANE.key: TempoUserSchedule(user=JANE, days=[])}
        report = build_workload(
            [JANE], {}, schedules, [], WINDOW[0], WINDOW[1], "day", 8.0
        )
        assert all(p.status == "non_working" for p in report.users[0].periods)


class TestBuckets:
    def test_week_buckets_sum_and_status(self):
        report = _report(
            [
                _plan(JANE, "2026-03-02", "PROJ-1", 8.0),
                _plan(JANE, "2026-03-03", "PROJ-1", 2.0),
                _plan(JANE, "2026-03-04", "PROJ-2", 1.5),
            ],
            granularity="week",
        )
        week = report.users[0].periods[0]
        assert (week.period, week.date_from, week.date_to) == (
            "2026-W10",
            "2026-03-02",
            "2026-03-08",
        )
        assert (week.capacity_hours, week.planned_hours, week.free_hours) == (
            32.0,
            11.5,
            20.5,
        )
        assert week.status == "partial"
        assert [(i.issue_key, i.hours) for i in week.items] == [
            ("PROJ-1", 10.0),
            ("PROJ-2", 1.5),
        ]

    def test_week_status_overbooked_if_any_day_overbooked(self):
        report = _report([_plan(JANE, "2026-03-02", "PROJ-1", 9.0)], granularity="week")
        assert report.users[0].periods[0].status == "overbooked"
        assert report.users[0].periods[0].overbooked_hours == 1.0

    def test_week_status_absent_if_all_working_days_absent(self):
        plans = [
            _plan(JANE, f"2026-03-0{d}", "PROJ-9", 8.0, absence=True)
            for d in (2, 3, 4, 5)
        ]
        report = _report(plans, granularity="week")
        assert report.users[0].periods[0].status == "absent"

    def test_total_granularity(self):
        report = _report(
            [_plan(JANE, "2026-03-02", "PROJ-1", 8.0)], granularity="total"
        )
        total = report.users[0].periods
        assert len(total) == 1
        assert (total[0].period, total[0].capacity_hours, total[0].planned_hours) == (
            "total",
            32.0,
            8.0,
        )

    def test_invalid_granularity(self):
        with pytest.raises(ValueError, match="granularity"):
            _report([], granularity="month")


class TestSummary:
    def test_summary_lists(self):
        report = _report(
            [
                _plan(JANE, "2026-03-02", "PROJ-1", 9.0),
                _plan(ALEX, "2026-03-03", "PROJ-9", 8.0, absence=True),
                _plan(ALEX, "2026-03-02", "PROJ-2", 8.0),
            ],
            users=(JANE, ALEX),
            roles={JANE.key: "QA Engineer"},
        )
        assert report.users[0].role == "QA Engineer"
        assert report.summary["overbooked"] == [
            {"user": JANE.to_simplified_dict(), "days": ["2026-03-02"]}
        ]
        assert report.summary["absent"] == [
            {"user": ALEX.to_simplified_dict(), "days": ["2026-03-03"]}
        ]
        free = report.summary["free_capacity"]
        assert [f["user"]["username"] for f in free] == ["jdoe", "asmith"]
        assert free[0]["free_hours"] == 24.0
        assert free[1]["free_hours"] == 16.0

    def test_summary_free_capacity_omits_zero(self):
        plans = [_plan(JANE, f"2026-03-0{d}", "PROJ-1", 8.0) for d in (2, 3, 4, 5)]
        report = _report(plans)
        assert report.summary["free_capacity"] == []

    def test_report_header(self):
        report = _report([], granularity="week", limit=7.5)
        assert (
            report.date_from,
            report.date_to,
            report.granularity,
            report.daily_limit_hours,
        ) == ("2026-03-02", "2026-03-08", "week", 7.5)


class TestWorkloadMixin:
    def test_get_workload_fetches_schedule_per_user(self):
        schedule_calls: list[dict] = []

        def schedule_route(params: dict) -> dict:
            schedule_calls.append(params)
            return {
                "numberOfWorkingDays": 1,
                "requiredSeconds": 28800,
                "days": [
                    {
                        "date": "2026-03-02",
                        "requiredSeconds": 28800,
                        "type": "WORKING_DAY",
                    }
                ],
            }

        fetcher = make_fetcher(
            {
                ("GET", "/rest/tempo-core/1/user/schedule"): schedule_route,
                ("POST", "/rest/tempo-planning/1/plan/search"): [
                    {
                        "assignee": "JIRAUSER1001",
                        "day": "2026-03-02",
                        "timePlannedSeconds": 3600.0,
                        "planItemType": "ISSUE",
                        "planItemInfo": {"key": "PROJ-1", "summary": "Work"},
                    }
                ],
            }
        )
        scope = TempoScope(team=TempoTeam(id=7, name="Platform QA"), users=[JANE, ALEX])
        report = fetcher.get_workload(scope, date(2026, 3, 2), date(2026, 3, 2))
        assert [c["user"] for c in schedule_calls] == ["jdoe", "asmith"]
        assert report.users[0].periods[0].planned_hours == 1.0
        assert report.users[1].periods[0].status == "free"


class TestAbsenceRegressions:
    def test_absence_under_lower_daily_limit_is_absent_not_overbooked(self):
        report = _report(
            [_plan(JANE, "2026-03-03", "PROJ-9", 8.0, absence=True)], limit=6.0
        )
        day = _day(report, "2026-03-03")
        assert (day.status, day.overbooked_hours, day.free_hours) == (
            "absent",
            0.0,
            0.0,
        )
        assert report.summary["overbooked"] == []
        assert report.summary["absent"] == [
            {"user": JANE.to_simplified_dict(), "days": ["2026-03-03"]}
        ]

    def test_absence_on_non_working_day_is_absent_not_overbooked(self):
        report = _report([_plan(JANE, "2026-03-07", "PROJ-9", 8.0, absence=True)])
        day = _day(report, "2026-03-07")
        assert (day.status, day.overbooked_hours) == ("absent", 0.0)

    def test_partial_week_absence_listed_in_summary_at_week_granularity(self):
        plans = [
            _plan(JANE, f"2026-03-0{d}", "PROJ-9", 8.0, absence=True) for d in (2, 3, 4)
        ]
        report = _report(plans, granularity="week")
        week = report.users[0].periods[0]
        assert week.status == "partial"
        assert report.summary["absent"] == [
            {
                "user": JANE.to_simplified_dict(),
                "days": ["2026-03-02", "2026-03-03", "2026-03-04"],
            }
        ]
        assert report.summary["free_capacity"] == [
            {"user": JANE.to_simplified_dict(), "free_hours": 8.0}
        ]

    def test_summary_overbooked_lists_dates_at_week_granularity(self):
        report = _report([_plan(JANE, "2026-03-05", "PROJ-1", 9.0)], granularity="week")
        assert report.summary["overbooked"] == [
            {"user": JANE.to_simplified_dict(), "days": ["2026-03-05"]}
        ]


class TestPartialAbsence:
    def test_partial_absence_without_plans_is_partial(self):
        report = _report([_plan(JANE, "2026-03-03", "PROJ-9", 2.0, absence=True)])
        day = _day(report, "2026-03-03")
        assert (day.status, day.free_hours, day.absence_hours) == ("partial", 6.0, 2.0)
        assert report.summary["absent"] == []

    def test_full_day_absence_is_absent(self):
        report = _report([_plan(JANE, "2026-03-03", "PROJ-9", 8.0, absence=True)])
        assert _day(report, "2026-03-03").status == "absent"
        assert report.summary["absent"] == [
            {"user": JANE.to_simplified_dict(), "days": ["2026-03-03"]}
        ]
