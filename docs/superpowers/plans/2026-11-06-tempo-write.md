# Tempo plan-writing tools — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four write tools (`tempo_plan_work`, `tempo_bulk_plan_work`, `tempo_update_plan`, `tempo_delete_plan`) that validate against schedule, absences and existing plans and default to dry run.

**Architecture:** Pure placement/validation in `tempo/fitting.py`; `PlanWriteMixin` in `tempo/writing.py` orchestrates reads (schedule, plans, memberships, issue id) and writes (`POST/PUT/DELETE /rest/tempo-planning/1/allocation`); tools tagged `write` in toolset `tempo_write`, guarded by `check_write_access`.

**Tech Stack:** as the read-only iteration.

**Spec:** `docs/superpowers/specs/2026-11-06-tempo-write-design.md`

## Global Constraints

Same as `2026-11-05-tempo-readonly.md`: no identifying data, `uv`, Ruff+mypy (hook args), Google docstrings, TDD, commit per task, docs regenerated via `scripts/generate_tool_docs.py`.

## Review Focus

1. `dry_run=true` (default) must never issue POST/PUT/DELETE, even when `ok`. (Task 3)
2. Fixed mode over a range containing only weekends → conflict `non_working`, no write. (Task 2)
3. Fit mode respects `allow_absence_days=false` by skipping absence days, and reports `does_not_fit` with the unplaced hours. (Task 2)
4. Bulk with `atomic=true` and one conflicting item writes nothing. (Task 3)
5. Update excludes the allocation's own existing rows from the load, so re-saving an unchanged allocation reports no overbooking. (Task 3)

---

### Task 1: Models, client verbs, memberships

**Files:** create `src/mcp_atlassian/models/tempo/allocation.py`; modify `models/tempo/__init__.py`, `tempo/client.py` (`put`, `delete`), `tempo/teams.py` (`get_user_memberships`), `tests/unit/tempo/conftest.py` (fake `put`/`delete`); tests `tests/unit/tempo/test_models.py`, `test_client.py`, `test_teams.py`.

**Produces:**
- `TempoAllocation(id: int, user: TempoUserRef, issue_key: str, issue_id: int, summary: str, team_id: int, start: str, end: str, seconds_per_day: int, hours_per_day: float, include_non_working_days: bool, description: str)`; `from_api_response(data)` (assignee key→`user.username`, `userKey`→`user.key`); `to_request_body() -> dict` producing the POST/PUT body; `to_simplified_dict()`.
- `TempoPlanDay(day, capacity_hours, planned_hours, absence_hours, added_hours, free_after_hours, status_after)`, `TempoPlanConflict(day: str | None, type: str, message: str)`, `TempoAllocationDraft(allocation_id: int | None, start, end, hours_per_day, total_hours, working_days)`, `TempoPlanResult(ok, written, mode, user, issue: dict, team: dict, days, conflicts, allocations, allocation_id: int | None = None, before: dict | None = None)` with `to_simplified_dict()`.
- `TempoClient.put(path, payload) -> Any`, `TempoClient.delete(path) -> Any`.
- `TeamsMixin.get_user_memberships(user: TempoUserRef) -> list[TempoTeam]` via `GET /rest/tempo-teams/2/user/{username or key}/memberships`.
- `FakeTempoClient.put/delete` recording calls.

- [ ] Tests → RED → implement → GREEN → commit `feat(tempo): add allocation models, client verbs and memberships`.

---

### Task 2: Pure fitting and validation

**Files:** create `src/mcp_atlassian/tempo/fitting.py`; test `tests/unit/tempo/test_fitting.py`.

**Produces:**
- `@dataclass DayLoad(day: date, capacity: float, planned: float, absence: float)`; `DayLoad.free -> float`.
- `build_day_loads(schedule: TempoUserSchedule | None, plans: list[TempoPlanItem], date_from, date_to, daily_limit_hours) -> list[DayLoad]` (same math as workload: capacity = min(norm, limit)).
- `fixed_placement(loads, hours_per_day) -> dict[date, float]` — every day with capacity > 0 gets `hours_per_day`.
- `fit_placement(loads, total_hours, allow_absence_days) -> tuple[dict[date, float], float]` — greedy, returns placements and unplaced hours.
- `find_conflicts(loads, placements, mode, allow_overbooking, allow_absence_days, unplaced=0.0) -> list[TempoPlanConflict]` — types `non_working`, `absent`, `overbooked`, `does_not_fit`.
- `group_allocations(loads, placements) -> list[TempoAllocationDraft]`.
- `plan_days(loads, placements) -> list[TempoPlanDay]` (status_after via `_DayFigures`-equivalent rules).

- [ ] Tests: fixed over weekend only → `non_working`; fixed with absence day → `absent` unless allowed; fixed overbooking → `overbooked` unless allowed; fit skips holiday and absence; fit grouping keeps a weekend inside one run but splits on a partially free day; fit does not fit → unplaced and conflict; decimals (1.25h) round-trip. RED → GREEN → commit `feat(tempo): add plan fitting and validation`.

---

### Task 3: PlanWriteMixin

**Files:** create `src/mcp_atlassian/tempo/writing.py`; modify `tempo/__init__.py`; test `tests/unit/tempo/test_writing.py`.

**Produces:**
- `PlanWriteMixin.default_team(user) -> TempoTeam` (memberships: 1 → it; else ValueError listing names).
- `issue_ref(issue_key) -> tuple[int, str]` via `self.jira.jira.get_issue(issue_key, fields="id,summary")`.
- `plan_work(user: str, issue_key: str, date_from: date, date_to: date | None, hours_per_day: float | None, total_hours: float | None, description: str = "", team: str | None = None, dry_run: bool = True, allow_overbooking=False, allow_absence_days=False, daily_limit_hours=8.0, extra_load: dict[date, float] | None = None, exclude_allocation_id: int | None = None) -> TempoPlanResult`.
- `bulk_plan_work(items: list[dict], team, dry_run, atomic, allow_*, daily_limit_hours) -> dict` per spec.
- `update_plan(allocation_id, date_from=None, date_to=None, hours_per_day=None, description=None, dry_run=True, allow_*, daily_limit_hours) -> TempoPlanResult`.
- `delete_plan(allocation_id) -> TempoAllocation`.

- [ ] Tests: dry run makes no POST; `dry_run=False` posts exact body (assignee username, planItem id, scope team, seconds); fit creates two allocations; conflict → no write, `written False`; bulk atomic stops all; bulk non-atomic writes the good one and skips the other; second bulk item sees first item's load; update excludes own rows and PUTs full body; delete GETs then DELETEs; default team from memberships; ambiguous memberships raise. RED → GREEN → commit `feat(tempo): add plan writing operations`.

---

### Task 4: Tools, toolset, docs, skill

**Files:** modify `servers/tempo.py` (4 tools, `@check_write_access`), `utils/toolsets.py` (`tempo_write`), `scripts/generate_tool_docs.py` (`tempo-write` category), template/README/.env.example/docs.json counts, `tests/unit/servers/test_tempo_server.py`, `tests/unit/utils/test_toolsets.py` (28 toolsets, 11 tempo tools), `skills/tempo-planning/SKILL.md`.

- [ ] Server tests: tags `write` + `toolset:tempo_write`; `READ_ONLY_MODE` blocks (reuse the pattern from Jira write-tool tests); argument plumbing for each tool. RED → GREEN; regenerate docs; `--check`; full unit suite; commit `feat(tempo): add plan writing tools` and `docs(tempo): document write tools`.

---

### Task 5: Verification
- [ ] `uv run pytest tests/unit -q`, `generate_tool_docs.py --check`, identifying-data scan, final review.
