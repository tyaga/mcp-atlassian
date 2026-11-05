"""Tests for plan-writing operations."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from mcp_atlassian.models.jira.common import JiraUser
from tests.unit.tempo.conftest import make_fetcher

PLAN_SEARCH = ("POST", "/rest/tempo-planning/1/plan/search")
SCHEDULE = ("GET", "/rest/tempo-core/1/user/schedule")
MEMBERSHIPS = ("GET", "/rest/tempo-teams/2/user/jdoe/memberships")
ALLOC = "/rest/tempo-planning/1/allocation"
TEAMS = ("GET", "/rest/tempo-teams/2/team")

# Mon 2026-03-02 .. Sun 2026-03-08


def _schedule_route(params: dict) -> dict:
    days = []
    d = date.fromisoformat(params["from"])
    end = date.fromisoformat(params["to"])
    while d <= end:
        if d.weekday() >= 5:
            days.append(
                {
                    "date": d.isoformat(),
                    "requiredSeconds": 0,
                    "type": "HOLIDAY_AND_NON_WORKING_DAY",
                }
            )
        else:
            days.append(
                {"date": d.isoformat(), "requiredSeconds": 28800, "type": "WORKING_DAY"}
            )
        d = date.fromordinal(d.toordinal() + 1)
    return {"days": days}


def _plan_row(
    day: str,
    hours: float,
    allocation_id: int = 1,
    key: str = "PROJ-9",
    summary: str = "Other",
):
    return {
        "allocationId": allocation_id,
        "assignee": "JIRAUSER1001",
        "day": day,
        "timePlannedSeconds": hours * 3600,
        "planItemType": "ISSUE",
        "planItemInfo": {
            "key": key,
            "type": "ISSUE",
            "summary": summary,
            "projectKey": "PROJ",
        },
    }


def _allocation_response(payload: dict, allocation_id: int = 500) -> dict:
    return {
        "id": allocation_id,
        "assignee": {
            "key": payload["assignee"]["key"],
            "type": "user",
            "userKey": "JIRAUSER1001",
        },
        "planItem": {
            "key": "PROJ-123",
            "id": payload["planItem"]["id"],
            "type": "ISSUE",
            "summary": "Write tests",
        },
        "scope": payload["scope"],
        "start": payload["start"],
        "end": payload["end"],
        "secondsPerDay": payload["secondsPerDay"],
        "includeNonWorkingDays": payload["includeNonWorkingDays"],
        "description": payload["description"],
    }


def _fetcher(plans=None, memberships=None, routes=None):
    created: list[dict] = []

    def post_alloc(payload: dict) -> dict:
        created.append(payload)
        return _allocation_response(payload, 500 + len(created))

    all_routes = {
        SCHEDULE: _schedule_route,
        PLAN_SEARCH: plans or [],
        MEMBERSHIPS: memberships
        if memberships is not None
        else [{"team": {"id": 7, "name": "Platform QA"}, "role": {"name": "Member"}}],
        TEAMS: [{"id": 7, "name": "Platform QA"}, {"id": 9, "name": "Mobile"}],
        ("POST", ALLOC): post_alloc,
    }
    all_routes.update(routes or {})
    fetcher = make_fetcher(all_routes)
    fetcher.jira.get_user_profile_by_identifier.return_value = JiraUser(
        username="jdoe", user_key="JIRAUSER1001", display_name="Jane Doe"
    )
    fetcher.jira.jira.get_issue.return_value = {
        "id": "4242",
        "key": "PROJ-123",
        "fields": {"summary": "Write tests"},
    }
    fetcher.created = created  # type: ignore[attr-defined]
    return fetcher


def _writes(fetcher) -> list[tuple[str, str, object]]:
    return [
        c
        for c in fetcher.client.calls
        if c[0] in ("POST", "PUT", "DELETE") and c[1] != PLAN_SEARCH[1]
    ]


class TestPlanWorkFixed:
    def test_dry_run_reports_without_writing(self):
        fetcher = _fetcher()
        result = fetcher.plan_work(
            "jdoe", "PROJ-123", date(2026, 3, 2), date(2026, 3, 3), hours_per_day=4.0
        )
        assert (result.ok, result.written, result.mode) == (True, False, "fixed")
        assert result.issue == {"key": "PROJ-123", "id": 4242, "summary": "Write tests"}
        assert result.team == {"id": 7, "name": "Platform QA"}
        assert [(d.day, d.added_hours, d.status_after) for d in result.days] == [
            ("2026-03-02", 4.0, "partial"),
            ("2026-03-03", 4.0, "partial"),
        ]
        assert [
            (a.start, a.end, a.hours_per_day, a.allocation_id)
            for a in result.allocations
        ] == [("2026-03-02", "2026-03-03", 4.0, None)]
        assert _writes(fetcher) == []

    def test_write_posts_exact_body(self):
        fetcher = _fetcher()
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 3),
            hours_per_day=4.0,
            description="Sprint work",
            dry_run=False,
        )
        assert (result.ok, result.written) == (True, True)
        assert fetcher.created == [  # type: ignore[attr-defined]
            {
                "assignee": {"key": "JIRAUSER1001", "type": "user"},
                "planItem": {"id": 4242, "type": "ISSUE"},
                "scope": {"id": 7, "type": "team"},
                "start": "2026-03-02",
                "end": "2026-03-03",
                "secondsPerDay": 14400,
                "includeNonWorkingDays": False,
                "description": "Sprint work",
            }
        ]
        assert result.allocations[0].allocation_id == 501

    def test_conflict_blocks_write(self):
        fetcher = _fetcher(plans=[_plan_row("2026-03-02", 6.0)])
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 2),
            hours_per_day=4.0,
            dry_run=False,
        )
        assert (result.ok, result.written) == (False, False)
        assert [c.type for c in result.conflicts] == ["overbooked"]
        assert _writes(fetcher) == []

    def test_allow_overbooking_writes(self):
        fetcher = _fetcher(plans=[_plan_row("2026-03-02", 6.0)])
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 2),
            hours_per_day=4.0,
            dry_run=False,
            allow_overbooking=True,
        )
        assert (result.ok, result.written) == (True, True)
        assert result.days[0].status_after == "overbooked"

    def test_explicit_team_by_name(self):
        fetcher = _fetcher(memberships=[])
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 2),
            hours_per_day=1.0,
            team="mobile",
        )
        assert result.team == {"id": 9, "name": "Mobile"}

    def test_requires_exactly_one_hours_argument(self):
        fetcher = _fetcher()
        with pytest.raises(ValueError, match="hours_per_day.*total_hours"):
            fetcher.plan_work("jdoe", "PROJ-123", date(2026, 3, 2), date(2026, 3, 2))
        with pytest.raises(ValueError, match="hours_per_day.*total_hours"):
            fetcher.plan_work(
                "jdoe",
                "PROJ-123",
                date(2026, 3, 2),
                date(2026, 3, 2),
                hours_per_day=1.0,
                total_hours=2.0,
            )

    def test_fixed_requires_date_to(self):
        fetcher = _fetcher()
        with pytest.raises(ValueError, match="date_to"):
            fetcher.plan_work(
                "jdoe", "PROJ-123", date(2026, 3, 2), None, hours_per_day=1.0
            )

    def test_hours_must_be_positive(self):
        fetcher = _fetcher()
        with pytest.raises(ValueError, match="positive"):
            fetcher.plan_work(
                "jdoe", "PROJ-123", date(2026, 3, 2), date(2026, 3, 2), hours_per_day=0
            )


class TestPlanWorkFit:
    def test_fit_creates_grouped_allocations(self):
        fetcher = _fetcher(plans=[_plan_row("2026-03-02", 6.0)])
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 8),
            total_hours=12.0,
            dry_run=False,
        )
        assert (result.ok, result.written, result.mode) == (True, True, "fit")
        assert [
            (a.start, a.end, a.hours_per_day, a.total_hours) for a in result.allocations
        ] == [
            ("2026-03-02", "2026-03-02", 2.0, 2.0),
            ("2026-03-03", "2026-03-03", 8.0, 8.0),
            ("2026-03-04", "2026-03-04", 2.0, 2.0),
        ]
        assert [c["secondsPerDay"] for c in fetcher.created] == [7200, 28800, 7200]  # type: ignore[attr-defined]
        assert [a.allocation_id for a in result.allocations] == [501, 502, 503]

    def test_fit_default_deadline_is_window_cap(self, monkeypatch):
        monkeypatch.setenv("TEMPO_MAX_WINDOW_DAYS", "7")
        fetcher = _fetcher()
        result = fetcher.plan_work(
            "jdoe", "PROJ-123", date(2026, 3, 2), None, total_hours=50.0
        )
        assert result.days[-1].day == "2026-03-08"
        assert [c.type for c in result.conflicts] == ["does_not_fit"]
        assert result.ok is False


class TestDefaultTeam:
    def test_no_memberships_raises(self):
        fetcher = _fetcher(memberships=[])
        with pytest.raises(ValueError, match="no Tempo team"):
            fetcher.plan_work(
                "jdoe",
                "PROJ-123",
                date(2026, 3, 2),
                date(2026, 3, 2),
                hours_per_day=1.0,
            )

    def test_several_memberships_raise_listing_names(self):
        fetcher = _fetcher(
            memberships=[
                {"team": {"id": 7, "name": "Platform QA"}},
                {"team": {"id": 9, "name": "Mobile"}},
            ]
        )
        with pytest.raises(ValueError, match="Platform QA.*Mobile"):
            fetcher.plan_work(
                "jdoe",
                "PROJ-123",
                date(2026, 3, 2),
                date(2026, 3, 2),
                hours_per_day=1.0,
            )


class TestBulk:
    def _items(self):
        return [
            {
                "user": "jdoe",
                "issue_key": "PROJ-123",
                "date_from": "2026-03-02",
                "date_to": "2026-03-02",
                "hours_per_day": 6.0,
            },
            {
                "user": "jdoe",
                "issue_key": "PROJ-124",
                "date_from": "2026-03-02",
                "date_to": "2026-03-02",
                "hours_per_day": 4.0,
            },
        ]

    def test_second_item_sees_first_items_load(self):
        fetcher = _fetcher()
        result = fetcher.bulk_plan_work(self._items())
        assert result["ok"] is False and result["written"] is False
        statuses = [r["status"] for r in result["results"]]
        assert statuses == ["planned", "skipped"]
        assert result["results"][1]["conflicts"][0]["type"] == "overbooked"
        assert result["results"][1]["index"] == 1

    def test_atomic_writes_nothing_on_conflict(self):
        fetcher = _fetcher()
        result = fetcher.bulk_plan_work(self._items(), dry_run=False, atomic=True)
        assert result["written"] is False
        assert _writes(fetcher) == []

    def test_non_atomic_writes_good_items(self):
        fetcher = _fetcher()
        result = fetcher.bulk_plan_work(self._items(), dry_run=False, atomic=False)
        assert result["written"] is True
        assert [r["status"] for r in result["results"]] == ["created", "skipped"]
        assert len(fetcher.created) == 1  # type: ignore[attr-defined]

    def test_all_good_writes_all(self):
        fetcher = _fetcher()
        items = self._items()
        items[1]["hours_per_day"] = 2.0
        result = fetcher.bulk_plan_work(items, dry_run=False)
        assert result["ok"] and result["written"]
        assert [r["status"] for r in result["results"]] == ["created", "created"]
        assert len(fetcher.created) == 2  # type: ignore[attr-defined]

    def test_fit_item_after_fixed_item(self):
        fetcher = _fetcher()
        items = [
            {
                "user": "jdoe",
                "issue_key": "PROJ-123",
                "date_from": "2026-03-02",
                "date_to": "2026-03-02",
                "hours_per_day": 6.0,
            },
            {
                "user": "jdoe",
                "issue_key": "PROJ-124",
                "date_from": "2026-03-02",
                "date_to": "2026-03-03",
                "total_hours": 4.0,
            },
        ]
        result = fetcher.bulk_plan_work(items)
        assert result["ok"] is True
        assert result["results"][1]["allocations"] == [
            {
                "allocation_id": None,
                "start": "2026-03-02",
                "end": "2026-03-03",
                "hours_per_day": 2.0,
                "total_hours": 4.0,
                "working_days": 2,
            },
        ]
        assert [d["added_hours"] for d in result["results"][1]["days"]] == [2.0, 2.0]

    def test_invalid_item_reports_error_not_crash(self):
        fetcher = _fetcher()
        result = fetcher.bulk_plan_work(
            [{"user": "jdoe", "issue_key": "PROJ-123", "date_from": "2026-03-02"}]
        )
        assert result["results"][0]["status"] == "skipped"
        assert result["results"][0]["conflicts"][0]["type"] == "invalid"


EXISTING = {
    "id": 777,
    "assignee": {"key": "jdoe", "type": "user", "userKey": "JIRAUSER1001"},
    "planItem": {
        "key": "PROJ-123",
        "id": 4242,
        "type": "ISSUE",
        "summary": "Write tests",
    },
    "scope": {"id": 7, "type": "team"},
    "start": "2026-03-02",
    "end": "2026-03-03",
    "secondsPerDay": 28800,
    "includeNonWorkingDays": False,
    "description": "Old",
}


class TestUpdate:
    def _fetcher(self, plans):
        put_calls: list[dict] = []

        def put_alloc(payload: dict) -> dict:
            put_calls.append(payload)
            return {**EXISTING, **payload, "id": 777}

        fetcher = _fetcher(
            plans=plans,
            routes={
                ("GET", f"{ALLOC}/777"): EXISTING,
                ("PUT", f"{ALLOC}/777"): put_alloc,
            },
        )
        fetcher.put_calls = put_calls  # type: ignore[attr-defined]
        return fetcher

    def test_update_excludes_own_rows_and_puts_full_body(self):
        own = [
            _plan_row("2026-03-02", 8.0, allocation_id=777, key="PROJ-123"),
            _plan_row("2026-03-03", 8.0, allocation_id=777, key="PROJ-123"),
        ]
        fetcher = self._fetcher(plans=own)
        result = fetcher.update_plan(
            777, date_to=date(2026, 3, 4), description="New", dry_run=False
        )
        assert (result.ok, result.written, result.allocation_id) == (True, True, 777)
        assert result.before == {
            "start": "2026-03-02",
            "end": "2026-03-03",
            "hours_per_day": 8.0,
            "description": "Old",
        }
        assert [
            (d.day, d.planned_hours, d.added_hours, d.status_after) for d in result.days
        ] == [
            ("2026-03-02", 0.0, 8.0, "full"),
            ("2026-03-03", 0.0, 8.0, "full"),
            ("2026-03-04", 0.0, 8.0, "full"),
        ]
        assert fetcher.put_calls == [  # type: ignore[attr-defined]
            {
                "id": 777,
                "assignee": {"key": "JIRAUSER1001", "type": "user"},
                "planItem": {"id": 4242, "type": "ISSUE"},
                "scope": {"id": 7, "type": "team"},
                "start": "2026-03-02",
                "end": "2026-03-04",
                "secondsPerDay": 28800,
                "includeNonWorkingDays": False,
                "description": "New",
            }
        ]

    def test_update_conflict_with_other_plans_blocks(self):
        fetcher = self._fetcher(plans=[_plan_row("2026-03-04", 4.0, allocation_id=1)])
        result = fetcher.update_plan(777, date_to=date(2026, 3, 4), dry_run=False)
        assert (result.ok, result.written) == (False, False)
        assert [(c.day, c.type) for c in result.conflicts] == [
            ("2026-03-04", "overbooked")
        ]
        assert fetcher.put_calls == []  # type: ignore[attr-defined]

    def test_update_dry_run_does_not_put(self):
        fetcher = self._fetcher(plans=[])
        result = fetcher.update_plan(777, hours_per_day=2.0)
        assert result.written is False
        assert result.allocations[0].hours_per_day == 2.0
        assert fetcher.put_calls == []  # type: ignore[attr-defined]


class TestDelete:
    def test_delete_gets_then_deletes(self):
        fetcher = _fetcher(
            routes={("GET", f"{ALLOC}/777"): EXISTING, ("DELETE", f"{ALLOC}/777"): None}
        )
        allocation = fetcher.delete_plan(777)
        assert allocation.id == 777 and allocation.issue_key == "PROJ-123"
        assert fetcher.client.calls[-1] == ("DELETE", f"{ALLOC}/777", None)


class TestReviewRegressions:
    def test_partial_failure_reports_created_allocations(self):
        fetcher = _fetcher(plans=[_plan_row("2026-03-02", 6.0)])
        calls = {"n": 0}

        def flaky(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError(
                    "Tempo API HTTP 500: /rest/tempo-planning/1/allocation | boom"
                )
            return _allocation_response(payload, 600 + calls["n"])

        fetcher.client.routes[("POST", ALLOC)] = flaky  # type: ignore[attr-defined]
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 8),
            total_hours=12.0,
            dry_run=False,
        )
        assert result.written is True
        assert result.ok is False
        assert [a.allocation_id for a in result.allocations] == [601, None, None]
        assert result.error is not None and "boom" in result.error
        assert "601" in result.error

    def test_atomic_bulk_rolls_back_on_write_failure(self):
        fetcher = _fetcher()
        deleted: list[str] = []
        calls = {"n": 0}

        def flaky(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("Tempo API HTTP 500: boom")
            return _allocation_response(payload, 700 + calls["n"])

        fetcher.client.routes[("POST", ALLOC)] = flaky  # type: ignore[attr-defined]
        fetcher.client.routes[("DELETE", f"{ALLOC}/701")] = lambda _: deleted.append(
            "701"
        )  # type: ignore[attr-defined]
        items = [
            {
                "user": "jdoe",
                "issue_key": "PROJ-123",
                "date_from": "2026-03-02",
                "date_to": "2026-03-02",
                "hours_per_day": 2.0,
            },
            {
                "user": "jdoe",
                "issue_key": "PROJ-124",
                "date_from": "2026-03-03",
                "date_to": "2026-03-03",
                "hours_per_day": 2.0,
            },
        ]
        result = fetcher.bulk_plan_work(items, dry_run=False, atomic=True)
        assert deleted == ["701"]
        assert result["written"] is False
        assert result["rolled_back"] == [701]
        assert "boom" in result["error"]

    def test_non_atomic_bulk_reports_failed_item(self):
        fetcher = _fetcher()
        calls = {"n": 0}

        def flaky(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("Tempo API HTTP 500: boom")
            return _allocation_response(payload, 800 + calls["n"])

        fetcher.client.routes[("POST", ALLOC)] = flaky  # type: ignore[attr-defined]
        items = [
            {
                "user": "jdoe",
                "issue_key": "PROJ-123",
                "date_from": "2026-03-02",
                "date_to": "2026-03-02",
                "hours_per_day": 2.0,
            },
            {
                "user": "jdoe",
                "issue_key": "PROJ-124",
                "date_from": "2026-03-03",
                "date_to": "2026-03-03",
                "hours_per_day": 2.0,
            },
        ]
        result = fetcher.bulk_plan_work(items, dry_run=False, atomic=False)
        assert result["written"] is True
        assert [r["status"] for r in result["results"]] == ["created", "failed"]
        assert "boom" in result["results"][1]["error"]

    def test_fit_with_absence_flag_uses_free_capacity(self):
        fetcher = _fetcher(
            plans=[_plan_row("2026-03-02", 8.0, key="PROJ-9", summary="Vacation")]
        )
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 3),
            total_hours=8.0,
            allow_absence_days=True,
        )
        assert result.ok is True
        assert [(d.day, d.added_hours) for d in result.days] == [
            ("2026-03-02", 0.0),
            ("2026-03-03", 8.0),
        ]

    def test_fit_with_absence_flag_uses_partial_absence_day(self):
        fetcher = _fetcher(
            plans=[_plan_row("2026-03-02", 4.0, key="PROJ-9", summary="Day off (half)")]
        )
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 3),
            total_hours=4.0,
            allow_absence_days=True,
        )
        assert result.ok is True
        assert result.days[0].added_hours == 4.0

    def test_body_uses_user_key_and_checks_returned_assignee(self):
        fetcher = _fetcher()
        fetcher.jira.get_user_profile_by_identifier.return_value = JiraUser(
            username="jdoe", user_key="JIRAUSER1001", display_name="Jane Doe"
        )
        fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 2),
            hours_per_day=1.0,
            dry_run=False,
        )
        assert fetcher.created[0]["assignee"] == {"key": "JIRAUSER1001", "type": "user"}  # type: ignore[attr-defined]

    def test_mismatched_returned_assignee_is_an_error(self):
        fetcher = _fetcher()

        def wrong_user(payload: dict) -> dict:
            body = _allocation_response(payload, 900)
            body["assignee"] = {
                "key": "other",
                "type": "user",
                "userKey": "JIRAUSER2002",
            }
            return body

        fetcher.client.routes[("POST", ALLOC)] = wrong_user  # type: ignore[attr-defined]
        result = fetcher.plan_work(
            "jdoe",
            "PROJ-123",
            date(2026, 3, 2),
            date(2026, 3, 2),
            hours_per_day=1.0,
            dry_run=False,
        )
        assert result.ok is False
        assert (
            result.error is not None
            and "JIRAUSER2002" in result.error
            and "900" in result.error
        )

    def test_unknown_issue_in_bulk_marks_item_invalid(self):
        from requests.exceptions import HTTPError

        fetcher = _fetcher()
        response = MagicMock(status_code=404, text="Issue Does Not Exist")
        fetcher.jira.jira.get_issue.side_effect = HTTPError("404", response=response)
        result = fetcher.bulk_plan_work(
            [
                {
                    "user": "jdoe",
                    "issue_key": "PROJ-404",
                    "date_from": "2026-03-02",
                    "date_to": "2026-03-02",
                    "hours_per_day": 1.0,
                }
            ]
        )
        entry = result["results"][0]
        assert entry["status"] == "skipped"
        assert entry["conflicts"][0]["type"] == "invalid"
        assert "PROJ-404" in entry["conflicts"][0]["message"]


class TestUpdateRegressions:
    def _fetcher(self, existing: dict, plans=None):
        put_calls: list[dict] = []

        def put_alloc(payload: dict) -> dict:
            put_calls.append(payload)
            return {**existing, **payload}

        fetcher = _fetcher(
            plans=plans or [],
            routes={
                ("GET", f"{ALLOC}/777"): existing,
                ("PUT", f"{ALLOC}/777"): put_alloc,
            },
        )
        fetcher.put_calls = put_calls  # type: ignore[attr-defined]
        return fetcher

    def test_update_keeps_exact_seconds_when_hours_not_given(self):
        existing = {**EXISTING, "secondsPerDay": 12000}
        fetcher = self._fetcher(existing)
        fetcher.update_plan(777, description="New", dry_run=False)
        assert fetcher.put_calls[0]["secondsPerDay"] == 12000  # type: ignore[attr-defined]

    def test_update_refuses_project_plans(self):
        existing = {
            **EXISTING,
            "planItem": {"key": "PROJ", "id": 31, "type": "PROJECT", "name": "Project"},
        }
        fetcher = self._fetcher(existing)
        with pytest.raises(ValueError, match="issue plans"):
            fetcher.update_plan(777, hours_per_day=1.0)

    def test_update_refuses_non_team_scope(self):
        existing = {**EXISTING, "scope": {"id": 4242, "type": "none"}}
        fetcher = self._fetcher(existing)
        with pytest.raises(ValueError, match="team-scoped"):
            fetcher.update_plan(777, hours_per_day=1.0)

    def test_update_refuses_include_non_working_days(self):
        existing = {**EXISTING, "includeNonWorkingDays": True}
        fetcher = self._fetcher(existing)
        with pytest.raises(ValueError, match="non-working"):
            fetcher.update_plan(777, hours_per_day=1.0)

    def test_update_sends_user_key(self):
        fetcher = self._fetcher(EXISTING)
        fetcher.update_plan(777, description="New", dry_run=False)
        assert fetcher.put_calls[0]["assignee"] == {
            "key": "JIRAUSER1001",
            "type": "user",
        }  # type: ignore[attr-defined]
