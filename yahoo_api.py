"""
Yahoo Fantasy Sports API client.

Stat ID mappings for league 469.l.12591:
  Batting:  7=R  12=HR  13=RBI  16=SB  3=AVG  61=XBH
  Pitching: 28=W  32=SV  42=K  26=ERA  27=WHIP  83=QS
"""

from __future__ import annotations

import requests

from auth import get_access_token

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"
SOCIAL_BASE_URL = "https://social.yahooapis.com/v1"
LEAGUE_KEY = "469.l.12591"

STAT_ID_MAP: dict[str, str] = {
    "7": "R",
    "12": "HR",
    "13": "RBI",
    "16": "SB",
    "3": "AVG",
    "61": "XBH",
    "28": "W",
    "32": "SV",
    "42": "K",
    "26": "ERA",
    "27": "WHIP",
    "83": "QS",
}


# ─── Low-level helpers ────────────────────────────────────────────────────────

def _api_get(path: str) -> dict:
    """Authenticated GET to the Yahoo Fantasy API, returns JSON."""
    token = get_access_token()
    url = f"{BASE_URL}/{path}"
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}format=json"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _safe_float(val) -> float:
    """Convert any Yahoo stat value to float; NULL / '-' / empty → 0.0"""
    if val is None or val == "" or val == "-":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_stats(stats_list: list) -> dict:
    """Convert Yahoo stats list → {stat_name: float}."""
    result: dict[str, float] = {}
    for entry in stats_list:
        stat = entry.get("stat", {}) if isinstance(entry, dict) else {}
        stat_id = str(stat.get("stat_id", ""))
        if stat_id in STAT_ID_MAP:
            result[STAT_ID_MAP[stat_id]] = _safe_float(stat.get("value"))
    return result


def _parse_team(team_data: list) -> tuple:
    """
    Parse a Yahoo team entry.

    team_data is [info_list, stats_obj]:
      info_list – list of single-key dicts (team_key, name, managers, …)
      stats_obj – dict with a 'team_stats' key

    Returns (team_name_or_None, stats_dict, manager_guid_or_None, manager_nickname_or_None).
    """
    if not team_data:
        return None, {}, None, None

    info_list = team_data[0] if isinstance(team_data[0], list) else [team_data[0]]

    name: str | None = None
    manager_guid: str | None = None
    manager_nickname: str | None = None

    for item in info_list:
        if not isinstance(item, dict):
            continue
        if "name" in item and name is None:
            name = item["name"]
        if "managers" in item and manager_guid is None:
            managers_val = item["managers"]
            # Yahoo returns managers as a list of {"manager": {...}} dicts
            if isinstance(managers_val, list) and managers_val:
                mgr = managers_val[0].get("manager", {})
            elif isinstance(managers_val, dict):
                mgr = managers_val.get("manager", {})
            else:
                mgr = {}
            manager_guid = mgr.get("guid") or None
            manager_nickname = mgr.get("nickname") or None

    stats: dict[str, float] = {}
    if len(team_data) > 1:
        stats_container = team_data[1]
        if isinstance(stats_container, dict):
            team_stats = stats_container.get("team_stats", {})
            raw_stats = team_stats.get("stats", [])
            if isinstance(raw_stats, list):
                stats = _parse_stats(raw_stats)

    return name, stats, manager_guid, manager_nickname


# ─── Public API ───────────────────────────────────────────────────────────────

def get_current_week() -> int:
    """Return the current scoring week number for the league."""
    try:
        data = _api_get(f"league/{LEAGUE_KEY}")
        meta = data["fantasy_content"]["league"][0]
        return int(meta.get("current_week", 1))
    except Exception as exc:
        raise RuntimeError(f"Failed to get current week: {exc}") from exc


def get_week_stats(week: int) -> dict:
    """
    Fetch all team stats for a specific week from the scoreboard.

    Returns {team_name: {stat_name: float}}.
    All NULL / non-numeric values are coerced to 0.0.
    """
    try:
        data = _api_get(f"league/{LEAGUE_KEY}/scoreboard;week={week}")
        league = data["fantasy_content"]["league"]

        scoreboard = league[1].get("scoreboard", {})

        # Yahoo sometimes wraps matchups under a "0" key, sometimes directly
        inner = scoreboard.get("0", scoreboard)
        matchups = inner.get("matchups", scoreboard.get("matchups", {}))

        count = int(matchups.get("count", 0))
        teams_stats: dict[str, dict] = {}

        for i in range(count):
            matchup_wrapper = matchups.get(str(i), {})
            matchup = matchup_wrapper.get("matchup", matchup_wrapper)

            # Teams are nested one more level under "0"
            teams_wrapper = matchup.get("0", matchup)
            teams_container = teams_wrapper.get("teams", {})
            team_count = int(teams_container.get("count", 0))

            for j in range(team_count):
                team_obj = teams_container.get(str(j), {})
                team_data = team_obj.get("team", [])
                name, stats, _, _ = _parse_team(team_data)
                if name:
                    teams_stats[name] = stats

        return teams_stats

    except Exception as exc:
        raise RuntimeError(f"Failed to get week {week} stats: {exc}") from exc


def get_season_stats() -> dict:
    """
    Fetch cumulative season stats for all teams.

    Returns {team_name: {stat_name: float}}.
    """
    try:
        data = _api_get(f"league/{LEAGUE_KEY}/teams/stats;type=season")
        league = data["fantasy_content"]["league"]
        teams_container = league[1].get("teams", {})

        count = int(teams_container.get("count", 0))
        teams_stats: dict[str, dict] = {}

        for i in range(count):
            team_obj = teams_container.get(str(i), {})
            team_data = team_obj.get("team", [])
            name, stats, _, _ = _parse_team(team_data)
            if name:
                teams_stats[name] = stats

        return teams_stats

    except Exception as exc:
        raise RuntimeError(f"Failed to get season stats: {exc}") from exc


def get_week_team_managers(week: int) -> dict:
    """
    Parse the scoreboard for a given week and return manager info per team.

    Returns {team_name: {"guid": str, "nickname": str}}.
    Uses the same scoreboard endpoint as get_week_stats.
    """
    try:
        data = _api_get(f"league/{LEAGUE_KEY}/scoreboard;week={week}")
        league = data["fantasy_content"]["league"]

        scoreboard = league[1].get("scoreboard", {})
        inner = scoreboard.get("0", scoreboard)
        matchups = inner.get("matchups", scoreboard.get("matchups", {}))

        count = int(matchups.get("count", 0))
        team_managers: dict[str, dict] = {}

        for i in range(count):
            matchup_wrapper = matchups.get(str(i), {})
            matchup = matchup_wrapper.get("matchup", matchup_wrapper)

            teams_wrapper = matchup.get("0", matchup)
            teams_container = teams_wrapper.get("teams", {})
            team_count = int(teams_container.get("count", 0))

            for j in range(team_count):
                team_obj = teams_container.get(str(j), {})
                team_data = team_obj.get("team", [])
                name, _, guid, nickname = _parse_team(team_data)
                if name and guid:
                    team_managers[name] = {"guid": guid, "nickname": nickname or ""}

        return team_managers

    except Exception as exc:
        raise RuntimeError(f"Failed to get week {week} team managers: {exc}") from exc


def get_manager_profile(guid: str) -> dict:
    """
    Fetch a manager's real name from the Yahoo Social API.

    Returns {"first_name": str, "last_name": str}.
    Falls back to empty strings on any error (privacy settings, 401/403, etc.).
    """
    try:
        token = get_access_token()
        url = f"{SOCIAL_BASE_URL}/user/{guid}/profile?format=json"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        profile = resp.json().get("profile", {})

        first_name = profile.get("givenName", "")
        if isinstance(first_name, dict):
            first_name = first_name.get("value", "")

        last_name = profile.get("familyName", "")
        if isinstance(last_name, dict):
            last_name = last_name.get("value", "")

        return {"first_name": str(first_name), "last_name": str(last_name)}
    except Exception:
        return {"first_name": "", "last_name": ""}


def get_league_managers() -> dict:
    """
    Fetch all current teams, resolve manager GUIDs, then enrich with real first
    names from the Yahoo Social API.

    Returns {guid: {"first_name": str, "nickname": str}}.
    Falls back to nickname when the Social API is unavailable for a user.
    """
    try:
        data = _api_get(f"league/{LEAGUE_KEY}/teams")
        league = data["fantasy_content"]["league"]
        teams_container = league[1].get("teams", {})
        count = int(teams_container.get("count", 0))

        managers: dict[str, dict] = {}
        for i in range(count):
            team_obj = teams_container.get(str(i), {})
            team_data = team_obj.get("team", [])
            _, _, guid, nickname = _parse_team(team_data)
            if guid and guid not in managers:
                managers[guid] = {
                    "first_name": nickname or guid,
                    "nickname": nickname or "",
                }

        for guid, info in managers.items():
            profile = get_manager_profile(guid)
            if profile["first_name"]:
                info["first_name"] = profile["first_name"]

        return managers

    except Exception as exc:
        raise RuntimeError(f"Failed to get league managers: {exc}") from exc
