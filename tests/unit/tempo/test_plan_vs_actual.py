"""Tests for the plan vs. actual report."""

from datetime import date

from mcp_atlassian.models.tempo import TempoPlanItem, TempoUserRef, TempoWorklog
from mcp_atlassian.tempo import TempoScope
from mcp_atlassian.tempo.workload import build_plan_vs_actual
from tests.unit.tempo.conftest import make_fetcher

JANE = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane Doe")
ALEX = TempoUserRef(key="JIRAUSER1002", username="asmith", display_name="Alex Smith")
WINDOW = (date(2026, 3, 2), date(2026, 3, 10))  # Mon W10 .. Tue W11


def _plan(user, day, key, hours, absence=False):
    return TempoPlanItem(
        day=day,
        user=user,
        issue_key=key,
        summary=f"Summary {key}",
        planned_seconds=int(hours * 3600),
        planned_hours=hours,
        is_absence=absence,
    )


def _log(user, day, key, hours):
    return TempoWorklog(
        day=day,
        user=user,
        issue_key=key,
        summary=f"Summary {key}",
        seconds=int(hours * 3600),
        hours=hours,
    )


class TestBuildPlanVsActual:
    def test_delta_per_issue_and_period(self):
        report = build_plan_vs_actual(
            [JANE],
            [
                _plan(JANE, "2026-03-02", "PROJ-1", 8.0),
                _plan(JANE, "2026-03-09", "PROJ-1", 4.0),
            ],
            [
                _log(JANE, "2026-03-02", "PROJ-1", 6.0),
                _log(JANE, "2026-03-03", "PROJ-1", 3.0),
            ],
            *WINDOW,
            "week",
        )
        assert (report.date_from, report.date_to, report.granularity) == (
            "2026-03-02",
            "2026-03-10",
            "week",
        )
        periods = report.users[0].periods
        assert [p.period for p in periods] == ["2026-W10", "2026-W11"]
        w10 = periods[0]
        assert (w10.planned_hours, w10.logged_hours, w10.delta_hours) == (8.0, 9.0, 1.0)
        assert w10.by_issue[0].to_simplified_dict() == {
            "issue_key": "PROJ-1",
            "summary": "Summary PROJ-1",
            "planned_hours": 8.0,
            "logged_hours": 9.0,
            "delta_hours": 1.0,
        }
        w11 = periods[1]
        assert (w11.planned_hours, w11.logged_hours, w11.delta_hours) == (
            4.0,
            0.0,
            -4.0,
        )

    def test_logged_unplanned_and_planned_not_logged(self):
        report = build_plan_vs_actual(
            [JANE],
            [_plan(JANE, "2026-03-02", "PROJ-1", 8.0)],
            [_log(JANE, "2026-03-02", "PROJ-2", 2.0)],
            *WINDOW,
            "total",
        )
        total = report.users[0].periods[0]
        assert total.period == "total"
        assert total.logged_unplanned == ["PROJ-2"]
        assert total.planned_not_logged == ["PROJ-1"]
        assert [i.issue_key for i in total.by_issue] == ["PROJ-1", "PROJ-2"]

    def test_absence_plans_excluded(self):
        report = build_plan_vs_actual(
            [JANE],
            [_plan(JANE, "2026-03-02", "PROJ-9", 8.0, absence=True)],
            [],
            *WINDOW,
            "total",
        )
        total = report.users[0].periods[0]
        assert (total.planned_hours, total.by_issue, total.planned_not_logged) == (
            0.0,
            [],
            [],
        )

    def test_users_without_data_get_empty_periods(self):
        report = build_plan_vs_actual([JANE, ALEX], [], [], *WINDOW, "day")
        assert len(report.users) == 2
        assert len(report.users[1].periods) == 9
        assert report.users[1].periods[0].to_simplified_dict()["delta_hours"] == 0.0


class TestPlanVsActualMixin:
    def test_get_plan_vs_actual_fetches_plans_and_worklogs(self):
        fetcher = make_fetcher(
            {
                ("POST", "/rest/tempo-planning/1/plan/search"): [
                    {
                        "assignee": "JIRAUSER1001",
                        "day": "2026-03-02",
                        "timePlannedSeconds": 7200.0,
                        "planItemType": "ISSUE",
                        "planItemInfo": {"key": "PROJ-1", "summary": "Work"},
                    },
                ],
                ("POST", "/rest/tempo-timesheets/4/worklogs/search"): [
                    {
                        "tempoWorklogId": 1,
                        "timeSpentSeconds": 3600,
                        "started": "2026-03-02 00:00:00.000",
                        "worker": "JIRAUSER1001",
                        "issue": {"key": "PROJ-1", "summary": "Work"},
                    },
                ],
            }
        )
        scope = TempoScope(team=None, users=[JANE])
        report = fetcher.get_plan_vs_actual(scope, date(2026, 3, 2), date(2026, 3, 2))
        period = report.users[0].periods[0]
        assert (
            period.period,
            period.planned_hours,
            period.logged_hours,
            period.delta_hours,
        ) == ("2026-W10", 2.0, 1.0, -1.0)
