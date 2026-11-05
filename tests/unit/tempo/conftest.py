"""Shared fixtures for Tempo unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from mcp_atlassian.jira import JiraFetcher
from mcp_atlassian.tempo import TempoFetcher

Route = Any
BASE_URL = "https://jira.example.com"


class FakeTempoClient:
    """In-memory stand-in for ``TempoClient``.

    ``routes`` maps ``(method, path)`` to a canned response or to a callable
    receiving the request params (GET) or payload (POST).
    """

    def __init__(self, routes: dict[tuple[str, str], Route]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, Any]] = []

    def _dispatch(self, method: str, path: str, data: Any) -> Any:
        self.calls.append((method, path, data))
        try:
            route = self.routes[(method, path)]
        except KeyError as exc:
            raise AssertionError(f"Unexpected Tempo call {method} {path}") from exc
        return route(data) if callable(route) else route

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._dispatch("GET", path, params or {})

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._dispatch("POST", path, payload)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        return self._dispatch("PUT", path, payload)

    def delete(self, path: str) -> Any:
        return self._dispatch("DELETE", path, None)


def make_fetcher(
    routes: dict[tuple[str, str], Route], jira: MagicMock | None = None
) -> TempoFetcher:
    """Build a ``TempoFetcher`` whose client is a ``FakeTempoClient``."""
    if jira is None:
        jira = MagicMock(spec=JiraFetcher)
        jira.config = MagicMock()
        jira.config.url = BASE_URL
        jira.jira = MagicMock()
        jira.jira._session = MagicMock()
    fetcher = TempoFetcher(jira)
    fetcher.client = FakeTempoClient(routes)  # type: ignore[assignment]
    return fetcher
