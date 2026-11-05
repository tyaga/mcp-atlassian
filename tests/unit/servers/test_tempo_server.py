"""Tests for the Tempo MCP server instance and its tools."""

import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client
from fastmcp.client import FastMCPTransport
from fastmcp.tools import Tool as FastMCPTool
from mcp.types import Tool as MCPTool

from mcp_atlassian.models.tempo import (
    TempoPlanItem,
    TempoPlanVsActualReport,
    TempoTeam,
    TempoTeamMember,
    TempoUserRef,
    TempoUserSchedule,
    TempoWorkloadReport,
    TempoWorklog,
)
from mcp_atlassian.servers.context import MainAppContext
from mcp_atlassian.servers.main import AtlassianMCP, main_lifespan
from mcp_atlassian.servers.tempo import tempo_mcp
from mcp_atlassian.tempo import TempoFetcher, TempoScope
from mcp_atlassian.utils.toolsets import get_toolset_tag


@pytest.fixture
def tempo_tools() -> dict[str, FastMCPTool]:
    async def _load() -> dict[str, FastMCPTool]:
        return {tool.name: tool for tool in await tempo_mcp.list_tools()}

    return asyncio.run(_load())


def _fake_tool(name: str, tags: set[str]) -> MagicMock:
    tool = MagicMock(spec=FastMCPTool)
    tool.name = name
    tool.tags = tags
    tool.to_mcp_tool.return_value = MCPTool(
        name=name, description=name, inputSchema={"type": "object", "properties": {}}
    )
    return tool


def _server_with(app_context: MainAppContext) -> AtlassianMCP:
    server = AtlassianMCP(name="Test", lifespan=main_lifespan)
    request_context = MagicMock()
    request_context.lifespan_context = {"app_lifespan_context": app_context}
    request_context.request = None
    server._mcp_server = MagicMock()
    server._mcp_server.request_context = request_context

    async def list_tools():
        return [_fake_tool("tempo_list_teams", {"tempo", "read"})]

    server.list_tools = list_tools  # type: ignore[method-assign]
    return server


class TestTempoServerInstance:
    def test_tempo_mcp_name(self):
        assert tempo_mcp.name == "Tempo MCP Service"

    def test_every_tempo_tool_is_read_and_has_one_toolset(self, tempo_tools):
        for name, tool in tempo_tools.items():
            assert "tempo" in tool.tags, name
            assert "read" in tool.tags, name
            assert "write" not in tool.tags, name
            assert get_toolset_tag(tool.tags) in {"tempo_teams", "tempo_planning"}, name


@pytest.mark.anyio
class TestTempoToolVisibility:
    async def test_tempo_tool_hidden_without_jira(self):
        server = _server_with(
            MainAppContext(full_jira_config=None, full_confluence_config=None)
        )
        tools = await server._list_tools_mcp()
        assert tools == []

    async def test_tempo_tool_listed_with_jira(self):
        jira_config = MagicMock()
        jira_config.is_cloud = False
        server = _server_with(
            MainAppContext(full_jira_config=jira_config, full_confluence_config=None)
        )
        tools = await server._list_tools_mcp()
        assert [tool.name for tool in tools] == ["tempo_list_teams"]


@pytest.fixture
def fake_tempo_fetcher():
    fetcher = MagicMock(spec=TempoFetcher)
    return fetcher


@pytest.fixture
async def tempo_client(fake_tempo_fetcher):
    with patch(
        "mcp_atlassian.servers.tempo.get_tempo_fetcher",
        AsyncMock(return_value=fake_tempo_fetcher),
    ):
        async with Client(transport=FastMCPTransport(tempo_mcp)) as client:
            yield client


@pytest.mark.anyio
class TestTeamTools:
    async def test_list_teams_tool_returns_json(self, tempo_client, fake_tempo_fetcher):
        fake_tempo_fetcher.list_teams.return_value = [
            TempoTeam(id=7, name="Platform QA", summary="", lead="jdoe")
        ]
        response = await tempo_client.call_tool("list_teams", {"query": "qa"})
        data = json.loads(response.content[0].text)
        assert data == {
            "teams": [{"id": 7, "name": "Platform QA", "summary": "", "lead": "jdoe"}]
        }
        fake_tempo_fetcher.list_teams.assert_called_once_with(query="qa")

    async def test_get_team_members_tool(self, tempo_client, fake_tempo_fetcher):
        team = TempoTeam(id=7, name="Platform QA")
        fake_tempo_fetcher.resolve_team.return_value = team
        fake_tempo_fetcher.get_team_members.return_value = [
            TempoTeamMember(
                user=TempoUserRef(key="JIRAUSER1001", username="jdoe"),
                role="QA Engineer",
            )
        ]
        response = await tempo_client.call_tool(
            "get_team_members", {"team": "Platform QA", "role": "qa"}
        )
        data = json.loads(response.content[0].text)
        assert data["team"] == {"id": 7, "name": "Platform QA"}
        assert data["members"][0]["user"]["username"] == "jdoe"
        fake_tempo_fetcher.get_team_members.assert_called_once_with(
            team, role="qa", active_only=True
        )


@pytest.mark.anyio
class TestScheduleTool:
    async def test_schedule_tool_resolves_users_and_calls_per_user(
        self, tempo_client, fake_tempo_fetcher
    ):
        jane = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane")
        alex = TempoUserRef(key="JIRAUSER1002", username="asmith", display_name="Alex")
        fake_tempo_fetcher.resolve_users.return_value = [jane, alex]
        fake_tempo_fetcher.get_user_schedule.side_effect = lambda user, *_: (
            TempoUserSchedule(user=user, working_days=1, required_hours=8.0)
        )
        response = await tempo_client.call_tool(
            "get_user_schedule",
            {
                "users": ["jdoe", "asmith"],
                "date_from": "2026-05-04",
                "date_to": "2026-05-04",
            },
        )
        data = json.loads(response.content[0].text)
        assert data["from"] == "2026-05-04"
        assert [s["user"]["username"] for s in data["schedules"]] == ["jdoe", "asmith"]
        assert fake_tempo_fetcher.get_user_schedule.call_count == 2
        fake_tempo_fetcher.get_user_schedule.assert_any_call(
            jane, date(2026, 5, 4), date(2026, 5, 4)
        )

    async def test_schedule_tool_rejects_bad_window(self, tempo_client):
        with pytest.raises(Exception, match="date_to"):
            await tempo_client.call_tool(
                "get_user_schedule",
                {"users": ["jdoe"], "date_from": "2026-05-04", "date_to": "bad"},
            )


@pytest.mark.anyio
class TestPlansTool:
    async def test_get_plans_tool_passes_scope_and_filters(
        self, tempo_client, fake_tempo_fetcher
    ):
        scope = TempoScope(team=TempoTeam(id=7, name="Platform QA"), users=[])
        fake_tempo_fetcher.resolve_scope.return_value = scope
        fake_tempo_fetcher.get_plans.return_value = [
            TempoPlanItem(day="2026-03-02", issue_key="PROJ-1", planned_hours=8.0)
        ]
        response = await tempo_client.call_tool(
            "get_plans",
            {
                "team": "Platform QA",
                "date_from": "2026-03-02",
                "date_to": "2026-03-04",
                "issue_key": "PROJ-1",
                "include_absences": False,
            },
        )
        data = json.loads(response.content[0].text)
        assert data["team"] == {"id": 7, "name": "Platform QA"}
        assert data["plans"][0]["issue_key"] == "PROJ-1"
        fake_tempo_fetcher.resolve_scope.assert_called_once_with("Platform QA", None)
        fake_tempo_fetcher.get_plans.assert_called_once_with(
            scope,
            date(2026, 3, 2),
            date(2026, 3, 4),
            issue_key="PROJ-1",
            include_absences=False,
        )

    async def test_get_plans_tool_rejects_long_window(self, tempo_client):
        with pytest.raises(Exception, match="92"):
            await tempo_client.call_tool(
                "get_plans",
                {"users": ["jdoe"], "date_from": "2026-01-01", "date_to": "2026-06-30"},
            )


@pytest.mark.anyio
class TestWorklogsTool:
    async def test_get_worklogs_tool(self, tempo_client, fake_tempo_fetcher):
        jane = TempoUserRef(key="JIRAUSER1001", username="jdoe", display_name="Jane")
        scope = TempoScope(team=None, users=[jane])
        fake_tempo_fetcher.resolve_scope.return_value = scope
        fake_tempo_fetcher.get_worklogs.return_value = [
            TempoWorklog(
                worklog_id=1, day="2026-03-02", user=jane, issue_key="PROJ-1", hours=2.0
            )
        ]
        response = await tempo_client.call_tool(
            "get_worklogs",
            {"users": ["jdoe"], "date_from": "2026-03-02", "date_to": "2026-03-03"},
        )
        data = json.loads(response.content[0].text)
        assert "team" not in data
        assert data["users"][0]["username"] == "jdoe"
        assert data["worklogs"][0]["hours"] == 2.0
        fake_tempo_fetcher.get_worklogs.assert_called_once_with(
            [jane], date(2026, 3, 2), date(2026, 3, 3), issue_key=None
        )


@pytest.mark.anyio
class TestWorkloadTool:
    async def test_get_workload_tool(self, tempo_client, fake_tempo_fetcher):
        scope = TempoScope(team=TempoTeam(id=7, name="Platform QA"), users=[])
        fake_tempo_fetcher.resolve_scope.return_value = scope
        fake_tempo_fetcher.get_workload.return_value = TempoWorkloadReport(
            date_from="2026-03-02",
            date_to="2026-03-08",
            granularity="week",
            daily_limit_hours=6.0,
            summary={"overbooked": [], "free_capacity": [], "absent": []},
        )
        response = await tempo_client.call_tool(
            "get_workload",
            {
                "team": "Platform QA",
                "date_from": "2026-03-02",
                "date_to": "2026-03-08",
                "granularity": "week",
                "role": "qa",
                "daily_limit_hours": 6.0,
            },
        )
        data = json.loads(response.content[0].text)
        assert data["team"] == {"id": 7, "name": "Platform QA"}
        assert data["granularity"] == "week"
        assert data["summary"]["overbooked"] == []
        fake_tempo_fetcher.resolve_scope.assert_called_once_with(
            "Platform QA", None, role="qa"
        )
        fake_tempo_fetcher.get_workload.assert_called_once_with(
            scope,
            date(2026, 3, 2),
            date(2026, 3, 8),
            granularity="week",
            daily_limit_hours=6.0,
        )


@pytest.mark.anyio
class TestPlanVsActualTool:
    async def test_get_plan_vs_actual_tool(self, tempo_client, fake_tempo_fetcher):
        scope = TempoScope(
            team=None, users=[TempoUserRef(key="JIRAUSER1001", username="jdoe")]
        )
        fake_tempo_fetcher.resolve_scope.return_value = scope
        fake_tempo_fetcher.get_plan_vs_actual.return_value = TempoPlanVsActualReport(
            date_from="2026-03-02", date_to="2026-03-08", granularity="week"
        )
        response = await tempo_client.call_tool(
            "get_plan_vs_actual",
            {"users": ["jdoe"], "date_from": "2026-03-02", "date_to": "2026-03-08"},
        )
        data = json.loads(response.content[0].text)
        assert data["granularity"] == "week"
        assert data["users"] == []
        fake_tempo_fetcher.get_plan_vs_actual.assert_called_once_with(
            scope, date(2026, 3, 2), date(2026, 3, 8), granularity="week"
        )
