"""Tempo FastMCP server instance and tool definitions."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from mcp_atlassian.servers.async_utils import run_jira_fetcher_call
from mcp_atlassian.servers.dependencies import get_tempo_fetcher
from mcp_atlassian.servers.error_handling import ErrorPreservingFastMCP
from mcp_atlassian.tempo.common import parse_window
from mcp_atlassian.tempo.teams import team_summary

logger = logging.getLogger(__name__)

tempo_mcp = ErrorPreservingFastMCP(
    name="Tempo MCP Service",
    instructions=(
        "Read-only tools for Tempo Timesheets and Tempo Planner on Jira "
        "Server/Data Center: teams, plans, schedules, worklogs and workload."
    ),
)

TEAM_PARAM = Annotated[
    str,
    Field(description="Tempo team id or team name (case-insensitive)."),
]
ROLE_PARAM = Annotated[
    str | None,
    Field(
        description=(
            "Keep only members whose team role contains this text "
            "(case-insensitive), e.g. 'automation'."
        )
    ),
]
USERS_PARAM = Annotated[
    list[str],
    Field(
        description=(
            "User identifiers: username, user key, display name or e-mail. "
            "Each must resolve to exactly one Jira user."
        )
    ),
]
DATE_FROM_PARAM = Annotated[str, Field(description="Start date, YYYY-MM-DD.")]
DATE_TO_PARAM = Annotated[
    str,
    Field(
        description=(
            "End date, YYYY-MM-DD, inclusive. The window may span at most "
            "TEMPO_MAX_WINDOW_DAYS days (default 92)."
        )
    ),
]


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


@tempo_mcp.tool(tags={"tempo", "read", "toolset:tempo_teams"})
async def list_teams(
    ctx: Context,
    query: Annotated[
        str | None,
        Field(description="Optional case-insensitive substring to filter team names."),
    ] = None,
) -> str:
    """List Tempo teams.

    Returns:
        JSON ``{"teams": [{id, name, summary, lead}]}`` sorted by name.
    """
    tempo = await get_tempo_fetcher(ctx)
    teams = await run_jira_fetcher_call(tempo.list_teams, query=query)
    return _dump({"teams": [team.to_simplified_dict() for team in teams]})


@tempo_mcp.tool(tags={"tempo", "read", "toolset:tempo_teams"})
async def get_team_members(
    ctx: Context,
    team: TEAM_PARAM,
    role: ROLE_PARAM = None,
    active_only: Annotated[
        bool,
        Field(
            description=(
                "Drop members inactive in Jira, with inactive membership, "
                "or whose membership end date has passed."
            )
        ),
    ] = True,
) -> str:
    """Get members of a Tempo team with their roles and availability.

    Returns:
        JSON ``{"team": {id, name}, "members": [{user, role, availability,
        date_from, date_to, active}]}``.
    """
    tempo = await get_tempo_fetcher(ctx)
    resolved = await run_jira_fetcher_call(tempo.resolve_team, team)
    members = await run_jira_fetcher_call(
        tempo.get_team_members, resolved, role=role, active_only=active_only
    )
    return _dump(
        {
            "team": team_summary(resolved),
            "members": [member.to_simplified_dict() for member in members],
        }
    )


@tempo_mcp.tool(tags={"tempo", "read", "toolset:tempo_planning"})
async def get_user_schedule(
    ctx: Context,
    users: USERS_PARAM,
    date_from: DATE_FROM_PARAM,
    date_to: DATE_TO_PARAM,
) -> str:
    """Get working days, weekends and holidays for users.

    Day ``type`` is ``WORKING_DAY``, ``HOLIDAY``, ``NON_WORKING_DAY`` or
    ``HOLIDAY_AND_NON_WORKING_DAY``; ``required_hours`` is the daily norm.

    Returns:
        JSON ``{"from", "to", "schedules": [{user, working_days,
        required_hours, days: [{day, type, required_hours, holiday_name}]}]}``.
    """
    start, end = parse_window(date_from, date_to)
    tempo = await get_tempo_fetcher(ctx)
    resolved = await run_jira_fetcher_call(tempo.resolve_users, users)
    schedules = [
        await run_jira_fetcher_call(tempo.get_user_schedule, user, start, end)
        for user in resolved
    ]
    return _dump(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "schedules": [schedule.to_simplified_dict() for schedule in schedules],
        }
    )
