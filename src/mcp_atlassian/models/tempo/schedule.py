"""Tempo user schedule models (working days, holidays)."""

from __future__ import annotations

from typing import Any

from ..base import ApiModel
from .common import TempoUserRef, seconds_to_hours


class TempoScheduleDay(ApiModel):
    """One calendar day of a user's schedule."""

    day: str = ""
    type: str = ""
    required_seconds: int = 0
    required_hours: float = 0.0
    holiday_name: str | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoScheduleDay:
        if not isinstance(data, dict):
            return cls()
        holiday = data.get("holiday") or {}
        required_seconds = int(float(data.get("requiredSeconds") or 0))
        return cls(
            day=str(data.get("date") or ""),
            type=str(data.get("type") or ""),
            required_seconds=required_seconds,
            required_hours=seconds_to_hours(required_seconds),
            holiday_name=str(holiday["name"]) if holiday.get("name") else None,
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "type": self.type,
            "required_hours": self.required_hours,
            "holiday_name": self.holiday_name,
        }


class TempoUserSchedule(ApiModel):
    """A user's schedule over a date window."""

    user: TempoUserRef = TempoUserRef()
    working_days: int = 0
    required_hours: float = 0.0
    days: list[TempoScheduleDay] = []

    @classmethod
    def from_api_response(
        cls, data: dict[str, Any], **kwargs: Any
    ) -> TempoUserSchedule:
        if not isinstance(data, dict):
            data = {}
        days = [
            TempoScheduleDay.from_api_response(item)
            for item in data.get("days") or []
            if isinstance(item, dict)
        ]
        return cls(
            user=kwargs.get("user") or TempoUserRef(),
            working_days=int(data.get("numberOfWorkingDays") or 0),
            required_hours=seconds_to_hours(data.get("requiredSeconds")),
            days=days,
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "user": self.user.to_simplified_dict(),
            "working_days": self.working_days,
            "required_hours": self.required_hours,
            "days": [day.to_simplified_dict() for day in self.days],
        }
