"""Tempo user schedules: working days, holidays and daily norms."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from mcp_atlassian.models.tempo import TempoUserRef, TempoUserSchedule

from .client import TempoClient

SCHEDULE_PATH = "/rest/tempo-core/1/user/schedule"


class _HasClient(Protocol):
    client: TempoClient


class ScheduleMixin:
    """Read per-user schedules from Tempo."""

    def get_user_schedule(
        self: _HasClient, user: TempoUserRef, date_from: date, date_to: date
    ) -> TempoUserSchedule:
        """Fetch a user's schedule for an inclusive date window."""
        data = self.client.get(
            SCHEDULE_PATH,
            params={
                "user": user.username or user.key,
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            },
        )
        return TempoUserSchedule.from_api_response(data or {}, user=user)
