"""Create, update and delete Tempo Planner allocations with validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from mcp_atlassian.jira import JiraFetcher
from mcp_atlassian.models.tempo import (
    TempoAllocation,
    TempoAllocationDraft,
    TempoPlanConflict,
    TempoPlanItem,
    TempoPlanResult,
    TempoTeam,
    TempoTeamMember,
    TempoUserRef,
    TempoUserSchedule,
)

from .client import TempoClient
from .common import max_window_days, parse_window
from .fitting import (
    Placements,
    build_day_loads,
    find_conflicts,
    fit_placement,
    fixed_placement,
    group_allocations,
    plan_days,
)
from .scope import TempoScope
from .teams import team_summary

ALLOCATION_PATH = "/rest/tempo-planning/1/allocation"


class _Deps(Protocol):
    jira: JiraFetcher
    client: TempoClient

    def resolve_users(
        self, identifiers: list[str], known: list[TempoTeamMember] | None = None
    ) -> list[TempoUserRef]: ...

    def resolve_team(self, team: str) -> TempoTeam: ...

    def get_user_memberships(self, user: TempoUserRef) -> list[TempoTeam]: ...

    def get_user_schedule(
        self, user: TempoUserRef, date_from: date, date_to: date
    ) -> TempoUserSchedule: ...

    def get_plans(
        self,
        scope: TempoScope,
        date_from: date,
        date_to: date,
        issue_key: str | None = None,
        include_absences: bool = True,
    ) -> list[TempoPlanItem]: ...


@dataclass
class _Prepared:
    """A validated plan: the report plus the request bodies to write it."""

    result: TempoPlanResult
    bodies: list[dict[str, Any]] = field(default_factory=list)
    placements: Placements = field(default_factory=dict)


@dataclass(frozen=True)
class _Target:
    user: TempoUserRef
    issue_id: int
    issue_key: str
    summary: str
    team: TempoTeam


def _positive(value: float | None, name: str) -> float:
    if value is None or value <= 0:
        raise ValueError(f"{name} must be a positive number of hours")
    return float(value)


class PlanWriteMixin:
    """Validated writes to Tempo Planner."""

    # ----- lookups -----------------------------------------------------

    def default_team(self: _Deps, user: TempoUserRef) -> TempoTeam:
        """The user's only Tempo team; several or none is an error."""
        teams = self.get_user_memberships(user)
        if len(teams) == 1:
            return teams[0]
        if not teams:
            raise ValueError(
                f"User '{user.display_name or user.username}' has no Tempo team; "
                "pass 'team' explicitly"
            )
        names = ", ".join(f"{t.name.strip()} (id {t.id})" for t in teams)
        raise ValueError(
            f"User '{user.display_name or user.username}' belongs to several Tempo "
            f"teams: {names}. Pass 'team' to choose the plan scope"
        )

    def issue_ref(self: _Deps, issue_key: str) -> tuple[int, str, str]:
        """``(issue id, key, summary)`` from Jira."""
        data: Any = self.jira.jira.get_issue(issue_key, fields="id,summary")
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError(f"Issue '{issue_key}' not found in Jira")
        fields = data.get("fields") or {}
        return (
            int(data["id"]),
            str(data.get("key") or issue_key).upper(),
            str(fields.get("summary") or ""),
        )

    def _target(
        self: _Deps,
        user: str | TempoUserRef,
        issue_key: str,
        team: str | TempoTeam | None,
    ) -> _Target:
        user_ref = (
            user if isinstance(user, TempoUserRef) else self.resolve_users([user])[0]
        )
        issue_id, key, summary = PlanWriteMixin.issue_ref(self, issue_key)
        if isinstance(team, TempoTeam):
            resolved_team = team
        elif team:
            resolved_team = self.resolve_team(team)
        else:
            resolved_team = PlanWriteMixin.default_team(self, user_ref)
        return _Target(user_ref, issue_id, key, summary, resolved_team)

    # ----- validation ----------------------------------------------------

    def _prepare(
        self: _Deps,
        target: _Target,
        date_from: date,
        date_to: date | None,
        *,
        hours_per_day: float | None,
        total_hours: float | None,
        description: str,
        allow_overbooking: bool,
        allow_absence_days: bool,
        daily_limit_hours: float,
        extra_load: Placements | None = None,
        exclude_allocation_id: int | None = None,
    ) -> _Prepared:
        if (hours_per_day is None) == (total_hours is None):
            raise ValueError("Provide exactly one of 'hours_per_day' or 'total_hours'")
        if daily_limit_hours <= 0:
            raise ValueError("daily_limit_hours must be a positive number of hours")
        if hours_per_day is not None:
            mode = "fixed"
            hours = _positive(hours_per_day, "hours_per_day")
            if date_to is None:
                raise ValueError("date_to is required when hours_per_day is given")
        else:
            mode = "fit"
            hours = _positive(total_hours, "total_hours")
            if date_to is None:
                date_to = date_from + timedelta(days=max_window_days() - 1)
        start, end = parse_window(date_from.isoformat(), date_to.isoformat())

        schedule = self.get_user_schedule(target.user, start, end)
        plans = self.get_plans(TempoScope(team=None, users=[target.user]), start, end)
        if exclude_allocation_id is not None:
            plans = [p for p in plans if p.allocation_id != exclude_allocation_id]
        loads = build_day_loads(schedule, plans, start, end, daily_limit_hours)
        for load in loads:
            if extra_load and load.day in extra_load:
                load.planned = round(load.planned + extra_load[load.day], 2)

        unplaced = 0.0
        if mode == "fixed":
            placements = fixed_placement(loads, hours)
        else:
            placements, unplaced = fit_placement(
                loads, hours, allow_absence_days=allow_absence_days
            )
        conflicts = find_conflicts(
            loads,
            placements,
            mode,
            allow_overbooking=allow_overbooking,
            allow_absence_days=allow_absence_days,
            unplaced=unplaced,
        )
        drafts = group_allocations(loads, placements)
        result = TempoPlanResult(
            ok=not conflicts,
            written=False,
            mode=mode,
            user=target.user,
            issue={
                "key": target.issue_key,
                "id": target.issue_id,
                "summary": target.summary,
            },
            team=team_summary(target.team),
            days=plan_days(loads, placements),
            conflicts=conflicts,
            allocations=drafts,
        )
        bodies = [
            TempoAllocation(
                user=target.user,
                issue_id=target.issue_id,
                team_id=target.team.id,
                start=draft.start,
                end=draft.end,
                seconds_per_day=round(draft.hours_per_day * 3600),
                description=description,
            ).to_request_body()
            for draft in drafts
        ]
        return _Prepared(result=result, bodies=bodies, placements=placements)

    def _write(self: _Deps, prepared: _Prepared) -> None:
        for draft, body in zip(
            prepared.result.allocations, prepared.bodies, strict=True
        ):
            created = TempoAllocation.from_api_response(
                self.client.post(ALLOCATION_PATH, body)
            )
            draft.allocation_id = created.id
        prepared.result.written = True

    # ----- public operations ---------------------------------------------

    def plan_work(
        self: _Deps,
        user: str | TempoUserRef,
        issue_key: str,
        date_from: date,
        date_to: date | None,
        hours_per_day: float | None = None,
        total_hours: float | None = None,
        description: str = "",
        team: str | TempoTeam | None = None,
        *,
        dry_run: bool = True,
        allow_overbooking: bool = False,
        allow_absence_days: bool = False,
        daily_limit_hours: float = 8.0,
        extra_load: Placements | None = None,
    ) -> TempoPlanResult:
        """Check (and unless ``dry_run``) write planned hours for one issue.

        ``hours_per_day`` plans a fixed amount on every working day of
        ``date_from..date_to``; ``total_hours`` fits the hours into free
        capacity from ``date_from`` on. Nothing is written when conflicts
        remain.
        """
        target = PlanWriteMixin._target(self, user, issue_key, team)
        prepared = PlanWriteMixin._prepare(
            self,
            target,
            date_from,
            date_to,
            hours_per_day=hours_per_day,
            total_hours=total_hours,
            description=description,
            allow_overbooking=allow_overbooking,
            allow_absence_days=allow_absence_days,
            daily_limit_hours=daily_limit_hours,
            extra_load=extra_load,
        )
        if not dry_run and prepared.result.ok:
            PlanWriteMixin._write(self, prepared)
        return prepared.result

    def bulk_plan_work(
        self: _Deps,
        items: list[dict[str, Any]],
        team: str | None = None,
        *,
        dry_run: bool = True,
        atomic: bool = True,
        allow_overbooking: bool = False,
        allow_absence_days: bool = False,
        daily_limit_hours: float = 8.0,
    ) -> dict[str, Any]:
        """Check and write several plans; later items see earlier placements."""
        resolved_team = self.resolve_team(team) if team else None
        extra: dict[str, Placements] = {}
        prepared: list[_Prepared | None] = []
        results: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            try:
                user_ref = self.resolve_users([str(item.get("user") or "")])[0]
                target = PlanWriteMixin._target(
                    self, user_ref, str(item.get("issue_key") or ""), resolved_team
                )
                date_from = date.fromisoformat(str(item.get("date_from") or ""))
                date_to_raw = item.get("date_to")
                date_to = date.fromisoformat(str(date_to_raw)) if date_to_raw else None
                prep = PlanWriteMixin._prepare(
                    self,
                    target,
                    date_from,
                    date_to,
                    hours_per_day=item.get("hours_per_day"),
                    total_hours=item.get("total_hours"),
                    description=str(item.get("description") or ""),
                    allow_overbooking=allow_overbooking,
                    allow_absence_days=allow_absence_days,
                    daily_limit_hours=daily_limit_hours,
                    extra_load=extra.get(user_ref.key),
                )
            except (ValueError, KeyError, TypeError) as exc:
                prepared.append(None)
                results.append(
                    {
                        "index": index,
                        "status": "skipped",
                        "ok": False,
                        "written": False,
                        "conflicts": [
                            TempoPlanConflict(
                                type="invalid", message=str(exc)
                            ).to_simplified_dict()
                        ],
                    }
                )
                continue
            prepared.append(prep)
            if prep.result.ok:
                load = extra.setdefault(target.user.key, {})
                for day, hours in prep.placements.items():
                    load[day] = round(load.get(day, 0.0) + hours, 2)
            entry = prep.result.to_simplified_dict()
            entry["index"] = index
            entry["status"] = "planned" if prep.result.ok else "skipped"
            results.append(entry)

        all_ok = all(p is not None and p.result.ok for p in prepared)
        written = False
        if not dry_run and (all_ok or not atomic):
            for prep, entry in zip(prepared, results, strict=True):
                if prep is None or not prep.result.ok:
                    continue
                PlanWriteMixin._write(self, prep)
                entry.update(prep.result.to_simplified_dict())
                entry["status"] = "created"
                written = True
        return {"ok": all_ok, "written": written, "results": results}

    def update_plan(
        self: _Deps,
        allocation_id: int,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        hours_per_day: float | None = None,
        description: str | None = None,
        dry_run: bool = True,
        allow_overbooking: bool = False,
        allow_absence_days: bool = False,
        daily_limit_hours: float = 8.0,
    ) -> TempoPlanResult:
        """Change dates, hours or description of an allocation after validation."""
        current = TempoAllocation.from_api_response(
            self.client.get(f"{ALLOCATION_PATH}/{allocation_id}")
        )
        if not current.id:
            raise ValueError(f"Allocation {allocation_id} not found")
        user_ref = self.resolve_users([current.user.username or current.user.key])[0]
        target = _Target(
            user=user_ref,
            issue_id=current.issue_id,
            issue_key=current.issue_key,
            summary=current.summary,
            team=self.resolve_team(str(current.team_id)),
        )
        new_from = date_from or date.fromisoformat(current.start)
        new_to = date_to or date.fromisoformat(current.end)
        new_hours = (
            hours_per_day if hours_per_day is not None else current.hours_per_day
        )
        new_description = (
            description if description is not None else current.description
        )
        prepared = PlanWriteMixin._prepare(
            self,
            target,
            new_from,
            new_to,
            hours_per_day=new_hours,
            total_hours=None,
            description=new_description,
            allow_overbooking=allow_overbooking,
            allow_absence_days=allow_absence_days,
            daily_limit_hours=daily_limit_hours,
            exclude_allocation_id=allocation_id,
        )
        result = prepared.result
        result.allocation_id = allocation_id
        result.before = {
            "start": current.start,
            "end": current.end,
            "hours_per_day": current.hours_per_day,
            "description": current.description,
        }
        # Tempo stores one range per allocation; the update keeps that shape.
        result.allocations = [
            TempoAllocationDraft(
                allocation_id=allocation_id,
                start=new_from.isoformat(),
                end=new_to.isoformat(),
                hours_per_day=round(new_hours, 2),
                total_hours=round(
                    new_hours * sum(d.added_hours > 0 for d in result.days), 2
                ),
                working_days=sum(d.added_hours > 0 for d in result.days),
            )
        ]
        if not dry_run and result.ok:
            body = {
                "id": allocation_id,
                **TempoAllocation(
                    user=user_ref,
                    issue_id=current.issue_id,
                    team_id=current.team_id,
                    start=new_from.isoformat(),
                    end=new_to.isoformat(),
                    seconds_per_day=round(new_hours * 3600),
                    include_non_working_days=current.include_non_working_days,
                    description=new_description,
                ).to_request_body(),
            }
            self.client.put(f"{ALLOCATION_PATH}/{allocation_id}", body)
            result.written = True
        return result

    def delete_plan(self: _Deps, allocation_id: int) -> TempoAllocation:
        """Delete an allocation and return what was deleted."""
        current = TempoAllocation.from_api_response(
            self.client.get(f"{ALLOCATION_PATH}/{allocation_id}")
        )
        if not current.id:
            raise ValueError(f"Allocation {allocation_id} not found")
        self.client.delete(f"{ALLOCATION_PATH}/{allocation_id}")
        return current
