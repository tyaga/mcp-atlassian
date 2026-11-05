"""Aggregated Tempo reports: workload and plan vs. actual."""

from __future__ import annotations

from typing import Any

from ..base import ApiModel
from .common import TempoUserRef


class TempoWorkloadItem(ApiModel):
    """Hours planned on one plan item within a period."""

    issue_key: str = ""
    summary: str = ""
    hours: float = 0.0
    is_absence: bool = False

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "issue_key": self.issue_key,
            "summary": self.summary,
            "hours": self.hours,
            "is_absence": self.is_absence,
        }


class TempoWorkloadPeriod(ApiModel):
    """Workload figures for one user over one period (day, week or total)."""

    period: str = ""
    date_from: str = ""
    date_to: str = ""
    capacity_hours: float = 0.0
    planned_hours: float = 0.0
    absence_hours: float = 0.0
    free_hours: float = 0.0
    overbooked_hours: float = 0.0
    status: str = ""
    items: list[TempoWorkloadItem] = []

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "from": self.date_from,
            "to": self.date_to,
            "capacity_hours": self.capacity_hours,
            "planned_hours": self.planned_hours,
            "absence_hours": self.absence_hours,
            "free_hours": self.free_hours,
            "overbooked_hours": self.overbooked_hours,
            "status": self.status,
            "items": [item.to_simplified_dict() for item in self.items],
        }


class TempoUserWorkload(ApiModel):
    """Workload periods for one user."""

    user: TempoUserRef = TempoUserRef()
    role: str = ""
    periods: list[TempoWorkloadPeriod] = []

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "user": self.user.to_simplified_dict(),
            "role": self.role,
            "periods": [period.to_simplified_dict() for period in self.periods],
        }


class TempoWorkloadReport(ApiModel):
    """Workload report for a set of users."""

    date_from: str = ""
    date_to: str = ""
    granularity: str = "day"
    daily_limit_hours: float = 8.0
    users: list[TempoUserWorkload] = []
    summary: dict[str, Any] = {}

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "from": self.date_from,
            "to": self.date_to,
            "granularity": self.granularity,
            "daily_limit_hours": self.daily_limit_hours,
            "users": [user.to_simplified_dict() for user in self.users],
            "summary": self.summary,
        }


class TempoPlanVsActualIssue(ApiModel):
    """Planned vs. logged hours on one issue."""

    issue_key: str = ""
    summary: str = ""
    planned_hours: float = 0.0
    logged_hours: float = 0.0
    delta_hours: float = 0.0

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "issue_key": self.issue_key,
            "summary": self.summary,
            "planned_hours": self.planned_hours,
            "logged_hours": self.logged_hours,
            "delta_hours": self.delta_hours,
        }


class TempoPlanVsActualPeriod(ApiModel):
    """Planned vs. logged hours for one user over one period."""

    period: str = ""
    date_from: str = ""
    date_to: str = ""
    planned_hours: float = 0.0
    logged_hours: float = 0.0
    delta_hours: float = 0.0
    by_issue: list[TempoPlanVsActualIssue] = []
    logged_unplanned: list[str] = []
    planned_not_logged: list[str] = []

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "from": self.date_from,
            "to": self.date_to,
            "planned_hours": self.planned_hours,
            "logged_hours": self.logged_hours,
            "delta_hours": self.delta_hours,
            "by_issue": [issue.to_simplified_dict() for issue in self.by_issue],
            "logged_unplanned": self.logged_unplanned,
            "planned_not_logged": self.planned_not_logged,
        }


class TempoUserPlanVsActual(ApiModel):
    """Plan vs. actual periods for one user."""

    user: TempoUserRef = TempoUserRef()
    periods: list[TempoPlanVsActualPeriod] = []

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "user": self.user.to_simplified_dict(),
            "periods": [period.to_simplified_dict() for period in self.periods],
        }


class TempoPlanVsActualReport(ApiModel):
    """Plan vs. actual report for a set of users."""

    date_from: str = ""
    date_to: str = ""
    granularity: str = "week"
    users: list[TempoUserPlanVsActual] = []

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "from": self.date_from,
            "to": self.date_to,
            "granularity": self.granularity,
            "users": [user.to_simplified_dict() for user in self.users],
        }
