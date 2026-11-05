# Tempo read-only tools — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seven read-only `tempo_*` MCP tools (teams, members, plans, schedule, worklogs, workload, plan vs. actual) for Tempo Server/DC, reusing the Jira session.

**Architecture:** `TempoFetcher(jira)` composes mixins over a thin `TempoClient` bound to `JiraFetcher.jira._session`; pure aggregation in `tempo/workload.py`; FastMCP server `tempo_mcp` mounted under namespace `tempo`; two toolsets. Minimal edits to upstream files.

**Tech Stack:** Python ≥ 3.10, FastMCP, Pydantic v2 (`ApiModel`), `requests` session from `atlassian-python-api`, pytest, Ruff + mypy strict.

**Spec:** `docs/superpowers/specs/2026-11-05-tempo-readonly-design.md`

## Global Constraints

- Line length 88; absolute imports; Google docstrings on public API; type hints everywhere; mypy strict.
- No personal, team, company, host, ticket or credential data anywhere in the repo. Fixtures use `jdoe` / `JIRAUSER1001` / `Jane Doe` / `Platform QA` / `PROJ-123` / `https://jira.example.com`.
- Comments and docs describe current behaviour only; no history, no AI attribution in commits.
- Package manager: `uv` only. Run `uv run pytest tests/unit/tempo tests/unit/servers tests/unit/utils -q` and `pre-commit run --all-files` before each commit.
- Dates `YYYY-MM-DD`, `date_to` inclusive, window ≤ `TEMPO_MAX_WINDOW_DAYS` (default 92). Hours = seconds / 3600 rounded to 2 decimals.
- Default absence regex: `отпуск|больничн|отгул|vacation|sick leave|day off|time off` (env `TEMPO_ABSENCE_PATTERN`, case-insensitive).
- Tool tags: `{"tempo", "read", "toolset:tempo_teams" | "toolset:tempo_planning"}`.

## Review Focus

1. `date_from > date_to` or a non-ISO date → `ValueError` naming the parameter, not a traceback. (Task 2)
2. Team name with trailing/leading whitespace or different case still resolves; unknown name lists up to 5 closest names. (Task 4)
3. Plan rows whose `assignee` is not among resolved users (user-scoped query) are dropped, not crashed on. (Task 6)
4. A plan on a weekend/holiday counts as overbooked, and `daily_limit_hours` smaller than the schedule norm lowers capacity. (Task 8)
5. Worklogs for an issue that was never planned appear in `logged_unplanned`, and planned issues with zero logged hours in `planned_not_logged`, per period. (Task 9)

---

### Task 1: Models

**Files:**
- Create: `src/mcp_atlassian/models/tempo/__init__.py`, `common.py`, `team.py`, `plan.py`, `schedule.py`, `worklog.py`, `workload.py`
- Test: `tests/unit/tempo/test_models.py`

**Interfaces:**
- Produces (all `ApiModel`, each with `from_api_response(data, **kwargs)` and `to_simplified_dict()`):
  - `TempoUserRef(key: str = "", username: str = "", display_name: str = "")`. `from_api_response` accepts a Tempo member dict (`name`, `key`, `displayname`) **or** a Jira user dict (`name`, `key`, `displayName`).
  - `TempoTeam(id: int = 0, name: str = "", summary: str = "", lead: str | None = None)`.
  - `TempoTeamMember(user: TempoUserRef, role: str = "", availability: int = 100, date_from: str = "", date_to: str = "", active: bool = True)`. `from_api_response(item, today: date)`; `active = member.activeInJira and membership.status == "active" and (not date_to or date_to >= today)`.
  - `TempoPlanItem(day: str, user: TempoUserRef, issue_key: str, summary: str, project_key: str, plan_type: str, planned_seconds: int, planned_hours: float, description: str, plan_start: str, plan_end: str, allocation_id: int, is_absence: bool, issue_url: str)`. `from_api_response(row, base_url: str, is_absence: bool, user: TempoUserRef)`; `issue_url` only for `plan_type == "ISSUE"`; `PROJECT` rows use `planItemInfo.key` as `issue_key` and `planItemInfo.name` as `summary`.
  - `TempoScheduleDay(day: str, type: str, required_seconds: int, required_hours: float, holiday_name: str | None)`; `TempoUserSchedule(user: TempoUserRef, working_days: int, required_hours: float, days: list[TempoScheduleDay])`. `from_api_response(data, user)`.
  - `TempoWorklog(worklog_id: int, day: str, user: TempoUserRef, issue_key: str, summary: str, project_key: str, seconds: int, hours: float, comment: str)`. `from_api_response(row, user)`; `day = started[:10]`.
  - `TempoWorkloadItem(issue_key, summary, hours, is_absence)`, `TempoWorkloadPeriod(period: str, date_from: str, date_to: str, capacity_hours, planned_hours, absence_hours, free_hours, overbooked_hours, status: str, items: list[TempoWorkloadItem])`, `TempoUserWorkload(user, role: str, periods)`, `TempoWorkloadReport(date_from, date_to, granularity, daily_limit_hours, users: list[TempoUserWorkload], summary: dict[str, Any])`.
  - `TempoPlanVsActualIssue(issue_key, summary, planned_hours, logged_hours, delta_hours)`, `TempoPlanVsActualPeriod(period, date_from, date_to, planned_hours, logged_hours, delta_hours, by_issue, logged_unplanned: list[str], planned_not_logged: list[str])`, `TempoUserPlanVsActual(user, periods)`, `TempoPlanVsActualReport(date_from, date_to, granularity, users)`.
  - Report models are built directly (no `from_api_response`), only `to_simplified_dict()`.

- [ ] **Step 1: Write failing tests** in `tests/unit/tempo/test_models.py`: `test_user_ref_from_member_dict`, `test_user_ref_from_jira_user_dict`, `test_team_member_inactive_when_date_to_past` (`date_to="2026-01-31"`, `today=date(2026,2,1)` → `active is False`), `test_team_member_active_without_date_to`, `test_plan_item_issue_url_and_hours` (`timePlannedSeconds=5400.0` → `planned_hours == 1.5`, `issue_url == "https://jira.example.com/browse/PROJ-123"`), `test_plan_item_project_row_has_no_url`, `test_schedule_day_holiday_name`, `test_worklog_day_from_started` (`started="2026-10-02 00:00:00.000"` → `day == "2026-10-02"`), `test_missing_fields_give_defaults` (empty dicts for every model).
- [ ] **Step 2: Run** `uv run pytest tests/unit/tempo/test_models.py -q` → ImportError.
- [ ] **Step 3: Implement** the models above; `models/tempo/__init__.py` re-exports all names.
- [ ] **Step 4: Run** the test file → PASS; `pre-commit run --files src/mcp_atlassian/models/tempo/*.py tests/unit/tempo/test_models.py` clean.
- [ ] **Step 5: Commit** `feat(tempo): add Tempo data models`.

---

### Task 2: Client, date window, fetcher skeleton

**Files:**
- Create: `src/mcp_atlassian/tempo/__init__.py`, `client.py`, `common.py`
- Test: `tests/unit/tempo/conftest.py`, `tests/unit/tempo/test_client.py`, `tests/unit/tempo/test_common.py`

**Interfaces:**
- Consumes: `JiraFetcher` (`.jira._session: requests.Session`, `.config.url`).
- Produces:
  - `TempoClient(session: requests.Session, base_url: str, timeout: int = 75)` with `get(path: str, params: dict[str, Any] | None = None) -> Any`, `post(path: str, payload: dict[str, Any]) -> Any`. `path` starts with `/rest/`. Empty body → `None`. HTTP 401/403 → `MCPAtlassianAuthenticationError`; other `HTTPError` → `ValueError(f"Tempo API HTTP {status}: {path} | {body[:500]}")`; `ConnectionError` → `MCPAtlassianAuthenticationError`.
  - `tempo/common.py`: `parse_window(date_from: str, date_to: str) -> tuple[date, date]` (ISO parse, `from <= to`, span ≤ `get_int_env("TEMPO_MAX_WINDOW_DAYS", 92)` days inclusive, else `ValueError`); `seconds_to_hours(seconds: float | int) -> float`; `absence_pattern() -> re.Pattern[str]` (compiled from `get_regex_env("TEMPO_ABSENCE_PATTERN", DEFAULT)`, `re.IGNORECASE`); `iso_week_buckets(date_from: date, date_to: date) -> list[tuple[str, date, date]]` (label `YYYY-Www`, bounds clipped to the window); `day_buckets(...)` and `total_bucket(...)` with the same return shape (`period` label = the day / `"total"`).
  - `TempoFetcher(jira: JiraFetcher)` in `tempo/__init__.py` with attributes `jira`, `client: TempoClient`, `base_url: str`; mixins added in later tasks.
  - `tests/unit/tempo/conftest.py`: `FakeTempoClient(routes: dict[tuple[str, str], Any])` — key `(method, path)`, value is a response or a callable `(params_or_payload) -> response`; records `calls: list[tuple[str, str, Any]]`; `make_fetcher(routes, jira=None) -> TempoFetcher` that injects the fake client and a `MagicMock(spec=JiraFetcher)` with `config.url = "https://jira.example.com"`.

- [ ] **Step 1: Write failing tests**: `test_client.py` — `test_get_builds_url_and_returns_json`, `test_403_raises_auth_error`, `test_500_raises_value_error_with_body`, `test_empty_body_returns_none` (use `responses` or a `MagicMock` session). `test_common.py` — `test_parse_window_ok`, `test_parse_window_rejects_reversed`, `test_parse_window_rejects_bad_format` (message contains the parameter name), `test_parse_window_rejects_long_window` (93 days), `test_iso_week_buckets_clips_to_window` (2026-10-29..2026-11-03 → `["2026-W44", "2026-W45"]`, first bucket `2026-10-29..2026-11-01`), `test_absence_pattern_env_override` (monkeypatch `TEMPO_ABSENCE_PATTERN="offsite"`).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** client, common, fetcher skeleton, conftest.
- [ ] **Step 4: Run** `uv run pytest tests/unit/tempo -q` → PASS; pre-commit clean.
- [ ] **Step 5: Commit** `feat(tempo): add Tempo client and date helpers`.

---

### Task 3: Server wiring (dependency, mount, toolsets, filter)

**Files:**
- Create: `src/mcp_atlassian/servers/tempo.py` (server instance only, tools come later)
- Modify: `src/mcp_atlassian/servers/dependencies.py` (append), `src/mcp_atlassian/servers/main.py` (`mount`, `_is_tool_enabled`), `src/mcp_atlassian/utils/toolsets.py` (`TEMPO_TOOLSETS`, `ALL_TOOLSETS`, counts in docstrings)
- Test: `tests/unit/servers/test_tempo_dependencies.py`, `tests/unit/utils/test_toolsets.py` (counts 25 → 27, add `tempo_tools` fixture + tag tests), `tests/unit/servers/test_main_server.py` (tempo tool hidden when Jira unavailable)

**Interfaces:**
- Produces: `async def get_tempo_fetcher(ctx: Context) -> TempoFetcher` — `jira = await get_jira_fetcher(ctx)`; inside an HTTP request reuse `request.state.tempo_fetcher` when its `.jira is jira`, else build and store; outside HTTP build a new `TempoFetcher(jira)`.
- `tempo_mcp = ErrorPreservingFastMCP(name="Tempo MCP Service", instructions=...)`.
- `TEMPO_TOOLSETS = {"tempo_teams": ToolsetDefinition(..., default=False), "tempo_planning": ToolsetDefinition(..., default=False)}`; `ALL_TOOLSETS = {**JIRA_TOOLSETS, **CONFLUENCE_TOOLSETS, **TEMPO_TOOLSETS}`.
- `main.py`: `main_mcp.mount(tempo_mcp, namespace="tempo")`; in `_is_tool_enabled`, `is_jira_tool = "jira" in tool_tags or "tempo" in tool_tags`.

- [ ] **Step 1: Write failing tests**: `test_get_tempo_fetcher_wraps_jira_fetcher` (patch `get_jira_fetcher`, assert `result.jira is jira_mock`), `test_get_tempo_fetcher_reuses_request_state` (patch `get_http_request`), toolset count assertions updated to 27 and `len(TEMPO_TOOLSETS) == 2`, `test_default_toolsets_unchanged` (still 6), main-server test: a tool tagged `tempo` is hidden when `full_jira_config is None`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** the wiring.
- [ ] **Step 4: Run** `uv run pytest tests/unit/servers tests/unit/utils -q` → PASS; pre-commit clean.
- [ ] **Step 5: Commit** `feat(tempo): wire Tempo server, dependency and toolsets`.

---

### Task 4: Users, teams, scope + tools `tempo_list_teams`, `tempo_get_team_members`

**Files:**
- Create: `src/mcp_atlassian/tempo/users.py`, `src/mcp_atlassian/tempo/teams.py`, `src/mcp_atlassian/tempo/scope.py`
- Modify: `src/mcp_atlassian/tempo/__init__.py` (mixins), `src/mcp_atlassian/servers/tempo.py`
- Test: `tests/unit/tempo/test_users.py`, `test_teams.py`, `tests/unit/servers/test_tempo_server.py`

**Interfaces:**
- `scope.py`: `@dataclass TempoScope(team: TempoTeam | None, users: list[TempoUserRef], roles: dict[str, str])` (`roles` keyed by user key, empty for user-scoped).
- `TeamsMixin`: `list_teams(query: str | None = None) -> list[TempoTeam]` (`GET /rest/tempo-teams/2/team`, sorted by name, substring filter case-insensitive); `resolve_team(team: str) -> TempoTeam` (digits → id match; else `name.strip().casefold()` equality; miss → `ValueError` with up to 5 names by `difflib.get_close_matches` or the first 5 alphabetically); `get_team_members(team: TempoTeam, role: str | None = None, active_only: bool = True) -> list[TempoTeamMember]` (`GET /rest/tempo-teams/2/team/{id}/member`, `today=date.today()`, role substring casefold).
- `UsersMixin`: `resolve_users(identifiers: list[str], known: list[TempoTeamMember] | None = None) -> list[TempoUserRef]` — per identifier: match `known` on key/username/display_name (casefold) → `self.jira.get_user_profile_by_identifier(identifier)` (JiraUser → `TempoUserRef(key=user_key, username=username, display_name=display_name)`) → on `ValueError` `self.jira.jira.user_find_by_user_string(username=identifier)`; exactly one result → use it; else `ValueError(f"User '{identifier}' not found")` / `ValueError(f"User '{identifier}' is ambiguous: {names}")`. Preserves input order, dedupes by key.
- `resolve_scope(team: str | None, users: list[str] | None, role: str | None = None) -> TempoScope` on `UsersMixin`: exactly one of `team`/`users` else `ValueError("Provide exactly one of 'team' or 'users'")`; team → active members filtered by role; users → `resolve_users`.
- Tools: `list_teams(ctx, query: str | None = None) -> str`, `get_team_members(ctx, team: str, role: str | None = None, active_only: bool = True) -> str`; outputs per spec; blocking work via `run_jira_fetcher_call`.

- [ ] **Step 1: Write failing tests**: `test_resolve_team_trims_and_ignores_case` (route returns `[{"id": 7, "name": "Platform QA ", ...}]`, `resolve_team("platform qa")` → id 7), `test_resolve_team_unknown_lists_candidates`, `test_get_team_members_role_filter_and_active_only`, `test_resolve_users_prefers_known_members` (no Jira call), `test_resolve_users_falls_back_to_search_single_match`, `test_resolve_users_ambiguous_raises`, `test_resolve_scope_requires_exactly_one`; server tests: `test_list_teams_tool_returns_json`, `test_get_team_members_tool` with `get_tempo_fetcher` patched; tag test: both tools carry `read` and `toolset:tempo_teams`.
- [ ] **Step 2: Run** → fail.  **Step 3: Implement.**  **Step 4: Run** `uv run pytest tests/unit/tempo tests/unit/servers/test_tempo_server.py -q` → PASS; pre-commit clean.
- [ ] **Step 5: Commit** `feat(tempo): add team and user resolution tools`.

---

### Task 5: Schedule + tool `tempo_get_user_schedule`

**Files:** Create `src/mcp_atlassian/tempo/schedule.py`; modify `tempo/__init__.py`, `servers/tempo.py`; test `tests/unit/tempo/test_schedule.py`, `tests/unit/servers/test_tempo_server.py`.

**Interfaces:** `ScheduleMixin.get_user_schedule(user: TempoUserRef, date_from: date, date_to: date) -> TempoUserSchedule` — `GET /rest/tempo-core/1/user/schedule` params `{"user": user.username or user.key, "from": iso, "to": iso}`. Tool `get_user_schedule(ctx, users: list[str], date_from: str, date_to: str) -> str` → `{"from","to","schedules":[...]}`.

- [ ] Tests: `test_schedule_maps_days_and_totals` (fixture with `WORKING_DAY`, `HOLIDAY` with name, `HOLIDAY_AND_NON_WORKING_DAY`; `working_days == 2`, `required_hours == 16.0`), `test_schedule_tool_resolves_users_and_calls_per_user`. Run → fail → implement → pass → pre-commit.
- [ ] Commit `feat(tempo): add user schedule tool`.

---

### Task 6: Plans + tool `tempo_get_plans`

**Files:** Create `src/mcp_atlassian/tempo/planning.py`; modify `tempo/__init__.py`, `servers/tempo.py`; test `tests/unit/tempo/test_planning.py`, server test.

**Interfaces:** `PlanningMixin.get_plans(scope: TempoScope, date_from: date, date_to: date, issue_key: str | None = None, include_absences: bool = True) -> list[TempoPlanItem]` — `POST /rest/tempo-planning/1/plan/search` payload `{"from","to"}` + `"teamId": [scope.team.id]` when team-scoped; keep rows whose `assignee` ∈ `{u.key for u in scope.users}`; `is_absence = bool(absence_pattern().search(summary + " " + description))`; `include_absences=False` drops them; `issue_key` equality on `planItemInfo.key`; sort by `(day, display_name, issue_key)`. Tool `get_plans(ctx, team: str | None = None, users: list[str] | None = None, date_from: str = ..., date_to: str = ..., issue_key: str | None = None, include_absences: bool = True) -> str`.

- [ ] Tests: `test_get_plans_team_scope_sends_team_id`, `test_get_plans_user_scope_filters_by_key_and_drops_unknown_assignees`, `test_get_plans_marks_absence_from_summary_and_description`, `test_get_plans_issue_key_filter`, `test_get_plans_exclude_absences`, server test `test_get_plans_tool_rejects_long_window`. Run → fail → implement → pass → pre-commit.
- [ ] Commit `feat(tempo): add plan search tool`.

---

### Task 7: Worklogs + tool `tempo_get_worklogs`

**Files:** Create `src/mcp_atlassian/tempo/worklogs.py`; modify `tempo/__init__.py`, `servers/tempo.py`; test `tests/unit/tempo/test_worklogs.py`, server test.

**Interfaces:** `WorklogsMixin.get_worklogs(users: list[TempoUserRef], date_from: date, date_to: date, issue_key: str | None = None) -> list[TempoWorklog]` — `POST /rest/tempo-timesheets/4/worklogs/search` payload `{"from","to","worker": [u.key ...]}`; rows with unknown `worker` dropped; sort `(day, display_name, issue_key)`. Tool `get_worklogs(ctx, team, users, date_from, date_to, issue_key=None) -> str`.

- [ ] Tests: `test_get_worklogs_sends_user_keys`, `test_get_worklogs_maps_rows_and_filters_issue`, server test. Run → fail → implement → pass → pre-commit.
- [ ] Commit `feat(tempo): add worklog search tool`.

---

### Task 8: Workload aggregation + tool `tempo_get_workload`

**Files:** Create `src/mcp_atlassian/tempo/workload.py`; modify `tempo/__init__.py`, `servers/tempo.py`; test `tests/unit/tempo/test_workload.py`, server test.

**Interfaces:**
- Pure: `build_workload(users: list[TempoUserRef], roles: dict[str, str], schedules: dict[str, TempoUserSchedule], plans: list[TempoPlanItem], date_from: date, date_to: date, granularity: str, daily_limit_hours: float) -> TempoWorkloadReport`. Day math exactly as the spec: `capacity = min(required_hours, daily_limit_hours)`, `free = max(capacity − absence − planned, 0)`, `overbooked = max(planned + absence − capacity, 0)`; statuses in spec order (`non_working`, `overbooked`, `absent`, `free`, `full`, `partial`). Week/total buckets from `common.py`; bucket status: `overbooked` if any day overbooked, else `absent` if every day with capacity > 0 is absent, else by `free_hours`. `summary = {"overbooked": [{user, days}], "free_capacity": [{user, free_hours}] sorted desc (only > 0), "absent": [{user, days}]}` where `days` lists day labels (for `day` granularity) or period labels.
- `WorkloadMixin.get_workload(scope: TempoScope, date_from: date, date_to: date, granularity: str = "day", daily_limit_hours: float = 8.0) -> TempoWorkloadReport` — fetches schedules per user, plans once, calls `build_workload`. `granularity` ∉ {day, week, total} → `ValueError`.
- Tool `get_workload(ctx, team, users, date_from, date_to, granularity="day", role=None, daily_limit_hours=8.0) -> str`.

- [ ] Tests (pure, no HTTP): `test_weekend_with_plan_is_overbooked`, `test_holiday_without_plan_is_non_working`, `test_absence_day_status_absent`, `test_partial_full_free_statuses`, `test_daily_limit_lowers_capacity` (`required 8`, limit 6, planned 7 → overbooked 1), `test_week_buckets_sum_and_status`, `test_summary_lists`, `test_total_granularity`; mixin test `test_get_workload_fetches_schedule_per_user`; server test for tags/shape.
- [ ] Run → fail → implement → pass → pre-commit.
- [ ] Commit `feat(tempo): add workload report tool`.

---

### Task 9: Plan vs. actual + tool `tempo_get_plan_vs_actual`

**Files:** Modify `src/mcp_atlassian/tempo/workload.py`, `servers/tempo.py`; test `tests/unit/tempo/test_plan_vs_actual.py`, server test.

**Interfaces:** Pure `build_plan_vs_actual(users, plans (non-absence only), worklogs, date_from, date_to, granularity) -> TempoPlanVsActualReport`; per user × bucket: sums, `by_issue` sorted by `issue_key`, `logged_unplanned` = issues with logged > 0 and planned == 0, `planned_not_logged` = planned > 0 and logged == 0. `WorkloadMixin.get_plan_vs_actual(scope, date_from, date_to, granularity="week")`. Tool `get_plan_vs_actual(ctx, team, users, date_from, date_to, granularity="week") -> str`.

- [ ] Tests: `test_delta_per_issue_and_period`, `test_logged_unplanned_and_planned_not_logged`, `test_absence_plans_excluded`, mixin + server tests. Run → fail → implement → pass → pre-commit.
- [ ] Commit `feat(tempo): add plan vs actual tool`.

---

### Task 10: Docs, env example, counts

**Files:** Modify `scripts/generate_tool_docs.py` (import `tempo_mcp`, prefix `tempo_`, categories `tempo-teams`, `tempo-planning` + `CATEGORY_META`), `docs/tools/*.mdx` + `docs/tools-reference.mdx` (generated), `.env.example` (`TEMPO_ABSENCE_PATTERN`, `TEMPO_MAX_WINDOW_DAYS`, commented), `README.md` (one Tempo paragraph + toolset rows), `AGENTS.md` repository map (`tempo/` line), `tests/unit/utils/test_toolsets.py` (`test_tempo_tool_count == 7`).

- [ ] Run `uv run python scripts/generate_tool_docs.py` then `--check` → exit 0.
- [ ] `uv run pytest tests/unit -q` → PASS; `pre-commit run --all-files` clean.
- [ ] Commit `docs(tempo): document Tempo tools and settings`.

---

### Task 11: Assistant skill

**Files:** Create `skills/tempo-planning/SKILL.md`.

Content (anonymised examples only): frontmatter `name: tempo-planning`, `description` (when to use: team load, free slots, overbooking, absences, plan vs. actual, who is planned on an issue); tool-selection table (question → tool + key args); identifier and date conventions; 92-day window and how to split; absence heuristic caveat; recipe "plan a feature": `jira_search` for epic children → `tempo_get_workload(granularity="day")` → propose slots (planning itself is manual/next iteration); recipe "weekly plan vs. fact"; limits (read-only, no Jira group members, team names may carry trailing spaces).

- [ ] Write the file; run `grep -nEi` for forbidden identifiers → none.
- [ ] Commit `docs(tempo): add tempo-planning assistant skill`.

---

### Task 12: Branch verification

- [ ] `uv run pytest -q` (full unit suite) → PASS.
- [ ] `pre-commit run --all-files` → clean.
- [ ] `uv run python scripts/generate_tool_docs.py --check` → exit 0.
- [ ] `git grep -nEi '<forbidden identifiers>' feature/tempo-readonly -- . ':!docs/superpowers'` → nothing (run with the real list locally, never commit it).
- [ ] Final review of the diff against the spec.
