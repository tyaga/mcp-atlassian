"""Tempo worklog models."""

from __future__ import annotations

from typing import Any

from ..base import ApiModel
from .common import TempoUserRef, seconds_to_hours


class TempoWorklog(ApiModel):
    """A Tempo worklog entry."""

    worklog_id: int = 0
    day: str = ""
    user: TempoUserRef = TempoUserRef()
    issue_key: str = ""
    summary: str = ""
    project_key: str = ""
    seconds: int = 0
    hours: float = 0.0
    comment: str = ""

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoWorklog:
        if not isinstance(data, dict):
            data = {}
        issue = data.get("issue") or {}
        seconds = int(float(data.get("timeSpentSeconds") or 0))
        return cls(
            worklog_id=int(data.get("tempoWorklogId") or 0),
            day=str(data.get("started") or "")[:10],
            user=kwargs.get("user") or TempoUserRef(),
            issue_key=str(issue.get("key") or ""),
            summary=str(issue.get("summary") or ""),
            project_key=str(issue.get("projectKey") or ""),
            seconds=seconds,
            hours=seconds_to_hours(seconds),
            comment=str(data.get("comment") or ""),
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "worklog_id": self.worklog_id,
            "day": self.day,
            "user": self.user.to_simplified_dict(),
            "issue_key": self.issue_key,
            "summary": self.summary,
            "project_key": self.project_key,
            "hours": self.hours,
            "comment": self.comment,
        }
