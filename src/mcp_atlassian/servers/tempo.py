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
from mcp_atlassian.tempo import TempoScope
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
TEAM_OPT_PARAM = Annotated[
    str | None,
    Field(
        description=(
            "Tempo team id or name. Provide either 'team' or 'users', not both."
        )
    ),
]
USERS_OPT_PARAM = Annotated[
    list[str] | None,
    Field(
        description=(
            "User identifiers (username, key, display name or e-mail). "
            "Provide either 'team' or 'users', not both."
        )
    ),
]
ISSUE_KEY_PARAM = Annotated[
    str | None,
    Field(description="Keep only rows for this issue key, e.g. 'PROJ-123'."),
]


def _scope_header(scope: TempoScope) -> dict[str, Any]:
    header: dict[str, Any] = {
        "users": [user.to_simplified_dict() for user in scope.users],
    }
    if scope.team is not None:
        header["team"] = team_summary(scope.team)
    return header


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


@tempo_mcp.tool(tags={"tempo", "read", "toolset:tempo_planning"})
async def get_plans(
    ctx: Context,
    date_from: DATE_FROM_PARAM,
    date_to: DATE_TO_PARAM,
    team: TEAM_OPT_PARAM = None,
    users: USERS_OPT_PARAM = None,
    issue_key: ISSUE_KEY_PARAM = None,
    include_absences: Annotated[
        bool,
        Field(
            description=(
                "Include plan items that look like absences (vacation, sick "
                "leave, day off) according to TEMPO_ABSENCE_PATTERN."
            )
        ),
    ] = True,
) -> str:
    """Get planned time from Tempo Planner for a team or a list of users.

    One entry per day per user per plan item. ``is_absence`` is inferred from
    the item summary/description, so treat it as a hint.

    Returns:
        JSON ``{"from", "to", "team"?, "users", "plans": [{day, user, issue_key,
        summary, project_key, plan_type, planned_hours, description, plan_start,
        plan_end, allocation_id, is_absence, issue_url}]}``.
    """
    start, end = parse_window(date_from, date_to)
    tempo = await get_tempo_fetcher(ctx)
    scope = await run_jira_fetcher_call(tempo.resolve_scope, team, users)
    plans = await run_jira_fetcher_call(
        tempo.get_plans,
        scope,
        start,
        end,
        issue_key=issue_key,
        include_absences=include_absences,
    )
    return _dump(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            **_scope_header(scope),
            "plans": [plan.to_simplified_dict() for plan in plans],
        }
    )
