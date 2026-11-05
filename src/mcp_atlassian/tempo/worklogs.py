"""Tempo Timesheets: search logged work."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from mcp_atlassian.models.tempo import TempoUserRef, TempoWorklog

from .client import TempoClient

WORKLOG_SEARCH_PATH = "/rest/tempo-timesheets/4/worklogs/search"


class _HasClient(Protocol):
    client: TempoClient


class WorklogsMixin:
    """Read Tempo worklogs for a list of users."""

    def get_worklogs(
        self: _HasClient,
        users: list[TempoUserRef],
        date_from: date,
        date_to: date,
        issue_key: str | None = None,
    ) -> list[TempoWorklog]:
        """Return worklogs of ``users`` in the window, sorted by day, user, issue.

        Tempo's worklog search accepts user keys only, so callers must pass
        resolved ``TempoUserRef`` values.
        """
        users_by_key = {user.key: user for user in users if user.key}
        if not users_by_key:
            return []
        data = self.client.post(
            WORKLOG_SEARCH_PATH,
            {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "worker": list(users_by_key),
            },
        )
        if not isinstance(data, list):
            return []
        wanted_key = issue_key.strip().upper() if issue_key else None
        worklogs: list[TempoWorklog] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            user = users_by_key.get(str(row.get("worker") or ""))
            if user is None:
                continue
            worklog = TempoWorklog.from_api_response(row, user=user)
            if wanted_key and worklog.issue_key.upper() != wanted_key:
                continue
            worklogs.append(worklog)
        worklogs.sort(
            key=lambda w: (w.day, w.user.display_name.casefold(), w.issue_key)
        )
        return worklogs
