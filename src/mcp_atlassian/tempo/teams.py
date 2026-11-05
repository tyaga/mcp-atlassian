"""Tempo team operations."""

from __future__ import annotations

import difflib
from datetime import date, datetime, timezone
from typing import Any, Protocol

from mcp_atlassian.models.tempo import TempoTeam, TempoTeamMember, TempoUserRef

from .client import TempoClient

TEAMS_PATH = "/rest/tempo-teams/2/team"


class _HasClient(Protocol):
    client: TempoClient


class TeamsMixin:
    """Read Tempo teams and their members."""

    def list_teams(self: _HasClient, query: str | None = None) -> list[TempoTeam]:
        """List teams sorted by name, optionally filtered by a name substring."""
        data = self.client.get(TEAMS_PATH)
        teams = [
            TempoTeam.from_api_response(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]
        if query:
            needle = query.strip().casefold()
            teams = [team for team in teams if needle in team.name.casefold()]
        return sorted(teams, key=lambda team: team.name.strip().casefold())

    def resolve_team(self, team: str) -> TempoTeam:
        """Find a team by numeric id or by name (case- and whitespace-insensitive)."""
        teams = TeamsMixin.list_teams(self)  # type: ignore[arg-type]
        wanted = team.strip()
        if wanted.isdigit():
            for candidate in teams:
                if candidate.id == int(wanted):
                    return candidate
        folded = wanted.casefold()
        for candidate in teams:
            if candidate.name.strip().casefold() == folded:
                return candidate
        names = [candidate.name.strip() for candidate in teams]
        close = difflib.get_close_matches(wanted, names, n=5, cutoff=0.5)
        suggestions = close or sorted(names, key=str.casefold)[:5]
        raise ValueError(
            f"Tempo team '{team}' not found. Did you mean: {', '.join(suggestions)}?"
        )

    def get_team_members(
        self: _HasClient,
        team: TempoTeam,
        role: str | None = None,
        active_only: bool = True,
        window: tuple[date, date] | None = None,
    ) -> list[TempoTeamMember]:
        """Return team members filtered by role, activity or a date window.

        With ``window`` the membership is judged against those dates instead of
        today: former members are kept for past windows and future members for
        future ones, as long as the membership status is active. ``active_only``
        is ignored when ``window`` is given.
        """
        data = self.client.get(f"{TEAMS_PATH}/{team.id}/member")
        today = datetime.now(tz=timezone.utc).date()
        members = [
            TempoTeamMember.from_api_response(item, today=today)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]
        if window is not None:
            members = [m for m in members if m.overlaps(window[0], window[1])]
        elif active_only:
            members = [member for member in members if member.active]
        if role:
            needle = role.strip().casefold()
            members = [member for member in members if needle in member.role.casefold()]
        return members

    def get_user_memberships(self: _HasClient, user: TempoUserRef) -> list[TempoTeam]:
        """Teams the user is a member of, in Tempo's order."""
        who = user.username or user.key
        data = self.client.get(f"/rest/tempo-teams/2/user/{who}/memberships")
        teams: list[TempoTeam] = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and isinstance(item.get("team"), dict):
                teams.append(TempoTeam.from_api_response(item["team"]))
        return teams


def team_summary(team: TempoTeam) -> dict[str, Any]:
    """Short team reference used in tool responses."""
    return {"id": team.id, "name": team.name}
