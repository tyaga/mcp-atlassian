"""Tempo FastMCP server instance and tool definitions."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from mcp_atlassian.servers.async_utils import run_jira_fetcher_call
from mcp_atlassian.servers.dependencies import get_tempo_fetcher
from mcp_atlassian.servers.error_handling import ErrorPreservingFastMCP
from mcp_atlassian.tempo import TempoScope
from mcp_atlassian.tempo.common import parse_window
from mcp_atlassian.tempo.teams import team_summary
from mcp_atlassian.utils.decorators import check_write_access

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


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_teams"},
    annotations={"title": "List Tempo Teams", "readOnlyHint": True},
)
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


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_teams"},
    annotations={"title": "Get Tempo Team Members", "readOnlyHint": True},
)
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


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_planning"},
    annotations={"title": "Get Tempo User Schedule", "readOnlyHint": True},
)
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


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_planning"},
    annotations={"title": "Get Tempo Plans", "readOnlyHint": True},
)
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
    scope = await run_jira_fetcher_call(
        tempo.resolve_scope, team, users, window=(start, end)
    )
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


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_planning"},
    annotations={"title": "Get Tempo Worklogs", "readOnlyHint": True},
)
async def get_worklogs(
    ctx: Context,
    date_from: DATE_FROM_PARAM,
    date_to: DATE_TO_PARAM,
    team: TEAM_OPT_PARAM = None,
    users: USERS_OPT_PARAM = None,
    issue_key: ISSUE_KEY_PARAM = None,
) -> str:
    """Get logged work (Tempo worklogs) for a team or a list of users.

    Returns:
        JSON ``{"from", "to", "team"?, "users", "worklogs": [{worklog_id, day,
        user, issue_key, summary, project_key, hours, comment}]}``.
    """
    start, end = parse_window(date_from, date_to)
    tempo = await get_tempo_fetcher(ctx)
    scope = await run_jira_fetcher_call(
        tempo.resolve_scope, team, users, window=(start, end)
    )
    worklogs = await run_jira_fetcher_call(
        tempo.get_worklogs, scope.users, start, end, issue_key=issue_key
    )
    return _dump(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            **_scope_header(scope),
            "worklogs": [worklog.to_simplified_dict() for worklog in worklogs],
        }
    )


GRANULARITY_DESC = (
    "Period size: 'day', 'week' (ISO weeks, labelled YYYY-Www) or 'total'."
)


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_planning"},
    annotations={"title": "Get Tempo Workload", "readOnlyHint": True},
)
async def get_workload(
    ctx: Context,
    date_from: DATE_FROM_PARAM,
    date_to: DATE_TO_PARAM,
    team: TEAM_OPT_PARAM = None,
    users: USERS_OPT_PARAM = None,
    granularity: Annotated[str, Field(description=GRANULARITY_DESC)] = "day",
    role: ROLE_PARAM = None,
    daily_limit_hours: Annotated[
        float,
        Field(
            description=(
                "Cap on daily capacity. Capacity is the smaller of the user's "
                "schedule norm and this value."
            )
        ),
    ] = 8.0,
) -> str:
    """Compute planned load, free capacity and overbooking per user and period.

    Per day: capacity = min(schedule norm, daily_limit_hours); free =
    capacity - absence - planned (floored at 0); overbooked = planned beyond
    what the absence leaves of the capacity (floored at 0). Status is one of
    non_working, overbooked, absent, free, partial, full. Absences are inferred
    from plan item text. Team members are selected by membership dates within
    the window. The summary lists name calendar days whatever the granularity.

    Returns:
        JSON ``{"from", "to", "granularity", "daily_limit_hours", "team"?,
        "users": [{user, role, periods: [{period, from, to, capacity_hours,
        planned_hours, absence_hours, free_hours, overbooked_hours, status,
        items}]}], "summary": {overbooked, free_capacity, absent}}``.
    """
    start, end = parse_window(date_from, date_to)
    tempo = await get_tempo_fetcher(ctx)
    scope = await run_jira_fetcher_call(
        tempo.resolve_scope, team, users, role=role, window=(start, end)
    )
    report = await run_jira_fetcher_call(
        tempo.get_workload,
        scope,
        start,
        end,
        granularity=granularity,
        daily_limit_hours=daily_limit_hours,
    )
    payload = report.to_simplified_dict()
    if scope.team is not None:
        payload["team"] = team_summary(scope.team)
    return _dump(payload)


@tempo_mcp.tool(
    tags={"tempo", "read", "toolset:tempo_planning"},
    annotations={"title": "Get Tempo Plan vs Actual", "readOnlyHint": True},
)
async def get_plan_vs_actual(
    ctx: Context,
    date_from: DATE_FROM_PARAM,
    date_to: DATE_TO_PARAM,
    team: TEAM_OPT_PARAM = None,
    users: USERS_OPT_PARAM = None,
    granularity: Annotated[str, Field(description=GRANULARITY_DESC)] = "week",
) -> str:
    """Compare planned hours (Tempo Planner) with logged hours (Tempo worklogs).

    Absence plan items are excluded. ``delta_hours`` is logged minus planned.
    Plans made on a whole project (plan_type PROJECT) are keyed by the project
    key and never match issue-level worklogs, so they appear in
    ``planned_not_logged`` while the matching worklogs appear in
    ``logged_unplanned``; the period totals are still correct.

    Returns:
        JSON ``{"from", "to", "granularity", "team"?, "users": [{user, periods:
        [{period, from, to, planned_hours, logged_hours, delta_hours, by_issue,
        logged_unplanned, planned_not_logged}]}]}``.
    """
    start, end = parse_window(date_from, date_to)
    tempo = await get_tempo_fetcher(ctx)
    scope = await run_jira_fetcher_call(
        tempo.resolve_scope, team, users, window=(start, end)
    )
    report = await run_jira_fetcher_call(
        tempo.get_plan_vs_actual, scope, start, end, granularity=granularity
    )
    payload = report.to_simplified_dict()
    if scope.team is not None:
        payload["team"] = team_summary(scope.team)
    return _dump(payload)


DRY_RUN_PARAM = Annotated[
    bool,
    Field(
        description=(
            "When true (default) only validate and report; nothing is written. "
            "Show the report to the user and repeat with dry_run=false after "
            "they confirm."
        )
    ),
]
ALLOW_OVERBOOKING_PARAM = Annotated[
    bool,
    Field(
        description=(
            "Write even if a day goes over capacity. Use only after the user "
            "explicitly accepts the overbooking."
        )
    ),
]
ALLOW_ABSENCE_PARAM = Annotated[
    bool,
    Field(
        description=(
            "Allow planning on days with an absence (vacation, sick leave). "
            "Absence hours still use up capacity, so a full-day absence also "
            "needs allow_overbooking."
        )
    ),
]
DAILY_LIMIT_PARAM = Annotated[
    float,
    Field(gt=0, le=24, description="Cap on daily capacity used for validation, hours."),
]
HOURS_PER_DAY_PARAM = Annotated[
    float | None,
    Field(
        gt=0,
        le=24,
        description=(
            "Fixed hours on every working day of date_from..date_to "
            "(requires date_to). Exclusive with total_hours."
        ),
    ),
]
TOTAL_HOURS_PARAM = Annotated[
    float | None,
    Field(
        gt=0,
        description=(
            "Hours to fit into the user's free capacity from date_from on, "
            "earliest days first; date_to is the deadline (optional). "
            "Exclusive with hours_per_day."
        ),
    ),
]
WRITE_TEAM_PARAM = Annotated[
    str | None,
    Field(
        description=(
            "Tempo team id or name used as the plan scope. Optional when the "
            "user belongs to exactly one team."
        )
    ),
]
ALLOCATION_ID_PARAM = Annotated[
    int,
    Field(description="Allocation id (``allocation_id`` from tempo_get_plans)."),
]


def _optional_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a YYYY-MM-DD date, got {value!r}") from exc


def _parse_plan_items(raw: str) -> list[dict[str, Any]]:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"items must be a JSON array of objects: {exc}") from exc
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("items must be a JSON array of objects")
    return items


@tempo_mcp.tool(
    tags={"tempo", "write", "toolset:tempo_write"},
    annotations={
        "title": "Plan Work in Tempo",
        "readOnlyHint": False,
        "destructiveHint": False,
    },
)
@check_write_access
async def plan_work(
    ctx: Context,
    user: Annotated[
        str, Field(description="Username, user key, display name or e-mail.")
    ],
    issue_key: Annotated[str, Field(description="Issue to plan, e.g. 'PROJ-123'.")],
    date_from: DATE_FROM_PARAM,
    date_to: Annotated[
        str | None,
        Field(
            description=(
                "End date, inclusive (fixed mode, required) or deadline "
                "(fit mode, optional), YYYY-MM-DD."
            )
        ),
    ] = None,
    hours_per_day: HOURS_PER_DAY_PARAM = None,
    total_hours: TOTAL_HOURS_PARAM = None,
    description: Annotated[str, Field(description="Plan description.")] = "",
    team: WRITE_TEAM_PARAM = None,
    dry_run: DRY_RUN_PARAM = True,
    allow_overbooking: ALLOW_OVERBOOKING_PARAM = False,
    allow_absence_days: ALLOW_ABSENCE_PARAM = False,
    daily_limit_hours: DAILY_LIMIT_PARAM = 8.0,
) -> str:
    """Plan time on an issue for a user in Tempo Planner, with validation.

    Checks the user's schedule (weekends, holidays), absences and existing
    plans. Conflicts (overbooked, absent, non_working, does_not_fit) block the
    write. Dry run by default. If Tempo fails part-way, ``error`` lists the
    allocations already created and ``written`` is true.

    Returns:
        JSON ``{ok, written, mode, user, issue, team, days: [{day,
        capacity_hours, planned_hours, absence_hours, added_hours,
        free_after_hours, status_after}], conflicts: [{day, type, message}],
        allocations: [{allocation_id, start, end, hours_per_day, total_hours,
        working_days}]}``.
    """
    start = _optional_date(date_from, "date_from")
    if start is None:
        raise ValueError("date_from is required")
    end = _optional_date(date_to, "date_to")
    tempo = await get_tempo_fetcher(ctx)
    result = await run_jira_fetcher_call(
        tempo.plan_work,
        user,
        issue_key,
        start,
        end,
        hours_per_day=hours_per_day,
        total_hours=total_hours,
        description=description,
        team=team,
        dry_run=dry_run,
        allow_overbooking=allow_overbooking,
        allow_absence_days=allow_absence_days,
        daily_limit_hours=daily_limit_hours,
    )
    return _dump(result.to_simplified_dict())


@tempo_mcp.tool(
    tags={"tempo", "write", "toolset:tempo_write"},
    annotations={
        "title": "Bulk Plan Work in Tempo",
        "readOnlyHint": False,
        "destructiveHint": False,
    },
)
@check_write_access
async def bulk_plan_work(
    ctx: Context,
    items: Annotated[
        str,
        Field(
            description=(
                "JSON array of plans, validated in order; each sees the hours "
                "taken by earlier items. Each object:\n"
                "- user (required): username, key, display name or e-mail\n"
                "- issue_key (required): e.g. 'PROJ-123'\n"
                "- date_from (required): YYYY-MM-DD\n"
                "- date_to (optional): end date (fixed) or deadline (fit)\n"
                "- hours_per_day or total_hours (exactly one)\n"
                "- description (optional)\n"
                'Example: [{"user": "jdoe", "issue_key": "PROJ-1", '
                '"date_from": "2026-03-02", "total_hours": 12}]'
            )
        ),
    ],
    team: WRITE_TEAM_PARAM = None,
    dry_run: DRY_RUN_PARAM = True,
    atomic: Annotated[
        bool,
        Field(
            description=(
                "When true, any conflict writes nothing. When false, "
                "conflict-free items are written and the rest are skipped."
            )
        ),
    ] = True,
    allow_overbooking: ALLOW_OVERBOOKING_PARAM = False,
    allow_absence_days: ALLOW_ABSENCE_PARAM = False,
    daily_limit_hours: DAILY_LIMIT_PARAM = 8.0,
) -> str:
    """Plan several issues in Tempo Planner at once, with validation.

    With ``atomic=true`` a Tempo failure during writing deletes the
    allocations this call already created (``rolled_back``).

    Returns:
        JSON ``{ok, written, error?, rolled_back?, results: [<plan_work result>
        + {index, status: planned | created | skipped | failed}]}``.
    """
    tempo = await get_tempo_fetcher(ctx)
    result = await run_jira_fetcher_call(
        tempo.bulk_plan_work,
        _parse_plan_items(items),
        team=team,
        dry_run=dry_run,
        atomic=atomic,
        allow_overbooking=allow_overbooking,
        allow_absence_days=allow_absence_days,
        daily_limit_hours=daily_limit_hours,
    )
    return _dump(result)


@tempo_mcp.tool(
    tags={"tempo", "write", "toolset:tempo_write"},
    annotations={
        "title": "Update Tempo Plan",
        "readOnlyHint": False,
        "destructiveHint": True,
    },
)
@check_write_access
async def update_plan(
    ctx: Context,
    allocation_id: ALLOCATION_ID_PARAM,
    date_from: Annotated[
        str | None, Field(description="New start date, YYYY-MM-DD.")
    ] = None,
    date_to: Annotated[
        str | None, Field(description="New end date, YYYY-MM-DD.")
    ] = None,
    hours_per_day: Annotated[
        float | None, Field(gt=0, le=24, description="New hours per working day.")
    ] = None,
    description: Annotated[str | None, Field(description="New description.")] = None,
    dry_run: DRY_RUN_PARAM = True,
    allow_overbooking: ALLOW_OVERBOOKING_PARAM = False,
    allow_absence_days: ALLOW_ABSENCE_PARAM = False,
    daily_limit_hours: DAILY_LIMIT_PARAM = 8.0,
) -> str:
    """Move, resize or re-describe a Tempo Planner allocation, with validation.

    Unspecified fields keep their current values. The allocation's own hours
    are excluded from the load during validation. Only team-scoped issue plans
    that skip non-working days can be updated.

    Returns:
        JSON as ``tempo_plan_work`` plus ``allocation_id`` and ``before``.
    """
    tempo = await get_tempo_fetcher(ctx)
    result = await run_jira_fetcher_call(
        tempo.update_plan,
        allocation_id,
        date_from=_optional_date(date_from, "date_from"),
        date_to=_optional_date(date_to, "date_to"),
        hours_per_day=hours_per_day,
        description=description,
        dry_run=dry_run,
        allow_overbooking=allow_overbooking,
        allow_absence_days=allow_absence_days,
        daily_limit_hours=daily_limit_hours,
    )
    return _dump(result.to_simplified_dict())


@tempo_mcp.tool(
    tags={"tempo", "write", "toolset:tempo_write"},
    annotations={
        "title": "Delete Tempo Plan",
        "readOnlyHint": False,
        "destructiveHint": True,
    },
)
@check_write_access
async def delete_plan(ctx: Context, allocation_id: ALLOCATION_ID_PARAM) -> str:
    """Delete a Tempo Planner allocation. Confirm with the user first.

    Returns:
        JSON ``{"deleted": true, "allocation": {...}}`` describing what was
        removed.
    """
    tempo = await get_tempo_fetcher(ctx)
    allocation = await run_jira_fetcher_call(tempo.delete_plan, allocation_id)
    return _dump({"deleted": True, "allocation": allocation.to_simplified_dict()})
