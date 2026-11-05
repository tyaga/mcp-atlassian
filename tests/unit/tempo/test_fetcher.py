"""Tests for TempoFetcher construction."""

from unittest.mock import MagicMock

from mcp_atlassian.jira import JiraFetcher
from mcp_atlassian.tempo import TempoFetcher
from mcp_atlassian.tempo.client import TempoClient


def test_fetcher_reuses_jira_session_and_url():
    jira = MagicMock(spec=JiraFetcher)
    jira.config = MagicMock()
    jira.config.url = "https://jira.example.com/"
    jira.jira = MagicMock()
    session = MagicMock()
    jira.jira._session = session

    fetcher = TempoFetcher(jira)

    assert fetcher.jira is jira
    assert isinstance(fetcher.client, TempoClient)
    assert fetcher.client.session is session
    assert fetcher.base_url == "https://jira.example.com"
