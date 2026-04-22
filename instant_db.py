"""
InstantDB client for Baseball-Roto.

Uses the Admin HTTP API since there is no official Python SDK.
Docs: https://www.instantdb.com/docs/http-api
"""

from __future__ import annotations

import os
import uuid

import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

INSTANT_BASE_URL = "https://api.instantdb.com"

# Public app ID — safe to hard-code. Admin token must stay in .env.
APP_ID = os.getenv("INSTANT_APP_ID", "ec69e612-8297-45c3-9556-0a73274d1147")

# Deterministic UUID namespace so the same week always maps to the same record.
_WEEK_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_DNS


def _week_uuid(week: int) -> str:
    return str(uuid.uuid5(_WEEK_NS, f"baseball-roto-week-{week}"))


def _headers() -> dict:
    token = os.getenv("INSTANT_ADMIN_TOKEN", "")
    if not token:
        raise RuntimeError(
            "INSTANT_ADMIN_TOKEN is not set. Add it to your .env file."
        )
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "App-Id": APP_ID,
    }


def load_winners() -> dict:
    """
    Fetch all weekly winners from InstantDB.
    Returns {week_str: {team, manager_guid, manager_name, score, batting, pitching}}.
    Raises on network/auth errors.
    """
    resp = requests.post(
        f"{INSTANT_BASE_URL}/admin/query",
        headers=_headers(),
        json={"query": {"weeklyWinners": {}}},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("weeklyWinners", [])
    return {
        str(item["week"]): {
            "team": item["team"],
            "manager_guid": item.get("manager_guid"),
            "manager_name": item.get("manager_name", ""),
            "score": float(item["score"]),
            "batting": float(item["batting"]),
            "pitching": float(item["pitching"]),
        }
        for item in items
    }


def save_winners(winners: dict) -> None:
    """
    Upsert all entries in `winners` to InstantDB in a single transaction.
    `winners` is keyed by week string: {"1": {team, manager_guid, ...}, ...}.
    """
    if not winners:
        return
    steps = []
    for week_str, data in winners.items():
        week = int(week_str)
        steps.append(
            [
                "update",
                "weeklyWinners",
                _week_uuid(week),
                {
                    "week": week,
                    "team": data["team"],
                    "manager_guid": data.get("manager_guid"),
                    "manager_name": data.get("manager_name", ""),
                    "score": float(data["score"]),
                    "batting": float(data["batting"]),
                    "pitching": float(data["pitching"]),
                },
            ]
        )
    resp = requests.post(
        f"{INSTANT_BASE_URL}/admin/transact",
        headers=_headers(),
        json={"steps": steps},
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} {resp.reason}: {resp.text}")
    resp.raise_for_status()
