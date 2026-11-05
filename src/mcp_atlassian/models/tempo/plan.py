"""Tempo Planner models."""

from __future__ import annotations

from typing import Any

from ..base import ApiModel
from .common import TempoUserRef, seconds_to_hours


class TempoPlanItem(ApiModel):
    """One planned day for one user on one plan item (issue or project)."""

    day: str = ""
    user: TempoUserRef = TempoUserRef()
    issue_key: str = ""
    summary: str = ""
    project_key: str = ""
    plan_type: str = ""
    planned_seconds: int = 0
    planned_hours: float = 0.0
    description: str = ""
    plan_start: str = ""
    plan_end: str = ""
    allocation_id: int = 0
    is_absence: bool = False
    issue_url: str = ""

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoPlanItem:
        """Build from a ``plan/search`` row.

        Args:
            data: Raw plan row.
            base_url: Jira base URL for ``issue_url``.
            is_absence: Whether the row matched the absence pattern.
            user: Resolved user for the row's ``assignee``.
        """
        if not isinstance(data, dict):
            data = {}
        info = data.get("planItemInfo") or {}
        plan_type = str(data.get("planItemType") or info.get("type") or "")
        issue_key = str(info.get("key") or "")
        base_url = str(kwargs.get("base_url") or "").rstrip("/")
        issue_url = ""
        if issue_key and plan_type == "ISSUE" and base_url:
            issue_url = f"{base_url}/browse/{issue_key}"
        planned_seconds = int(float(data.get("timePlannedSeconds") or 0))
        return cls(
            day=str(data.get("day") or ""),
            user=kwargs.get("user") or TempoUserRef(),
            issue_key=issue_key,
            summary=str(info.get("summary") or info.get("name") or ""),
            project_key=str(info.get("projectKey") or ""),
            plan_type=plan_type,
            planned_seconds=planned_seconds,
            planned_hours=seconds_to_hours(planned_seconds),
            description=str(data.get("planDescription") or ""),
            plan_start=str(data.get("planStart") or ""),
            plan_end=str(data.get("planEnd") or ""),
            allocation_id=int(data.get("allocationId") or 0),
            is_absence=bool(kwargs.get("is_absence", False)),
            issue_url=issue_url,
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "user": self.user.to_simplified_dict(),
            "issue_key": self.issue_key,
            "summary": self.summary,
            "project_key": self.project_key,
            "plan_type": self.plan_type,
            "planned_hours": self.planned_hours,
            "description": self.description,
            "plan_start": self.plan_start,
            "plan_end": self.plan_end,
            "allocation_id": self.allocation_id,
            "is_absence": self.is_absence,
            "issue_url": self.issue_url,
        }
