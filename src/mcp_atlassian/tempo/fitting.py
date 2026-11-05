"""Placement of planned hours onto days and validation against the load."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from mcp_atlassian.models.tempo import (
    TempoAllocationDraft,
    TempoPlanConflict,
    TempoPlanDay,
    TempoPlanItem,
    TempoUserSchedule,
)

from .workload import _DayFigures

Placements = dict[date, float]


@dataclass
class DayLoad:
    """Capacity and existing load of one day, in hours."""

    day: date
    capacity: float
    planned: float
    absence: float

    @property
    def free(self) -> float:
        return round(max(self.capacity - self.absence - self.planned, 0.0), 2)

    @property
    def is_working(self) -> bool:
        return self.capacity > 0


def build_day_loads(
    schedule: TempoUserSchedule | None,
    plans: list[TempoPlanItem],
    date_from: date,
    date_to: date,
    daily_limit_hours: float,
) -> list[DayLoad]:
    """One ``DayLoad`` per calendar day of the window.

    Uses the same capacity rule as the workload report:
    ``capacity = min(schedule norm, daily_limit_hours)``.
    """
    norms = {d.day: d.required_hours for d in schedule.days} if schedule else {}
    planned: dict[str, float] = {}
    absence: dict[str, float] = {}
    for plan in plans:
        bucket = absence if plan.is_absence else planned
        bucket[plan.day] = bucket.get(plan.day, 0.0) + plan.planned_seconds / 3600
    loads: list[DayLoad] = []
    current = date_from
    while current <= date_to:
        iso = current.isoformat()
        loads.append(
            DayLoad(
                day=current,
                capacity=round(min(norms.get(iso, 0.0), daily_limit_hours), 2),
                planned=round(planned.get(iso, 0.0), 2),
                absence=round(absence.get(iso, 0.0), 2),
            )
        )
        current += timedelta(days=1)
    return loads


def fixed_placement(loads: list[DayLoad], hours_per_day: float) -> Placements:
    """Put ``hours_per_day`` on every working day, as Tempo does for a range."""
    return {load.day: round(hours_per_day, 2) for load in loads if load.is_working}


def fit_placement(
    loads: list[DayLoad], total_hours: float, *, allow_absence_days: bool
) -> tuple[Placements, float]:
    """Greedily fill free hours from the first day on.

    Returns the placements and the hours that did not fit before the end.
    """
    remaining = round(total_hours, 2)
    placements: Placements = {}
    for load in loads:
        if remaining <= 0:
            break
        if not load.is_working:
            continue
        if load.absence > 0 and not allow_absence_days:
            continue
        free = (
            load.free
            if not allow_absence_days
            else round(max(load.capacity - load.planned, 0.0), 2)
        )
        if free <= 0:
            continue
        added = round(min(free, remaining), 2)
        placements[load.day] = added
        remaining = round(remaining - added, 2)
    return placements, max(remaining, 0.0)


def find_conflicts(
    loads: list[DayLoad],
    placements: Placements,
    mode: str,
    *,
    allow_overbooking: bool,
    allow_absence_days: bool,
    unplaced: float = 0.0,
) -> list[TempoPlanConflict]:
    """Conflicts that block writing the placements as requested."""
    conflicts: list[TempoPlanConflict] = []
    if mode == "fixed" and not placements:
        conflicts.append(
            TempoPlanConflict(
                type="non_working",
                message="The date range contains no working days for this user",
            )
        )
    for load in loads:
        added = placements.get(load.day, 0.0)
        if added <= 0:
            continue
        iso = load.day.isoformat()
        if load.absence > 0 and not allow_absence_days:
            conflicts.append(
                TempoPlanConflict(
                    day=iso,
                    type="absent",
                    message=(
                        f"{load.absence}h of absence is planned on {iso}; "
                        "set allow_absence_days to plan over it"
                    ),
                )
            )
            continue
        over = round(load.planned + load.absence + added - load.capacity, 2)
        if over > 0 and not allow_overbooking:
            conflicts.append(
                TempoPlanConflict(
                    day=iso,
                    type="overbooked",
                    message=(
                        f"{iso}: {load.planned}h planned + {load.absence}h absence "
                        f"+ {added}h new exceeds capacity {load.capacity}h by {over}h"
                    ),
                )
            )
    if unplaced > 0:
        conflicts.append(
            TempoPlanConflict(
                type="does_not_fit",
                message=(
                    f"{unplaced}h could not be placed before the end of the window; "
                    "extend date_to, lower the hours or allow overbooking"
                ),
            )
        )
    return conflicts


def group_allocations(
    loads: list[DayLoad], placements: Placements
) -> list[TempoAllocationDraft]:
    """Merge consecutive days with equal hours into allocation drafts.

    Non-working days never break a run because Tempo skips them inside a
    range; a working day with different (or no) hours does.
    """
    drafts: list[TempoAllocationDraft] = []
    run_hours: float | None = None
    run_start: date | None = None
    run_end: date | None = None
    run_days = 0

    def close() -> None:
        nonlocal run_hours, run_start, run_end, run_days
        if run_hours is not None and run_start is not None and run_end is not None:
            drafts.append(
                TempoAllocationDraft(
                    start=run_start.isoformat(),
                    end=run_end.isoformat(),
                    hours_per_day=run_hours,
                    total_hours=round(run_hours * run_days, 2),
                    working_days=run_days,
                )
            )
        run_hours, run_start, run_end, run_days = None, None, None, 0

    for load in loads:
        added = placements.get(load.day, 0.0)
        if not load.is_working and added <= 0:
            continue
        if added <= 0:
            close()
            continue
        if run_hours is not None and added == run_hours:
            run_end = load.day
            run_days += 1
            continue
        close()
        run_hours, run_start, run_end, run_days = added, load.day, load.day, 1
    close()
    return drafts


def plan_days(loads: list[DayLoad], placements: Placements) -> list[TempoPlanDay]:
    """Per-day view of the load after the placements are applied."""
    days: list[TempoPlanDay] = []
    for load in loads:
        added = placements.get(load.day, 0.0)
        figures = _DayFigures(
            capacity=load.capacity,
            planned=round(load.planned + added, 2),
            absence=load.absence,
        )
        days.append(
            TempoPlanDay(
                day=load.day.isoformat(),
                capacity_hours=load.capacity,
                planned_hours=load.planned,
                absence_hours=load.absence,
                added_hours=added,
                free_after_hours=round(figures.free, 2),
                status_after=figures.status,
            )
        )
    return days
