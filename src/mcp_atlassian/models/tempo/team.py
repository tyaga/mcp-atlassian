"""Tempo team models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from ..base import ApiModel
from .common import TempoUserRef


class TempoTeam(ApiModel):
    """A Tempo team."""

    id: int = 0
    name: str = ""
    summary: str = ""
    lead: str | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoTeam:
        if not isinstance(data, dict):
            return cls()
        lead = data.get("lead")
        return cls(
            id=int(data.get("id") or 0),
            name=str(data.get("name") or ""),
            summary=str(data.get("summary") or ""),
            lead=str(lead) if lead else None,
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "lead": self.lead,
        }


class TempoTeamMember(ApiModel):
    """A team membership: user plus role and availability."""

    user: TempoUserRef = TempoUserRef()
    role: str = ""
    availability: int = 100
    date_from: str = ""
    date_to: str = ""
    status: str = "active"
    active: bool = True

    def overlaps(self, date_from: date, date_to: date) -> bool:
        """Whether an active membership covers any day of the window."""
        if self.status != "active":
            return False
        if self.date_from and self.date_from > date_to.isoformat():
            return False
        if self.date_to and self.date_to < date_from.isoformat():
            return False
        return True

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoTeamMember:
        """Build from a ``/team/{id}/member`` item.

        Args:
            data: Raw member item.
            today: ``date`` used to decide whether ``dateTo`` has passed.
        """
        if not isinstance(data, dict):
            return cls()
        today: date = kwargs.get("today") or datetime.now(tz=timezone.utc).date()
        member = data.get("member") or {}
        membership = data.get("membership") or {}
        role = membership.get("role") or {}
        date_to = str(membership.get("dateTo") or "")
        status = str(membership.get("status") or "active")
        active = bool(member.get("activeInJira", True))
        if status != "active":
            active = False
        if date_to and date_to < today.isoformat():
            active = False
        try:
            availability = int(float(membership.get("availability") or 100))
        except (TypeError, ValueError):
            availability = 100
        return cls(
            user=TempoUserRef.from_api_response(member),
            role=str(role.get("name") or ""),
            availability=availability,
            date_from=str(membership.get("dateFrom") or ""),
            date_to=date_to,
            status=status,
            active=active,
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "user": self.user.to_simplified_dict(),
            "role": self.role,
            "availability": self.availability,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "active": self.active,
        }
