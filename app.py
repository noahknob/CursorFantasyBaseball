"""
Fantasy Baseball BB Roto Standings — Streamlit app.

Tabs:
  1. This Week    – live weekly roto standings + raw stats
  2. Full Season  – cumulative season roto standings + raw stats
  3. Weekly Winners – cards for each completed week's winner
  4. Weekly Category Highs – season-best single-week stat per category
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from auth import (
    OOB_REDIRECT_URI,
    exchange_code,
    get_auth_url,
    get_oauth_config_errors,
    has_refresh_token,
)
import instant_db
from roto import (
    ALL_CATS,
    BATTING_CATS,
    CAT_LABELS,
    PITCHING_CATS,
    calculate_roto,
    compute_season_weekly_highs,
    get_category_leaders,
)
from yahoo_api import (
    get_current_week,
    get_season_stats,
    get_week_stats,
    get_week_team_managers,
)

INT_STATS = {"R", "HR", "RBI", "SB", "XBH", "W", "SV", "K", "QS"}


# ─── Page config & global CSS ─────────────────────────────────────────────────

st.set_page_config(
    page_title="Fantasy Baseball BB Roto Standings",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    /* ── Global app styling ─────────────────── */
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(124, 58, 237, 0.14), transparent 28%),
            radial-gradient(circle at top right, rgba(59, 130, 246, 0.12), transparent 22%),
            linear-gradient(180deg, #f8f7ff 0%, #eef2ff 100%);
        color: #111827;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    h1, h2, h3 {
        color: #111827;
        letter-spacing: -0.02em;
    }
    [data-testid="stTabs"] {
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid rgba(139, 92, 246, 0.12);
        border-radius: 18px;
        padding: 0.5rem 0.65rem 0.8rem 0.65rem;
        box-shadow: 0 18px 40px rgba(76, 29, 149, 0.08);
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.5rem;
        margin-bottom: 0.75rem;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        background: rgba(139, 92, 246, 0.08);
        border-radius: 999px;
        padding: 0.55rem 1rem;
        color: #5b21b6;
        font-weight: 600;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
        color: white;
        box-shadow: 0 10px 24px rgba(109, 40, 217, 0.22);
    }
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(139, 92, 246, 0.12);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.06);
        background: rgba(255, 255, 255, 0.88);
    }
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(139, 92, 246, 0.12);
        border-radius: 14px;
        padding: 0.75rem 1rem;
    }
    .stButton > button {
        border-radius: 12px;
        border: 0;
        background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
        color: white;
        font-weight: 700;
        box-shadow: 0 10px 24px rgba(109, 40, 217, 0.22);
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #6d28d9 0%, #4338ca 100%);
        color: white;
    }

    /* ── Header ──────────────────────────────── */
    .roto-header {
        background:
            radial-gradient(circle at top right, rgba(255, 255, 255, 0.22), transparent 24%),
            linear-gradient(135deg, #4c1d95 0%, #6d28d9 52%, #2563eb 100%);
        padding: 1.55rem 1.8rem;
        border-radius: 22px;
        margin-bottom: 1.25rem;
        box-shadow: 0 22px 48px rgba(67, 56, 202, 0.22);
        border: 1px solid rgba(255, 255, 255, 0.16);
    }
    .roto-header .brand-row {
        display: flex;
        align-items: center;
        gap: 0.9rem;
        margin-bottom: 0.45rem;
    }
    .roto-header .brand-icon {
        width: 52px;
        height: 52px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.16);
        backdrop-filter: blur(8px);
        flex: 0 0 auto;
    }
    .roto-header .brand-icon svg {
        width: 32px;
        height: 32px;
        stroke: white;
        fill: none;
        stroke-width: 1.9;
        stroke-linecap: round;
        stroke-linejoin: round;
    }
    .roto-header .eyebrow {
        color: rgba(237, 233, 254, 0.88);
        margin: 0 0 0.2rem 0;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
    .roto-header h1 {
        color: white;
        margin: 0;
        font-size: 2.15rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .roto-header p {
        color: rgba(237, 233, 254, 0.92);
        margin: 0.35rem 0 0 0;
        font-size: 0.96rem;
    }

    /* ── Subtitles ───────────────────────────── */
    .roto-subtitle {
        color: #5b21b6;
        font-size: 0.93rem;
        font-weight: 600;
        margin-bottom: 0.85rem;
    }

    /* ── Winner cards ────────────────────────── */
    .winner-card {
        background: rgba(255, 255, 255, 0.88);
        border-radius: 18px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.8rem;
        border: 1px solid rgba(139, 92, 246, 0.12);
        border-left: 4px solid #8b5cf6;
        box-shadow: 0 18px 34px rgba(15, 23, 42, 0.06);
    }
    .winner-card .week-label {
        color: #7c3aed;
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 0 0 0.2rem 0;
    }
    .winner-card .team-name {
        color: #111827;
        font-size: 1.25rem;
        font-weight: 700;
        margin: 0 0 0.35rem 0;
    }
    .winner-card .score-line {
        color: #6b7280;
        font-size: 0.85rem;
        margin: 0;
    }
    .winner-card .score-line strong {
        color: #312e81;
    }

    /* ── Auth setup card ─────────────────────── */
    .auth-card {
        background: rgba(255, 255, 255, 0.9);
        border-radius: 18px;
        padding: 2rem;
        max-width: 560px;
        margin: 3rem auto;
        border: 1px solid rgba(139, 92, 246, 0.12);
        box-shadow: 0 22px 48px rgba(15, 23, 42, 0.08);
    }
    .auth-card h2 { color: #111827; margin: 0 0 0.5rem 0; }
    .auth-card p  { color: #6b7280; margin: 0 0 1.5rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─── Weekly winners helpers ───────────────────────────────────────────────────

def load_winners() -> dict:
    try:
        return instant_db.load_winners()
    except Exception:
        return {}


def save_winners(data: dict) -> None:
    try:
        instant_db.save_winners(data)
    except Exception as exc:
        st.warning(f"Could not save winners to InstantDB: {exc}")


def backfill_weekly_winners(current_week: int) -> dict:
    """
    For every completed week (1 … current_week-1) not yet in the JSON,
    fetch stats, calculate roto, and persist the winner.
    Also migrates existing entries that are missing manager_guid.
    Returns the updated winners dict.
    """
    winners = load_winners()
    changed = False

    for week in range(1, current_week):
        week_str = str(week)

        # Migration: backfill manager info for existing entries that lack it
        if week_str in winners and "manager_guid" not in winners[week_str]:
            try:
                team_managers = get_week_team_managers(week)
                team_name = winners[week_str]["team"]
                mgr_info = team_managers.get(team_name, {})
                winners[week_str]["manager_guid"] = mgr_info.get("guid")
                winners[week_str]["manager_name"] = mgr_info.get("nickname") or team_name
                changed = True
            except Exception:
                pass
            continue

        if week_str in winners:
            continue

        try:
            stats = get_week_stats(week)
            if not stats:
                continue
            roto_df = calculate_roto(stats)
            if roto_df.empty:
                continue
            top = roto_df.iloc[0]
            team_name = top["Team"]

            manager_guid = None
            manager_name = team_name
            try:
                team_managers = get_week_team_managers(week)
                mgr_info = team_managers.get(team_name, {})
                manager_guid = mgr_info.get("guid")
                manager_name = mgr_info.get("nickname") or team_name
            except Exception:
                pass

            winners[week_str] = {
                "team": team_name,
                "manager_guid": manager_guid,
                "manager_name": manager_name,
                "score": float(top["Total"]),
                "batting": float(top["Batting"]),
                "pitching": float(top["Pitching"]),
            }
            changed = True
        except Exception as exc:
            st.warning(f"Could not fetch week {week} data: {exc}")

    if changed:
        save_winners(winners)

    return winners


# ─── Table styling helpers ────────────────────────────────────────────────────

def _standings_styler(df: pd.DataFrame):
    cols = ["Rank", "Team", "Batting", "Pitching", "Total"]
    display = df[[c for c in cols if c in df.columns]].copy()
    return display.style.format(
        {"Batting": "{:.1f}", "Pitching": "{:.1f}", "Total": "{:.1f}"}
    )


def _raw_stats_styler(df: pd.DataFrame):
    stat_cols = ["Team"] + ALL_CATS
    available = [c for c in stat_cols if c in df.columns]
    display = df[available].copy()

    fmt: dict[str, str] = {}
    for col in available:
        if col in INT_STATS:
            fmt[col] = "{:.0f}"
        elif col == "AVG":
            fmt[col] = "{:.3f}"
        elif col in {"ERA", "WHIP"}:
            fmt[col] = "{:.2f}"

    return display.style.format(fmt)


# ─── Tab renderers ────────────────────────────────────────────────────────────

def render_standings(teams_stats: dict, subtitle: str) -> None:
    st.markdown(f'<p class="roto-subtitle">{subtitle}</p>', unsafe_allow_html=True)

    if not teams_stats:
        st.info("No stats available yet. Check back once games have been played.")
        return

    any_data = any(
        any(v != 0 for v in stats.values())
        for stats in teams_stats.values()
        if stats
    )
    if not any_data:
        st.info("No stats recorded yet for this period. All values are zero.")
        return

    roto_df = calculate_roto(teams_stats)
    if roto_df.empty:
        st.info("Could not calculate standings — insufficient data.")
        return

    st.subheader("Roto Standings")
    st.dataframe(
        _standings_styler(roto_df),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Raw Stats")
    st.dataframe(
        _raw_stats_styler(roto_df),
        use_container_width=True,
        hide_index=True,
    )


# ─── OAuth setup screen ───────────────────────────────────────────────────────

def _trophy_icon_svg() -> str:
    return """
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 21h8"></path>
            <path d="M12 17v4"></path>
            <path d="M7 4h10v3a5 5 0 0 1-10 0V4Z"></path>
            <path d="M7 5H5a2 2 0 0 0 0 4h2"></path>
            <path d="M17 5h2a2 2 0 1 1 0 4h-2"></path>
        </svg>
    """


def render_brand_header(subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="roto-header">
            <div class="brand-row">
                <span class="brand-icon">{_trophy_icon_svg()}</span>
                <div>
                    <p class="eyebrow">Fantasy Baseball BB</p>
                    <h1>Fantasy Baseball BB Roto Standings</h1>
                </div>
            </div>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_oauth_setup() -> None:
    render_brand_header("One-time Yahoo authorization required")

    # ── Auto-handle Yahoo's redirect back with ?code= ────────────────────────
    params = st.query_params
    callback_code = params.get("code", "")
    if callback_code:
        with st.spinner("Completing authorization…"):
            try:
                exchange_code(callback_code.strip())
                load_dotenv(override=True)
                # Clear the ?code= from the URL so a page refresh doesn't re-use it
                st.query_params.clear()
                st.success("✓ Authorization successful! Loading your league…")
                st.rerun()
            except Exception as exc:
                st.error(f"Authorization failed: {exc}")
                st.query_params.clear()
        st.stop()

    config_errors = get_oauth_config_errors()
    if config_errors:
        st.error(
            "Yahoo OAuth is not fully configured for this app. Fix the missing "
            "settings below, then reload the page."
        )
        for err in config_errors:
            st.code(err)
        st.caption(
            "On Streamlit Cloud, add these values in the app Secrets settings. "
            "The redirect URI must exactly match the Yahoo Developer app."
        )
        st.stop()

    st.info(
        "**First-time setup:** This app needs access to your Yahoo Fantasy league. "
        "Authorize with Yahoo, copy the verification code Yahoo shows, then paste it below."
    )

    auth_url = get_auth_url(redirect_uri=OOB_REDIRECT_URI)

    st.markdown("### Authorization Steps")
    st.markdown(
        f"**Step 1 →** [Click here to authorize with Yahoo]({auth_url})",
        unsafe_allow_html=True,
    )
    st.caption(
        "Make sure you're signed in to the Yahoo account that manages league **469.l.12591**. "
        "After you approve access, Yahoo will show a short verification code."
    )
    code = st.text_input(
        "Step 2 → Paste Yahoo's verification code",
        placeholder="Example: ca6s8b7",
    ).strip()
    if st.button("Complete Yahoo authorization", type="primary", use_container_width=True):
        if not code:
            st.warning("Paste the Yahoo verification code before continuing.")
        else:
            with st.spinner("Completing authorization…"):
                try:
                    exchange_code(code, redirect_uri=OOB_REDIRECT_URI)
                    load_dotenv(override=True)
                    st.success("✓ Authorization successful! Loading your league…")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Authorization failed: {exc}")

    with st.expander("🔍 Debug: view generated auth URL"):
        st.code(auth_url)

    st.stop()


# ─── Cached API calls ─────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def cached_week_stats(week: int) -> dict:
    return get_week_stats(week)


@st.cache_data(ttl=3600)
def cached_season_stats() -> dict:
    return get_season_stats()


@st.cache_data(ttl=600)
def cached_current_week() -> int:
    return get_current_week()


@st.cache_data(ttl=300)
def cached_all_weeks_stats(current_week: int) -> dict[int, dict]:
    all_stats: dict[int, dict] = {}
    for week in range(1, current_week + 1):
        try:
            stats = get_week_stats(week)
            if stats:
                all_stats[week] = stats
        except Exception:
            pass
    return all_stats


@st.cache_data(ttl=600)
def cached_week_managers(week: int) -> dict:
    return get_week_team_managers(week)


def _format_stat_value(cat: str, value: float) -> str:
    if cat in INT_STATS:
        return f"{value:.0f}"
    if cat == "AVG":
        return f"{value:.3f}"
    if cat in {"ERA", "WHIP"}:
        return f"{value:.2f}"
    return f"{value:.1f}"


def _leader_display_name(team: str, managers: dict) -> str:
    mgr = managers.get(team, {})
    nickname = mgr.get("nickname")
    if nickname and nickname != team:
        return f"{nickname} ({team})"
    return team


def _build_category_highs_rows(
    cats: list[str],
    leaders: dict[str, list[tuple[str, float]]],
    managers: dict,
) -> list[dict]:
    rows: list[dict] = []
    for cat in cats:
        tied = leaders.get(cat, [])
        if not tied:
            continue
        value = tied[0][1]
        names = [_leader_display_name(team, managers) for team, _ in tied]
        rows.append(
            {
                "Category": CAT_LABELS.get(cat, cat),
                "Leaders": ", ".join(names),
                "Value": _format_stat_value(cat, value),
            }
        )
    return rows


def _build_season_highs_rows(
    cats: list[str],
    records: dict[str, dict],
    managers_by_week: dict[int, dict],
) -> list[dict]:
    rows: list[dict] = []
    for cat in cats:
        record = records.get(cat)
        if not record:
            continue

        value = record["value"]
        entries = record["entries"]

        # Group by week so same-week ties read naturally
        by_week: dict[int, list[str]] = {}
        for week, team, _ in entries:
            managers = managers_by_week.get(week, {})
            by_week.setdefault(week, []).append(_leader_display_name(team, managers))

        leader_parts = [
            f"{', '.join(names)} (Week {week})"
            for week, names in sorted(by_week.items())
        ]

        rows.append(
            {
                "Category": CAT_LABELS.get(cat, cat),
                "Leaders": "; ".join(leader_parts),
                "Value": _format_stat_value(cat, value),
            }
        )
    return rows


def render_weekly_category_highs(current_week: int) -> None:
    st.markdown(
        '<p class="roto-subtitle">'
        "Best single-week performance in each category — ties are listed together"
        "</p>",
        unsafe_allow_html=True,
    )

    try:
        with st.spinner("Loading weekly stats across the season…"):
            all_week_stats = cached_all_weeks_stats(current_week)
    except Exception as exc:
        st.error(f"Error loading weekly stats: {exc}")
        return

    if not all_week_stats:
        st.info("No weekly stats available yet.")
        return

    season_records = compute_season_weekly_highs(all_week_stats)

    managers_by_week: dict[int, dict] = {}
    for week in all_week_stats:
        try:
            managers_by_week[week] = cached_week_managers(week)
        except Exception:
            managers_by_week[week] = {}

    st.subheader("Season Weekly Highs")
    st.caption(
        f"Best weekly total in each category across weeks 1–{current_week}."
    )

    batting_rows = _build_season_highs_rows(
        BATTING_CATS, season_records, managers_by_week
    )
    pitching_rows = _build_season_highs_rows(
        PITCHING_CATS, season_records, managers_by_week
    )

    if batting_rows:
        st.markdown("**Batting**")
        st.dataframe(
            pd.DataFrame(batting_rows),
            use_container_width=True,
            hide_index=True,
        )

    if pitching_rows:
        st.markdown("**Pitching**")
        st.dataframe(
            pd.DataFrame(pitching_rows),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.subheader("Category Leaders by Week")
    week_options = list(range(current_week, 0, -1))
    selected_week = st.selectbox(
        "Select week",
        week_options,
        format_func=lambda w: f"Week {w}",
        key="weekly_highs_week_select",
    )

    week_stats = all_week_stats.get(selected_week)
    if not week_stats:
        st.warning(f"No stats available for week {selected_week}.")
        return

    week_leaders = get_category_leaders(week_stats)
    try:
        week_managers = cached_week_managers(selected_week)
    except Exception:
        week_managers = {}

    st.caption(f"Top team(s) in each category for week {selected_week}.")

    week_batting = _build_category_highs_rows(
        BATTING_CATS, week_leaders, week_managers
    )
    week_pitching = _build_category_highs_rows(
        PITCHING_CATS, week_leaders, week_managers
    )

    if week_batting:
        st.markdown("**Batting**")
        st.dataframe(
            pd.DataFrame(week_batting),
            use_container_width=True,
            hide_index=True,
        )

    if week_pitching:
        st.markdown("**Pitching**")
        st.dataframe(
            pd.DataFrame(week_pitching),
            use_container_width=True,
            hide_index=True,
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(override=True)

    # On Streamlit Cloud there is no .env file — sync st.secrets into os.environ
    # so all downstream modules (auth, instant_db) can use os.getenv as normal.
    try:
        for _k, _v in st.secrets.items():
            if not os.environ.get(_k):
                os.environ[_k] = str(_v)
    except Exception:
        pass

    if not has_refresh_token():
        show_oauth_setup()
        return

    # ── Header ──────────────────────────────────────────────────────────────
    header_col, btn_col = st.columns([7, 1])
    with header_col:
        render_brand_header(
            "League 469.l.12591 · Head-to-head league, weekly roto side competition"
        )
    with btn_col:
        st.markdown("<div style='height:1.1rem'></div>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            for key in ("backfill_done", "winners"):
                st.session_state.pop(key, None)
            st.session_state["run_backfill"] = True
            st.rerun()

    # ── Resolve current week ─────────────────────────────────────────────────
    try:
        current_week = cached_current_week()
    except Exception as exc:
        st.error(f"Failed to connect to Yahoo API: {exc}")
        st.stop()

    # ── Load winners: backfill only when explicitly refreshed or new week found ──
    if st.session_state.pop("run_backfill", False):
        with st.spinner("Syncing historical week results…"):
            st.session_state["winners"] = backfill_weekly_winners(current_week)
            st.session_state["backfill_done"] = True
    elif "winners" not in st.session_state:
        # Fast path: load from JSON directly — no Yahoo API calls needed
        stored = load_winners()
        completed_weeks = set(str(w) for w in range(1, current_week))
        has_new_weeks = not completed_weeks.issubset(stored.keys())
        needs_migration = any("manager_guid" not in v for v in stored.values())
        if has_new_weeks or needs_migration:
            with st.spinner("Syncing historical week results…"):
                st.session_state["winners"] = backfill_weekly_winners(current_week)
        else:
            st.session_state["winners"] = stored
        st.session_state["backfill_done"] = True

    winners: dict = st.session_state.get("winners", load_winners())

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_week, tab_season, tab_history, tab_highs = st.tabs(
        [
            "📅 Current Week",
            "📊 Full Season Roto",
            "🏆 Previous Winners",
            "📈 Weekly Category Highs",
        ]
    )

    # ── Tab 1: This Week ─────────────────────────────────────────────────────
    with tab_week:
        today = date.today()
        subtitle = (
            f"Week {current_week} · live data through {today.strftime('%B %d, %Y')}"
        )
        try:
            with st.spinner("Fetching this week's stats…"):
                week_stats = cached_week_stats(current_week)
            render_standings(week_stats, subtitle)
        except Exception as exc:
            st.error(f"Error loading week {current_week} data: {exc}")

    # ── Tab 2: Full Season ───────────────────────────────────────────────────
    with tab_season:
        yesterday = date.today() - timedelta(days=1)
        subtitle = (
            f"Season stats through {yesterday.strftime('%B %d, %Y')} — updated nightly"
        )
        try:
            with st.spinner("Fetching season stats…"):
                season_stats = cached_season_stats()
            render_standings(season_stats, subtitle)
        except Exception as exc:
            st.error(f"Error loading season stats: {exc}")

    # ── Tab 3: Weekly Winners ────────────────────────────────────────────────
    with tab_history:
        st.subheader("Weekly Winners")

        if not winners:
            st.info(
                "No completed weeks yet. "
                "The first winner will appear here after week 1 is finished."
            )
        else:
            # ── Manager leaderboard ──────────────────────────────────────────
            from collections import Counter

            win_counts = Counter(
                info.get("manager_name") or info["team"]
                for info in winners.values()
            )
            leaderboard_df = pd.DataFrame(
                [
                    {"Rank": i + 1, "Manager": name, "Wins": count}
                    for i, (name, count) in enumerate(win_counts.most_common())
                ]
            )
            st.subheader("Manager Leaderboard")
            st.dataframe(leaderboard_df, use_container_width=True, hide_index=True)
            st.divider()

            if "selected_winner_week" not in st.session_state:
                st.session_state["selected_winner_week"] = None

            sorted_weeks = sorted(winners.keys(), key=int, reverse=True)
            left_col, right_col = st.columns(2)
            cols = [left_col, right_col]

            for idx, week_str in enumerate(sorted_weeks):
                info = winners[week_str]
                manager_display = info.get("manager_name") or info["team"]
                team_display = info["team"]
                # Only show team name in parens when it differs from the manager display name
                name_line = (
                    f'🏆 {manager_display} '
                    f'<span style="color:#9ca3af;font-size:0.9rem">({team_display})</span>'
                    if manager_display != team_display
                    else f"🏆 {manager_display}"
                )
                with cols[idx % 2]:
                    st.markdown(
                        f"""
                        <div class="winner-card">
                            <p class="week-label">Week {week_str}</p>
                            <p class="team-name">{name_line}</p>
                            <p class="score-line">
                                Score: <strong>{info["score"]:.1f}</strong> / 120
                                &nbsp;·&nbsp;
                                Bat: {info["batting"]:.1f}
                                &nbsp;·&nbsp;
                                Pitch: {info["pitching"]:.1f}
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    is_selected = st.session_state["selected_winner_week"] == week_str
                    btn_label = "▲ Hide Stats" if is_selected else "📊 View Stats"
                    if st.button(btn_label, key=f"btn_week_{week_str}", use_container_width=True):
                        st.session_state["selected_winner_week"] = None if is_selected else week_str
                        st.rerun()

            # ── Stats panel for the selected week ───────────────────────────
            sel_week = st.session_state.get("selected_winner_week")
            if sel_week is not None:
                st.divider()
                sel_info = winners[sel_week]
                manager_display = sel_info.get("manager_name") or sel_info["team"]
                team_display = sel_info["team"]
                panel_title = (
                    f"Week {sel_week} · {manager_display} ({team_display})"
                    if manager_display != team_display
                    else f"Week {sel_week} · {manager_display}"
                )
                st.subheader(panel_title)
                try:
                    with st.spinner(f"Loading week {sel_week} stats…"):
                        week_data = cached_week_stats(int(sel_week))
                    if week_data:
                        roto_df = calculate_roto(week_data)
                        if not roto_df.empty:
                            st.markdown("**Roto Standings**")
                            st.dataframe(
                                _standings_styler(roto_df),
                                use_container_width=True,
                                hide_index=True,
                            )
                            st.markdown("**Raw Stats**")
                            st.dataframe(
                                _raw_stats_styler(roto_df),
                                use_container_width=True,
                                hide_index=True,
                            )
                        else:
                            st.warning("Could not calculate standings for this week.")
                    else:
                        st.warning("No data available for this week.")
                except Exception as exc:
                    st.error(f"Error loading week {sel_week} stats: {exc}")

    # ── Tab 4: Weekly Category Highs ─────────────────────────────────────────
    with tab_highs:
        render_weekly_category_highs(current_week)


main()
