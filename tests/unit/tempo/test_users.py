"""Tests for Tempo user resolution and scope."""

from datetime import date

import pytest

from mcp_atlassian.models.jira.common import JiraUser
from mcp_atlassian.models.tempo import TempoTeamMember, TempoUserRef
from tests.unit.tempo.conftest import make_fetcher
from tests.unit.tempo.test_teams import MEMBERS, TEAMS


def _known() -> list[TempoTeamMember]:
    return [
        TempoTeamMember(
            user=TempoUserRef(
                key="JIRAUSER1001", username="jdoe", display_name="Jane Doe"
            ),
            role="QA Engineer",
        )
    ]


class TestResolveUsers:
    def test_resolve_users_prefers_known_members(self):
        fetcher = make_fetcher({})
        fetcher.jira.get_user_profile_by_identifier.side_effect = AssertionError(
            "Jira must not be called"
        )
        users = fetcher.resolve_users(["jane doe", "JIRAUSER1001", "jdoe"], _known())
        assert [u.key for u in users] == ["JIRAUSER1001"]

    def test_resolve_users_via_jira_profile(self):
        fetcher = make_fetcher({})
        fetcher.jira.get_user_profile_by_identifier.return_value = JiraUser(
            username="asmith", user_key="JIRAUSER1002", display_name="Alex Smith"
        )
        users = fetcher.resolve_users(["asmith"])
        assert users[0].to_simplified_dict() == {
            "key": "JIRAUSER1002",
            "username": "asmith",
            "display_name": "Alex Smith",
        }

    def test_resolve_users_falls_back_to_search_single_match(self):
        fetcher = make_fetcher({})
        fetcher.jira.get_user_profile_by_identifier.side_effect = ValueError("nope")
        fetcher.jira.jira.user_find_by_user_string.return_value = [
            {"name": "asmith", "key": "JIRAUSER1002", "displayName": "Alex Smith"}
        ]
        users = fetcher.resolve_users(["Alex Smith"])
        assert users[0].key == "JIRAUSER1002"
        fetcher.jira.jira.user_find_by_user_string.assert_called_once_with(
            username="Alex Smith"
        )

    def test_resolve_users_ambiguous_raises(self):
        fetcher = make_fetcher({})
        fetcher.jira.get_user_profile_by_identifier.side_effect = ValueError("nope")
        fetcher.jira.jira.user_find_by_user_string.return_value = [
            {"name": "asmith", "key": "JIRAUSER1002", "displayName": "Alex Smith"},
            {"name": "asmithe", "key": "JIRAUSER1003", "displayName": "Alex Smithe"},
        ]
        with pytest.raises(ValueError, match="ambiguous.*Alex Smithe"):
            fetcher.resolve_users(["Alex"])

    def test_resolve_users_not_found_raises(self):
        fetcher = make_fetcher({})
        fetcher.jira.get_user_profile_by_identifier.side_effect = ValueError("nope")
        fetcher.jira.jira.user_find_by_user_string.return_value = []
        with pytest.raises(ValueError, match="'nobody' not found"):
            fetcher.resolve_users(["nobody"])


class TestResolveScope:
    def _fetcher(self):
        return make_fetcher(
            {
                ("GET", "/rest/tempo-teams/2/team"): TEAMS,
                ("GET", "/rest/tempo-teams/2/team/7/member"): MEMBERS,
            }
        )

    def test_resolve_scope_requires_exactly_one(self):
        fetcher = self._fetcher()
        with pytest.raises(ValueError, match="exactly one"):
            fetcher.resolve_scope(None, None)
        with pytest.raises(ValueError, match="exactly one"):
            fetcher.resolve_scope("7", ["jdoe"])

    def test_resolve_scope_team_with_role(self):
        scope = self._fetcher().resolve_scope("Platform QA", None, role="automation")
        assert scope.team is not None and scope.team.id == 7
        assert [u.username for u in scope.users] == ["asmith"]
        assert scope.roles == {"JIRAUSER1002": "QA Automation"}

    def test_resolve_scope_passes_window_to_members(self):
        fetcher = self._fetcher()
        fetcher.client.routes[("GET", "/rest/tempo-teams/2/team/7/member")] = [  # type: ignore[attr-defined]
            *MEMBERS,
            {
                "member": {
                    "name": "former",
                    "key": "JIRAUSER1005",
                    "displayname": "Former",
                    "activeInJira": True,
                },
                "membership": {
                    "role": {"name": "QA Engineer"},
                    "status": "active",
                    "availability": "100",
                    "dateFrom": "",
                    "dateTo": "2026-02-15",
                },
            },
        ]
        scope = fetcher.resolve_scope(
            "7", None, window=(date(2026, 2, 1), date(2026, 2, 28))
        )
        assert "JIRAUSER1005" in scope.roles

    def test_resolve_scope_users(self):
        fetcher = self._fetcher()
        fetcher.jira.get_user_profile_by_identifier.return_value = JiraUser(
            username="jdoe", user_key="JIRAUSER1001", display_name="Jane Doe"
        )
        scope = fetcher.resolve_scope(None, ["jdoe"])
        assert scope.team is None
        assert [u.key for u in scope.users] == ["JIRAUSER1001"]
        assert scope.roles == {}
