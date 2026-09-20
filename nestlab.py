"""
NESTLAB — an AI Upscale LLC tool
================================
Retirement planner + monthly budget calculator with named, downloadable plans.

Run:  streamlit run nestlab.py
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    money,
    pct,
    project_retirement,
    required_monthly_contribution,
    summarize_budget,
)

SITE_URL = "https://aiupscalellc.netlify.app/"
LOGO_URL = "https://aiupscalellc.netlify.app/logo.svg"
DATA_PATH = Path(__file__).parent / "data" / "plans.json"

NAVY = "#081325"
NAVY_MID = "#0d1d38"
NAVY_CARD = "#122040"
AMBER = "#F5A623"
AMBER_HOT = "#f09238"
CREAM = "#F6F4E9"
MUTED = "#8FA3C8"
GREEN = "#00b87a"
RED = "#e05252"
BORDER = "#1a2f4a"

RETIRE_KEYS = (
    "current_age",
    "retire_age",
    "life_expectancy",
    "current_savings",
    "monthly_contribution",
    "employer_annual",
    "pre_return",
    "post_return",
    "inflation",
    "contrib_growth",
    "desired_annual_income",
    "healthcare_annual",
    "ss_annual",
    "ss_start_age",
    "pension_annual",
    "pension_start_age",
    "other_income",
)

RETIRE_DEFAULTS = {
    "current_age": 35,
    "retire_age": 65,
    "life_expectancy": 90,
    "current_savings": 75000.0,
    "monthly_contribution": 800.0,
    "employer_annual": 3000.0,
    "pre_return": 7.0,
    "post_return": 5.0,
    "inflation": 2.5,
    "contrib_growth": 2.0,
    "desired_annual_income": 60000.0,
    "healthcare_annual": 6000.0,
    "ss_annual": 20000.0,
    "ss_start_age": 67,
    "pension_annual": 0.0,
    "pension_start_age": 65,
    "other_income": 0.0,
}

DEFAULT_INCOME = [
    {"name": "Primary job", "amount": 5500.0},
    {"name": "Partner / side income", "amount": 0.0},
]

DEFAULT_EXPENSES = [
    {"name": "Housing / rent / mortgage", "amount": 1600.0, "kind": "need"},
    {"name": "Utilities", "amount": 250.0, "kind": "need"},
    {"name": "Groceries", "amount": 550.0, "kind": "need"},
    {"name": "Transportation", "amount": 350.0, "kind": "need"},
    {"name": "Insurance", "amount": 220.0, "kind": "need"},
    {"name": "Healthcare", "amount": 150.0, "kind": "need"},
    {"name": "Debt payments", "amount": 300.0, "kind": "need"},
    {"name": "Dining out", "amount": 200.0, "kind": "want"},
    {"name": "Entertainment", "amount": 120.0, "kind": "want"},
    {"name": "Subscriptions", "amount": 60.0, "kind": "want"},
    {"name": "Personal / other", "amount": 100.0, "kind": "want"},
    {"name": "Retirement & savings", "amount": 800.0, "kind": "save"},
]


def default_plan(name: str = "My plan") -> dict:
    return {
        "version": 1,
        "name": name,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "retirement": dict(RETIRE_DEFAULTS),
        "budget": {
            "income": deepcopy(DEFAULT_INCOME),
            "expenses": deepcopy(DEFAULT_EXPENSES),
        },
    }


def _load_disk() -> dict:
    if not DATA_PATH.is_file():
        return {}
    try:
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _normalize_library(payload)


def _normalize_library(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    if "plans" in payload and isinstance(payload["plans"], dict):
        return {str(k): v for k, v in payload["plans"].items() if isinstance(v, dict)}
    if "retirement" in payload or "budget" in payload:
        name = str(payload.get("name") or "Imported plan")
        return {name: payload}
    cleaned = {}
    for key, value in payload.items():
        if isinstance(value, dict) and ("retirement" in value or "budget" in value):
            cleaned[str(key)] = value
    return cleaned


def _write_disk(library: dict) -> bool:
    try:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(
            json.dumps(
                {"version": 1, "updated": datetime.now().isoformat(timespec="seconds"), "plans": library},
                indent=2,
            ),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _collect_items(prefix: str, items: list[dict], extra_keys: tuple[str, ...] = ()) -> list[dict]:
    collected = []
    for i, item in enumerate(items):
        row = {
            "name": st.session_state.get(f"{prefix}_name_{i}", item.get("name", "")),
            "amount": float(st.session_state.get(f"{prefix}_amt_{i}", item.get("amount", 0.0)) or 0.0),
        }
        for extra in extra_keys:
            row[extra] = st.session_state.get(f"{prefix}_{extra}_{i}", item.get(extra))
        collected.append(row)
    return collected


def collect_plan(name: str | None = None) -> dict:
    plan = default_plan(name or st.session_state.get("plan_name", "My plan"))
    plan["name"] = name or st.session_state.get("plan_name", "My plan")
    for key in RETIRE_KEYS:
        plan["retirement"][key] = st.session_state.get(key, RETIRE_DEFAULTS[key])
    plan["budget"]["income"] = _collect_items("inc", st.session_state.income_items)
    plan["budget"]["expenses"] = _collect_items("exp", st.session_state.expense_items, extra_keys=("kind",))
    return plan


def _clear_item_keys() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(("inc_name_", "inc_amt_", "exp_name_", "exp_amt_", "exp_kind_")):
            del st.session_state[key]


def apply_plan(plan: dict) -> None:
    retirement = plan.get("retirement") or {}
    for key in RETIRE_KEYS:
        value = retirement.get(key, RETIRE_DEFAULTS[key])
        if key.endswith("_age") or key in ("current_age", "retire_age", "life_expectancy"):
            st.session_state[key] = int(value)
        else:
            st.session_state[key] = float(value)
    budget = plan.get("budget") or {}
    st.session_state.income_items = deepcopy(budget.get("income") or DEFAULT_INCOME)
    st.session_state.expense_items = deepcopy(budget.get("expenses") or DEFAULT_EXPENSES)
    st.session_state.plan_name = str(plan.get("name") or "My plan")
    _clear_item_keys()


def queue_plan(plan: dict, active_name: str | None = None) -> None:
    """Apply on the next run, before widgets exist."""
    st.session_state["_pending_plan"] = deepcopy(plan)
    if active_name:
        st.session_state["_pending_active"] = active_name
    st.rerun()


def apply_pending() -> None:
    pending = st.session_state.pop("_pending_plan", None)
    if pending:
        apply_plan(pending)
        active = st.session_state.pop("_pending_active", None)
        if active:
            st.session_state.active_plan = active
            st.session_state["library_pick"] = active
    if "_pending_monthly" in st.session_state:
        st.session_state.monthly_contribution = float(st.session_state.pop("_pending_monthly"))
    pick = st.session_state.pop("_pending_library_pick", None)
    if pick is not None:
        if pick:
            st.session_state["library_pick"] = pick
        else:
            st.session_state.pop("library_pick", None)


def seed_item_keys() -> None:
    for i, item in enumerate(st.session_state.income_items):
        st.session_state.setdefault(f"inc_name_{i}", item.get("name", ""))
        st.session_state.setdefault(f"inc_amt_{i}", float(item.get("amount") or 0.0))
    for i, item in enumerate(st.session_state.expense_items):
        st.session_state.setdefault(f"exp_name_{i}", item.get("name", ""))
        st.session_state.setdefault(f"exp_amt_{i}", float(item.get("amount") or 0.0))
        kind = item.get("kind", "want")
        st.session_state.setdefault(f"exp_kind_{i}", kind if kind in ("need", "want", "save") else "want")


def init_state() -> None:
    if st.session_state.get("_nestlab_ready"):
        return
    library = _load_disk()
    if library:
        first_name = next(iter(library))
        apply_plan(library[first_name])
        st.session_state.library = library
        st.session_state.active_plan = first_name
    else:
        apply_plan(default_plan())
        st.session_state.library = {}
        st.session_state.active_plan = st.session_state.plan_name
    st.session_state._nestlab_ready = True


def _chart_layout(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=NAVY,
        plot_bgcolor=NAVY_MID,
        font=dict(color=CREAM, family="Plus Jakarta Sans, sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=40, r=20, t=30, b=40),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, tickprefix="$", separatethousands=True),
        hovermode="x unified",
    )
    return fig


st.set_page_config(
    page_title="NestLab | AI Upscale",
    page_icon="🪺",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_state()
apply_pending()

st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
h1, h2, h3, h4, [data-testid="stMetricValue"] {{ font-family: 'Rajdhani', sans-serif !important; letter-spacing: 0.02em; }}
h1 {{ color: {AMBER} !important; }}
h2, h3 {{ color: {CREAM} !important; }}
[data-testid="stMetricValue"] {{ color: {AMBER} !important; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{ background: {NAVY_MID}; border-radius: 8px 8px 0 0; font-family: 'Rajdhani', sans-serif; font-weight: 600; }}
.stTabs [aria-selected="true"] {{ background: {AMBER} !important; color: {NAVY} !important; }}
.stButton > button {{ font-family: 'Rajdhani', sans-serif; font-weight: 600; border: 1px solid {AMBER}; }}
.aiu-header {{ display: flex; align-items: center; gap: 14px; padding: 2px 0 10px 0; border-bottom: 1px solid {BORDER}; margin-bottom: 8px; }}
.aiu-header img {{ height: 56px; width: auto; }}
.aiu-header a, .aiu-footer a {{ color: inherit; text-decoration: none; }}
.aiu-footer {{ margin-top: 40px; padding-top: 14px; border-top: 1px solid {BORDER}; font-size: 0.85rem; color: {MUTED}; }}
.aiu-footer a:hover {{ color: {AMBER}; }}
.nest-note {{ color: {MUTED}; font-size: 0.92rem; }}
.nest-card {{ background: {NAVY_CARD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 16px 18px; margin-bottom: 12px; }}
.nest-ok {{ color: {GREEN}; font-weight: 600; }}
.nest-bad {{ color: {RED}; font-weight: 600; }}
</style>
<div class="aiu-header">
  <a href="{SITE_URL}" target="_blank" rel="noopener">
    <img src="{LOGO_URL}" alt="AI Upscale LLC">
  </a>
  <div>
    <div style="font-family:'Rajdhani',sans-serif;font-size:1.55rem;font-weight:700;color:{AMBER};line-height:1.05;">
      🪺 NESTLAB
    </div>
    <div style="color:{MUTED};font-size:0.9rem;">
      Retirement + budget planner — an
      <a href="{SITE_URL}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;">AI Upscale LLC</a> tool
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Saved plans")
    st.caption("Plans stay in this session, download as JSON, and also write to disk when the server allows it.")
    st.text_input("Plan name", key="plan_name")

    names = list(st.session_state.library.keys())
    if names:
        st.selectbox("Saved plans", names, key="library_pick")

    c_save, c_apply = st.columns(2)
    with c_save:
        if st.button("Save plan", width="stretch"):
            plan = collect_plan()
            st.session_state.library[plan["name"]] = plan
            st.session_state.active_plan = plan["name"]
            saved = _write_disk(st.session_state.library)
            st.success("Saved locally." if saved else "Saved in this session. Download the JSON to keep it.")
    with c_apply:
        if names and st.button("Load selected", width="stretch"):
            chosen = st.session_state.get("library_pick") or names[0]
            if chosen in st.session_state.library:
                queue_plan(st.session_state.library[chosen], chosen)

    if names and st.button("Delete selected"):
        doomed = st.session_state.get("library_pick")
        if doomed and doomed in st.session_state.library:
            del st.session_state.library[doomed]
            _write_disk(st.session_state.library)
            leftover = list(st.session_state.library.keys())
            st.session_state["_pending_library_pick"] = leftover[0] if leftover else ""
            st.rerun()

    export_blob = json.dumps(
        {
            "version": 1,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "plans": st.session_state.library or {st.session_state.plan_name: collect_plan()},
        },
        indent=2,
    )
    st.download_button(
        "Download plans JSON",
        data=export_blob,
        file_name="nestlab-plans.json",
        mime="application/json",
        width="stretch",
    )
    uploaded = st.file_uploader("Upload plans JSON", type="json")
    if uploaded is not None:
        try:
            incoming = _normalize_library(json.loads(uploaded.getvalue().decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            st.error("That file is not valid JSON.")
        else:
            if incoming:
                file_id = f"{uploaded.name}:{uploaded.size}"
                if st.session_state.get("_upload_token") != file_id:
                    st.session_state.library.update(incoming)
                    _write_disk(st.session_state.library)
                    st.session_state["_upload_token"] = file_id
                    first = next(iter(incoming))
                    queue_plan(incoming[first], first)
            else:
                st.error("No NestLab plans found in that file.")

    st.divider()
    st.markdown(
        f'<p class="nest-note">Planning tool, not advice. Markets, taxes, and life change. '
        f'Built by <a href="{SITE_URL}" target="_blank" rel="noopener">AI Upscale LLC</a>.</p>',
        unsafe_allow_html=True,
    )

retire_tab, budget_tab = st.tabs(["Retirement calculator", "Budget calculator"])

with retire_tab:
    inputs = {key: st.session_state[key] for key in RETIRE_KEYS}
    result = project_retirement(inputs)
    needed = required_monthly_contribution(inputs)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Nest egg at retirement", money(result["nest_egg_at_retirement"]))
    m2.metric("4% rule target (future $)", money(result["target_future"]))
    m3.metric("First-year withdrawal rate", pct(result["withdrawal_rate"]))
    if result["success"]:
        m4.metric("Money lasts through", f"age {result['life_expectancy']}")
    else:
        gone = result["depleted_age"] or result["retire_age"]
        m4.metric("Runs out around", f"age {gone}")

    if result["success"]:
        st.markdown(
            f'<p class="nest-ok">This plan funds the lifestyle through age {result["life_expectancy"]}.</p>',
            unsafe_allow_html=True,
        )
    else:
        extra = max(0.0, needed - float(st.session_state.monthly_contribution))
        st.markdown(
            f'<p class="nest-bad">Short of the goal. Saving about {money(needed)} / month '
            f'(${extra:,.0f} more than today) is the modeled path that lasts.</p>',
            unsafe_allow_html=True,
        )

    st.subheader("Your timeline")
    a1, a2, a3 = st.columns(3)
    a1.number_input("Current age", min_value=18, max_value=90, step=1, key="current_age")
    a2.number_input("Retirement age", min_value=30, max_value=90, step=1, key="retire_age")
    a3.number_input("Plan through age", min_value=50, max_value=110, step=1, key="life_expectancy")

    st.subheader("Savings & growth")
    s1, s2, s3 = st.columns(3)
    s1.number_input("Current nest egg ($)", min_value=0.0, step=1000.0, key="current_savings")
    s2.number_input("Monthly contribution ($)", min_value=0.0, step=50.0, key="monthly_contribution")
    s3.number_input("Employer contribution / year ($)", min_value=0.0, step=250.0, key="employer_annual")
    r1, r2, r3, r4 = st.columns(4)
    r1.number_input("Return before retirement (%)", min_value=0.0, max_value=15.0, step=0.1, key="pre_return")
    r2.number_input("Return in retirement (%)", min_value=0.0, max_value=12.0, step=0.1, key="post_return")
    r3.number_input("Inflation (%)", min_value=0.0, max_value=10.0, step=0.1, key="inflation")
    r4.number_input("Contribution growth (%)", min_value=0.0, max_value=10.0, step=0.1, key="contrib_growth")

    st.subheader("Retirement income (today's dollars)")
    i1, i2, i3 = st.columns(3)
    i1.number_input("Lifestyle you want / year ($)", min_value=0.0, step=1000.0, key="desired_annual_income")
    i2.number_input("Extra healthcare / year ($)", min_value=0.0, step=250.0, key="healthcare_annual")
    i3.number_input("Other retirement income / year ($)", min_value=0.0, step=250.0, key="other_income")
    p1, p2, p3, p4 = st.columns(4)
    p1.number_input("Social Security / year ($)", min_value=0.0, step=500.0, key="ss_annual")
    p2.number_input("Social Security starts at", min_value=62, max_value=70, step=1, key="ss_start_age")
    p3.number_input("Pension / year ($)", min_value=0.0, step=500.0, key="pension_annual")
    p4.number_input("Pension starts at", min_value=50, max_value=80, step=1, key="pension_start_age")

    g1, g2, g3 = st.columns(3)
    g1.metric("Years to retirement", result["years_to_retire"])
    g2.metric("You + employer contribute", money(result["total_contributed"]))
    g3.metric("Peak balance", money(result["peak_balance"]))

    rows = result["rows"]
    if rows:
        ages = [row["age"] for row in rows]
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=ages,
                y=[row["end_balance"] for row in rows],
                name="Portfolio",
                line=dict(color=AMBER, width=3),
                fill="tozeroy",
                fillcolor="rgba(245,166,35,0.18)",
            )
        )
        fig.add_vline(
            x=result["retire_age"],
            line_dash="dot",
            line_color=MUTED,
            annotation_text="Retire",
            annotation_font_color=MUTED,
        )
        if result["depleted_age"]:
            fig.add_vline(
                x=result["depleted_age"],
                line_dash="dash",
                line_color=RED,
                annotation_text="Depleted",
                annotation_font_color=RED,
            )
        st.plotly_chart(_chart_layout(fig), width="stretch")

        retire_rows = [row for row in rows if row["phase"] == "retired"]
        if retire_rows:
            income_fig = go.Figure()
            income_fig.add_trace(
                go.Bar(x=[r["age"] for r in retire_rows], y=[r["withdrawal"] for r in retire_rows], name="From portfolio", marker_color=AMBER)
            )
            income_fig.add_trace(
                go.Bar(x=[r["age"] for r in retire_rows], y=[r["social_security"] for r in retire_rows], name="Social Security", marker_color="#5DCAA5")
            )
            income_fig.add_trace(
                go.Bar(x=[r["age"] for r in retire_rows], y=[r["pension"] for r in retire_rows], name="Pension", marker_color="#7ad4ff")
            )
            income_fig.add_trace(
                go.Bar(x=[r["age"] for r in retire_rows], y=[r["other_income"] for r in retire_rows], name="Other income", marker_color=MUTED)
            )
            income_fig.add_trace(
                go.Scatter(
                    x=[r["age"] for r in retire_rows],
                    y=[r["spend"] for r in retire_rows],
                    name="Spending need",
                    line=dict(color=CREAM, width=2, dash="dot"),
                )
            )
            income_fig.update_layout(barmode="stack")
            st.plotly_chart(_chart_layout(income_fig, 380), width="stretch")

        with st.expander("Year-by-year table"):
            table = pd.DataFrame(rows)
            show = table[
                [
                    "age",
                    "phase",
                    "start_balance",
                    "contribution",
                    "growth",
                    "withdrawal",
                    "social_security",
                    "pension",
                    "spend",
                    "end_balance",
                    "shortfall",
                ]
            ].copy()
            money_cols = [c for c in show.columns if c not in ("age", "phase")]
            for col in money_cols:
                show[col] = show[col].map(lambda v: f"{v:,.0f}")
            st.dataframe(show, width="stretch", hide_index=True)

    st.caption(
        "Model assumes annual compounding, contributions at year-end, and that Social Security / pension / "
        "desired spending all rise with your inflation rate. The 4% rule is a back-of-the-envelope target, not a guarantee."
    )

with budget_tab:
    seed_item_keys()
    income_now = _collect_items("inc", st.session_state.income_items)
    expenses_now = _collect_items("exp", st.session_state.expense_items, extra_keys=("kind",))
    budget = summarize_budget(income_now, expenses_now)

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Income", money(budget["income_total"]))
    b2.metric("Spending", money(budget["expense_total"]))
    b3.metric("Left over", money(budget["surplus"]))
    b4.metric("Savings rate", pct(budget["savings_rate"]))

    if budget["surplus"] < 0:
        st.markdown(
            f'<p class="nest-bad">This month is short {money(abs(budget["surplus"]))}.</p>',
            unsafe_allow_html=True,
        )
    elif budget["surplus"] > 0:
        st.markdown(
            f'<p class="nest-ok">Surplus of {money(budget["surplus"])} / month. '
            f"If that went into NestLab retirement savings, it would be "
            f"{money(st.session_state.monthly_contribution + budget['surplus'])} / month.</p>",
            unsafe_allow_html=True,
        )
        if st.button("Use surplus as retirement contribution"):
            st.session_state["_pending_monthly"] = float(st.session_state.monthly_contribution) + budget["surplus"]
            st.rerun()

    st.subheader("Monthly money in")
    for i, _item in enumerate(st.session_state.income_items):
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.text_input("Income name", key=f"inc_name_{i}", label_visibility="collapsed")
        c2.number_input("Income amount", min_value=0.0, step=50.0, key=f"inc_amt_{i}", label_visibility="collapsed")
        if c3.button("Remove", key=f"inc_del_{i}"):
            st.session_state.income_items = _collect_items("inc", st.session_state.income_items)
            st.session_state.income_items.pop(i)
            _clear_item_keys()
            st.rerun()
    if st.button("Add income line"):
        st.session_state.income_items = _collect_items("inc", st.session_state.income_items)
        st.session_state.income_items.append({"name": "New income", "amount": 0.0})
        _clear_item_keys()
        st.rerun()

    st.subheader("Monthly money out")
    st.caption("Tag each line as a need, a want, or savings so the 50/30/20 check has something honest to compare.")
    kind_labels = {"need": "Need", "want": "Want", "save": "Savings"}
    for i, _item in enumerate(st.session_state.expense_items):
        c1, c2, c3, c4 = st.columns([3.4, 2, 2, 1])
        c1.text_input("Expense name", key=f"exp_name_{i}", label_visibility="collapsed")
        c2.number_input("Expense amount", min_value=0.0, step=25.0, key=f"exp_amt_{i}", label_visibility="collapsed")
        c3.selectbox(
            "Type",
            options=["need", "want", "save"],
            format_func=lambda k: kind_labels[k],
            key=f"exp_kind_{i}",
            label_visibility="collapsed",
        )
        if c4.button("Remove", key=f"exp_del_{i}"):
            st.session_state.expense_items = _collect_items("exp", st.session_state.expense_items, extra_keys=("kind",))
            st.session_state.expense_items.pop(i)
            _clear_item_keys()
            st.rerun()
    if st.button("Add expense line"):
        st.session_state.expense_items = _collect_items("exp", st.session_state.expense_items, extra_keys=("kind",))
        st.session_state.expense_items.append({"name": "New expense", "amount": 0.0, "kind": "want"})
        _clear_item_keys()
        st.rerun()

    h1, h2 = st.columns(2)
    with h1:
        if budget["expense_total"] > 0:
            pie = go.Figure(
                data=[
                    go.Pie(
                        labels=["Needs", "Wants", "Savings"],
                        values=[budget["needs"], budget["wants"], budget["savings"]],
                        hole=0.58,
                        marker=dict(colors=[AMBER_HOT, MUTED, GREEN]),
                        textinfo="label+percent",
                    )
                ]
            )
            pie.update_layout(
                height=360,
                paper_bgcolor=NAVY,
                plot_bgcolor=NAVY,
                font=dict(color=CREAM, family="Plus Jakarta Sans, sans-serif"),
                showlegend=False,
                margin=dict(t=20, b=20, l=20, r=20),
                annotations=[dict(text="50/30/20", x=0.5, y=0.5, font_size=16, showarrow=False, font_color=AMBER)],
            )
            st.plotly_chart(pie, width="stretch")
    with h2:
        compare = go.Figure()
        compare.add_trace(
            go.Bar(name="Your split", x=["Needs", "Wants", "Savings"], y=[budget["needs"], budget["wants"], budget["savings"]], marker_color=AMBER)
        )
        compare.add_trace(
            go.Bar(
                name="50/30/20 target",
                x=["Needs", "Wants", "Savings"],
                y=[budget["rule"]["need"], budget["rule"]["want"], budget["rule"]["save"]],
                marker_color=MUTED,
            )
        )
        st.plotly_chart(_chart_layout(compare, 360), width="stretch")

    k1, k2, k3 = st.columns(3)
    k1.metric("Needs (target 50%)", f"{money(budget['needs'])} vs {money(budget['rule']['need'])}")
    k2.metric("Wants (target 30%)", f"{money(budget['wants'])} vs {money(budget['rule']['want'])}")
    k3.metric("Savings (target 20%)", f"{money(budget['savings'])} vs {money(budget['rule']['save'])}")
    st.metric("Housing share of income", pct(budget["housing_ratio"]))
    if budget["housing_ratio"] > 0.30 and budget["income_total"]:
        st.caption("Housing is above the common 30% guideline. That is a flag, not a law.")

    if budget["expenses"]:
        ranked = sorted(budget["expenses"], key=lambda row: row["amount"], reverse=True)
        bars = go.Figure(
            go.Bar(
                x=[row["amount"] for row in ranked],
                y=[row["name"] for row in ranked],
                orientation="h",
                marker_color=AMBER,
            )
        )
        bars.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(_chart_layout(bars, max(320, 28 * len(ranked))), width="stretch")

    annual = pd.DataFrame(
        [
            {"Line": row["name"], "Type": row["kind"], "Monthly": row["amount"], "Annual": row["amount"] * 12}
            for row in budget["expenses"]
        ]
    )
    if not annual.empty:
        st.dataframe(
            annual.assign(
                Monthly=annual["Monthly"].map(lambda v: f"{v:,.0f}"),
                Annual=annual["Annual"].map(lambda v: f"{v:,.0f}"),
            ),
            width="stretch",
            hide_index=True,
        )

st.markdown(
    f'<div class="aiu-footer">Built by '
    f'<a href="{SITE_URL}" target="_blank" rel="noopener">AI Upscale LLC</a>'
    f" · Columbia, SC · Planning estimates only — not financial, tax, or investment advice</div>",
    unsafe_allow_html=True,
)
