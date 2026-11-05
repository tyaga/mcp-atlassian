"""Tests for plan placement and validation."""

from datetime import date

from mcp_atlassian.models.tempo import (
    TempoPlanItem,
    TempoScheduleDay,
    TempoUserRef,
    TempoUserSchedule,
)
from mcp_atlassian.tempo.fitting import (
    DayLoad,
    build_day_loads,
    find_conflicts,
    fit_placement,
    fixed_placement,
    group_allocations,
    plan_days,
)

JANE = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane Doe")
# Mon 2026-03-02 .. Sun 2026-03-15; Fri 2026-03-06 is a public holiday.
START, END = date(2026, 3, 2), date(2026, 3, 15)


def _schedule() -> TempoUserSchedule:
    days = []
    d = START
    while d <= END:
        if d.weekday() >= 5:
            days.append(
                TempoScheduleDay(day=d.isoformat(), type="HOLIDAY_AND_NON_WORKING_DAY")
            )
        elif d == date(2026, 3, 6):
            days.append(
                TempoScheduleDay(
                    day=d.isoformat(), type="HOLIDAY", holiday_name="Day X"
                )
            )
        else:
            days.append(
                TempoScheduleDay(
                    day=d.isoformat(),
                    type="WORKING_DAY",
                    required_seconds=28800,
                    required_hours=8.0,
                )
            )
        d = date.fromordinal(d.toordinal() + 1)
    return TempoUserSchedule(user=JANE, days=days)


def _plan(
    day: str, hours: float, absence: bool = False, key: str = "PROJ-1"
) -> TempoPlanItem:
    return TempoPlanItem(
        day=day,
        user=JANE,
        issue_key=key,
        planned_seconds=int(hours * 3600),
        planned_hours=hours,
        is_absence=absence,
    )


def _loads(plans=(), limit=8.0, start=START, end=END) -> list[DayLoad]:
    return build_day_loads(_schedule(), list(plans), start, end, limit)


def _by_day(placements: dict[date, float]) -> dict[str, float]:
    return {d.isoformat(): h for d, h in placements.items()}


class TestBuildDayLoads:
    def test_loads_follow_schedule_and_plans(self):
        loads = _loads(
            [_plan("2026-03-02", 3.0), _plan("2026-03-03", 8.0, absence=True)]
        )
        by = {load.day.isoformat(): load for load in loads}
        assert len(loads) == 14
        assert (
            by["2026-03-02"].capacity,
            by["2026-03-02"].planned,
            by["2026-03-02"].free,
        ) == (8.0, 3.0, 5.0)
        assert (by["2026-03-03"].absence, by["2026-03-03"].free) == (8.0, 0.0)
        assert by["2026-03-06"].capacity == 0.0
        assert by["2026-03-07"].capacity == 0.0

    def test_daily_limit_caps_capacity(self):
        loads = _loads(limit=6.0)
        assert loads[0].capacity == 6.0

    def test_missing_schedule_means_no_capacity(self):
        loads = build_day_loads(None, [], START, date(2026, 3, 3), 8.0)
        assert [load.capacity for load in loads] == [0.0, 0.0]


class TestFixedPlacement:
    def test_fixed_places_on_working_days_only(self):
        placements = fixed_placement(_loads(start=START, end=date(2026, 3, 8)), 2.0)
        assert _by_day(placements) == {
            "2026-03-02": 2.0,
            "2026-03-03": 2.0,
            "2026-03-04": 2.0,
            "2026-03-05": 2.0,
        }

    def test_fixed_over_weekend_only_is_non_working_conflict(self):
        loads = _loads(start=date(2026, 3, 7), end=date(2026, 3, 8))
        placements = fixed_placement(loads, 2.0)
        assert placements == {}
        conflicts = find_conflicts(
            loads,
            placements,
            "fixed",
            allow_overbooking=False,
            allow_absence_days=False,
        )
        assert [c.type for c in conflicts] == ["non_working"]

    def test_fixed_absence_day_conflict_unless_allowed(self):
        loads = _loads(
            [_plan("2026-03-03", 8.0, absence=True)], start=START, end=date(2026, 3, 3)
        )
        placements = fixed_placement(loads, 2.0)
        conflicts = find_conflicts(
            loads,
            placements,
            "fixed",
            allow_overbooking=False,
            allow_absence_days=False,
        )
        assert [(c.day, c.type) for c in conflicts] == [("2026-03-03", "absent")]
        assert (
            find_conflicts(
                loads,
                placements,
                "fixed",
                allow_overbooking=True,
                allow_absence_days=True,
            )
            == []
        )

    def test_fixed_overbooking_conflict_unless_allowed(self):
        loads = _loads([_plan("2026-03-02", 7.0)], start=START, end=START)
        placements = fixed_placement(loads, 2.0)
        conflicts = find_conflicts(
            loads,
            placements,
            "fixed",
            allow_overbooking=False,
            allow_absence_days=False,
        )
        assert len(conflicts) == 1
        assert (conflicts[0].day, conflicts[0].type) == ("2026-03-02", "overbooked")
        assert "1.0" in conflicts[0].message
        assert (
            find_conflicts(
                loads,
                placements,
                "fixed",
                allow_overbooking=True,
                allow_absence_days=False,
            )
            == []
        )

    def test_fixed_absence_and_overbooking_both_reported(self):
        loads = _loads([_plan("2026-03-02", 8.0, absence=True)], start=START, end=START)
        conflicts = find_conflicts(
            loads,
            fixed_placement(loads, 2.0),
            "fixed",
            allow_overbooking=False,
            allow_absence_days=True,
        )
        assert [c.type for c in conflicts] == ["overbooked"]


class TestFitPlacement:
    def test_fit_fills_free_hours_in_order_skipping_holiday_and_absence(self):
        loads = _loads(
            [_plan("2026-03-02", 6.0), _plan("2026-03-04", 8.0, absence=True)]
        )
        placements, unplaced = fit_placement(loads, 12.0, allow_absence_days=False)
        assert unplaced == 0.0
        assert _by_day(placements) == {
            "2026-03-02": 2.0,
            "2026-03-03": 8.0,
            "2026-03-05": 2.0,
        }

    def test_fit_uses_partial_absence_days_when_allowed(self):
        loads = _loads(
            [
                _plan("2026-03-02", 8.0, absence=True),
                _plan("2026-03-03", 4.0, absence=True),
            ],
            start=START,
            end=date(2026, 3, 4),
        )
        placements, unplaced = fit_placement(loads, 8.0, allow_absence_days=True)
        assert _by_day(placements) == {"2026-03-03": 4.0, "2026-03-04": 4.0}
        assert unplaced == 0.0
        skipped, _ = fit_placement(loads, 8.0, allow_absence_days=False)
        assert _by_day(skipped) == {"2026-03-04": 8.0}

    def test_fit_reports_unplaced_hours(self):
        loads = _loads(start=START, end=date(2026, 3, 3))
        placements, unplaced = fit_placement(loads, 20.0, allow_absence_days=False)
        assert _by_day(placements) == {"2026-03-02": 8.0, "2026-03-03": 8.0}
        assert unplaced == 4.0
        conflicts = find_conflicts(
            loads,
            placements,
            "fit",
            allow_overbooking=False,
            allow_absence_days=False,
            unplaced=unplaced,
        )
        assert [(c.day, c.type) for c in conflicts] == [(None, "does_not_fit")]
        assert "4.0" in conflicts[0].message

    def test_fit_decimals(self):
        loads = _loads(start=START, end=START)
        placements, unplaced = fit_placement(loads, 1.25, allow_absence_days=False)
        assert _by_day(placements) == {"2026-03-02": 1.25}
        assert unplaced == 0.0


class TestGroupAllocations:
    def test_group_keeps_weekend_inside_run(self):
        loads = _loads()
        placements = {date(2026, 3, d): 8.0 for d in (2, 3, 4, 5, 9, 10)}
        drafts = group_allocations(loads, placements)
        assert [
            (a.start, a.end, a.hours_per_day, a.total_hours, a.working_days)
            for a in drafts
        ] == [("2026-03-02", "2026-03-10", 8.0, 48.0, 6)]

    def test_group_splits_on_different_hours_and_gaps(self):
        loads = _loads()
        placements = {
            date(2026, 3, 2): 8.0,
            date(2026, 3, 3): 2.0,
            date(2026, 3, 5): 8.0,
        }
        drafts = group_allocations(loads, placements)
        assert [(a.start, a.end, a.hours_per_day) for a in drafts] == [
            ("2026-03-02", "2026-03-02", 8.0),
            ("2026-03-03", "2026-03-03", 2.0),
            ("2026-03-05", "2026-03-05", 8.0),
        ]

    def test_group_empty(self):
        assert group_allocations(_loads(), {}) == []


class TestPlanDays:
    def test_plan_days_report_state_after(self):
        loads = _loads([_plan("2026-03-02", 6.0)], start=START, end=date(2026, 3, 3))
        days = plan_days(loads, {date(2026, 3, 2): 4.0, date(2026, 3, 3): 2.0})
        assert days[0].to_simplified_dict() == {
            "day": "2026-03-02",
            "capacity_hours": 8.0,
            "planned_hours": 6.0,
            "absence_hours": 0.0,
            "added_hours": 4.0,
            "free_after_hours": 0.0,
            "status_after": "overbooked",
        }
        assert (days[1].free_after_hours, days[1].status_after) == (6.0, "partial")

    def test_plan_days_only_touched_or_working_days(self):
        days = plan_days(_loads(start=date(2026, 3, 6), end=date(2026, 3, 8)), {})
        assert [(d.day, d.status_after) for d in days] == [
            ("2026-03-06", "non_working"),
            ("2026-03-07", "non_working"),
            ("2026-03-08", "non_working"),
        ]
