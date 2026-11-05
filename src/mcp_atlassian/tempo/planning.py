"""Tempo Planner: search planned time."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from mcp_atlassian.models.tempo import TempoPlanItem

from .client import TempoClient
from .common import absence_pattern
from .scope import TempoScope

PLAN_SEARCH_PATH = "/rest/tempo-planning/1/plan/search"


class _HasClient(Protocol):
    client: TempoClient
    base_url: str


class PlanningMixin:
    """Read Tempo plans for a scope of users."""

    def get_plans(
        self: _HasClient,
        scope: TempoScope,
        date_from: date,
        date_to: date,
        issue_key: str | None = None,
        include_absences: bool = True,
    ) -> list[TempoPlanItem]:
        """Return one item per planned day per user per plan item.

        Tempo filters server-side by team only; rows are then reduced to the
        scope's users. Absences are detected by the absence pattern.
        """
        if not scope.users:
            raise ValueError("Scope contains no users; nothing to search for")
        payload: dict[str, Any] = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        if scope.team is not None:
            payload["teamId"] = [scope.team.id]
        data = self.client.post(PLAN_SEARCH_PATH, payload)
        if not isinstance(data, list):
            return []

        users_by_key = {user.key: user for user in scope.users}
        pattern = absence_pattern()
        wanted_key = issue_key.strip().upper() if issue_key else None
        plans: list[TempoPlanItem] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            user = users_by_key.get(str(row.get("assignee") or ""))
            if user is None:
                continue
            info = row.get("planItemInfo") or {}
            if wanted_key and str(info.get("key") or "").upper() != wanted_key:
                continue
            text = f"{info.get('summary') or ''} {row.get('planDescription') or ''}"
            is_absence = bool(pattern.search(text))
            if is_absence and not include_absences:
                continue
            plans.append(
                TempoPlanItem.from_api_response(
                    row, base_url=self.base_url, is_absence=is_absence, user=user
                )
            )
        plans.sort(key=lambda p: (p.day, p.user.display_name.casefold(), p.issue_key))
        return plans
