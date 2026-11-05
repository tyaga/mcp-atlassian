"""Tempo Server/DC integration built on top of the Jira client."""

from __future__ import annotations

from mcp_atlassian.jira import JiraFetcher

from .client import TempoClient
from .planning import PlanningMixin
from .schedule import ScheduleMixin
from .scope import TempoScope
from .teams import TeamsMixin
from .users import UsersMixin
from .workload import WorkloadMixin
from .worklogs import WorklogsMixin
from .writing import PlanWriteMixin


class TempoFetcher(
    TeamsMixin,
    UsersMixin,
    ScheduleMixin,
    PlanningMixin,
    WorklogsMixin,
    WorkloadMixin,
    PlanWriteMixin,
):
    """Entry point for Tempo operations.

    Reuses the authenticated session and base URL of a ``JiraFetcher``; Tempo
    needs no configuration of its own.
    """

    def __init__(self, jira: JiraFetcher) -> None:
        self.jira = jira
        self.base_url = str(jira.config.url or "").rstrip("/")
        self.client = TempoClient(jira.jira._session, self.base_url)


__all__ = ["TempoClient", "TempoFetcher", "TempoScope"]
