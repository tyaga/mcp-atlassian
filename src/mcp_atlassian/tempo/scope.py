"""Resolved target of a Tempo query: a team or an explicit list of users."""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_atlassian.models.tempo import TempoTeam, TempoUserRef


@dataclass
class TempoScope:
    """Users a Tempo query applies to.

    ``roles`` maps user key to team role; empty for user-scoped queries.
    """

    team: TempoTeam | None
    users: list[TempoUserRef]
    roles: dict[str, str] = field(default_factory=dict)

    @property
    def user_keys(self) -> set[str]:
        return {user.key for user in self.users if user.key}
