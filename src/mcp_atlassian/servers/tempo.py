"""Tempo FastMCP server instance and tool definitions."""

from __future__ import annotations

import logging

from mcp_atlassian.servers.error_handling import ErrorPreservingFastMCP

logger = logging.getLogger(__name__)

tempo_mcp = ErrorPreservingFastMCP(
    name="Tempo MCP Service",
    instructions=(
        "Read-only tools for Tempo Timesheets and Tempo Planner on Jira "
        "Server/Data Center: teams, plans, schedules, worklogs and workload."
    ),
)
