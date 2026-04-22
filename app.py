"""
Fantasy Baseball Roto Standings — Streamlit app.

Tabs:
  1. This Week    – live weekly roto standings + raw stats
  2. Full Season  – cumulative season roto standings + raw stats
  3. Weekly Winners – cards for each completed week's winner
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from auth import exchange_code, get_auth_url, has_refresh_token
from roto import ALL_CATS, BATTING_CATS, PITCHING_CATS, calculate_roto
from yahoo_api import get_current_week, get_season_stats, get_week_stats

# ─── Constants ────────────────────────────────────────────────────────────────

WINNERS_FILE = Path(__file__).parent / "weekly_winners.json"

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
    if WINNERS_FILE.exists():
        try:
            return json.loads(WINNERS_FILE.read_text())
        except Exception:
            pass
    return {}


def save_winners(data: dict) -> None:
    WINNERS_FILE.write_text(json.dumps(data, indent=2))


def backfill_weekly_winners(current_week: int) -> dict:
    """
    For every completed week (1 … current_week-1) not yet in the JSON,
    fetch stats, calculate roto, and persist the winner.
    Returns the updated winners dict.
    """
    winners = load_winners()
    changed = False

    for week in range(1, current_week):
        if str(week) in winners:
            continue
        try:
            stats = get_week_stats(week)
            if not stats:
                continue
            roto_df = calculate_roto(stats)
            if roto_df.empty:
                continue
            top = roto_df.iloc[0]
            winners[str(week)] = {
                "team": top["Team"],
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

    st.info(
        "**First-time setup:** This app needs access to your Yahoo Fantasy league. "
        "Complete the one-time authorization below — it takes about 30 seconds."
    )

    auth_url = get_auth_url()

    st.markdown("### Authorization Steps")
    st.markdown(
        f"**Step 1 →** [Click here to open Yahoo's authorization page]({auth_url})",
        unsafe_allow_html=True,
    )
    st.caption(
        "Make sure you're signed in to the Yahoo account that manages league **469.l.12591**."
    )
    st.markdown("**Step 2 →** Yahoo will display a short verification code. Copy it.")

    code = st.text_input("**Step 3 →** Paste the verification code here:", key="oauth_code")
    if st.button("Complete Authorization", type="primary") and code:
        with st.spinner("Exchanging code for tokens…"):
            try:
                exchange_code(code.strip())
                load_dotenv(override=True)
                st.success("✓ Authorization successful! Loading your league…")
                st.rerun()
            except Exception as exc:
                st.error(f"Authorization failed: {exc}")

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


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(override=True)

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
            st.rerun()

    # ── Resolve current week ─────────────────────────────────────────────────
    try:
        current_week = cached_current_week()
    except Exception as exc:
        st.error(f"Failed to connect to Yahoo API: {exc}")
        st.stop()

    # ── Backfill weekly winners (once per session) ───────────────────────────
    if "backfill_done" not in st.session_state:
        with st.spinner("Syncing historical week results…"):
            st.session_state["winners"] = backfill_weekly_winners(current_week)
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
            if "selected_winner_week" not in st.session_state:
                st.session_state["selected_winner_week"] = None

            sorted_weeks = sorted(winners.keys(), key=int, reverse=True)
            left_col, right_col = st.columns(2)
            cols = [left_col, right_col]

            for idx, week_str in enumerate(sorted_weeks):
                info = winners[week_str]
                with cols[idx % 2]:
                    st.markdown(
                        f"""
                        <div class="winner-card">
                            <p class="week-label">Week {week_str}</p>
                            <p class="team-name">🏆 {info["team"]}</p>
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
                winner_name = winners[sel_week]["team"]
                st.subheader(f"Week {sel_week} · {winner_name}")
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
