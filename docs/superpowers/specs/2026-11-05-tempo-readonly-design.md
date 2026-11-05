# Tempo (Server/DC) read-only tools — design

## Goal

Let an LLM assistant answer resource-planning questions for a Jira Data Center
instance with Tempo Timesheets + Tempo Planner installed:

- who is on a team and in which role;
- what is planned for a person or team in a period, including absences;
- how loaded each person is per day / week, who is free, who is overbooked;
- which days are non-working for a person (weekends, public holidays);
- what was logged vs. what was planned (plan vs. actual).

All tools are read-only. Writing allocations is a later iteration; this design
lays down the data model (schedule + plans + worklogs) that write validation
will reuse.

## Non-goals

- Writing or editing Tempo plans or worklogs.
- Tempo Cloud (`api.tempo.io`) — only the Server/DC REST API under the Jira
  base URL is supported.
- CSV export/import, deep links into Tempo UI screens — these are Tempo UI
  features, not MCP concerns.
- A Jira group-members tool: `GET /rest/api/2/group/member` requires Jira
  administrator rights on Server/DC; Tempo team membership is the supported
  substitute.

## Verified API surface (Tempo Server/DC)

| Endpoint | Used for | Notes |
| --- | --- | --- |
| `GET /rest/tempo-teams/2/team` | list teams | `id`, `name`, `summary`, `lead` |
| `GET /rest/tempo-teams/2/team/{id}/member` | members | `member.{name,key,displayname,activeInJira}`, `membership.{role.name,availability,dateFrom,dateTo,status}` |
| `GET /rest/tempo-teams/2/role` | role catalogue | optional, used only for validation messages |
| `POST /rest/tempo-planning/1/plan/search` | plans | body `{from,to,teamId:[…]}`; `teamId` is the **only** server-side filter. One row per day × assignee × plan item: `assignee` (user key), `day`, `timePlannedSeconds`, `planItemType` (`ISSUE`/`PROJECT`), `planItemInfo.{key,summary,projectKey,originalEstimateSeconds,estimatedRemainingSeconds,issueStatus}`, `planDescription`, `planStart`, `planEnd`, `allocationId` |
| `GET /rest/tempo-core/1/user/schedule?user=&from=&to=` | working days | `days[].{date,type,requiredSeconds,holiday.name}`; `type` ∈ `WORKING_DAY`, `HOLIDAY`, `HOLIDAY_AND_NON_WORKING_DAY`, `NON_WORKING_DAY` |
| `POST /rest/tempo-timesheets/4/worklogs/search` | worklogs | body `{from,to,worker:[user keys]}`; `worker` accepts **keys only**. `teamId` filter returns incomplete data and is not used |
| `GET /rest/api/2/user?username=` / `?key=` | identity | resolve username/key to a `JiraUser` |

Not available: `tempo-core/1/workloadscheme`, `tempo-core/1/holidayscheme`
(403 for non-admins), `tempo-planning/1/allocation` (ignores all filters).

Absences (vacation, sick leave, day off) are **not** structured in Tempo
Server: teams plan them as ordinary issues whose summary says "vacation" etc.
They are detected heuristically (see below).

## Architecture

```
src/mcp_atlassian/tempo/
  __init__.py      TempoFetcher(jira: JiraFetcher) composed from mixins
  client.py        TempoClient: get/post on jira._session, error mapping
  users.py         UsersMixin: identifier -> TempoUserRef resolution
  teams.py         TeamsMixin: list_teams, resolve_team, get_team_members
  planning.py      PlanningMixin: get_plans (+ absence flag)
  schedule.py      ScheduleMixin: get_user_schedule
  worklogs.py      WorklogsMixin: get_worklogs
  workload.py      WorkloadMixin: get_workload, get_plan_vs_actual (pure math
                   over the three fetchers above)
src/mcp_atlassian/models/tempo/
  team.py, plan.py, schedule.py, worklog.py, workload.py
src/mcp_atlassian/servers/tempo.py   tempo_mcp + 7 tools
```

- **No Tempo configuration.** `TempoFetcher` wraps the `JiraFetcher` returned
  by `get_jira_fetcher(ctx)` and reuses its authenticated `requests.Session`
  and base URL. Every Jira auth mode (PAT, basic, OAuth, per-request headers)
  works unchanged. Tempo tools are available whenever Jira is configured.
- **Wiring into upstream code is minimal** so that merges from upstream stay
  cheap:
  - `servers/main.py`: `main_mcp.mount(tempo_mcp, namespace="tempo")`; in the
    tool filter, tools tagged `tempo` require `full_jira_config` (same branch
    as `jira`).
  - `servers/dependencies.py`: `get_tempo_fetcher(ctx)` — builds
    `TempoFetcher` around `get_jira_fetcher(ctx)`, cached per request in
    `request.state.tempo_fetcher` (HTTP) or on the context (stdio).
  - `utils/toolsets.py`: two toolsets, both `default=False`:
    `tempo_teams` (teams, members) and `tempo_planning` (plans, schedule,
    worklogs, workload, plan vs. actual). Tool count constants updated.
  - `scripts/generate_tool_docs.py`: include `tempo_mcp`; new
    `docs/tools/tempo.mdx`.
- **Tool tags**: `{"tempo", "read", "toolset:tempo_teams" | "toolset:tempo_planning"}`.
  All tools are read-only and work under `READ_ONLY_MODE=true`.
- **Blocking calls** go through `run_jira_fetcher_call` like Jira tools.
- **Errors**: `ValueError` with actionable messages (unknown team → closest
  names, ambiguous user → candidates, window too long → the limit). HTTP errors
  from Tempo are re-raised as `ValueError("Tempo API HTTP <status>: <path> | <body[:500]>")`;
  401/403 → `MCPAtlassianAuthenticationError`.

## Common parameters and rules

- `users`: list of identifiers; each may be a username, a user key, a display
  name or an e-mail. Resolution order per identifier: already-known member of
  the resolved team (if any) → `GET /rest/api/2/user?username=` → `?key=` →
  `GET /rest/api/2/user/search?username=` requiring exactly one match. No
  match or several matches → `ValueError` naming the identifier and candidates.
- `team`: numeric id or name. Name matching is case-insensitive after
  trimming whitespace (team names in Tempo may carry trailing spaces).
- Exactly one of `team` / `users` is required where both are accepted.
  When `team` is given together with `role`, members are filtered by role
  substring (case-insensitive) before any data is fetched.
- Dates are `YYYY-MM-DD`; `date_to` is inclusive. The window is limited to
  **92 days** (`TEMPO_MAX_WINDOW_DAYS`, default 92) because plan search
  returns one row per day per person.
- Hours are seconds / 3600 rounded to 2 decimals.
- Every user in a response is a `TempoUserRef`
  `{key, username, display_name}`.
- `issue_url` is `<jira url>/browse/<key>` for `ISSUE` plan items.

### Absence detection

A plan row is an absence when `planItemInfo.summary` or `planDescription`
matches `TEMPO_ABSENCE_PATTERN` (case-insensitive regex). Default:

```
отпуск|больничн|отгул|vacation|sick leave|day off|time off
```

Absence rows get `is_absence: true` and are excluded from `planned_hours`
but counted in `absence_hours`. The heuristic is documented in tool
descriptions so the assistant can tell the user when a day is "absent" by
inference.

## Tools

All tools live in `servers/tempo.py` and return a JSON string.

### `tempo_list_teams`

- Input: `query: str | None` — substring filter on name (case-insensitive).
- Output: `{"teams": [{id, name, summary, lead}]}` sorted by name.

### `tempo_get_team_members`

- Input: `team: str`, `role: str | None`, `active_only: bool = True`.
- `active_only` drops members with `activeInJira == false`,
  `membership.status != "active"`, or `membership.dateTo` in the past.
- Output: `{"team": {id, name}, "members": [{user, role, availability, date_from, date_to, active}]}`.

### `tempo_get_plans`

- Input: `team | users`, `date_from`, `date_to`, `issue_key: str | None`,
  `include_absences: bool = True`.
- Fetch: `plan/search` with `teamId=[id]` when `team` is given; without a
  filter when `users` is given, then filtered client-side by resolved user
  keys. `issue_key` filters on `planItemInfo.key`.
- Output: `{"from", "to", "plans": [{day, user, issue_key, summary, project_key,
  plan_type, planned_hours, description, plan_start, plan_end, allocation_id,
  is_absence, issue_url}]}` sorted by `day`, `user.display_name`, `issue_key`.

### `tempo_get_user_schedule`

- Input: `users`, `date_from`, `date_to`.
- One `user/schedule` call per user.
- Output: `{"from", "to", "schedules": [{user, working_days, required_hours,
  days: [{day, type, required_hours, holiday_name}]}]}`.

### `tempo_get_worklogs`

- Input: `team | users`, `date_from`, `date_to`, `issue_key: str | None`.
- Resolve users (team → members), one `worklogs/search` call with all keys.
- Output: `{"from", "to", "worklogs": [{worklog_id, day, user, issue_key,
  summary, project_key, hours, comment}]}` sorted by `day`, user, issue.

### `tempo_get_workload`

- Input: `team | users`, `date_from`, `date_to`,
  `granularity: "day" | "week" | "total" = "day"`, `role: str | None`,
  `daily_limit_hours: float = 8`.
- Data: schedule per user + plans for the window.
- Per user per day:
  - `capacity_hours = min(schedule.required_hours, daily_limit_hours)`
  - `planned_hours` = non-absence plan hours, `absence_hours` = absence hours
  - `free_hours = max(capacity − absence − planned, 0)`
  - `overbooked_hours = max(planned + absence − capacity, 0)`
  - `status`:
    - `non_working` if capacity = 0 and planned = 0
    - `overbooked` if overbooked_hours > 0 (including anything planned on a
      non-working day)
    - `absent` if absence ≥ capacity
    - `free` if planned = 0
    - `full` if free = 0
    - `partial` otherwise
  - `items: [{issue_key, summary, hours, is_absence}]`
- `week` buckets are ISO weeks labelled `YYYY-Www` with `from`/`to`; hours are
  summed, `status` is `overbooked` if any day is overbooked, else `absent` if
  all working days are absent, else `free`/`partial`/`full` by `free_hours`.
  `total` is one bucket for the whole window.
- Output:

```
{
  "from", "to", "granularity", "daily_limit_hours",
  "users": [{user, role, periods: [{period, from, to, capacity_hours,
             planned_hours, absence_hours, free_hours, overbooked_hours,
             status, items}]}],
  "summary": {
    "overbooked": [{user, days: [...]}],
    "free_capacity": [{user, free_hours}],      # free_hours > 0, sorted desc
    "absent": [{user, days: [...]}]
  }
}
```

### `tempo_get_plan_vs_actual`

- Input: `team | users`, `date_from`, `date_to`,
  `granularity: "week" | "day" | "total" = "week"`.
- Data: plans (non-absence) + worklogs for the window.
- Output per user per period: `planned_hours`, `logged_hours`,
  `delta_hours = logged − planned`, `by_issue: [{issue_key, summary,
  planned_hours, logged_hours, delta_hours}]`, `logged_unplanned` (issues with
  worklogs but no plan) and `planned_not_logged` (issues planned but with
  zero worklogs) as issue-key lists.

## Performance

- Team-scoped calls: 1 members call + 1 plan search + N schedule calls
  (N = members) + 1 worklog call. For 30 people × 31 days this is ~33 HTTP
  calls and well under a second of CPU.
- User-scoped plan search without a team filter returns all plans for the
  instance in the window; the 92-day cap keeps this to a few thousand rows.
- No cross-request caching; each tool call is self-contained.

## Testing

Unit tests only (`tests/unit/tempo/`, `tests/unit/servers/test_tempo*.py`),
`TempoClient` replaced by a fake that serves canned JSON. Fixtures are
anonymised (`jdoe`, `JIRAUSER1001`, `Jane Doe`, team `Platform QA`,
`PROJ-123`, `https://jira.example.com`).

- models: `from_api_response` for every model, including missing fields.
- users: resolution by username, key, display name; ambiguity error.
- teams: name match with trailing whitespace, role filter, `active_only`.
- planning: client-side user filter, `issue_key` filter, absence regex (default
  and `TEMPO_ABSENCE_PATTERN` override).
- schedule: day types, totals.
- worklogs: team → keys, `issue_key` filter.
- workload: weekend/holiday, absence, overbooking, planning on a non-working
  day, `daily_limit_hours`, week bucketing across a month boundary, summary.
- plan vs actual: delta, `logged_unplanned`, `planned_not_logged`.
- servers: `get_tempo_fetcher` reuses the Jira fetcher; tool count = 7; every
  tool has `read` and exactly one `toolset:` tag; tools hidden when Jira is
  not configured.
- toolsets/docs: `ALL_TOOLSETS` counts, `generate_tool_docs.py --check`.

`pre-commit run --all-files` (Ruff + mypy strict) must pass.

## Assistant skill

`skills/tempo-planning/SKILL.md` ships with the repository and explains how an
assistant should use the tools: which tool answers which kind of question,
identifier and date conventions, the 92-day window, the absence heuristic,
how to combine `tempo_get_workload` with Jira issue tools for feature
planning, and known limits (no Jira group members, read-only). Examples use
anonymised data only.

## Out of scope for this iteration, kept in mind

- Write tools (`tempo_plan_work`, `tempo_delete_plan`) with dry-run and the
  same workload math as validation.
- Jira group members if the instance grants the required permission.
