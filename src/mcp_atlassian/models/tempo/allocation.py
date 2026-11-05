"""Tempo Planner allocations and plan-writing reports."""

from __future__ import annotations

from typing import Any

from ..base import ApiModel
from .common import TempoUserRef, seconds_to_hours


class TempoAllocation(ApiModel):
    """A Tempo Planner allocation (one plan item for one user over a range)."""

    id: int = 0
    user: TempoUserRef = TempoUserRef()
    issue_key: str = ""
    issue_id: int = 0
    plan_item_type: str = "ISSUE"
    summary: str = ""
    team_id: int = 0
    scope_type: str = "team"
    start: str = ""
    end: str = ""
    seconds_per_day: int = 0
    hours_per_day: float = 0.0
    include_non_working_days: bool = False
    description: str = ""

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoAllocation:
        if not isinstance(data, dict):
            data = {}
        assignee = data.get("assignee") or {}
        item = data.get("planItem") or {}
        scope = data.get("scope") or {}
        seconds_per_day = int(float(data.get("secondsPerDay") or 0))
        return cls(
            id=int(data.get("id") or 0),
            user=TempoUserRef(
                key=str(assignee.get("userKey") or assignee.get("key") or ""),
                username=str(assignee.get("key") or ""),
            ),
            issue_key=str(item.get("key") or ""),
            issue_id=int(item.get("id") or 0),
            plan_item_type=str(item.get("type") or "ISSUE"),
            summary=str(item.get("summary") or item.get("name") or ""),
            team_id=int(scope.get("id") or 0),
            scope_type=str(scope.get("type") or "team"),
            start=str(data.get("start") or ""),
            end=str(data.get("end") or ""),
            seconds_per_day=seconds_per_day,
            hours_per_day=seconds_to_hours(seconds_per_day),
            include_non_working_days=bool(data.get("includeNonWorkingDays", False)),
            description=str(data.get("description") or ""),
        )

    def to_request_body(self) -> dict[str, Any]:
        """Body for ``POST``/``PUT /rest/tempo-planning/1/allocation``.

        Tempo accepts a username or a user key as ``assignee.key``; the user
        key is sent because a username can collide with another user's legacy
        key after a rename.
        """
        return {
            "assignee": {"key": self.user.key or self.user.username, "type": "user"},
            "planItem": {"id": self.issue_id, "type": self.plan_item_type},
            "scope": {"id": self.team_id, "type": self.scope_type},
            "start": self.start,
            "end": self.end,
            "secondsPerDay": self.seconds_per_day,
            "includeNonWorkingDays": self.include_non_working_days,
            "description": self.description,
        }

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.id,
            "user": self.user.to_simplified_dict(),
            "issue_key": self.issue_key,
            "issue_id": self.issue_id,
            "summary": self.summary,
            "team_id": self.team_id,
            "start": self.start,
            "end": self.end,
            "hours_per_day": self.hours_per_day,
            "include_non_working_days": self.include_non_working_days,
            "description": self.description,
        }


class TempoPlanDay(ApiModel):
    """One day of a plan check: load before, hours added, state after."""

    day: str = ""
    capacity_hours: float = 0.0
    planned_hours: float = 0.0
    absence_hours: float = 0.0
    added_hours: float = 0.0
    free_after_hours: float = 0.0
    status_after: str = ""

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "capacity_hours": self.capacity_hours,
            "planned_hours": self.planned_hours,
            "absence_hours": self.absence_hours,
            "added_hours": self.added_hours,
            "free_after_hours": self.free_after_hours,
            "status_after": self.status_after,
        }


class TempoPlanConflict(ApiModel):
    """Why a plan cannot be written as requested."""

    day: str | None = None
    type: str = ""
    message: str = ""

    def to_simplified_dict(self) -> dict[str, Any]:
        return {"day": self.day, "type": self.type, "message": self.message}


class TempoAllocationDraft(ApiModel):
    """An allocation to be created (or created, when ``allocation_id`` is set)."""

    allocation_id: int | None = None
    start: str = ""
    end: str = ""
    hours_per_day: float = 0.0
    total_hours: float = 0.0
    working_days: int = 0

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "start": self.start,
            "end": self.end,
            "hours_per_day": self.hours_per_day,
            "total_hours": self.total_hours,
            "working_days": self.working_days,
        }


class TempoPlanResult(ApiModel):
    """Outcome of a plan check or write."""

    ok: bool = False
    written: bool = False
    mode: str = ""
    user: TempoUserRef = TempoUserRef()
    issue: dict[str, Any] = {}
    team: dict[str, Any] = {}
    days: list[TempoPlanDay] = []
    conflicts: list[TempoPlanConflict] = []
    allocations: list[TempoAllocationDraft] = []
    allocation_id: int | None = None
    before: dict[str, Any] | None = None
    error: str | None = None

    def to_simplified_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ok": self.ok,
            "written": self.written,
            "mode": self.mode,
            "user": self.user.to_simplified_dict(),
            "issue": self.issue,
            "team": self.team,
            "days": [day.to_simplified_dict() for day in self.days],
            "conflicts": [c.to_simplified_dict() for c in self.conflicts],
            "allocations": [a.to_simplified_dict() for a in self.allocations],
        }
        if self.allocation_id is not None:
            data["allocation_id"] = self.allocation_id
        if self.before is not None:
            data["before"] = self.before
        if self.error is not None:
            data["error"] = self.error
        return data
