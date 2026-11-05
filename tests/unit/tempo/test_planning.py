"""Tests for Tempo plan search."""

from datetime import date

import pytest

from mcp_atlassian.models.tempo import TempoTeam, TempoUserRef
from mcp_atlassian.tempo import TempoScope
from tests.unit.tempo.conftest import make_fetcher

JANE = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane Doe")
ALEX = TempoUserRef(key="JIRAUSER1002", username="asmith", display_name="Alex Smith")
PLAN_SEARCH = ("POST", "/rest/tempo-planning/1/plan/search")


def _row(
    assignee: str,
    day: str,
    key: str,
    summary: str,
    seconds: float = 28800.0,
    description: str = "",
) -> dict:
    return {
        "allocationId": 1,
        "assignee": assignee,
        "day": day,
        "timePlannedSeconds": seconds,
        "planItemType": "ISSUE",
        "planItemInfo": {
            "key": key,
            "type": "ISSUE",
            "summary": summary,
            "projectKey": "PROJ",
        },
        "planDescription": description,
        "planStart": day,
        "planEnd": day,
    }


ROWS = [
    _row("JIRAUSER1002", "2026-03-02", "PROJ-2", "Review"),
    _row("JIRAUSER1001", "2026-03-02", "PROJ-1", "Write tests"),
    _row("JIRAUSER1001", "2026-03-03", "PROJ-9", "Vacation 3-4 March"),
    _row("JIRAUSER1001", "2026-03-04", "PROJ-5", "Misc", description="Sick leave"),
    _row("JIRAUSER9999", "2026-03-02", "PROJ-1", "Write tests"),
]


def _team_scope() -> TempoScope:
    return TempoScope(team=TempoTeam(id=7, name="Platform QA"), users=[JANE, ALEX])


def _user_scope() -> TempoScope:
    return TempoScope(team=None, users=[JANE])


class TestGetPlans:
    def test_get_plans_team_scope_sends_team_id(self):
        fetcher = make_fetcher({PLAN_SEARCH: ROWS})
        fetcher.get_plans(_team_scope(), date(2026, 3, 2), date(2026, 3, 4))
        assert fetcher.client.calls[0][2] == {  # type: ignore[attr-defined]
            "from": "2026-03-02",
            "to": "2026-03-04",
            "teamId": [7],
        }

    def test_get_plans_user_scope_filters_by_key_and_drops_unknown_assignees(self):
        fetcher = make_fetcher({PLAN_SEARCH: ROWS})
        plans = fetcher.get_plans(_user_scope(), date(2026, 3, 2), date(2026, 3, 4))
        assert "teamId" not in fetcher.client.calls[0][2]  # type: ignore[attr-defined]
        assert {p.user.key for p in plans} == {"JIRAUSER1001"}
        assert [p.issue_key for p in plans] == ["PROJ-1", "PROJ-9", "PROJ-5"]
        assert plans[0].user.display_name == "Jane Doe"

    def test_get_plans_sorted_by_day_user_issue(self):
        fetcher = make_fetcher({PLAN_SEARCH: ROWS})
        plans = fetcher.get_plans(_team_scope(), date(2026, 3, 2), date(2026, 3, 4))
        assert [(p.day, p.user.username, p.issue_key) for p in plans] == [
            ("2026-03-02", "asmith", "PROJ-2"),
            ("2026-03-02", "jdoe", "PROJ-1"),
            ("2026-03-03", "jdoe", "PROJ-9"),
            ("2026-03-04", "jdoe", "PROJ-5"),
        ]

    def test_get_plans_marks_absence_from_summary_and_description(self):
        fetcher = make_fetcher({PLAN_SEARCH: ROWS})
        plans = fetcher.get_plans(_user_scope(), date(2026, 3, 2), date(2026, 3, 4))
        assert [(p.issue_key, p.is_absence) for p in plans] == [
            ("PROJ-1", False),
            ("PROJ-9", True),
            ("PROJ-5", True),
        ]

    def test_get_plans_issue_key_filter(self):
        fetcher = make_fetcher({PLAN_SEARCH: ROWS})
        plans = fetcher.get_plans(
            _team_scope(), date(2026, 3, 2), date(2026, 3, 4), issue_key="proj-1"
        )
        assert [(p.user.username, p.issue_key) for p in plans] == [("jdoe", "PROJ-1")]

    def test_get_plans_exclude_absences(self):
        fetcher = make_fetcher({PLAN_SEARCH: ROWS})
        plans = fetcher.get_plans(
            _user_scope(), date(2026, 3, 2), date(2026, 3, 4), include_absences=False
        )
        assert [p.issue_key for p in plans] == ["PROJ-1"]

    def test_get_plans_handles_non_list_response(self):
        fetcher = make_fetcher({PLAN_SEARCH: {"error": "x"}})
        assert (
            fetcher.get_plans(_user_scope(), date(2026, 3, 2), date(2026, 3, 2)) == []
        )

    def test_get_plans_empty_scope_skips_request(self):
        fetcher = make_fetcher({})
        scope = TempoScope(team=None, users=[])
        with pytest.raises(ValueError, match="no users"):
            fetcher.get_plans(scope, date(2026, 3, 2), date(2026, 3, 2))
