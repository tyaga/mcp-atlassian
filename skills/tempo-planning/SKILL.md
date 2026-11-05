---
name: tempo-planning
description: Use when answering resource-planning questions from Tempo on Jira Server/Data Center through the tempo_* MCP tools — team load, free slots, overbooking, absences, who is planned on an issue, plan vs. logged hours.
---

# Tempo planning

Read-only `tempo_*` tools over Tempo Timesheets + Tempo Planner (Server/DC).
They reuse the Jira connection; nothing is written to Jira or Tempo.

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

**Plan a feature into free slots** (planning itself is manual for now)
1. Collect the issues with Jira tools (`jira_search`, `jira_get_issue`); keep
   `timeoriginalestimate`, links and blockers; list issues without an
   estimate separately.
2. `tempo_get_workload(users=[assignee], ..., granularity="day")` for the
   candidate window.
3. Fill `free_hours` day by day in dependency order; never place work on
   `non_working` or `absent` days; stop and ask before exceeding capacity.
4. Present the proposed schedule as a table; the user enters it into Tempo.

## Limits

- Read-only: no tools create, move or delete plans or worklogs.
- Jira group membership is not available (`GET /rest/api/2/group/member`
  needs Jira administrator rights on Server/DC); use Tempo teams instead.
- Plan search is filtered server-side by team only; `users`-scoped calls
  fetch all plans in the window and filter locally, so keep windows short.
- Team members are chosen by membership dates within the requested window,
  so past windows include people who have since left the team.
- Membership `availability` (e.g. 50%) is reported but does not reduce
  capacity.
- Tempo Cloud is not supported by these tools.
