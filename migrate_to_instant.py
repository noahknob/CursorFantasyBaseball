"""
One-time migration: push weekly_winners.json → InstantDB.

Run once after adding INSTANT_ADMIN_TOKEN to your .env:
    python migrate_to_instant.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

import instant_db  # noqa: E402  (must be after load_dotenv)

WINNERS_FILE = Path(__file__).parent / "weekly_winners.json"


def main() -> None:
    if not WINNERS_FILE.exists():
        print("weekly_winners.json not found — nothing to migrate.")
        sys.exit(0)

    try:
        winners = json.loads(WINNERS_FILE.read_text())
    except Exception as exc:
        print(f"Failed to read weekly_winners.json: {exc}")
        sys.exit(1)

    if not winners:
        print("weekly_winners.json is empty — nothing to migrate.")
        sys.exit(0)

    print(f"Migrating {len(winners)} week(s) to InstantDB…")
    try:
        instant_db.save_winners(winners)
    except Exception as exc:
        print(f"Migration failed: {exc}")
        sys.exit(1)

    print("Done! Weeks migrated:", sorted(winners.keys(), key=int))
    print(
        "\nYou can now delete weekly_winners.json — "
        "InstantDB is the source of truth."
    )


if __name__ == "__main__":
    main()
