# Tempo (Server/DC) plan-writing tools — design

Builds on `2026-11-05-tempo-readonly-design.md`.

## Goal

Let an assistant put work into Tempo Planner safely: one allocation, a
batch of allocations, an edit, a deletion — always validated against the
person's schedule, absences and existing plans, with a dry run by default so
the human confirms before anything is written.

## Verified API surface (Tempo Planner Server/DC)

| Endpoint | Notes |
| --- | --- |
| `POST /rest/tempo-planning/1/allocation` | body `{assignee:{key:<username>,type:"user"}, planItem:{id:<issue id>,type:"ISSUE"}, scope:{id:<team id>,type:"team"}, start, end, secondsPerDay, includeNonWorkingDays:false, description}`; returns the allocation with `id`. `scope` is **required** and must be a team; membership is not enforced. |
| `GET /rest/tempo-planning/1/allocation/{id}` | same shape plus `commitment`, `createdBy`, `seconds` |
| `PUT /rest/tempo-planning/1/allocation/{id}` | full body (same as POST, plus `id`) |
| `DELETE /rest/tempo-planning/1/allocation/{id}` | 204 |
| `GET /rest/tempo-teams/2/user/{username}/memberships` | `[{team:{id,name}, role:{name}, availability}]` — default scope |
| `GET /rest/api/2/issue/{key}?fields=id` | issue id for `planItem.id` |

Tempo spreads `secondsPerDay` over the working days of `start..end`
(`includeNonWorkingDays:false`); `plan/search` rows carry `allocationId`.

## Tools (all `write`, toolset `tempo_write`, `default=False`)

Common: `user` and `issue_key` as in the read-only tools; `team` optional —
when omitted, the user's Tempo memberships decide: exactly one → that team,
none/several → `ValueError` listing the teams. Dates `YYYY-MM-DD`, inclusive,
window ≤ `TEMPO_MAX_WINDOW_DAYS`. `daily_limit_hours` (default 8) caps daily
capacity exactly as in `tempo_get_workload`. Hours accept decimals; seconds
are rounded to the nearest integer.

### `tempo_plan_work`

Input: `user`, `issue_key`, `date_from`, `date_to?`, `hours_per_day?`,
`total_hours?`, `description?`, `team?`, `dry_run=true`,
`allow_overbooking=false`, `allow_absence_days=false`, `daily_limit_hours=8`.

Exactly one of `hours_per_day` / `total_hours`:

- **fixed** (`hours_per_day`, requires `date_to`): one allocation
  `start=date_from, end=date_to, secondsPerDay=hours_per_day*3600`. Each
  working day in the range receives `hours_per_day`.
- **fit** (`total_hours`): greedy fill from `date_from` to `date_to`
  (default: `date_from` + `TEMPO_MAX_WINDOW_DAYS` − 1). Per day
  `free = capacity − absence − planned`; non-working days and days with
  `free ≤ 0` are skipped; absence days are skipped unless
  `allow_absence_days`. Hours placed on a day = `min(free, remaining)`.
  Remaining hours at the deadline → conflict `does_not_fit`. Consecutive
  placements with equal hours become one allocation (non-working days inside
  a run do not break it; a working day with a different amount does).

Validation (both modes), per day with `capacity > 0`:

- `absent` if the day carries an absence plan and `allow_absence_days` is
  false (fixed mode only — fit skips such days);
- `overbooked` if `planned + absence + added > capacity` and
  `allow_overbooking` is false;
- fixed mode with no working day in the range → `non_working`.

`existing plans` = user-scoped plan search over the window (all teams).

Output:

```
{
  "ok": bool, "written": bool, "mode": "fixed" | "fit",
  "user", "issue": {key, id, summary}, "team": {id, name},
  "days": [{day, capacity_hours, planned_hours, absence_hours, added_hours,
            free_after_hours, status_after}],
  "conflicts": [{day?, type, message}],
  "allocations": [{allocation_id?, start, end, hours_per_day, total_hours,
                   working_days}]
}
```

`ok` = no conflicts. `dry_run=true` never writes. `dry_run=false` writes only
when `ok`; otherwise returns the report with `written=false`.

### `tempo_bulk_plan_work`

Input: `items: [{user, issue_key, date_from, date_to?, hours_per_day?,
total_hours?, description?}]`, `team?`, `dry_run=true`, `atomic=true`,
`allow_overbooking`, `allow_absence_days`, `daily_limit_hours`.

Items are validated in order; each accepted item's placements are added to
the in-memory load before the next item is checked, so a fit item sees the
slots an earlier item took. `atomic=true`: any conflict → nothing is
written, every item reported. `atomic=false`: conflict-free items are
written, others reported as `skipped`. Output: `{"ok", "written",
"results": [<plan_work output> + {"index", "status": "planned" |
"created" | "skipped"}]}`.

### `tempo_update_plan`

Input: `allocation_id`, `date_from?`, `date_to?`, `hours_per_day?`,
`description?`, `dry_run=true`, `allow_overbooking`, `allow_absence_days`,
`daily_limit_hours`.

`GET` the allocation, overlay the given fields, validate as fixed mode with
the allocation's own rows excluded from existing plans (`allocationId`),
then `PUT` the full body. Output as `tempo_plan_work` plus
`"allocation_id"` and `"before": {start, end, hours_per_day, description}`.

### `tempo_delete_plan`

Input: `allocation_id`. `GET` then `DELETE`. Output
`{"deleted": true, "allocation": {...}}`. No dry run.

## Architecture

```
src/mcp_atlassian/tempo/
  fitting.py     pure: DayLoad, fixed_placement, fit_placement, find_conflicts,
                 group_allocations
  writing.py     PlanWriteMixin: plan_work, bulk_plan_work, update_plan,
                 delete_plan, default_team, issue_ref
  client.py      + put, delete
  teams.py       + get_user_memberships
src/mcp_atlassian/models/tempo/allocation.py
                 TempoAllocation, TempoPlanDay, TempoPlanConflict,
                 TempoAllocationDraft, TempoPlanResult
servers/tempo.py + 4 tools (@check_write_access)
utils/toolsets.py + tempo_write
```

`PlanWriteMixin` depends on `resolve_users`, `get_user_schedule`,
`get_plans` (user scope) and the Jira fetcher for issue ids; all HTTP goes
through `TempoClient`. The write tools reuse `_DayFigures` semantics via
`DayLoad` so dry-run numbers match `tempo_get_workload`.

Errors: Tempo validation failures (HTTP 400 with `errors`) surface as
`ValueError` with the Tempo message; 403 as auth error.

## Testing

Unit only, anonymised fixtures. `fitting.py` is tested exhaustively (fixed
over weekend, absence, overbooking with/without allow flags, fit across a
holiday, fit grouping with a non-working gap, fit not fitting, decimals).
Mixin tests use `FakeTempoClient` and assert the exact POST/PUT bodies and
that `dry_run` makes no write call. Server tests check tags (`write`,
`toolset:tempo_write`), `READ_ONLY_MODE` blocking, and argument plumbing.
Docs regenerated; counts updated; skill extended with the write recipes.
