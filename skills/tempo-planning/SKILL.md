---
name: tempo-planning
description: Use when answering resource-planning questions or planning work in Tempo on Jira Server/Data Center through the tempo_* MCP tools — team load, free slots, overbooking, absences, who is planned on an issue, plan vs. logged hours, putting issues into people's plans, moving or deleting planned time.
---

# Tempo planning

`tempo_*` tools over Tempo Timesheets + Tempo Planner (Server/DC). They reuse
the Jira connection. Reading tools never write; the plan-writing tools
(`tempo_plan_work`, `tempo_bulk_plan_work`, `tempo_update_plan`,
`tempo_delete_plan`) write to Tempo Planner only, never to Jira issues or
worklogs, and are blocked in read-only mode.

## Pick the tool

| Question | Tool | Key arguments |
| --- | --- | --- |
| Which teams exist / what is the team called? | `tempo_list_teams` | `query` |
| Who is on the team, in which role? | `tempo_get_team_members` | `team`, `role`, `active_only` |
| What is planned for a person / team? Who is planned on PROJ-123? | `tempo_get_plans` | `team` or `users`, dates, `issue_key`, `include_absences` |
| Which days are working days / holidays for a person? | `tempo_get_user_schedule` | `users`, dates |
| What was logged? | `tempo_get_worklogs` | `team` or `users`, dates, `issue_key` |
| How loaded is the team, who is free, who is overbooked, who is absent? | `tempo_get_workload` | `team` or `users`, dates, `granularity`, `role`, `daily_limit_hours` |
| Plan vs. fact per week | `tempo_get_plan_vs_actual` | `team` or `users`, dates, `granularity` |
| Put an issue into someone's plan | `tempo_plan_work` | `user`, `issue_key`, `date_from`, `date_to`, `hours_per_day` or `total_hours`, `dry_run` |
| Plan several issues / a whole feature | `tempo_bulk_plan_work` | `items`, `atomic`, `dry_run` |
| Move, stretch or change hours of a plan | `tempo_update_plan` | `allocation_id`, new dates / hours, `dry_run` |
| Remove a plan | `tempo_delete_plan` | `allocation_id` |

Prefer the aggregate tools (`tempo_get_workload`, `tempo_get_plan_vs_actual`)
for anything that involves sums or comparisons; use `tempo_get_plans` /
`tempo_get_worklogs` only when the user needs the individual rows.

## Conventions

- **Scope**: pass exactly one of `team` or `users`. `team` accepts an id or a
  name (case-insensitive; trailing spaces in Tempo team names are ignored).
  `users` accepts usernames, user keys, display names or e-mails; each must
  resolve to exactly one Jira user, otherwise the tool returns candidates —
  ask the user to pick one.
- **Role filter**: `role` is a substring match on the Tempo team role
  (e.g. `automation` matches `QA Automation`). Roles live on the membership,
  not on the user, so `role` only works together with `team`.
- **Dates**: `YYYY-MM-DD`, `date_to` inclusive, at most 92 days per call
  (`TEMPO_MAX_WINDOW_DAYS`). For longer ranges call per month and merge.
- **Granularity**: `day`, `week` (ISO weeks, `2026-W12`) or `total`.
- **Hours** are decimal (`1.5`), rounded to two places.
- Every user in a response is `{key, username, display_name}`; refer to
  people by `display_name` in answers.

## Reading `tempo_get_workload`

Per user and period: `capacity_hours` (schedule norm capped by
`daily_limit_hours`), `planned_hours`, `absence_hours`, `free_hours`,
`overbooked_hours`, `status` and the planned `items`.

| `status` | Meaning |
| --- | --- |
| `non_working` | weekend or holiday, nothing planned |
| `free` | working day, nothing planned |
| `partial` | some free hours left |
| `full` | exactly at capacity |
| `overbooked` | planned + absence above capacity, or anything planned on a non-working day |
| `absent` | the day is covered by an absence plan item |

`summary.overbooked`, `summary.free_capacity` (sorted by free hours, desc)
and `summary.absent` are ready-made answers for "who is overbooked / free /
away". Quote them instead of re-adding the periods yourself.

**Absences are inferred**, not structured: a plan item counts as an absence
when its summary or description matches `TEMPO_ABSENCE_PATTERN`
(by default vacation / sick leave / day off wording in English and Russian).
Say "looks like vacation (from plan item PROJ-9)" rather than stating it as
fact, and mention when a suspicious item (e.g. "Trip") was not caught.

## Recipes

**Team load this week**
1. `tempo_get_workload(team="Platform QA", date_from=<Mon>, date_to=<Sun>, granularity="day")`.
2. Answer with the summary lists first, then a short per-person line
   (planned / capacity, free hours). Mention holidays from `non_working`
   days only if they matter.

**Find people with at most N hours per day**
`tempo_get_workload(..., granularity="day")`, then keep periods whose
`planned_hours <= N` and `status` is not `non_working` / `absent`.

**Compare two roles** (e.g. "Backend" vs "Frontend")
Call `tempo_get_workload` twice with the same team and dates and different
`role` values; compare `summary.free_capacity` and the totals.

**Who is planned on an issue**
`tempo_get_plans(team=..., issue_key="PROJ-123")` — or with `users` if the
team is unknown. Each row has `user`, `day`, `planned_hours`, `issue_url`.

**Weekly plan vs. fact**
`tempo_get_plan_vs_actual(team=..., granularity="week")`. Report
`delta_hours` per person, then `planned_not_logged` (planned work nobody
logged) and `logged_unplanned` (unplanned work that consumed time).
Plans made on a whole project (`plan_type: PROJECT`) never match issue
worklogs; mention them separately instead of calling them "not logged".

**Plan a feature into free slots**
1. Collect the issues with Jira tools (`jira_search`, `jira_get_issue`); keep
   `timeoriginalestimate`, links and blockers. Issues without an estimate go
   to a separate list for the user — do not plan them.
2. Order the issues so that blockers come before what they block.
3. `tempo_bulk_plan_work(items=[{user, issue_key, date_from,
   total_hours: <estimate in hours>}, ...])` — dry run, `atomic=true`. Items are
   placed in order, so each starts in the free hours left by the previous
   ones. For a dependency, set the dependent item's `date_from` after the
   blocker's last planned day from the dry-run result.
4. Show the plan per person and day, plus every conflict. On `does_not_fit`,
   offer a later `date_to`, another assignee, or fewer hours.
5. After the user confirms, call again with `dry_run=false`. Report the
   created `allocation_id`s.
6. Assigning the issue in Jira is a separate step (`jira_update_issue` /
   `jira_assign_issue`) — do it only if the user asked for it.

## Writing plans

- **Always dry run first** (the default). Show the user the `days` table
  and `conflicts`, then repeat with `dry_run=false` only after an explicit
  "yes". Never set `dry_run=false` on the first call.
- **Modes.** `hours_per_day` + `date_to`: fixed hours on every working day
  of the range (Tempo skips weekends and holidays itself). `total_hours`:
  fit the hours into free capacity from `date_from`, earliest first, up to
  `date_to` if given; the result may be several allocations.
- **Conflicts block the write**: `overbooked` (above capacity),
  `absent` (vacation / sick leave that day), `non_working` (range has no
  working day), `does_not_fit` (fit mode ran out of days), `invalid` (bulk
  item could not be read). Return them to the user as they are.
- **Overbooking and absence days are opt-in.** Set `allow_overbooking` or
  `allow_absence_days` only after the user explicitly accepts the conflict
  shown in the dry run; then list the people whose schedule now needs
  adjusting (from `days` with `status_after: overbooked`).
- **Team scope.** Every plan belongs to a Tempo team. If the user is in one
  team it is used automatically; otherwise the tool returns the list —
  ask which team, then pass `team`.
- **Plan a task for a whole team at N hours each**:
  `tempo_get_team_members(team)` → `tempo_bulk_plan_work` with one item per
  member (`hours_per_day=N`, same dates), `atomic=false` if the user wants
  the conflict-free part written anyway.
- **Edit / delete** need `allocation_id` — take it from `tempo_get_plans`.
  Confirm deletions with the user; `tempo_delete_plan` has no dry run.
- `daily_limit_hours` (default 8) lowers capacity for validation, e.g. 6 for
  a focus-factor plan.

## Limits

- Worklogs are read-only; only Tempo Planner allocations can be written.
- Plans are always issue plans; project-level plans cannot be created.
- Jira group membership is not available (`GET /rest/api/2/group/member`
  needs Jira administrator rights on Server/DC); use Tempo teams instead.
- Plan search is filtered server-side by team only; `users`-scoped calls
  fetch all plans in the window and filter locally, so keep windows short.
- Team members are chosen by membership dates within the requested window,
  so past windows include people who have since left the team.
- Membership `availability` (e.g. 50%) is reported but does not reduce
  capacity.
- Tempo Cloud is not supported by these tools.
