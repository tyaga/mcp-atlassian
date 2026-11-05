"""Shared Tempo model types."""

from __future__ import annotations

from typing import Any

from ..base import ApiModel


def seconds_to_hours(seconds: float | int | None) -> float:
    """Convert seconds to hours rounded to two decimals."""
    return round(float(seconds or 0) / 3600, 2)


class TempoUserRef(ApiModel):
    """Minimal user identity used across Tempo models."""

    key: str = ""
    username: str = ""
    display_name: str = ""

    @classmethod
    def from_api_response(cls, data: dict[str, Any], **kwargs: Any) -> TempoUserRef:
        """Build from a Tempo member dict or a Jira user dict.

        Tempo team members carry ``displayname``; Jira users carry ``displayName``.
        """
        if not isinstance(data, dict):
            return cls()
        return cls(
            key=str(data.get("key") or ""),
            username=str(data.get("name") or ""),
            display_name=str(data.get("displayname") or data.get("displayName") or ""),
        )

    def to_simplified_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "username": self.username,
            "display_name": self.display_name,
        }
