"""Tests for TempoClient."""

from unittest.mock import MagicMock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError

from mcp_atlassian.exceptions import MCPAtlassianAuthenticationError
from mcp_atlassian.tempo.client import TempoClient


def _response(status: int, text: str = "", payload: object = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = text
    response.content = text.encode() if text else b""
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = HTTPError(response=response)
    return response


class TestTempoClient:
    def test_get_builds_url_and_returns_json(self):
        session = MagicMock()
        session.request.return_value = _response(200, "[]", payload=[{"id": 1}])
        client = TempoClient(session, "https://jira.example.com/")

        result = client.get("/rest/tempo-teams/2/team", params={"q": "x"})

        assert result == [{"id": 1}]
        session.request.assert_called_once_with(
            method="GET",
            url="https://jira.example.com/rest/tempo-teams/2/team",
            params={"q": "x"},
            json=None,
            timeout=75,
        )

    def test_post_sends_payload(self):
        session = MagicMock()
        session.request.return_value = _response(200, "{}", payload={})
        client = TempoClient(session, "https://jira.example.com")

        client.post("/rest/tempo-planning/1/plan/search", {"from": "2026-01-01"})

        kwargs = session.request.call_args.kwargs
        assert kwargs["method"] == "POST"
        assert kwargs["json"] == {"from": "2026-01-01"}

    def test_403_raises_auth_error(self):
        session = MagicMock()
        session.request.return_value = _response(403, "forbidden")
        client = TempoClient(session, "https://jira.example.com")

        with pytest.raises(MCPAtlassianAuthenticationError):
            client.get("/rest/tempo-core/1/holidayscheme")

    def test_500_raises_value_error_with_body(self):
        session = MagicMock()
        session.request.return_value = _response(500, "boom")
        client = TempoClient(session, "https://jira.example.com")

        with pytest.raises(ValueError, match=r"HTTP 500: /rest/x \| boom"):
            client.get("/rest/x")

    def test_connection_error_raises_auth_error(self):
        session = MagicMock()
        session.request.side_effect = RequestsConnectionError("down")
        client = TempoClient(session, "https://jira.example.com")

        with pytest.raises(MCPAtlassianAuthenticationError):
            client.get("/rest/x")

    def test_empty_body_returns_none(self):
        session = MagicMock()
        session.request.return_value = _response(204, "")
        client = TempoClient(session, "https://jira.example.com")

        assert client.get("/rest/x") is None
