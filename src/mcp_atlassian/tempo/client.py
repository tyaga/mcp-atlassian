"""HTTP client for the Tempo Server/DC REST API."""

from __future__ import annotations

import logging
from typing import Any

from requests import Session
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError

from mcp_atlassian.exceptions import MCPAtlassianAuthenticationError

logger = logging.getLogger("mcp-atlassian.tempo")


class TempoClient:
    """Thin JSON client over an already-authenticated Jira session.

    Tempo Server/DC exposes its REST API under the Jira base URL, so the Jira
    session (auth headers, SSL, proxies) is reused as-is.
    """

    def __init__(self, session: Session, base_url: str, timeout: int = 75) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except RequestsConnectionError as exc:
            raise MCPAtlassianAuthenticationError(
                f"Could not connect to Tempo at {self.base_url}"
            ) from exc
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = (exc.response.text or "")[:500] if exc.response is not None else ""
            if status in (401, 403):
                raise MCPAtlassianAuthenticationError(
                    f"Tempo API HTTP {status}: {path} | {body}"
                ) from exc
            raise ValueError(f"Tempo API HTTP {status}: {path} | {body}") from exc
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``path`` (starting with ``/rest/``) and return parsed JSON."""
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        """POST ``payload`` as JSON to ``path`` and return parsed JSON."""
        return self._request("POST", path, json_data=payload)
