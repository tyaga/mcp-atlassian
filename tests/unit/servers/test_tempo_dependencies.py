"""Tests for the Tempo fetcher dependency."""

from unittest.mock import MagicMock, patch

import pytest

from mcp_atlassian.jira import JiraFetcher
from mcp_atlassian.servers.dependencies import get_tempo_fetcher
from mcp_atlassian.tempo import TempoFetcher


def _jira_mock() -> MagicMock:
    jira = MagicMock(spec=JiraFetcher)
    jira.config = MagicMock()
    jira.config.url = "https://jira.example.com"
    jira.jira = MagicMock()
    jira.jira._session = MagicMock()
    return jira


@pytest.mark.anyio
async def test_get_tempo_fetcher_wraps_jira_fetcher():
    jira = _jira_mock()
    with (
        patch("mcp_atlassian.servers.dependencies.get_jira_fetcher", return_value=jira),
        patch(
            "mcp_atlassian.servers.dependencies.get_http_request",
            side_effect=RuntimeError("no request"),
        ),
    ):
        result = await get_tempo_fetcher(MagicMock())

    assert isinstance(result, TempoFetcher)
    assert result.jira is jira


@pytest.mark.anyio
async def test_get_tempo_fetcher_reuses_request_state():
    jira = _jira_mock()
    request = MagicMock()
    request.state.tempo_fetcher = None
    with (
        patch("mcp_atlassian.servers.dependencies.get_jira_fetcher", return_value=jira),
        patch(
            "mcp_atlassian.servers.dependencies.get_http_request",
            return_value=request,
        ),
    ):
        first = await get_tempo_fetcher(MagicMock())
        second = await get_tempo_fetcher(MagicMock())

    assert first is second
    assert request.state.tempo_fetcher is first


@pytest.mark.anyio
async def test_get_tempo_fetcher_rebuilds_when_jira_fetcher_changes():
    request = MagicMock()
    stale = TempoFetcher(_jira_mock())
    request.state.tempo_fetcher = stale
    fresh_jira = _jira_mock()
    with (
        patch(
            "mcp_atlassian.servers.dependencies.get_jira_fetcher",
            return_value=fresh_jira,
        ),
        patch(
            "mcp_atlassian.servers.dependencies.get_http_request",
            return_value=request,
        ),
    ):
        result = await get_tempo_fetcher(MagicMock())

    assert result is not stale
    assert result.jira is fresh_jira
