"""Tests for Tempo worklog search."""

from datetime import date

from mcp_atlassian.models.tempo import TempoUserRef
from tests.unit.tempo.conftest import make_fetcher

JANE = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane Doe")
ALEX = TempoUserRef(key="JIRAUSER1002", username="asmith", display_name="Alex Smith")
WORKLOG_SEARCH = ("POST", "/rest/tempo-timesheets/4/worklogs/search")


def _row(worker: str, started: str, key: str, seconds: int, worklog_id: int) -> dict:
    return {
        "tempoWorklogId": worklog_id,
        "timeSpentSeconds": seconds,
        "started": f"{started} 00:00:00.000",
        "worker": worker,
        "issue": {"key": key, "summary": f"Summary {key}", "projectKey": "PROJ"},
        "comment": "Working on it",
    }


ROWS = [
    _row("JIRAUSER1002", "2026-03-03", "PROJ-2", 3600, 2),
    _row("JIRAUSER1001", "2026-03-02", "PROJ-1", 7200, 1),
    _row("JIRAUSER1001", "2026-03-03", "PROJ-2", 1800, 3),
    _row("JIRAUSER9999", "2026-03-02", "PROJ-1", 7200, 4),
]


def test_get_worklogs_sends_user_keys():
    fetcher = make_fetcher({WORKLOG_SEARCH: ROWS})
    fetcher.get_worklogs([JANE, ALEX], date(2026, 3, 2), date(2026, 3, 3))
    assert fetcher.client.calls[0][2] == {  # type: ignore[attr-defined]
        "from": "2026-03-02",
        "to": "2026-03-03",
        "worker": ["JIRAUSER1001", "JIRAUSER1002"],
    }


def test_get_worklogs_maps_rows_and_filters_issue():
    fetcher = make_fetcher({WORKLOG_SEARCH: ROWS})
    worklogs = fetcher.get_worklogs([JANE, ALEX], date(2026, 3, 2), date(2026, 3, 3))
    assert [(w.day, w.user.username, w.issue_key, w.hours) for w in worklogs] == [
        ("2026-03-02", "jdoe", "PROJ-1", 2.0),
        ("2026-03-03", "asmith", "PROJ-2", 1.0),
        ("2026-03-03", "jdoe", "PROJ-2", 0.5),
    ]
    only = fetcher.get_worklogs(
        [JANE, ALEX], date(2026, 3, 2), date(2026, 3, 3), issue_key="proj-2"
    )
    assert [w.worklog_id for w in only] == [2, 3]


def test_get_worklogs_empty_users_skips_request():
    fetcher = make_fetcher({})
    assert fetcher.get_worklogs([], date(2026, 3, 2), date(2026, 3, 3)) == []
    assert fetcher.client.calls == []  # type: ignore[attr-defined]
