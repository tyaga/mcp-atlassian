"""Resolve user identifiers to Tempo user references."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from mcp_atlassian.jira import JiraFetcher
from mcp_atlassian.models.jira.common import JiraUser
from mcp_atlassian.models.tempo import TempoTeam, TempoTeamMember, TempoUserRef

from .scope import TempoScope


class _HasJira(Protocol):
    jira: JiraFetcher

    def resolve_team(self, team: str) -> TempoTeam: ...

    def get_team_members(
        self,
        team: TempoTeam,
        role: str | None = None,
        active_only: bool = True,
        window: tuple[date, date] | None = None,
    ) -> list[TempoTeamMember]: ...


def _from_jira_user(user: JiraUser) -> TempoUserRef:
    return TempoUserRef(
        key=user.user_key or "",
        username=user.username or "",
        display_name=user.display_name or "",
    )


class UsersMixin:
    """Turn usernames, keys, display names or e-mails into ``TempoUserRef``."""

    def resolve_users(
        self: _HasJira,
        identifiers: list[str],
        known: list[TempoTeamMember] | None = None,
    ) -> list[TempoUserRef]:
        """Resolve identifiers in order, de-duplicated by user key.

        Known team members are matched first (no network call); then the Jira
        user lookup; then a user search that must return exactly one match.
        """
        resolved: list[TempoUserRef] = []
        seen: set[str] = set()
        for identifier in identifiers:
            user = UsersMixin._resolve_one(self, identifier.strip(), known or [])
            if user.key in seen:
                continue
            seen.add(user.key)
            resolved.append(user)
        return resolved

    @staticmethod
    def _match_known(
        identifier: str, known: list[TempoTeamMember]
    ) -> TempoUserRef | None:
        folded = identifier.casefold()
        for member in known:
            user = member.user
            if folded in {
                user.key.casefold(),
                user.username.casefold(),
                user.display_name.casefold(),
            }:
                return user
        return None

    def _resolve_one(
        self: _HasJira, identifier: str, known: list[TempoTeamMember]
    ) -> TempoUserRef:
        if not identifier:
            raise ValueError("User identifier must not be empty")
        matched = UsersMixin._match_known(identifier, known)
        if matched is not None:
            return matched
        try:
            return _from_jira_user(self.jira.get_user_profile_by_identifier(identifier))
        except ValueError:
            pass
        results: Any = self.jira.jira.user_find_by_user_string(username=identifier)
        candidates = [
            TempoUserRef.from_api_response(item)
            for item in (results if isinstance(results, list) else [])
            if isinstance(item, dict)
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ValueError(f"User '{identifier}' not found in Jira")
        names = ", ".join(f"{c.display_name} ({c.username})" for c in candidates[:10])
        raise ValueError(f"User '{identifier}' is ambiguous: {names}")

    def resolve_scope(
        self: _HasJira,
        team: str | None,
        users: list[str] | None,
        role: str | None = None,
        window: tuple[date, date] | None = None,
    ) -> TempoScope:
        """Build the query scope from exactly one of ``team`` / ``users``.

        ``window`` selects team members by membership dates instead of today.
        """
        if bool(team) == bool(users):
            raise ValueError("Provide exactly one of 'team' or 'users'")
        if team:
            resolved_team = self.resolve_team(team)
            members = self.get_team_members(
                resolved_team, role=role, active_only=True, window=window
            )
            return TempoScope(
                team=resolved_team,
                users=[member.user for member in members],
                roles={member.user.key: member.role for member in members},
            )
        return TempoScope(team=None, users=UsersMixin.resolve_users(self, users or []))
