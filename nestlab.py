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
from plotly.subplots import make_subplots

from engine import (
    money,
    monthly_payout_for_years,
    pct,
    pct_of,
    project_accumulation,
    project_investments,
    project_payout,
    project_savings,
    project_social_security,
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
    "salary",
    "raise_pct",
    "raise_every",
    "save_pct",
    "match_pct",
    "pre_return",
    "inflation",
    "current_savings",
    "current_age",
    "retire_age",
    "s_balance",
    "s_rate",
    "s_pct",
    "s_amt",
    "s_freq",
    "p_amt",
    "p_return",
    "p_src",
    "p_base",
    "ss_contrib_pct",
    "ss_benefit",
    "ss_claim_age",
)

RETIRE_INT_KEYS = ("raise_every", "current_age", "retire_age", "ss_claim_age")
RETIRE_STR_KEYS = ("s_freq", "p_src", "p_base")

RETIRE_DEFAULTS = {
    "salary": 75000.0,
    "raise_pct": 3.0,
    "raise_every": 1,
    "save_pct": 10.0,
    "match_pct": 4.0,
    "pre_return": 7.0,
    "inflation": 2.5,
    "current_savings": 25000.0,
    "current_age": 35,
    "retire_age": 65,
    "s_balance": 10000.0,
    "s_rate": 4.0,
    "s_pct": 5.0,
    "s_amt": 200.0,
    "s_freq": "monthly",
    "p_amt": 5000.0,
    "p_return": 5.0,
    "p_src": "ret",
    "p_base": "you",
    "ss_contrib_pct": 6.2,
    "ss_benefit": 20000.0,
    "ss_claim_age": 67,
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
        "version": 2,
        "name": name,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "retirement": dict(RETIRE_DEFAULTS),
        "budget": {
            "income": deepcopy(DEFAULT_INCOME),
            "expenses": deepcopy(DEFAULT_EXPENSES),
        },
        "investments": [],
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
    plan["investments"] = _collect_investments()
    return plan


def _payout_source_label(src: str) -> str:
    return {
        "ret": "retirement account only",
        "both": "retirement + savings",
        "all": "retirement + savings + investments",
    }.get(src, "retirement account only")


def _collect_investments() -> list[dict]:
    collected = []
    for i, item in enumerate(st.session_state.get("investment_items") or []):
        collected.append(
            {
                "name": st.session_state.get(f"inv_name_{i}", item.get("name", "")),
                "balance": float(st.session_state.get(f"inv_bal_{i}", item.get("balance", 0.0)) or 0.0),
                "growth": float(st.session_state.get(f"inv_growth_{i}", item.get("growth", 7.0)) or 0.0),
                "monthly": float(st.session_state.get(f"inv_m_{i}", item.get("monthly", 0.0)) or 0.0),
            }
        )
    return collected


def _clear_item_keys() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(("inc_name_", "inc_amt_", "exp_name_", "exp_amt_", "exp_kind_", "inv_name_", "inv_bal_", "inv_growth_", "inv_m_")):
            del st.session_state[key]


def apply_plan(plan: dict) -> None:
    retirement = plan.get("retirement") or {}
    for key in RETIRE_KEYS:
        value = retirement.get(key, RETIRE_DEFAULTS[key])
        if key in RETIRE_STR_KEYS:
            st.session_state[key] = str(value)
        elif key in RETIRE_INT_KEYS:
            st.session_state[key] = int(value)
        else:
            st.session_state[key] = float(value)
    budget = plan.get("budget") or {}
    st.session_state.income_items = deepcopy(budget.get("income") or DEFAULT_INCOME)
    st.session_state.expense_items = deepcopy(budget.get("expenses") or DEFAULT_EXPENSES)
    st.session_state.investment_items = deepcopy(plan.get("investments") or [])
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
    if "_pending_save_pct" in st.session_state:
        st.session_state.save_pct = float(st.session_state.pop("_pending_save_pct"))
    if "_pending_payout" in st.session_state:
        st.session_state.p_amt = float(st.session_state.pop("_pending_payout"))
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
    for i, item in enumerate(st.session_state.get("investment_items") or []):
        st.session_state.setdefault(f"inv_name_{i}", item.get("name", ""))
        st.session_state.setdefault(f"inv_bal_{i}", float(item.get("balance") or 0.0))
        st.session_state.setdefault(f"inv_growth_{i}", float(item.get("growth") if item.get("growth") is not None else 7.0))
        st.session_state.setdefault(f"inv_m_{i}", float(item.get("monthly") or 0.0))


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
st.session_state.setdefault("investment_items", [])
for _key in RETIRE_KEYS:
    if _key not in st.session_state:
        st.session_state[_key] = RETIRE_DEFAULTS[_key]

st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
h1, h2, h3, h4, [data-testid="stMetricValue"] {{ font-family: 'Rajdhani', sans-serif !important; letter-spacing: 0.02em; }}
h1 {{ color: {AMBER} !important; }}
h2, h3 {{ color: {CREAM} !important; }}
[data-testid="stMetricValue"] {{ color: {AMBER} !important; }}
.stTabs [data-baseweb="tab-list"] {{
    background: {NAVY}; border-radius: 10px; gap: 4px; padding: 4px;
    border: 1px solid {BORDER};
}}
.stTabs [data-baseweb="tab"] {{
    color: {MUTED}; font-family: 'Rajdhani', sans-serif; font-weight: 700;
    font-size: 15px; letter-spacing: 1px; text-transform: uppercase;
    border-radius: 8px !important; padding: 8px 20px;
    border: 1px solid transparent; transition: all 0.15s;
    background: transparent;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {AMBER}; background: {NAVY_MID}; border-color: {BORDER};
}}
.stTabs [aria-selected="true"] {{
    color: {AMBER} !important; background: {NAVY_MID} !important;
    border: 1px solid {AMBER} !important;
    box-shadow: 0 0 10px rgba(245,166,35,0.2);
}}
.stTabs [data-baseweb="tab"]:focus,
.stTabs [data-baseweb="tab"]:focus-visible {{ outline: none !important; }}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {{ display: none !important; }}
.stTabs [data-baseweb="tab-panel"] {{ background: transparent; }}
div[data-testid="stExpander"] {{
    background: {NAVY_CARD}; border: 1px solid {BORDER}; border-radius: 12px;
}}
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
    seed_item_keys()
    inputs = {key: st.session_state[key] for key in RETIRE_KEYS}
    acc = project_accumulation(inputs)
    sav = project_savings(inputs, acc)
    inv = project_investments(_collect_investments(), acc, float(inputs["inflation"]))
    ss = project_social_security(inputs, acc)
    draw = project_payout(inputs, acc, sav, inv)

    s1, s2, s3, s4 = st.columns(4)
    s1.metric(f"Balance at {acc['retire']}", money(acc["final"]), money(acc["real"]) + " in today's dollars", delta_color="off")
    s2.metric("Contributed", money(acc["total_you"] + acc["total_emp"]), f"{money(acc['total_you'])} you · {money(acc['total_emp'])} employer", delta_color="off")
    s3.metric("Earned by growth", money(acc["total_growth"]), f"{pct_of(acc['total_growth'], acc['final'])} of the final balance", delta_color="off")
    s4.metric("Income at 4% a year", money(acc["income_4"]), f"{money(acc['income_4'] / 12)} a month", delta_color="off")

    st.caption(
        "Every raise becomes a bigger contribution. Set pay, how often it steps up, what share you save, and the return. "
        "The staircase is salary; the curve is the balance it builds. Compounded monthly."
    )

    left, right = st.columns([0.38, 0.62], gap="large")
    with left:
        st.markdown("**Pay**")
        st.number_input("Salary this year ($)", min_value=0.0, step=1000.0, key="salary")
        st.number_input("Raise each time (%)", min_value=0.0, max_value=50.0, step=0.25, key="raise_pct")
        st.segmented_control(
            "Raise arrives every",
            options=[1, 2, 3, 5],
            format_func=lambda y: "1 yr" if y == 1 else f"{y} yrs",
            key="raise_every",
        )
        st.markdown("**Contributions**")
        st.number_input("You save (% of salary)", min_value=0.0, max_value=100.0, step=0.5, key="save_pct")
        st.number_input("Employer adds (% of salary)", min_value=0.0, max_value=100.0, step=0.5, key="match_pct")
        st.markdown("**Timeline**")
        st.number_input("Balance today ($)", min_value=0.0, step=1000.0, key="current_savings")
        st.number_input("Age now", min_value=14, max_value=90, step=1, key="current_age")
        st.number_input("Retire at", min_value=15, max_value=100, step=1, key="retire_age")
        st.number_input("Return per year (%)", min_value=-20.0, max_value=30.0, step=0.25, key="pre_return")
        st.number_input("Inflation (%)", min_value=0.0, max_value=20.0, step=0.25, key="inflation")

    with right:
        note = (
            f"{acc['years']} years · raise every {acc['raise_every']} "
            f"{'year' if acc['raise_every'] == 1 else 'years'}"
            if acc["years"]
            else "Set a retirement age above your current age to see a projection."
        )
        st.markdown(f"**Salary staircase & balance** · {note}")
        if acc["years"] and acc["rows"]:
            ages = [acc["age"]] + [row["age"] for row in acc["rows"]]
            bals = [acc["start_bal"]] + [row["end"] for row in acc["rows"]]
            sals = [acc["rows"][0]["salary"]] + [row["salary"] for row in acc["rows"]]
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(
                go.Scatter(
                    x=ages,
                    y=bals,
                    name="Account balance",
                    line=dict(color=AMBER, width=3),
                    fill="tozeroy",
                    fillcolor="rgba(245,166,35,0.18)",
                    hovertemplate="Age %{x}<br>Balance $%{y:,.0f}<extra></extra>",
                ),
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(
                    x=ages,
                    y=sals,
                    name="Salary",
                    line=dict(color="#5DCAA5", width=2, shape="hv"),
                    hovertemplate="Age %{x}<br>Salary $%{y:,.0f}<extra></extra>",
                ),
                secondary_y=True,
            )
            fig.update_yaxes(title_text="Balance", secondary_y=False, tickprefix="$", separatethousands=True)
            fig.update_yaxes(title_text="Salary", secondary_y=True, tickprefix="$", separatethousands=True, showgrid=False)
            fig.update_xaxes(title_text="Age")
            st.plotly_chart(_chart_layout(fig, 420), width="stretch")
        else:
            st.info("Set a retirement age above your current age to see a projection.")

        st.markdown("**Year by year**")
        if acc["rows"]:
            table = pd.DataFrame(acc["rows"])
            show = table[["age", "salary", "you", "employer", "growth", "end", "real"]].rename(
                columns={
                    "age": "Age",
                    "salary": "Salary",
                    "you": "You",
                    "employer": "Employer",
                    "growth": "Growth",
                    "end": "End balance",
                    "real": "In today's $",
                }
            )
            for col in show.columns:
                if col != "Age":
                    show[col] = show[col].map(lambda v: f"{v:,.0f}")
            st.dataframe(show, width="stretch", hide_index=True, height=320)
        else:
            st.caption("No years to project yet.")

    with st.expander("Savings, kept on its own books", expanded=False, key="exp_savings"):
        st.caption("Money outside the retirement account. Contribute a share of salary, a flat amount on a schedule, or both.")
        sv1, sv2 = st.columns([0.38, 0.62], gap="large")
        with sv1:
            st.number_input("Savings balance today ($)", min_value=0.0, step=500.0, key="s_balance")
            st.number_input("Interest earned (%)", min_value=-10.0, max_value=30.0, step=0.05, key="s_rate")
            st.number_input("Rate of salary (%)", min_value=0.0, max_value=100.0, step=0.5, key="s_pct")
            st.number_input("Flat amount ($)", min_value=0.0, step=25.0, key="s_amt")
            st.segmented_control(
                "Flat amount arrives",
                options=["monthly", "biweekly", "yearly"],
                format_func=lambda v: v.title(),
                key="s_freq",
            )
        with sv2:
            st.markdown(
                f"**Savings at retirement** · "
                + (f"{acc['years']} years at {sav['rate'] * 100:.2f}% APY" if acc["years"] else "no years to project")
            )
            r1, r2, r3 = st.columns(3)
            r1.metric(f"Balance at {acc['retire']}", money(sav["final"]), money(sav["real"]) + " in today's dollars", delta_color="off")
            r2.metric("You deposited", money(sav["deposited"]), f"{money(sav['from_pct'])} from salary · {money(sav['from_flat'])} flat", delta_color="off")
            r3.metric("Interest earned", money(sav["interest"]), f"{pct_of(sav['interest'], sav['final'])} of the balance", delta_color="off")
            if acc["years"] and sav["pts"]:
                ages = [acc["age"] + i for i in range(len(sav["pts"]))]
                spark = go.Figure(
                    go.Scatter(
                        x=ages,
                        y=sav["pts"],
                        name="Savings balance",
                        line=dict(color="#5DCAA5", width=3),
                        fill="tozeroy",
                        fillcolor="rgba(93,202,165,0.16)",
                    )
                )
                spark.update_xaxes(title_text="Age")
                spark.update_yaxes(title_text="Balance", tickprefix="$", separatethousands=True)
                st.plotly_chart(_chart_layout(spark, 240), width="stretch")

    with st.expander("Social Security contributions", expanded=False, key="exp_ss"):
        st.caption("Payroll tax while you work, then an estimated benefit starting at the age you claim.")
        ss1, ss2 = st.columns([0.38, 0.62], gap="large")
        with ss1:
            st.number_input("Contribution (% of salary)", min_value=0.0, max_value=20.0, step=0.1, key="ss_contrib_pct")
            st.number_input("Annual benefit today ($)", min_value=0.0, step=500.0, key="ss_benefit")
            st.number_input("Claim at age", min_value=62, max_value=70, step=1, key="ss_claim_age")
        with ss2:
            st.markdown(
                f"**Social Security** · claim at {ss['claim_age']}"
                + (f" · {acc['years']} working years" if acc["years"] else "")
            )
            g1, g2, g3 = st.columns(3)
            g1.metric("Paid in while working", money(ss["paid"]), f"{ss['contrib_pct'] * 100:.1f}% of salary", delta_color="off")
            g2.metric(f"Benefit at {ss['claim_age']}", money(ss["benefit_at_claim"]), money(ss["benefit_today"]) + " in today's dollars", delta_color="off")
            g3.metric("Monthly benefit", money(ss["monthly"]), "after inflation to claim age", delta_color="off")
            st.caption("Contributions here are payroll tax, not an account you own. The benefit is an estimate you enter, grown with inflation to the year you claim.")

    with st.expander("Other investments", expanded=False, key="exp_inv"):
        st.caption("Brokerage, crypto, or any named account with its own growth rate. Add as many as you want.")
        for i, _item in enumerate(st.session_state.investment_items):
            vis = "visible" if i == 0 else "collapsed"
            n, b, g, m, rm = st.columns([3, 2, 1.6, 2, 1])
            n.text_input("Name", key=f"inv_name_{i}", label_visibility=vis)
            b.number_input("Balance today ($)", min_value=0.0, step=500.0, key=f"inv_bal_{i}", label_visibility=vis)
            g.number_input("Growth (%)", min_value=-20.0, max_value=50.0, step=0.25, key=f"inv_growth_{i}", label_visibility=vis)
            m.number_input("Monthly add ($)", min_value=0.0, step=25.0, key=f"inv_m_{i}", label_visibility=vis)
            if rm.button("Remove", key=f"inv_del_{i}"):
                st.session_state.investment_items = _collect_investments()
                st.session_state.investment_items.pop(i)
                _clear_item_keys()
                st.rerun()
        if st.button("Add investment"):
            st.session_state.investment_items = _collect_investments()
            st.session_state.investment_items.append({"name": "New investment", "balance": 0.0, "growth": 7.0, "monthly": 0.0})
            _clear_item_keys()
            st.rerun()
        if inv["details"]:
            i1, i2, i3 = st.columns(3)
            i1.metric(f"Balance at {acc['retire']}", money(inv["final"]), money(inv["real"]) + " in today's dollars", delta_color="off")
            i2.metric("You deposited", money(inv["deposited"]), f"{money(inv['start_bal'])} starting balance", delta_color="off")
            i3.metric("Growth earned", money(inv["growth"]), f"{pct_of(inv['growth'], inv['final'])} of the balance", delta_color="off")
            table = pd.DataFrame(inv["details"]).rename(
                columns={
                    "name": "Investment",
                    "start": "Start",
                    "deposited": "Deposited",
                    "growth": "Growth",
                    "final": "At retirement",
                    "real": "In today's $",
                }
            )
            for col in table.columns:
                if col != "Investment":
                    table[col] = table[col].map(lambda v: f"{v:,.0f}")
            st.dataframe(table, width="stretch", hide_index=True)
            if acc["years"] and inv["pts"]:
                ages = [acc["age"] + i for i in range(len(inv["pts"]))]
                spark = go.Figure(
                    go.Scatter(
                        x=ages,
                        y=inv["pts"],
                        name="Investments",
                        line=dict(color="#7B8CDE", width=3),
                        fill="tozeroy",
                        fillcolor="rgba(123,140,222,0.16)",
                    )
                )
                spark.update_xaxes(title_text="Age")
                spark.update_yaxes(title_text="Balance", tickprefix="$", separatethousands=True)
                st.plotly_chart(_chart_layout(spark, 240), width="stretch")
        else:
            st.caption("No other investments yet. Add one to project a named account with its own growth rate.")

    with st.expander("What it pays out, and when you break even", expanded=False, key="exp_payout"):
        st.caption("Name a monthly payout. This shows the yearly figure, how long until you've drawn back what you put in, and how long the balance holds.")
        d1, d2 = st.columns([0.38, 0.62], gap="large")
        with d1:
            st.number_input("Take each month ($)", min_value=0.0, step=100.0, key="p_amt")
            q1, q2 = st.columns(2)
            with q1:
                if st.button("Use 4% rule", width="stretch"):
                    st.session_state["_pending_payout"] = float(round(draw["bal0"] * 0.04 / 12 / 50) * 50)
                    st.rerun()
            with q2:
                if st.button("Make it last 30 yrs", width="stretch"):
                    raw = monthly_payout_for_years(draw["bal0"], float(st.session_state.p_return), 30)
                    st.session_state["_pending_payout"] = float(round(raw / 50) * 50)
                    st.rerun()
            st.number_input("Return while retired (%)", min_value=-10.0, max_value=30.0, step=0.25, key="p_return")
            st.segmented_control(
                "Draw from",
                options=["ret", "both", "all"],
                format_func=lambda v: {"ret": "Retirement", "both": "+ Savings", "all": "+ Investments"}[v],
                key="p_src",
            )
            st.segmented_control(
                "Break even against",
                options=["you", "all"],
                format_func=lambda v: "Your share" if v == "you" else "Everything in",
                key="p_base",
            )
        with d2:
            st.markdown("**Payout & break-even** · " + _payout_source_label(draw["src"]))
            p1, p2, p3 = st.columns(3)
            p1.metric("Payout per year", money(draw["annual"]), f"{money(draw['P'])} a month", delta_color="off")
            p2.metric(
                "Break even after",
                draw["be_label"],
                f"at age {draw['be_age']} · {money(draw['paid_in'])} paid in" if draw["be_age"] is not None else "enter a payout",
                delta_color="off",
            )
            p3.metric(
                "Balance lasts",
                draw["lasts_label"],
                "interest covers the payout" if draw["depleted"] is None else f"runs dry at age {draw['empty_age']}",
                delta_color="off",
            )
            if not draw["P"]:
                st.info("Enter a monthly payout to see the break-even point.")
            elif draw["be_reached"]:
                extra = ""
                if draw["bal_at_be"] is not None:
                    extra = f", with {money(draw['bal_at_be'])} still in the account"
                st.markdown(
                    f'<p class="nest-ok">Breaks even by age {draw["be_age"]}. You\'ve drawn back the {money(draw["paid_in"])} '
                    f"you paid in{extra}. Total drawn over the full run: {money(draw['total_received'])}.</p>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<p class="nest-bad">Runs short. The balance empties after {draw["lasts_label"]} having paid out '
                    f"{money(draw['total_received'])} — short of the {money(draw['paid_in'])} you put in. "
                    f"Up to {money(draw['sustainable'])} a month is covered by interest alone at this return.</p>",
                    unsafe_allow_html=True,
                )
            if draw["P"] and draw["bal0"] > 0 and draw["pts"]:
                horizon = min(720, max((draw["depleted"] or 0) + 12, int(draw["be_months"]) + 24 if draw["be_months"] != float("inf") else 0, 360))
                xs = [acc["retire"] + pt["m"] / 12.0 for pt in draw["pts"] if pt["m"] <= horizon]
                recv = [pt["recv"] for pt in draw["pts"] if pt["m"] <= horizon]
                left_bal = [max(0.0, pt["bal"]) for pt in draw["pts"] if pt["m"] <= horizon]
                pfig = go.Figure()
                pfig.add_trace(go.Scatter(x=xs, y=left_bal, name="Balance left", line=dict(color="#5DCAA5", width=2)))
                pfig.add_trace(go.Scatter(x=xs, y=recv, name="Total received", line=dict(color=AMBER, width=2.5)))
                pfig.add_hline(y=draw["paid_in"], line_dash="dash", line_color="#e18028", annotation_text="Paid in")
                if draw["be_months"] != float("inf") and draw["be_months"] <= horizon:
                    pfig.add_vline(
                        x=acc["retire"] + draw["be_months"] / 12.0,
                        line_dash="dot",
                        line_color=CREAM,
                        annotation_text="Break even",
                        annotation_font_color=CREAM,
                    )
                pfig.update_xaxes(title_text="Age")
                pfig.update_yaxes(title_text="Dollars", tickprefix="$", separatethousands=True)
                st.plotly_chart(_chart_layout(pfig, 280), width="stretch")

    st.caption(
        "Projections assume level returns and contributions made monthly. Real markets vary — a planning sketch, not a forecast."
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
        salary = float(st.session_state.get("salary") or 0)
        extra_pct = (budget["surplus"] * 12.0 / salary * 100.0) if salary else 0.0
        new_pct = float(st.session_state.get("save_pct") or 0) + extra_pct
        st.markdown(
            f'<p class="nest-ok">Surplus of {money(budget["surplus"])} / month. '
            f"If that went into retirement as a share of salary, you would save about "
            f"{new_pct:.1f}% of pay.</p>",
            unsafe_allow_html=True,
        )
        if st.button("Use surplus as retirement contribution"):
            st.session_state["_pending_save_pct"] = new_pct
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
