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
