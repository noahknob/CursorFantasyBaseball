"""
Fantasy Baseball Roto Standings — Streamlit app.

Tabs:
  1. This Week    – live weekly roto standings + raw stats
  2. Full Season  – cumulative season roto standings + raw stats
  3. Weekly Winners – cards for each completed week's winner
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
from roto import ALL_CATS, BATTING_CATS, PITCHING_CATS, calculate_roto
from yahoo_api import (
    get_current_week,
    get_league_managers,
    get_season_stats,
    get_week_stats,
    get_week_team_managers,
)

INT_STATS = {"R", "HR", "RBI", "SB", "XBH", "W", "SV", "K", "QS"}

# ─── Page config & global CSS ─────────────────────────────────────────────────

st.set_page_config(
    page_title="Fantasy Baseball Roto",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    /* ── Header ──────────────────────────────── */
    .roto-header {
        background: #1a1a2e;
        padding: 1.4rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.25rem;
    }
    .roto-header h1 {
        color: white;
        margin: 0;
        font-size: 1.9rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .roto-header p {
        color: #9ca3af;
        margin: 0.3rem 0 0 0;
        font-size: 0.9rem;
    }

    /* ── Subtitles ───────────────────────────── */
    .roto-subtitle {
        color: #6b7280;
        font-size: 0.88rem;
        font-style: italic;
        margin-bottom: 0.75rem;
    }

    /* ── Winner cards ────────────────────────── */
    .winner-card {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.8rem;
        border-left: 4px solid #f59e0b;
    }
    .winner-card .week-label {
        color: #f59e0b;
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 0 0 0.2rem 0;
    }
    .winner-card .team-name {
        color: white;
        font-size: 1.25rem;
        font-weight: 700;
        margin: 0 0 0.35rem 0;
    }
    .winner-card .score-line {
        color: #9ca3af;
        font-size: 0.85rem;
        margin: 0;
    }
    .winner-card .score-line strong {
        color: #e5e7eb;
    }

    /* ── Auth setup card ─────────────────────── */
    .auth-card {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 2rem;
        max-width: 560px;
        margin: 3rem auto;
        border: 1px solid #2d2d4e;
    }
    .auth-card h2 { color: white; margin: 0 0 0.5rem 0; }
    .auth-card p  { color: #9ca3af; margin: 0 0 1.5rem 0; }
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


def _resolve_manager_name(guid: str | None, nickname: str, manager_profiles: dict) -> str:
    """Return the best available display name for a manager."""
    if guid:
        profile = manager_profiles.get(guid, {})
        first_name = profile.get("first_name", "")
        if first_name and first_name != guid:
            return first_name
    return nickname or guid or ""


def backfill_weekly_winners(current_week: int) -> dict:
    """
    For every completed week (1 … current_week-1) not yet in the JSON,
    fetch stats, calculate roto, and persist the winner.
    Also migrates existing entries that are missing manager_guid.
    Returns the updated winners dict.
    """
    winners = load_winners()
    changed = False

    # Resolve real names from Social API (falls back gracefully per manager)
    try:
        manager_profiles = cached_league_managers()
    except Exception:
        manager_profiles = {}

    for week in range(1, current_week):
        week_str = str(week)

        # Migration: backfill manager info for existing entries that lack it
        if week_str in winners and "manager_guid" not in winners[week_str]:
            try:
                team_managers = get_week_team_managers(week)
                team_name = winners[week_str]["team"]
                mgr_info = team_managers.get(team_name, {})
                guid = mgr_info.get("guid")
                nickname = mgr_info.get("nickname", "")
                winners[week_str]["manager_guid"] = guid
                winners[week_str]["manager_name"] = _resolve_manager_name(
                    guid, nickname, manager_profiles
                ) or team_name
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

            # Fetch manager GUID from scoreboard and resolve real name
            manager_guid = None
            manager_name = team_name
            try:
                team_managers = get_week_team_managers(week)
                mgr_info = team_managers.get(team_name, {})
                manager_guid = mgr_info.get("guid")
                nickname = mgr_info.get("nickname", "")
                manager_name = _resolve_manager_name(
                    manager_guid, nickname, manager_profiles
                ) or team_name
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

def show_oauth_setup() -> None:
    st.markdown(
        """
        <div class="roto-header">
            <h1>⚾ Fantasy Baseball Roto Standings</h1>
            <p>One-time Yahoo authorization required</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

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


@st.cache_data(ttl=3600)
def cached_league_managers() -> dict:
    return get_league_managers()


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
        st.markdown(
            """
            <div class="roto-header">
                <h1>⚾ Fantasy Baseball Roto Standings</h1>
                <p>League 469.l.12591 · Head-to-Head league, weekly roto side competition</p>
            </div>
            """,
            unsafe_allow_html=True,
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
    tab_week, tab_season, tab_history = st.tabs(
        ["📅 Current Week", "📊 Full Season Roto", "🏆 Previous Winners"]
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


main()
