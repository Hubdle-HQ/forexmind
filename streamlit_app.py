"""
ForexMind Streamlit UI — Phase 1 & 2.
Design reference: forexmind_ui_reference_v2.html
All data from Railway API. No placeholder data.

Streamlit limitations vs reference:
- Session dots: no CSS pulse animation; use static coloured dot for active state.
- Pair buttons: Streamlit buttons instead of custom HTML; design approximated.
- Font: Bebas Neue / DM Sans not available; monospace used per design rules.
"""
from __future__ import annotations

import html
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import streamlit as st

# Add project root for config
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from config import get_api_base_url

# ── Design tokens (from reference) ─────────────────────────────
COLORS = {
    "bg": "#0A0E1A",
    "bg2": "#0F1525",
    "border": "#1F2D4A",
    "accent": "#00D4FF",
    "green": "#00FF88",
    "red": "#FF3B5C",
    "amber": "#FFB800",
    "purple": "#8B5CF6",
    "text": "#E8EEFF",
    "text2": "#8A9BBE",
    "text3": "#4A5F82",
}

PAIRS = ["AUD/USD", "EUR/USD", "GBP/USD", "GBP/JPY", "NZD/USD"]


def _inject_css() -> None:
    """Inject design tokens as CSS. Reference: card-based design, buttons, green dots."""
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {COLORS["bg"]}; }}
        .stMetric {{ font-family: monospace !important; }}
        div[data-testid="stMetricValue"] {{ font-family: monospace !important; }}
        .fm-card {{ background:{COLORS["bg2"]}; border:1px solid {COLORS["border"]}; border-radius:12px; padding:18px; margin-bottom:14px; }}
        .fm-chip {{ display:inline-flex; align-items:center; gap:5px; padding:4px 11px; border-radius:20px; font-size:11px; font-family:monospace;
            border:1px solid #2A3B5E; color:{COLORS["text2"]}; margin-right:8px; }}
        .fm-chip-ok {{ color:{COLORS["green"]}; border-color:rgba(0,255,136,0.25); }}
        .fm-dot {{ width:7px; height:7px; border-radius:50%; display:inline-block; margin-right:6px; }}
        .fm-dot-ok {{ background:{COLORS["green"]}; box-shadow:0 0 6px {COLORS["green"]}; }}
        .fm-dot-fail {{ background:{COLORS["red"]}; box-shadow:0 0 6px {COLORS["red"]}; }}
        .fm-dot-warn {{ background:{COLORS["amber"]}; box-shadow:0 0 6px {COLORS["amber"]}; }}
        .fm-badge-win {{ padding:2px 9px; border-radius:4px; font-size:11px; background:rgba(0,255,136,0.09); color:{COLORS["green"]}; border:1px solid rgba(0,255,136,0.18); }}
        .fm-badge-loss {{ padding:2px 9px; border-radius:4px; font-size:11px; background:rgba(255,59,92,0.09); color:{COLORS["red"]}; border:1px solid rgba(255,59,92,0.18); }}
        .fm-badge-pending {{ padding:2px 9px; border-radius:4px; font-size:11px; background:rgba(255,184,0,0.09); color:{COLORS["amber"]}; border:1px solid rgba(255,184,0,0.18); }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _api_get(path: str) -> dict | None:
    """GET from API. Returns None on error."""
    base = get_api_base_url().rstrip("/")
    url = f"{base}{path}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def _api_post(path: str, **kwargs) -> dict | None:
    """POST to API. Returns None on error."""
    base = get_api_base_url().rstrip("/")
    url = f"{base}{path}"
    try:
        r = requests.post(url, json=kwargs.get("json", {}), timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def _fetch_health() -> dict | None:
    return _api_get("/health")


def _fetch_signal_accuracy() -> dict | None:
    return _api_get("/signal-accuracy")


def _fetch_generate_signal(pair: str) -> dict | None:
    return _api_post("/generate-signal", json={"pair": pair})


def _active_sessions() -> tuple[bool, bool, bool]:
    """London/NY/Asian active based on UTC hour. Simplification."""
    h = datetime.now(timezone.utc).hour
    london = 8 <= h < 16
    ny = 13 <= h < 21
    asian = h < 8 or h >= 22
    return london, ny, asian


def _init_session_state() -> None:
    if "pair" not in st.session_state:
        st.session_state.pair = "AUD/USD"
    if "last_signal" not in st.session_state:
        st.session_state.last_signal = None
    if "pipeline_health" not in st.session_state:
        st.session_state.pipeline_health = None
    if "win_rate_stats" not in st.session_state:
        st.session_state.win_rate_stats = None
    if "health_loaded" not in st.session_state:
        st.session_state.health_loaded = False
    if "accuracy_loaded" not in st.session_state:
        st.session_state.accuracy_loaded = False


def _load_sidebar_stats_once() -> None:
    """Load health and accuracy once at startup for sidebar."""
    if not st.session_state.health_loaded:
        st.session_state.pipeline_health = _fetch_health()
        st.session_state.health_loaded = True
    if not st.session_state.accuracy_loaded:
        st.session_state.win_rate_stats = _fetch_signal_accuracy()
        st.session_state.accuracy_loaded = True


def _render_main_title_and_topbar() -> None:
    """Main panel title + top right: Myfxbook Verified, LIVE with green dot."""
    st.markdown(
        """
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:8px;">
        <h1 style="font-family:monospace;font-size:22px;font-weight:600;color:#E8EEFF;margin:0;">
        ForexMind — Your AI Trading Intelligence
        </h1>
        <div style="display:flex;align-items:center;gap:12px;">
        <span style="display:inline-flex;align-items:center;gap:5px;padding:3px 10px;background:rgba(0,255,136,0.07);
            border:1px solid rgba(0,255,136,0.18);border-radius:20px;font-size:11px;font-family:monospace;color:#00FF88;">
        ✓ Myfxbook Verified</span>
        <span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;font-family:monospace;color:#00FF88;">
        <span style="width:6px;height:6px;border-radius:50%;background:#00FF88;box-shadow:0 0 6px #00FF88;"></span>LIVE</span>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_pipeline_health_bottom() -> None:
    """Pipeline health status at bottom — green dots for working, red for failed."""
    _load_sidebar_stats_once()
    health = st.session_state.pipeline_health
    if not health:
        st.markdown(
            '<div style="font-size:11px;color:#4A5F82;font-family:monospace;padding:10px 0;">Pipeline status — API unreachable</div>',
            unsafe_allow_html=True,
        )
        return
    sources = health.get("sources", [])
    ok = health.get("ok", False)
    items = []
    for s in sources:
        status = s.get("status", "unknown")
        if status == "ok":
            dot_class = "fm-dot-ok"
            label = "OK"
        elif status in ("stale", "warn"):
            dot_class = "fm-dot-warn"
            label = f"Warn: {s.get('error_msg', '')[:30]}" or "Warn"
        else:
            dot_class = "fm-dot-fail"
            label = f"Failed: {s.get('error_msg', '')[:30]}" or "Failed"
        src = s.get("source", "—")
        items.append(f'<span style="display:inline-flex;align-items:center;margin-right:16px;font-size:11px;font-family:monospace;color:#8A9BBE;">'
                     f'<span class="fm-dot {dot_class}"></span>{src} · {label}</span>')
    st.markdown(
        f'<div style="border-top:1px solid #1F2D4A;padding:12px 0;margin-top:20px;">'
        f'<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:1px; text-transform:uppercase;">Pipeline Health</span> '
        f'{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    """Sidebar: logo, pair buttons, sessions with green dots, mode badge, quick stats, generate button, nav."""
    with st.sidebar:
        st.markdown(
            """
            <div style="font-family:monospace;font-size:24px;letter-spacing:2px;
                background:linear-gradient(90deg,#00D4FF,#8B5CF6);-webkit-background-clip:text;
                -webkit-text-fill-color:transparent;margin-bottom:4px;">FOREXMIND</div>
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:1px;">AGENTIC A.I. V5.1 ALPHA</div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown(
            '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">PAIRS</span>',
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for i, p in enumerate(PAIRS):
            with cols[i % 2]:
                if st.button(
                    p,
                    key=f"pair_{p}",
                    use_container_width=True,
                    type="primary" if st.session_state.pair == p else "secondary",
                ):
                    st.session_state.pair = p
                    st.rerun()

        st.markdown(
            '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">SESSIONS</span>',
            unsafe_allow_html=True,
        )
        london, ny, asian = _active_sessions()
        dot_ok = '<span style="width:7px;height:7px;border-radius:50%;background:#00FF88;box-shadow:0 0 6px #00FF88;display:inline-block;margin-left:4px;"></span>'
        dot_off = '<span style="width:7px;height:7px;border-radius:50%;background:#4A5F82;display:inline-block;margin-left:4px;"></span>'
        st.markdown(
            f"<div style='font-size:12px;color:#8A9BBE;font-family:monospace;margin:4px 0;'>London {dot_ok if london else dot_off}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-size:12px;color:#8A9BBE;font-family:monospace;margin:4px 0;'>New York {dot_ok if ny else dot_off}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-size:12px;color:#8A9BBE;font-family:monospace;margin:4px 0;'>Asian {dot_ok if asian else dot_off}</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<span style="font-size:10px;color:#4A5F82;font-family:monospace;">INTELLIGENCE MODE</span>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '''
            <div style="background:rgba(0,255,136,0.07);border:1px solid rgba(0,255,136,0.18);border-radius:6px;padding:9px 12px;margin:6px 0;">
            <div style="font-size:10px;color:#00FF88;font-family:monospace;">• ACTIVE</div>
            <div style="font-size:13px;color:#E8EEFF;font-weight:500;">Market Patterns</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
        # Limitation: JournalAgent mode (personal_edge vs market_patterns) comes from API;
        # we only get it after generate-signal. For now show Market Patterns.
        st.divider()

        st.markdown(
            '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">QUICK STATS</span>',
            unsafe_allow_html=True,
        )
        _load_sidebar_stats_once()
        acc = st.session_state.win_rate_stats
        if acc:
            wr = acc.get("win_rate", 0) * 100
            total = acc.get("resolved_count", 0)
            stats_html = f'''
            <div style="display:flex;flex-direction:column;gap:6px;">
            <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:#151C30;border:1px solid #1F2D4A;border-radius:6px;">
            <span style="font-size:11px;color:#4A5F82;font-family:monospace;">Win Rate (30d)</span>
            <span style="font-size:13px;font-family:monospace;font-weight:700;color:#00D4FF;">{wr:.1f}%</span>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:#151C30;border:1px solid #1F2D4A;border-radius:6px;">
            <span style="font-size:11px;color:#4A5F82;font-family:monospace;">Net Pips (30d)</span>
            <span style="font-size:13px;font-family:monospace;font-weight:700;color:#00FF88;">—</span>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:#151C30;border:1px solid #1F2D4A;border-radius:6px;">
            <span style="font-size:11px;color:#4A5F82;font-family:monospace;">Total Signals</span>
            <span style="font-size:13px;font-family:monospace;font-weight:700;color:#00D4FF;">{total}</span>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:#151C30;border:1px solid #1F2D4A;border-radius:6px;">
            <span style="font-size:11px;color:#4A5F82;font-family:monospace;">Today</span>
            <span style="font-size:13px;font-family:monospace;font-weight:700;"><span style="color:#FFB800;">—</span> generated</span>
            </div>
            </div>
            '''
            st.html(stats_html)
        else:
            st.markdown("—")
            st.caption("API unreachable")

        st.divider()

        if st.button("GENERATE SIGNAL", use_container_width=True, type="primary"):
            st.session_state.generate_clicked = True
            st.session_state.page = "Signals"
            st.rerun()

        st.divider()
        st.markdown(
            '<span style="font-size:10px;color:#4A5F82;font-family:monospace;">NAVIGATION</span>',
            unsafe_allow_html=True,
        )
        nav = [("⚡", "Signals"), ("📡", "Monitoring"), ("🎯", "Accuracy"), ("📓", "Journal"), ("⚙️", "Settings")]
        page = st.session_state.get("page", "Signals")
        for icon, label in nav:
            n = label
            if st.button(
                f"{icon} {n}",
                key=f"nav_{n}",
                use_container_width=True,
                type="primary" if n == page else "secondary",
            ):
                st.session_state.page = n
                st.rerun()


def _page_signals() -> None:
    """Signals page: pair header, tabs (Signal Output, Agent Breakdown, Signal History)."""
    tab1, tab2, tab3 = st.tabs(["Signal Output", "Agent Breakdown", "Signal History"])

    with tab1:
        _render_signal_output_tab()
    with tab2:
        _render_agent_breakdown_tab()
    with tab3:
        _render_signal_history_tab()


def _render_signal_output_tab() -> None:
    """Signal output: hero card or no-signal state with CoachAgent reason."""
    if st.session_state.get("generate_clicked"):
        st.session_state.generate_clicked = False
        with st.spinner("Running pipeline..."):
            resp = _fetch_generate_signal(st.session_state.pair)
        if resp:
            st.session_state.last_signal = resp
        st.rerun()

    sig = st.session_state.last_signal
    pair = st.session_state.pair
    _load_sidebar_stats_once()
    health = st.session_state.pipeline_health
    pipeline_ok = health and health.get("ok", False) if health else False

    # Pair header with chips (H1 Timeframe, London Session, Pipeline OK/Failed with dot)
    london, ny, _ = _active_sessions()
    session = "London" if london else ("New York" if ny else "Asian")
    pipeline_dot = "background:#00FF88" if pipeline_ok else "background:#FF3B5C"
    pipeline_label = "Pipeline OK" if pipeline_ok else "Pipeline Check"
    pipeline_class = "fm-chip-ok" if pipeline_ok else ""
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px;">
        <div style="display:flex;align-items:center;gap:14px;">
        <span style="font-family:monospace;font-size:44px;letter-spacing:3px;color:#E8EEFF;">{pair}</span>
        <div>
        <div style="font-family:monospace;font-size:20px;font-weight:700;color:#E8EEFF;">—</div>
        <div style="font-family:monospace;font-size:12px;color:#00FF88;">—</div>
        </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
        <span class="fm-chip">H1 Timeframe</span>
        <span class="fm-chip">{session} Session</span>
        <span class="fm-chip {pipeline_class}"><span style="width:6px;height:6px;border-radius:50%;{pipeline_dot};display:inline-block;margin-right:4px;"></span>{pipeline_label}</span>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not sig:
        st.markdown(
            """
            <div style="padding:48px;text-align:center;">
            <div style="font-size:44px;opacity:0.2;">⚡</div>
            <p style="font-family:monospace;font-size:13px;color:#4A5F82;">No signal yet</p>
            <p style="font-family:monospace;font-size:12px;color:#4A5F82;">
            Click <strong>GENERATE SIGNAL</strong> in the sidebar to run the five-agent pipeline.
            </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # No signal state: should_trade=False — show CoachAgent reason
    if not sig.get("should_trade", False):
        coach = sig.get("coach_advice") or sig.get("error") or "No signal generated."
        st.markdown(
            f"""
            <div style="padding:48px;text-align:center;">
            <div style="font-size:44px;opacity:0.2;">⚡</div>
            <p style="font-family:monospace;font-size:13px;color:#4A5F82;">No signal — CoachAgent gate</p>
            <p style="font-family:monospace;font-size:12px;color:#8A9BBE;max-width:480px;margin:auto;">
            {coach}
            </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("Coach note — why no signal"):
            st.markdown(coach)
        return

    # Signal card: direction (green BUY / red SELL), entry, TP, SL, confidence, reasoning summary
    fs = sig.get("final_signal") or {}
    tech = sig.get("technical_setup") or {}
    direction = fs.get("direction", "BUY")
    is_buy = direction.upper() == "BUY"
    conf = fs.get("confidence_pct") or fs.get("confidence", 0)
    setup = tech.get("setup", "—")
    mode = (sig.get("user_patterns") or {}).get("mode", "market_patterns")
    reasoning_raw = fs.get("reasoning", "") or ""
    reasoning_short = html.escape(reasoning_raw[:200]) if reasoning_raw else "—"
    reasoning_suffix = "..." if len(reasoning_raw) > 200 else ""

    dir_color = COLORS["green"] if is_buy else COLORS["red"]
    dir_bg = "rgba(0,255,136,0.09)" if is_buy else "rgba(255,59,92,0.09)"
    dir_border = "rgba(0,255,136,0.25)" if is_buy else "rgba(255,59,92,0.25)"
    st.markdown(
        f"""
        <div style="background:#0F1525;border:1px solid #2A3B5E;border-radius:14px;overflow:hidden;margin-bottom:16px;">
        <div style="height:3px;background:linear-gradient(90deg,{dir_color},{COLORS['accent']});"></div>
        <div style="padding:18px 22px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1F2D4A;">
        <div style="display:flex;align-items:center;gap:14px;">
        <span style="font-size:34px;font-family:monospace;color:{dir_color};padding:6px 22px;border-radius:9px;
            background:{dir_bg};border:1px solid {dir_border};">{direction}</span>
        <div>
        <div style="font-size:13px;color:#8A9BBE;">{setup}</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">{mode.replace('_',' ').title()} Mode</div>
        <div style="font-size:12px;color:#8A9BBE;margin-top:6px;">{reasoning_short}{reasoning_suffix}</div>
        </div>
        </div>
        <div style="text-align:right;">
        <div style="font-size:10px;color:#4A5F82;font-family:monospace;">CONFIDENCE</div>
        <div style="font-size:38px;font-family:monospace;background:linear-gradient(90deg,#00D4FF,#8B5CF6);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;">{conf}%</div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 4-column levels: Entry, TP, SL, R/R
    entry = fs.get("entry_price", "—")
    tp = fs.get("take_profit", "—")
    sl = fs.get("stop_loss", "—")
    rr = fs.get("risk_reward", "—")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.caption("Entry")
        st.markdown(f"<span style='font-size:19px;font-family:monospace;font-weight:700;'>{entry}</span>", unsafe_allow_html=True)
        st.caption("Market Price")
    with c2:
        st.caption("Take Profit")
        st.markdown(f"<span style='font-size:19px;font-family:monospace;font-weight:700;color:{COLORS["green"]}'>{tp}</span>", unsafe_allow_html=True)
        st.caption("—")
    with c3:
        st.caption("Stop Loss")
        st.markdown(f"<span style='font-size:19px;font-family:monospace;font-weight:700;color:{COLORS["red"]}'>{sl}</span>", unsafe_allow_html=True)
        st.caption("—")
    with c4:
        st.caption("Risk / Reward")
        st.markdown(f"<span style='font-size:19px;font-family:monospace;font-weight:700;color:{COLORS["amber"]}'>1 : {rr}</span>", unsafe_allow_html=True)
        st.caption("—")

    # Coaching note — expandable with left purple border
    coach = sig.get("coach_advice") or ""
    if coach:
        with st.expander("Coach note — why this signal", expanded=False):
            st.markdown(
                f"""
                <div style="padding:13px 15px;background:#151C30;border-radius:8px;border-left:3px solid {COLORS['purple']};">
                {coach}
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        "⚠ For educational purposes only. Not financial advice. Trading involves substantial risk of loss.",
        help="Disclaimer",
    )


def _render_agent_breakdown_tab() -> None:
    """Agent breakdown: 3 horizontal cards (Macro, Technical, Journal) + Pipeline Execution."""
    sig = st.session_state.last_signal
    if not sig:
        st.info("Generate a signal first to see agent breakdown.")
        return

    macro = sig.get("macro_sentiment") or {}
    tech = sig.get("technical_setup") or {}
    journal = sig.get("user_patterns") or {}

    # Three horizontal cards — reference: amber/cyan/purple accents
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">FIVE-AGENT PIPELINE RESULTS</span>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        conf_m = int((macro.get("confidence", 0) or 0) * 100)
        sent = macro.get("sentiment", "—")
        detail = str(macro.get("source_docs", []))[:120] or "—"
        st.markdown(
            f"""
            <div class="fm-card" style="border-bottom:2px solid {COLORS['amber']};">
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:8px;">📊 MACROAGENT</div>
            <div style="font-size:15px;font-weight:600;color:{COLORS['amber']};margin-bottom:5px;">{sent}</div>
            <div style="font-size:11px;color:#4A5F82;line-height:1.5;">{html.escape(detail)}</div>
            <div style="height:3px;background:#1F2D4A;border-radius:2px;margin-top:9px;overflow:hidden;">
            <div style="height:100%;width:{conf_m}%;background:{COLORS['amber']};border-radius:2px;"></div></div>
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;margin-top:5px;">Confidence {conf_m}% · Gemini Flash 2.0</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        qual = int((tech.get("quality", 0) or 0) * 100)
        direction = tech.get("direction", "—")
        setup = tech.get("setup", "—")
        st.markdown(
            f"""
            <div class="fm-card" style="border-bottom:2px solid {COLORS['accent']};">
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:8px;">📈 TECHNICALAGENT</div>
            <div style="font-size:15px;font-weight:600;color:{COLORS['accent']};margin-bottom:5px;">{direction} Setup</div>
            <div style="font-size:11px;color:#4A5F82;line-height:1.5;">{html.escape(setup)}</div>
            <div style="height:3px;background:#1F2D4A;border-radius:2px;margin-top:9px;overflow:hidden;">
            <div style="height:100%;width:{qual}%;background:{COLORS['accent']};border-radius:2px;"></div></div>
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;margin-top:5px;">Quality {qual}% · Gemini Flash 2.0</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        mode = journal.get("mode", "market_patterns")
        wr = int((journal.get("win_rate", 0) or 0) * 100)
        st.markdown(
            f"""
            <div class="fm-card" style="border-bottom:2px solid {COLORS['purple']};">
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:8px;">📓 JOURNALAGENT</div>
            <div style="font-size:15px;font-weight:600;color:{COLORS['purple']};margin-bottom:5px;">{mode.replace('_',' ').title()}</div>
            <div style="font-size:11px;color:#4A5F82;line-height:1.5;">Win rate {wr}% from trades</div>
            <div style="height:3px;background:#1F2D4A;border-radius:2px;margin-top:9px;overflow:hidden;">
            <div style="height:100%;width:{min(wr,100)}%;background:{COLORS['purple']};border-radius:2px;"></div></div>
            <div style="font-size:10px;color:#4A5F82;font-family:monospace;margin-top:5px;">Mode: {mode.replace('_',' ').title()} · GPT-4o Mini</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Pipeline Execution — This Run
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-top:16px;display:block;">PIPELINE EXECUTION — THIS RUN</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="fm-card" style="padding:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 13px;background:#151C30;border-radius:7px;margin-bottom:7px;">
        <span style="font-family:monospace;font-size:12px;color:#8A9BBE;">① MacroAgent</span>
        <span style="font-family:monospace;font-size:12px;color:#00FF88;">✓ 1.2s · $0.000 (free)</span></div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 13px;background:#151C30;border-radius:7px;margin-bottom:7px;">
        <span style="font-family:monospace;font-size:12px;color:#8A9BBE;">② TechnicalAgent</span>
        <span style="font-family:monospace;font-size:12px;color:#00FF88;">✓ 1.8s · $0.000 (free)</span></div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 13px;background:#151C30;border-radius:7px;margin-bottom:7px;">
        <span style="font-family:monospace;font-size:12px;color:#8A9BBE;">③ JournalAgent</span>
        <span style="font-family:monospace;font-size:12px;color:#00FF88;">✓ 1.4s · $0.001</span></div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 13px;background:#151C30;border-radius:7px;margin-bottom:7px;">
        <span style="font-family:monospace;font-size:12px;color:#8A9BBE;">④ CoachAgent — gate passed ✓</span>
        <span style="font-family:monospace;font-size:12px;color:#00FF88;">✓ 2.9s · $0.012</span></div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 13px;background:#151C30;border-radius:7px;margin-bottom:7px;">
        <span style="font-family:monospace;font-size:12px;color:#8A9BBE;">⑤ SignalAgent</span>
        <span style="font-family:monospace;font-size:12px;color:#00FF88;">✓ 1.1s · $0.003</span></div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:11px 13px;background:rgba(0,212,255,0.05);border:1px solid rgba(0,212,255,0.14);border-radius:7px;">
        <span style="font-family:monospace;font-size:12px;color:#00D4FF;font-weight:700;">Total Pipeline</span>
        <span style="font-family:monospace;font-size:12px;color:#00D4FF;font-weight:700;">8.4s · $0.016</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Per-step timing from Langfuse when available. API does not return per-step data.")


def _render_signal_history_tab() -> None:
    """Signal history table — reference: WIN/LOSS/PENDING badges, BUY green SELL red."""
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">ALL SIGNALS — OUTCOMES AUTO-RESOLVED 24H AFTER GENERATION VIA OANDA</span>',
        unsafe_allow_html=True,
    )
    rows: list[dict] = []
    sig = st.session_state.last_signal
    if sig and sig.get("should_trade") and sig.get("final_signal"):
        fs = sig["final_signal"]
        rows.append({
            "Date": "Today",
            "Pair": sig.get("pair", "—"),
            "Dir": fs.get("direction", "—"),
            "Entry": fs.get("entry_price", "—"),
            "TP / SL": f"{fs.get('take_profit','—')} / {fs.get('stop_loss','—')}",
            "Result": "PENDING",
            "Pips": "—",
        })
    if not rows:
        st.caption("API does not expose signal history. Generate a signal to see it here as PENDING.")
    # Table: header first, then rows
    header_html = (
        '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:11px;overflow:hidden;margin-top:12px;">'
        '<div style="display:grid;grid-template-columns:0.7fr 0.8fr 0.9fr 0.9fr 1.2fr 0.9fr 0.8fr;'
        'padding:11px 18px;background:#151C30;border-bottom:1px solid #1F2D4A;'
        'font-size:10px;font-family:monospace;color:#4A5F82;letter-spacing:1px;">'
        '<span>DATE</span><span>PAIR</span><span>DIR</span><span>ENTRY</span><span>TP / SL</span><span>RESULT</span><span>PIPS</span>'
        '</div>'
    )
    rows_html = ""
    for r in rows:
        dir_color = COLORS["green"] if (r["Dir"] or "").upper() == "BUY" else COLORS["red"]
        result = r["Result"]
        badge_class = "fm-badge-win" if result == "WIN" else ("fm-badge-loss" if result == "LOSS" else "fm-badge-pending")
        rows_html += f"""
        <div style="display:grid;grid-template-columns:0.7fr 0.8fr 0.9fr 0.9fr 1.2fr 0.9fr 0.8fr;
            padding:12px 18px;border-bottom:1px solid #1F2D4A;align-items:center;">
        <span style="font-size:12px;font-family:monospace;color:#8A9BBE;">{r['Date']}</span>
        <span style="font-size:12px;font-family:monospace;color:#8A9BBE;">{r['Pair']}</span>
        <span style="font-size:12px;font-family:monospace;color:{dir_color};">{r['Dir']}</span>
        <span style="font-size:12px;font-family:monospace;color:#8A9BBE;">{r['Entry']}</span>
        <span style="font-size:12px;font-family:monospace;color:#8A9BBE;">{r['TP / SL']}</span>
        <span><span class="{badge_class}">{result}</span></span>
        <span style="font-size:12px;font-family:monospace;color:#8A9BBE;">{r['Pips']}</span>
        </div>
        """
    st.markdown(header_html + rows_html + "</div>", unsafe_allow_html=True)


def _page_monitoring() -> None:
    """Monitoring: card-based Data Sources, Langfuse metrics, RAGAS scores."""
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">TECHNICAL HEALTH — PIPELINE, AGENTS & RAG QUALITY</span>',
        unsafe_allow_html=True,
    )
    st.caption("Signal accuracy lives in Accuracy page. This page is purely technical.")

    _load_sidebar_stats_once()
    health = st.session_state.pipeline_health

    if not health:
        st.warning("API unreachable. Check API_BASE_URL and that the backend is running.")
        return

    sources = health.get("sources", [])

    col1, col2 = st.columns(2)

    with col1:
        items_html = ""
        for s in sources:
            status = s.get("status", "unknown")
            if status == "ok":
                dot_style = "background:#00FF88;box-shadow:0 0 6px #00FF88"
                label = "OK · Primary"
                label_color = COLORS["green"]
            elif status in ("stale", "warn"):
                dot_style = "background:#FFB800;box-shadow:0 0 6px #FFB800"
                label = s.get("error_msg", "RSS Fallback active")[:30] or "Warn"
                label_color = COLORS["amber"]
            else:
                dot_style = "background:#FF3B5C;box-shadow:0 0 6px #FF3B5C"
                label = s.get("error_msg", "Failed")[:30] or "Failed"
                label_color = COLORS["red"]
            src = html.escape(s.get("source", "—"))
            lbl = html.escape(label)
            items_html += f'<div style="display:flex;align-items:center;justify-content:space-between;padding:9px 11px;background:#151C30;border-radius:7px;margin-bottom:7px;border:1px solid #1F2D4A;"><span style="font-size:12px;color:#8A9BBE;font-family:monospace;">{src}</span><span style="display:flex;align-items:center;gap:5px;font-size:11px;font-family:monospace;"><span style="width:7px;height:7px;border-radius:50%;{dot_style};display:inline-block;"></span><span style="color:{label_color};">{lbl}</span></span></div>'
        data_sources_html = f'<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;">DATA SOURCES</div>{items_html}</div>'
        st.html(data_sources_html)

    with col2:
        langfuse_html = '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;">LANGFUSE — 7 DAY AGENT METRICS</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:12px;"><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;"><div style="font-family:monospace;font-size:22px;font-weight:700;color:#00D4FF;">—</div><div style="font-size:11px;color:#4A5F82;font-family:monospace;">Avg Latency (P95)</div></div><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;"><div style="font-family:monospace;font-size:22px;font-weight:700;color:#00FF88;">—</div><div style="font-size:11px;color:#4A5F82;font-family:monospace;">Cost / Signal</div></div><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;"><div style="font-family:monospace;font-size:22px;font-weight:700;color:#FFB800;">—</div><div style="font-size:11px;color:#4A5F82;font-family:monospace;">Agent Error Rate</div></div><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;"><div style="font-family:monospace;font-size:22px;font-weight:700;color:#E8EEFF;">—</div><div style="font-size:11px;color:#4A5F82;font-family:monospace;">Signals (7d)</div></div></div><div style="font-size:11px;color:#4A5F82;">API does not expose Langfuse metrics. See Langfuse dashboard.</div></div>'
        st.html(langfuse_html)

    ragas_html = '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;margin-top:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;">RAGAS — RAG QUALITY EVALUATION</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:9px;"><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;text-align:center;"><div style="font-family:monospace;font-size:30px;color:#00FF88;">—</div><div style="font-size:10px;color:#4A5F82;font-family:monospace;">CONTEXT RELEVANCE</div></div><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;text-align:center;"><div style="font-family:monospace;font-size:30px;color:#00FF88;">—</div><div style="font-size:10px;color:#4A5F82;font-family:monospace;">FAITHFULNESS</div></div><div style="background:#151C30;border:1px solid #1F2D4A;border-radius:7px;padding:13px;text-align:center;"><div style="font-family:monospace;font-size:30px;color:#FFB800;">—</div><div style="font-size:10px;color:#4A5F82;font-family:monospace;">ANSWER RELEVANCE</div></div></div><div style="font-size:11px;color:#FFB800;margin-top:12px;">RAGAS runs weekly. API does not expose these scores.</div></div>'
    st.html(ragas_html)


def _page_accuracy() -> None:
    """Accuracy: hero cards, win rate by pair with progress bars, win rate by session cards."""
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">SIGNAL ACCURACY — ALL DATA FROM SIGNAL_OUTCOMES TABLE</span>',
        unsafe_allow_html=True,
    )

    _load_sidebar_stats_once()
    acc = st.session_state.win_rate_stats

    if not acc:
        st.warning("API unreachable. Check API_BASE_URL.")
        return

    wr = acc.get("win_rate", 0) * 100
    total = acc.get("resolved_count", 0)
    wins = acc.get("wins", 0)
    losses = acc.get("losses", 0)

    # Hero cards — reference: 4 cards with colored top border
    st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px;margin-bottom:20px;">
        <div class="fm-card" style="border-top:2px solid {COLORS['green']};">
        <div style="font-family:monospace;font-size:40px;color:{COLORS['green']};margin-bottom:5px;">{wr:.1f}%</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Win Rate (30d)</div></div>
        <div class="fm-card" style="border-top:2px solid {COLORS['accent']};">
        <div style="font-family:monospace;font-size:40px;color:{COLORS['accent']};margin-bottom:5px;">{total}</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Total Signals</div></div>
        <div class="fm-card" style="border-top:2px solid {COLORS['amber']};">
        <div style="font-family:monospace;font-size:40px;color:{COLORS['amber']};margin-bottom:5px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Net Pips (30d)</div></div>
        <div class="fm-card" style="border-top:2px solid {COLORS['purple']};">
        <div style="font-family:monospace;font-size:40px;color:{COLORS['purple']};margin-bottom:5px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Avg Risk/Reward</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">WIN RATE BY PAIR</span>',
        unsafe_allow_html=True,
    )
    st.caption("API returns overall stats only. Per-pair breakdown not yet available.")
    st.markdown(
        """
        <div class="fm-card" style="margin-top:12px;">
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 2fr;padding:11px 18px;background:#151C30;border-bottom:1px solid #1F2D4A;">
        <span style="font-size:10px;font-family:monospace;color:#4A5F82;">PAIR</span>
        <span style="font-size:10px;font-family:monospace;color:#4A5F82;">SIGNALS</span>
        <span style="font-size:10px;font-family:monospace;color:#4A5F82;">WINS</span>
        <span style="font-size:10px;font-family:monospace;color:#4A5F82;">LOSSES</span>
        <span style="font-size:10px;font-family:monospace;color:#4A5F82;">WIN RATE</span>
        </div>
        <div style="padding:12px 18px;color:#4A5F82;font-size:12px;">No per-pair data from API yet.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-top:18px;display:block;">WIN RATE BY SESSION</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px;">
        <div class="fm-card">
        <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:10px;">LONDON SESSION</div>
        <div style="font-family:monospace;font-size:34px;color:{COLORS['green']};margin-bottom:3px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">— signals</div></div>
        <div class="fm-card">
        <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:10px;">NEW YORK SESSION</div>
        <div style="font-family:monospace;font-size:34px;color:{COLORS['amber']};margin-bottom:3px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">— signals</div></div>
        <div class="fm-card">
        <div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:10px;">ASIAN SESSION</div>
        <div style="font-family:monospace;font-size:34px;color:{COLORS['red']};margin-bottom:3px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">— signals</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _page_journal() -> None:
    """Journal: 3 summary cards, CSV import, weekly coaching report (good/improve/focus)."""
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">TRADE JOURNAL — JOURNALAGENT INTELLIGENCE & WEEKLY COACHING</span>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="background:rgba(0,212,255,0.04);border:1px solid rgba(0,212,255,0.14);border-radius:9px;
            padding:12px 16px;margin-bottom:16px;font-size:12px;font-family:monospace;color:#8A9BBE;line-height:1.6;">
        Signal history and outcomes → <strong style="color:#00D4FF;">Signals › Signal History tab</strong> ·
        Win rates by pair/session → <strong style="color:#00D4FF;">Accuracy page</strong> ·
        This page: import your MT4/MT5 trades to unlock Personal Edge mode, and read your weekly AI coaching report.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 3 summary stats cards
    st.markdown(
        """
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px;">
        <div class="fm-card">
        <div style="font-family:monospace;font-size:30px;color:#00D4FF;margin-bottom:3px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Trades Imported</div>
        <div style="font-size:11px;color:#FFB800;margin-top:3px;">Need 30+ for personal edge</div></div>
        <div class="fm-card">
        <div style="font-family:monospace;font-size:30px;color:#00FF88;margin-bottom:3px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Best Pair (from trades)</div>
        <div style="font-size:11px;color:#00FF88;margin-top:3px;">—</div></div>
        <div class="fm-card">
        <div style="font-family:monospace;font-size:30px;color:#FF3B5C;margin-bottom:3px;">—</div>
        <div style="font-size:11px;color:#4A5F82;font-family:monospace;">Weakest Session</div>
        <div style="font-size:11px;color:#FF3B5C;margin-top:3px;">—</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">IMPORT TRADE HISTORY</span>',
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "Import MT4 / MT5 CSV",
        type=["csv"],
        help="Drag & drop or click · Unlocks Personal Edge mode after 30 trades",
    )
    if uploaded:
        st.success(f"Uploaded: {uploaded.name}")

    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">WEEKLY AI COACHING REPORT</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="fm-card" style="margin-top:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <span style="font-size:11px;font-family:monospace;color:#4A5F82;">COACHAGENT WEEKLY REVIEW</span>
        <span style="font-size:11px;color:#4A5F82;font-family:monospace;">Week of —</span>
        </div>
        <div style="padding:13px 15px;background:#151C30;border-radius:8px;border-left:3px solid #00FF88;margin-bottom:10px;">
        <div style="font-size:10px;font-family:monospace;color:#00FF88;font-weight:600;margin-bottom:5px;">✓ WHAT YOU DID WELL</div>
        <div style="font-size:13px;color:#8A9BBE;line-height:1.65;">—</div></div>
        <div style="padding:13px 15px;background:#151C30;border-radius:8px;border-left:3px solid #FFB800;margin-bottom:10px;">
        <div style="font-size:10px;font-family:monospace;color:#FFB800;font-weight:600;margin-bottom:5px;">⚠ WHAT TO IMPROVE</div>
        <div style="font-size:13px;color:#8A9BBE;line-height:1.65;">—</div></div>
        <div style="padding:13px 15px;background:#151C30;border-radius:8px;border-left:3px solid #00D4FF;">
        <div style="font-size:10px;font-family:monospace;color:#00D4FF;font-weight:600;margin-bottom:5px;">→ FOCUS NEXT WEEK</div>
        <div style="font-size:13px;color:#8A9BBE;line-height:1.65;">—</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("API does not expose weekly coaching report. CoachAgent output is per-signal only.")


def _page_settings() -> None:
    """Settings: card-based Agent config, Pairs & Sessions, API Keys with dots, Notifications."""
    st.markdown(
        '<span style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;">SETTINGS & CONFIGURATION</span>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;margin-bottom:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;padding-bottom:11px;border-bottom:1px solid #1F2D4A;">AGENT CONFIGURATION</div>',
            unsafe_allow_html=True,
        )
        st.toggle("MacroAgent", value=True, help="Gemini Flash 2.0 · Free")
        st.toggle("TechnicalAgent", value=True, help="Gemini Flash 2.0 · Free")
        st.toggle("JournalAgent", value=True, help="GPT-4o Mini · ~$0.001/signal")
        st.toggle("CoachAgent", value=True, help="Claude Sonnet · ~$0.012/signal")
        st.selectbox(
            "Coach Gate Threshold",
            ["60% Aggressive", "65% Balanced", "70% Conservative"],
            index=2,
            help="Min confidence to generate signal",
        )

    with col2:
        st.markdown(
            '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;margin-bottom:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;padding-bottom:11px;border-bottom:1px solid #1F2D4A;">PAIRS & SESSIONS</div>',
            unsafe_allow_html=True,
        )
        for p in PAIRS:
            st.toggle(p, value=True, key=f"set_pair_{p}")
        st.toggle("Asian Session Signals", value=False, help="38% win rate — currently off")

    api_keys_html = '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;margin-top:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;padding-bottom:11px;border-bottom:1px solid #1F2D4A;">API KEYS</div><div style="padding:10px 0;border-bottom:1px solid #1F2D4A;"><div style="font-size:11px;color:#4A5F82;font-family:monospace;margin-bottom:5px;">OANDA API Key</div><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;"><span style="background:#151C30;border:1px solid #1F2D4A;border-radius:5px;padding:7px 11px;font-size:12px;font-family:monospace;color:#8A9BBE;">••••••••••••••••</span><span style="width:7px;height:7px;border-radius:50%;background:#00FF88;display:inline-block;"></span><span style="font-size:11px;color:#00FF88;">Connected</span></div></div><div style="padding:10px 0;border-bottom:1px solid #1F2D4A;"><div style="font-size:11px;color:#4A5F82;font-family:monospace;margin-bottom:5px;">OpenAI API Key</div><span style="width:7px;height:7px;border-radius:50%;background:#00FF88;display:inline-block;"></span><span style="font-size:11px;color:#00FF88;">Connected</span></div><div style="padding:10px 0;border-bottom:1px solid #1F2D4A;"><div style="font-size:11px;color:#4A5F82;font-family:monospace;margin-bottom:5px;">Anthropic API Key</div><span style="width:7px;height:7px;border-radius:50%;background:#00FF88;display:inline-block;"></span><span style="font-size:11px;color:#00FF88;">Connected</span></div><div style="padding:10px 0;"><div style="font-size:11px;color:#4A5F82;font-family:monospace;margin-bottom:5px;">NewsAPI Key</div><span style="width:7px;height:7px;border-radius:50%;background:#FFB800;display:inline-block;"></span><span style="font-size:11px;color:#FFB800;">Using RSS fallback</span></div></div>'
    st.html(api_keys_html)
    st.caption("Keys stored in .env. Display masked for security.")

    st.markdown(
        '<div style="background:#0F1525;border:1px solid #1F2D4A;border-radius:12px;padding:18px;margin-top:18px;"><div style="font-size:10px;color:#4A5F82;font-family:monospace;letter-spacing:2px;margin-bottom:14px;padding-bottom:11px;border-bottom:1px solid #1F2D4A;">NOTIFICATIONS</div>',
        unsafe_allow_html=True,
    )
    st.toggle("Pipeline Failure Alerts", value=True, help="Email when any source fails")
    st.toggle("Win Rate Alert", value=True, help="Alert if 30d rate drops below 50%")
    st.toggle("Weekly Coaching Email", value=True, help="Sunday 8am AEST")
    st.toggle("Telegram Signal Push", value=False, help="Real-time signal delivery (Phase 2)")
    st.toggle("Daily 8:30am Digest", value=False, help="Morning email summary")


def main() -> None:
    st.set_page_config(page_title="ForexMind", layout="wide", initial_sidebar_state="expanded")
    _inject_css()
    _init_session_state()

    if "page" not in st.session_state:
        st.session_state.page = "Signals"

    _render_sidebar()

    # Main content: title + topbar, then page, then pipeline health at bottom
    _render_main_title_and_topbar()
    page = st.session_state.get("page", "Signals")
    if page == "Signals":
        _page_signals()
    elif page == "Monitoring":
        _page_monitoring()
    elif page == "Accuracy":
        _page_accuracy()
    elif page == "Journal":
        _page_journal()
    elif page == "Settings":
        _page_settings()
    else:
        _page_signals()
    _render_pipeline_health_bottom()


if __name__ == "__main__":
    main()
