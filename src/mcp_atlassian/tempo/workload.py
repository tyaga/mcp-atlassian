"""Workload report: capacity vs. planned hours per user and period."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from mcp_atlassian.models.tempo import (
    TempoPlanItem,
    TempoPlanVsActualIssue,
    TempoPlanVsActualPeriod,
    TempoPlanVsActualReport,
    TempoUserPlanVsActual,
    TempoUserRef,
    TempoUserSchedule,
    TempoUserWorkload,
    TempoWorkloadItem,
    TempoWorkloadPeriod,
    TempoWorkloadReport,
    TempoWorklog,
)

from .common import Bucket, buckets_for, day_buckets, seconds_to_hours
from .scope import TempoScope


@dataclass
class _DayFigures:
    capacity: float
    planned: float
    absence: float

    @property
    def free(self) -> float:
        return max(self.capacity - self.absence - self.planned, 0.0)

    @property
    def overbooked(self) -> float:
        """Work planned beyond what the absence leaves of the capacity.

        An absence can never overbook a day on its own: a full-day leave
        recorded at the schedule norm is still just a day off.
        """
        remaining = max(self.capacity - self.absence, 0.0)
        return max(self.planned - remaining, 0.0)

    @property
    def status(self) -> str:
        if self.capacity == 0 and self.planned == 0 and self.absence == 0:
            return "non_working"
        if self.overbooked > 0:
            return "overbooked"
        if self.absence > 0 and self.absence >= self.capacity:
            return "absent"
        if self.planned == 0 and self.absence == 0:
            return "free"
        if self.free == 0:
            return "full"
        return "partial"


def _day_figures(
    schedule: TempoUserSchedule | None,
    plans: list[TempoPlanItem],
    day: date,
    daily_limit_hours: float,
) -> _DayFigures:
    required = 0.0
    if schedule is not None:
        iso = day.isoformat()
        required = next((d.required_hours for d in schedule.days if d.day == iso), 0.0)
    capacity = min(required, daily_limit_hours)
    planned = sum(p.planned_seconds for p in plans if not p.is_absence)
    absence = sum(p.planned_seconds for p in plans if p.is_absence)
    return _DayFigures(
        capacity=round(capacity, 2),
        planned=seconds_to_hours(planned),
        absence=seconds_to_hours(absence),
    )


def _bucket_status(days: list[_DayFigures], free: float) -> str:
    if any(d.overbooked > 0 for d in days):
        return "overbooked"
    working = [d for d in days if d.capacity > 0]
    if working and all(d.status == "absent" for d in working):
        return "absent"
    if all(d.planned == 0 and d.absence == 0 for d in days):
        return "free"
    if free == 0:
        return "full"
    return "partial"


def _items(plans: list[TempoPlanItem]) -> list[TempoWorkloadItem]:
    seconds: dict[tuple[str, bool], int] = defaultdict(int)
    summaries: dict[tuple[str, bool], str] = {}
    for plan in plans:
        key = (plan.issue_key, plan.is_absence)
        seconds[key] += plan.planned_seconds
        summaries.setdefault(key, plan.summary)
    return [
        TempoWorkloadItem(
            issue_key=issue_key,
            summary=summaries[(issue_key, is_absence)],
            hours=seconds_to_hours(total),
            is_absence=is_absence,
        )
        for (issue_key, is_absence), total in sorted(seconds.items())
    ]


def _period(
    bucket: Bucket,
    schedule: TempoUserSchedule | None,
    plans_by_day: dict[str, list[TempoPlanItem]],
    daily_limit_hours: float,
) -> TempoWorkloadPeriod:
    label, start, end = bucket
    days: list[_DayFigures] = []
    plans: list[TempoPlanItem] = []
    current = start
    while current <= end:
        day_plans = plans_by_day.get(current.isoformat(), [])
        days.append(_day_figures(schedule, day_plans, current, daily_limit_hours))
        plans.extend(day_plans)
        current = current.fromordinal(current.toordinal() + 1)
    capacity = round(sum(d.capacity for d in days), 2)
    planned = round(sum(d.planned for d in days), 2)
    absence = round(sum(d.absence for d in days), 2)
    free = round(sum(d.free for d in days), 2)
    overbooked = round(sum(d.overbooked for d in days), 2)
    status = days[0].status if len(days) == 1 else _bucket_status(days, free)
    return TempoWorkloadPeriod(
        period=label,
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        capacity_hours=capacity,
        planned_hours=planned,
        absence_hours=absence,
        free_hours=free,
        overbooked_hours=overbooked,
        status=status,
        items=_items(plans),
    )


def build_workload(
    users: list[TempoUserRef],
    roles: dict[str, str],
    schedules: dict[str, TempoUserSchedule],
    plans: list[TempoPlanItem],
    date_from: date,
    date_to: date,
    granularity: str,
    daily_limit_hours: float,
) -> TempoWorkloadReport:
    """Aggregate schedules and plans into a workload report.

    Per day: ``capacity = min(schedule norm, daily_limit_hours)``,
    ``free = max(capacity - absence - planned, 0)``,
    ``overbooked = max(planned - max(capacity - absence, 0), 0)``.
    """
    buckets = buckets_for(granularity, date_from, date_to)
    plans_by_user: dict[str, dict[str, list[TempoPlanItem]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for plan in plans:
        plans_by_user[plan.user.key][plan.day].append(plan)

    user_reports: list[TempoUserWorkload] = []
    overbooked: list[dict[str, Any]] = []
    absent: list[dict[str, Any]] = []
    free_capacity: list[dict[str, Any]] = []
    for user in users:
        schedule = schedules.get(user.key)
        user_plans = plans_by_user.get(user.key, {})
        periods = [
            _period(bucket, schedule, user_plans, daily_limit_hours)
            for bucket in buckets
        ]
        user_reports.append(
            TempoUserWorkload(user=user, role=roles.get(user.key, ""), periods=periods)
        )
        user_dict = user.to_simplified_dict()
        # Summary lists always name calendar days, whatever the granularity,
        # so a three-day leave inside a week is still reported.
        day_statuses = {
            label: _day_figures(
                schedule, user_plans.get(label, []), start, daily_limit_hours
            ).status
            for label, start, _ in day_buckets(date_from, date_to)
        }
        over_days = [d for d, status in day_statuses.items() if status == "overbooked"]
        if over_days:
            overbooked.append({"user": user_dict, "days": over_days})
        absent_days = [d for d, status in day_statuses.items() if status == "absent"]
        if absent_days:
            absent.append({"user": user_dict, "days": absent_days})
        free_total = round(sum(p.free_hours for p in periods), 2)
        if free_total > 0:
            free_capacity.append({"user": user_dict, "free_hours": free_total})
    free_capacity.sort(key=lambda entry: -float(entry["free_hours"]))

    return TempoWorkloadReport(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        granularity=granularity,
        daily_limit_hours=daily_limit_hours,
        users=user_reports,
        summary={
            "overbooked": overbooked,
            "free_capacity": free_capacity,
            "absent": absent,
        },
    )


def _plan_vs_actual_period(
    bucket: Bucket,
    plans: list[TempoPlanItem],
    worklogs: list[TempoWorklog],
) -> TempoPlanVsActualPeriod:
    label, start, end = bucket
    lo, hi = start.isoformat(), end.isoformat()
    planned: dict[str, int] = defaultdict(int)
    logged: dict[str, int] = defaultdict(int)
    summaries: dict[str, str] = {}
    for plan in plans:
        if lo <= plan.day <= hi:
            planned[plan.issue_key] += plan.planned_seconds
            summaries.setdefault(plan.issue_key, plan.summary)
    for worklog in worklogs:
        if lo <= worklog.day <= hi:
            logged[worklog.issue_key] += worklog.seconds
            summaries.setdefault(worklog.issue_key, worklog.summary)
    by_issue = []
    for issue_key in sorted(set(planned) | set(logged)):
        planned_hours = seconds_to_hours(planned.get(issue_key, 0))
        logged_hours = seconds_to_hours(logged.get(issue_key, 0))
        by_issue.append(
            TempoPlanVsActualIssue(
                issue_key=issue_key,
                summary=summaries.get(issue_key, ""),
                planned_hours=planned_hours,
                logged_hours=logged_hours,
                delta_hours=round(logged_hours - planned_hours, 2),
            )
        )
    planned_total = seconds_to_hours(sum(planned.values()))
    logged_total = seconds_to_hours(sum(logged.values()))
    return TempoPlanVsActualPeriod(
        period=label,
        date_from=lo,
        date_to=hi,
        planned_hours=planned_total,
        logged_hours=logged_total,
        delta_hours=round(logged_total - planned_total, 2),
        by_issue=by_issue,
        logged_unplanned=[i.issue_key for i in by_issue if i.planned_hours == 0],
        planned_not_logged=[i.issue_key for i in by_issue if i.logged_hours == 0],
    )


def build_plan_vs_actual(
    users: list[TempoUserRef],
    plans: list[TempoPlanItem],
    worklogs: list[TempoWorklog],
    date_from: date,
    date_to: date,
    granularity: str,
) -> TempoPlanVsActualReport:
    """Compare planned (non-absence) hours with logged hours per user and period."""
    buckets = buckets_for(granularity, date_from, date_to)
    plans_by_user: dict[str, list[TempoPlanItem]] = defaultdict(list)
    for plan in plans:
        if not plan.is_absence:
            plans_by_user[plan.user.key].append(plan)
    worklogs_by_user: dict[str, list[TempoWorklog]] = defaultdict(list)
    for worklog in worklogs:
        worklogs_by_user[worklog.user.key].append(worklog)
    return TempoPlanVsActualReport(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        granularity=granularity,
        users=[
            TempoUserPlanVsActual(
                user=user,
                periods=[
                    _plan_vs_actual_period(
                        bucket,
                        plans_by_user.get(user.key, []),
                        worklogs_by_user.get(user.key, []),
                    )
                    for bucket in buckets
                ],
            )
            for user in users
        ],
    )


class _Deps(Protocol):
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

    def get_worklogs(
        self,
        users: list[TempoUserRef],
        date_from: date,
        date_to: date,
        issue_key: str | None = None,
    ) -> list[TempoWorklog]: ...


class WorkloadMixin:
    """Workload report built from schedules and plans."""

    def get_workload(
        self: _Deps,
        scope: TempoScope,
        date_from: date,
        date_to: date,
        granularity: str = "day",
        daily_limit_hours: float = 8.0,
    ) -> TempoWorkloadReport:
        """Fetch schedules (one call per user) and plans, then aggregate."""
        buckets_for(granularity, date_from, date_to)
        schedules = {
            user.key: self.get_user_schedule(user, date_from, date_to)
            for user in scope.users
        }
        plans = self.get_plans(scope, date_from, date_to) if scope.users else []
        return build_workload(
            scope.users,
            scope.roles,
            schedules,
            plans,
            date_from,
            date_to,
            granularity,
            daily_limit_hours,
        )

    def get_plan_vs_actual(
        self: _Deps,
        scope: TempoScope,
        date_from: date,
        date_to: date,
        granularity: str = "week",
    ) -> TempoPlanVsActualReport:
        """Fetch plans and worklogs for the scope, then compare them."""
        buckets_for(granularity, date_from, date_to)
        if not scope.users:
            return build_plan_vs_actual([], [], [], date_from, date_to, granularity)
        plans = self.get_plans(scope, date_from, date_to, include_absences=False)
        worklogs = self.get_worklogs(scope.users, date_from, date_to)
        return build_plan_vs_actual(
            scope.users, plans, worklogs, date_from, date_to, granularity
        )
