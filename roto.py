"""
Roto standings calculator.

12 categories across 10 teams:
  Batting  (higher = better): R, HR, RBI, SB, AVG, XBH
  Pitching (higher = better): W, SV, K, QS
  Pitching (lower  = better): ERA, WHIP  ← ranks are inverted

Each team earns 1–10 points per category (with average for ties).
Maximum possible total score: 120 (10 pts × 12 categories).
"""

import pandas as pd

BATTING_CATS = ["R", "HR", "RBI", "SB", "AVG", "XBH"]
PITCHING_CATS = ["W", "SV", "K", "ERA", "WHIP", "QS"]
ALL_CATS = BATTING_CATS + PITCHING_CATS

LOWER_IS_BETTER = {"ERA", "WHIP"}

CAT_LABELS = {
    "R": "Runs",
    "HR": "Home Runs",
    "RBI": "RBI",
    "SB": "Stolen Bases",
    "AVG": "Batting Average",
    "XBH": "Extra Base Hits",
    "W": "Wins",
    "SV": "Saves",
    "K": "Strikeouts",
    "ERA": "ERA",
    "WHIP": "WHIP",
    "QS": "Quality Starts",
}


def get_category_leaders(teams_stats: dict) -> dict[str, list[tuple[str, float]]]:
    """
    For each category, return all teams tied for the best weekly value.

    Returns {cat: [(team_name, value), ...]}.
    """
    if not teams_stats:
        return {}

    leaders: dict[str, list[tuple[str, float]]] = {}
    for cat in ALL_CATS:
        best_val: float | None = None
        tied: list[tuple[str, float]] = []

        for team, stats in teams_stats.items():
            raw = stats.get(cat, 0)
            try:
                val = float(raw) if raw is not None else 0.0
            except (ValueError, TypeError):
                val = 0.0

            if best_val is None:
                best_val = val
                tied = [(team, val)]
            elif cat in LOWER_IS_BETTER:
                if val < best_val:
                    best_val = val
                    tied = [(team, val)]
                elif val == best_val:
                    tied.append((team, val))
            else:
                if val > best_val:
                    best_val = val
                    tied = [(team, val)]
                elif val == best_val:
                    tied.append((team, val))

        leaders[cat] = tied
    return leaders


def compute_season_weekly_highs(
    all_week_stats: dict[int, dict],
) -> dict[str, dict]:
    """
    Best single-week performance per category across all supplied weeks.

    Returns {cat: {"value": float, "entries": [(week, team, value), ...]}}
    where entries are every team/week that tied for the season weekly high.
    """
    records: dict[str, dict] = {}

    for cat in ALL_CATS:
        best_val: float | None = None
        entries: list[tuple[int, str, float]] = []

        for week, teams_stats in all_week_stats.items():
            for team, stats in teams_stats.items():
                raw = stats.get(cat, 0)
                try:
                    val = float(raw) if raw is not None else 0.0
                except (ValueError, TypeError):
                    val = 0.0

                if best_val is None:
                    best_val = val
                    entries = [(week, team, val)]
                elif cat in LOWER_IS_BETTER:
                    if val < best_val:
                        best_val = val
                        entries = [(week, team, val)]
                    elif val == best_val:
                        entries.append((week, team, val))
                else:
                    if val > best_val:
                        best_val = val
                        entries = [(week, team, val)]
                    elif val == best_val:
                        entries.append((week, team, val))

        if best_val is not None:
            records[cat] = {"value": best_val, "entries": entries}

    return records


def calculate_roto(teams_stats: dict) -> pd.DataFrame:
    """
    Calculate roto standings from raw team stats.

    Args:
        teams_stats: {team_name: {stat_name: numeric_value}}
                     Missing stats and non-numeric values are treated as 0.

    Returns:
        DataFrame sorted by Total (desc) with columns:
            Rank, Team, R, HR, RBI, SB, AVG, XBH, W, SV, K, ERA, WHIP, QS,
            Batting, Pitching, Total
    """
    if not teams_stats:
        return pd.DataFrame()

    rows = []
    for team, stats in teams_stats.items():
        row: dict = {"Team": team}
        for cat in ALL_CATS:
            raw = stats.get(cat, 0)
            try:
                row[cat] = float(raw) if raw is not None else 0.0
            except (ValueError, TypeError):
                row[cat] = 0.0
        rows.append(row)

    df = pd.DataFrame(rows).set_index("Team")

    ranks = pd.DataFrame(index=df.index)
    for cat in ALL_CATS:
        ranks[cat] = df[cat].rank(
            method="average",
            ascending=(cat not in LOWER_IS_BETTER),
        )

    ranks["Batting"] = ranks[BATTING_CATS].sum(axis=1)
    ranks["Pitching"] = ranks[PITCHING_CATS].sum(axis=1)
    ranks["Total"] = ranks["Batting"] + ranks["Pitching"]

    result = df[ALL_CATS].copy()
    result["Batting"] = ranks["Batting"].round(1)
    result["Pitching"] = ranks["Pitching"].round(1)
    result["Total"] = ranks["Total"].round(1)

    result = result.sort_values("Total", ascending=False).reset_index()
    result.insert(0, "Rank", range(1, len(result) + 1))

    return result
