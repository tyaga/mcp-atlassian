"""Tests for Tempo team operations."""

from datetime import date

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


class TestMembersForWindow:
    def _fetcher(self):
        members = MEMBERS + [
            _member("future", "JIRAUSER1004", "QA Engineer", dateFrom="2026-04-01"),
            _member("former", "JIRAUSER1005", "QA Engineer", dateTo="2026-02-15"),
        ]
        return make_fetcher(
            {
                ("GET", "/rest/tempo-teams/2/team"): TEAMS,
                ("GET", "/rest/tempo-teams/2/team/7/member"): members,
            }
        )

    def test_window_in_past_includes_former_member(self):
        fetcher = self._fetcher()
        team = fetcher.resolve_team("7")
        members = fetcher.get_team_members(
            team, window=(date(2026, 2, 1), date(2026, 2, 28))
        )
        assert [m.user.username for m in members] == ["jdoe", "asmith", "former"]

    def test_window_before_date_from_excludes_future_member(self):
        fetcher = self._fetcher()
        team = fetcher.resolve_team("7")
        members = fetcher.get_team_members(
            team, window=(date(2026, 3, 2), date(2026, 3, 8))
        )
        assert [m.user.username for m in members] == ["jdoe", "asmith"]
        april = fetcher.get_team_members(
            team, window=(date(2026, 4, 1), date(2026, 4, 7))
        )
        assert "future" in [m.user.username for m in april]

    def test_window_excludes_inactive_membership_status(self):
        fetcher = self._fetcher()
        team = fetcher.resolve_team("7")
        fetcher.client.routes[("GET", "/rest/tempo-teams/2/team/7/member")] = [  # type: ignore[attr-defined]
            _member("paused", "JIRAUSER1006", "QA Engineer", status="inactive")
        ]
        assert (
            fetcher.get_team_members(team, window=(date(2026, 3, 2), date(2026, 3, 8)))
            == []
        )


class TestUserMemberships:
    def test_get_user_memberships(self):
        from mcp_atlassian.models.tempo import TempoUserRef

        fetcher = make_fetcher(
            {
                ("GET", "/rest/tempo-teams/2/user/jdoe/memberships"): [
                    {
                        "id": 1,
                        "availability": "100",
                        "team": {"id": 7, "name": "Platform QA"},
                        "role": {"name": "Member"},
                    },
                    {
                        "id": 2,
                        "availability": "50",
                        "team": {"id": 9, "name": "Mobile"},
                        "role": {"name": "Member"},
                    },
                ]
            }
        )
        teams = fetcher.get_user_memberships(
            TempoUserRef(key="JIRAUSER1001", username="jdoe")
        )
        assert [(t.id, t.name) for t in teams] == [(7, "Platform QA"), (9, "Mobile")]

    def test_get_user_memberships_uses_key_without_username(self):
        from mcp_atlassian.models.tempo import TempoUserRef

        fetcher = make_fetcher(
            {("GET", "/rest/tempo-teams/2/user/JIRAUSER1001/memberships"): []}
        )
        assert fetcher.get_user_memberships(TempoUserRef(key="JIRAUSER1001")) == []
