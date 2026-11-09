"""Tests for Tempo data models."""

from datetime import date

from mcp_atlassian.models.tempo import (
    TempoPlanItem,
    TempoScheduleDay,
    TempoTeam,
    TempoTeamMember,
    TempoUserRef,
    TempoUserSchedule,
    TempoWorklog,
)

BASE_URL = "https://jira.example.com"


def _member_item(**membership: object) -> dict:
    return {
        "id": 1,
        "member": {
            "name": "jdoe",
            "key": "JIRAUSER1001",
            "displayname": "Jane Doe",
            "activeInJira": True,
        },
        "membership": {
            "role": {"id": 5, "name": "QA Engineer"},
            "dateFrom": "",
            "dateTo": "",
            "availability": "100",
            "status": "active",
            **membership,
        },
    }


class TestTempoUserRef:
    def test_user_ref_from_member_dict(self):
        user = TempoUserRef.from_api_response(
            {"name": "jdoe", "key": "JIRAUSER1001", "displayname": "Jane Doe"}
        )
        assert user.to_simplified_dict() == {
            "key": "JIRAUSER1001",
            "username": "jdoe",
            "display_name": "Jane Doe",
        }

    def test_user_ref_from_jira_user_dict(self):
        user = TempoUserRef.from_api_response(
            {"name": "jdoe", "key": "JIRAUSER1001", "displayName": "Jane Doe"}
        )
        assert user.display_name == "Jane Doe"
        assert user.username == "jdoe"


class TestTempoTeam:
    def test_team_from_api_response(self):
        team = TempoTeam.from_api_response(
            {"id": 7, "name": "Platform QA ", "summary": "QA", "lead": "jdoe"}
        )
        assert team.id == 7
        assert team.name == "Platform QA "
        assert team.lead == "jdoe"


class TestTempoTeamMember:
    def test_team_member_active_without_date_to(self):
        member = TempoTeamMember.from_api_response(
            _member_item(), today=date(2026, 2, 1)
        )
        assert member.user.key == "JIRAUSER1001"
        assert member.role == "QA Engineer"
        assert member.availability == 100
        assert member.active is True

    def test_team_member_inactive_when_date_to_past(self):
        member = TempoTeamMember.from_api_response(
            _member_item(dateTo="2026-01-31"), today=date(2026, 2, 1)
        )
        assert member.active is False
        assert member.date_to == "2026-01-31"

    def test_team_member_inactive_when_not_active_in_jira(self):
        item = _member_item()
        item["member"]["activeInJira"] = False
        member = TempoTeamMember.from_api_response(item, today=date(2026, 2, 1))
        assert member.active is False


class TestTempoPlanItem:
    def _row(self, **overrides: object) -> dict:
        row = {
            "allocationId": 42,
            "assignee": "JIRAUSER1001",
            "day": "2026-03-02",
            "timePlannedSeconds": 5400.0,
            "planItemType": "ISSUE",
            "planItemInfo": {
                "key": "PROJ-123",
                "type": "ISSUE",
                "summary": "Write tests",
                "projectKey": "PROJ",
            },
            "planDescription": "",
            "planStart": "2026-03-02",
            "planEnd": "2026-03-04",
        }
        row.update(overrides)
        return row

    def test_plan_item_issue_url_and_hours(self):
        user = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane")
        item = TempoPlanItem.from_api_response(
            self._row(), base_url=BASE_URL, is_absence=False, user=user
        )
        assert item.planned_hours == 1.5
        assert item.planned_seconds == 5400
        assert item.issue_url == "https://jira.example.com/browse/PROJ-123"
        assert item.user.username == "jdoe"
        assert item.is_absence is False
        assert item.allocation_id == 42

    def test_plan_item_project_row_has_no_url(self):
        row = self._row(
            planItemType="PROJECT",
            planItemInfo={
                "key": "PROJ",
                "type": "PROJECT",
                "name": "Project Alpha",
                "projectKey": "PROJ",
            },
            planDescription="On-call duty",
        )
        item = TempoPlanItem.from_api_response(
            row, base_url=BASE_URL, is_absence=False, user=TempoUserRef()
        )
        assert item.issue_key == "PROJ"
        assert item.summary == "Project Alpha"
        assert item.issue_url == ""
        assert item.description == "On-call duty"


class TestTempoSchedule:
    def test_schedule_day_holiday_name(self):
        day = TempoScheduleDay.from_api_response(
            {
                "date": "2026-05-01",
                "requiredSeconds": 0,
                "type": "HOLIDAY",
                "holiday": {"name": "Labour Day"},
            }
        )
        assert day.holiday_name == "Labour Day"
        assert day.required_hours == 0.0

    def test_user_schedule_totals(self):
        schedule = TempoUserSchedule.from_api_response(
            {
                "numberOfWorkingDays": 2,
                "requiredSeconds": 57600,
                "days": [
                    {
                        "date": "2026-05-04",
                        "requiredSeconds": 28800,
                        "type": "WORKING_DAY",
                    },
                    {
                        "date": "2026-05-05",
                        "requiredSeconds": 28800,
                        "type": "WORKING_DAY",
                    },
                ],
            },
            user=TempoUserRef(key="JIRAUSER1001"),
        )
        assert schedule.working_days == 2
        assert schedule.required_hours == 16.0
        assert [d.day for d in schedule.days] == ["2026-05-04", "2026-05-05"]
        assert schedule.days[0].holiday_name is None


class TestTempoWorklog:
    def test_worklog_day_from_started(self):
        worklog = TempoWorklog.from_api_response(
            {
                "tempoWorklogId": 99,
                "timeSpentSeconds": 7200,
                "started": "2026-10-02 00:00:00.000",
                "worker": "JIRAUSER1001",
                "issue": {
                    "key": "PROJ-123",
                    "summary": "Fix bug",
                    "projectKey": "PROJ",
                },
                "comment": "Working on it",
            },
            user=TempoUserRef(key="JIRAUSER1001"),
        )
        assert worklog.day == "2026-10-02"
        assert worklog.hours == 2.0
        assert worklog.worklog_id == 99
        assert worklog.issue_key == "PROJ-123"


class TestDefaults:
    def test_missing_fields_give_defaults(self):
        assert TempoUserRef.from_api_response({}).key == ""
        assert TempoTeam.from_api_response({}).id == 0
        member = TempoTeamMember.from_api_response({}, today=date(2026, 1, 1))
        assert member.role == ""
        item = TempoPlanItem.from_api_response(
            {}, base_url=BASE_URL, is_absence=True, user=TempoUserRef()
        )
        assert item.is_absence is True
        assert item.planned_hours == 0.0
        assert TempoScheduleDay.from_api_response({}).type == ""
        assert TempoUserSchedule.from_api_response({}, user=TempoUserRef()).days == []
        assert TempoWorklog.from_api_response({}, user=TempoUserRef()).hours == 0.0


ALLOCATION = {
    "id": 347,
    "assignee": {"key": "jdoe", "type": "user", "userKey": "JIRAUSER1001"},
    "planItem": {
        "key": "PROJ-123",
        "id": 4242,
        "type": "ISSUE",
        "summary": "Write tests",
        "projectKey": "PROJ",
    },
    "scope": {"id": 7, "type": "team"},
    "commitment": 12.5,
    "secondsPerDay": 3600,
    "includeNonWorkingDays": False,
    "start": "2026-03-02",
    "startTime": "00:00",
    "end": "2026-03-03",
    "description": "Probe",
    "seconds": 7200,
}


class TestTempoAllocation:
    def test_allocation_from_api_response(self):
        from mcp_atlassian.models.tempo import TempoAllocation

        allocation = TempoAllocation.from_api_response(ALLOCATION)
        assert allocation.id == 347
        assert allocation.user.to_simplified_dict() == {
            "key": "JIRAUSER1001",
            "username": "jdoe",
            "display_name": "",
        }
        assert (allocation.issue_key, allocation.issue_id, allocation.summary) == (
            "PROJ-123",
            4242,
            "Write tests",
        )
        assert allocation.team_id == 7
        assert (allocation.start, allocation.end) == ("2026-03-02", "2026-03-03")
        assert (allocation.seconds_per_day, allocation.hours_per_day) == (3600, 1.0)
        assert allocation.include_non_working_days is False
        assert allocation.description == "Probe"

    def test_allocation_request_body(self):
        from mcp_atlassian.models.tempo import TempoAllocation

        allocation = TempoAllocation.from_api_response(ALLOCATION)
        assert allocation.to_request_body() == {
            "assignee": {"key": "jdoe", "type": "user"},
            "planItem": {"id": 4242, "type": "ISSUE"},
            "scope": {"id": 7, "type": "team"},
            "start": "2026-03-02",
            "end": "2026-03-03",
            "secondsPerDay": 3600,
            "includeNonWorkingDays": False,
            "description": "Probe",
        }

    def test_allocation_simplified_dict(self):
        from mcp_atlassian.models.tempo import TempoAllocation

        data = TempoAllocation.from_api_response(ALLOCATION).to_simplified_dict()
        assert data["allocation_id"] == 347
        assert data["hours_per_day"] == 1.0
        assert data["issue_key"] == "PROJ-123"
        assert data["team_id"] == 7

    def test_allocation_defaults(self):
        from mcp_atlassian.models.tempo import TempoAllocation

        allocation = TempoAllocation.from_api_response({})
        assert allocation.id == 0
        assert allocation.hours_per_day == 0.0


class TestTempoPlanResult:
    def test_plan_result_simplified_dict(self):
        from mcp_atlassian.models.tempo import (
            TempoAllocationDraft,
            TempoPlanConflict,
            TempoPlanDay,
            TempoPlanResult,
        )

        result = TempoPlanResult(
            ok=False,
            written=False,
            mode="fixed",
            user=TempoUserRef(key="JIRAUSER1001", username="jdoe"),
            issue={"key": "PROJ-123", "id": 4242, "summary": "Write tests"},
            team={"id": 7, "name": "Platform QA"},
            days=[
                TempoPlanDay(
                    day="2026-03-02",
                    capacity_hours=8.0,
                    planned_hours=6.0,
                    absence_hours=0.0,
                    added_hours=4.0,
                    free_after_hours=0.0,
                    status_after="overbooked",
                )
            ],
            conflicts=[
                TempoPlanConflict(
                    day="2026-03-02", type="overbooked", message="2.0h over"
                )
            ],
            allocations=[
                TempoAllocationDraft(
                    start="2026-03-02",
                    end="2026-03-02",
                    hours_per_day=4.0,
                    total_hours=4.0,
                    working_days=1,
                )
            ],
        )
        data = result.to_simplified_dict()
        assert data["ok"] is False and data["written"] is False
        assert data["days"][0]["status_after"] == "overbooked"
        assert data["conflicts"][0]["type"] == "overbooked"
        assert data["allocations"][0] == {
            "allocation_id": None,
            "start": "2026-03-02",
            "end": "2026-03-02",
            "hours_per_day": 4.0,
            "total_hours": 4.0,
            "working_days": 1,
        }
        assert "allocation_id" not in data
        assert "before" not in data

    def test_plan_result_includes_update_fields(self):
        from mcp_atlassian.models.tempo import TempoPlanResult

        result = TempoPlanResult(
            ok=True,
            written=True,
            mode="fixed",
            allocation_id=347,
            before={"start": "2026-03-02"},
        )
        data = result.to_simplified_dict()
        assert data["allocation_id"] == 347
        assert data["before"] == {"start": "2026-03-02"}
