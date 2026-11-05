"""Tests for Tempo team operations."""

import pytest

from tests.unit.tempo.conftest import make_fetcher

TEAMS = [
    {"id": 7, "name": "Platform QA ", "summary": "", "lead": "jdoe"},
    {"id": 8, "name": "Platform Backend", "summary": "", "lead": None},
    {"id": 9, "name": "Mobile", "summary": "", "lead": None},
]


def _member(name: str, key: str, role: str, **membership: object) -> dict:
    return {
        "member": {
            "name": name,
            "key": key,
            "displayname": name.title(),
            "activeInJira": True,
        },
        "membership": {
            "role": {"name": role},
            "status": "active",
            "availability": "100",
            "dateFrom": "",
            "dateTo": "",
            **membership,
        },
    }


MEMBERS = [
    _member("jdoe", "JIRAUSER1001", "QA Engineer"),
    _member("asmith", "JIRAUSER1002", "QA Automation"),
    _member("bgone", "JIRAUSER1003", "QA Engineer", dateTo="2020-01-01"),
]


class TestListTeams:
    def test_list_teams_sorted_and_filtered(self):
        fetcher = make_fetcher({("GET", "/rest/tempo-teams/2/team"): TEAMS})
        assert [t.name for t in fetcher.list_teams()] == [
            "Mobile",
            "Platform Backend",
            "Platform QA ",
        ]
        assert [t.id for t in fetcher.list_teams(query="platform")] == [8, 7]


class TestResolveTeam:
    def test_resolve_team_trims_and_ignores_case(self):
        fetcher = make_fetcher({("GET", "/rest/tempo-teams/2/team"): TEAMS})
        assert fetcher.resolve_team("platform qa").id == 7

    def test_resolve_team_by_id(self):
        fetcher = make_fetcher({("GET", "/rest/tempo-teams/2/team"): TEAMS})
        assert fetcher.resolve_team("9").name == "Mobile"

    def test_resolve_team_unknown_lists_candidates(self):
        fetcher = make_fetcher({("GET", "/rest/tempo-teams/2/team"): TEAMS})
        with pytest.raises(ValueError, match="Platform QA") as exc:
            fetcher.resolve_team("Platfrom QA")
        assert "Platform Backend" in str(exc.value)


class TestGetTeamMembers:
    def _fetcher(self):
        return make_fetcher(
            {
                ("GET", "/rest/tempo-teams/2/team"): TEAMS,
                ("GET", "/rest/tempo-teams/2/team/7/member"): MEMBERS,
            }
        )

    def test_get_team_members_role_filter_and_active_only(self):
        fetcher = self._fetcher()
        team = fetcher.resolve_team("7")
        members = fetcher.get_team_members(team)
        assert [m.user.username for m in members] == ["jdoe", "asmith"]

        automation = fetcher.get_team_members(team, role="automation")
        assert [m.user.username for m in automation] == ["asmith"]

        everyone = fetcher.get_team_members(team, active_only=False)
        assert [m.user.username for m in everyone] == ["jdoe", "asmith", "bgone"]
