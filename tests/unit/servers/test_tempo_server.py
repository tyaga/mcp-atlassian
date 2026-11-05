"""Tests for the Tempo MCP server instance and its tools."""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastmcp.tools import Tool as FastMCPTool
from mcp.types import Tool as MCPTool

from mcp_atlassian.servers.context import MainAppContext
from mcp_atlassian.servers.main import AtlassianMCP, main_lifespan
from mcp_atlassian.servers.tempo import tempo_mcp
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
