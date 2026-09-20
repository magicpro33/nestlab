"""
NESTLAB — an AI Upscale LLC tool
================================
Retirement planner + monthly budget calculator with named, downloadable plans.

Run:  streamlit run nestlab.py
"""

from __future__ import annotations

import html
import json
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    TAX_MONTH_NAMES,
    combine_balance,
    money,
    monthly_payout_for_years,
    pct,
    pct_of,
    project_accumulation,
    project_investments,
    project_payout,
    project_savings,
    project_social_security,
    project_taxes,
    summarize_budget,
    tax_kind,
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
    "ss_balance",
    "ss_monthly",
    "ss_claim_age",
    "include_ret",
    "include_sav",
    "include_ss",
)

RETIRE_INT_KEYS = ("raise_every", "current_age", "retire_age", "ss_claim_age")
RETIRE_STR_KEYS = ("s_freq", "p_src", "p_base")
RETIRE_BOOL_KEYS = ("include_ret", "include_sav", "include_ss")

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
    "ss_balance": 0.0,
    "ss_monthly": 400.0,
    "ss_claim_age": 67,
    "include_ret": True,
    "include_sav": True,
    "include_ss": True,
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

DEFAULT_TAXES = [
    {"name": "Federal tax", "amount": 500.0, "freq": "paycheck", "when": 1, "kind": "federal"},
    {"name": "State tax", "amount": 150.0, "freq": "paycheck", "when": 1, "kind": "state"},
    {"name": "Car tax", "amount": 350.0, "freq": "yearly", "when": 3, "kind": "car"},
    {"name": "Property tax", "amount": 2400.0, "freq": "yearly", "when": 11, "kind": "property"},
]

TAX_FREQ_LABELS = {
    "paycheck": "Per paycheck",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "yearly": "Yearly",
}
TAX_PAYCHECK_LABELS = {
    52: "Weekly",
    26: "Every 2 weeks",
    24: "Twice a month",
    12: "Monthly",
}
TAX_KIND_COLORS = {
    "federal": AMBER,
    "state": "#7B8CDE",
    "car": "#5DCAA5",
    "property": AMBER_HOT,
    "other": MUTED,
}


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
        "taxes": {
            "paychecks_per_year": 26,
            "horizon": 30,
            "items": deepcopy(DEFAULT_TAXES),
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
    plan["investments"] = _collect_investments()
    plan["taxes"] = {
        "paychecks_per_year": int(st.session_state.get("tax_paychecks") or 26),
        "horizon": int(st.session_state.get("tax_horizon") or 30),
        "items": _collect_taxes(),
    }
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
                "include": bool(st.session_state.get(f"inv_inc_{i}", item.get("include", True))),
            }
        )
    return collected


def _collect_taxes() -> list[dict]:
    collected = []
    for i, item in enumerate(st.session_state.get("tax_items") or []):
        name = st.session_state.get(f"tax_name_{i}", item.get("name", ""))
        freq = str(st.session_state.get(f"tax_freq_{i}", item.get("freq", "monthly")) or "monthly")
        if freq not in TAX_FREQ_LABELS:
            freq = "monthly"
        try:
            when = int(st.session_state.get(f"tax_when_{i}", item.get("when", 1)) or 1)
        except (TypeError, ValueError):
            when = 1
        collected.append(
            {
                "name": name,
                "amount": float(st.session_state.get(f"tax_amt_{i}", item.get("amount", 0.0)) or 0.0),
                "freq": freq,
                "when": max(1, min(12, when)),
                "kind": item.get("kind") or tax_kind({"name": name}),
            }
        )
    return collected


def _clear_item_keys() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(
            (
                "inc_name_",
                "inc_amt_",
                "exp_name_",
                "exp_amt_",
                "exp_kind_",
                "inv_name_",
                "inv_bal_",
                "inv_growth_",
                "inv_m_",
                "inv_inc_",
                "tax_name_",
                "tax_amt_",
                "tax_freq_",
                "tax_when_",
            )
        ):
            del st.session_state[key]


def apply_plan(plan: dict) -> None:
    retirement = dict(plan.get("retirement") or {})
    if "ss_monthly" not in retirement and "ss_contrib_pct" in retirement:
        try:
            salary = float(retirement.get("salary", RETIRE_DEFAULTS["salary"]) or 0.0)
            pct_val = float(retirement.get("ss_contrib_pct") or 0.0)
        except (TypeError, ValueError):
            salary, pct_val = RETIRE_DEFAULTS["salary"], 6.2
        retirement["ss_monthly"] = salary * pct_val / 100.0 / 12.0
    for key in RETIRE_KEYS:
        value = retirement.get(key, RETIRE_DEFAULTS[key])
        if key in RETIRE_STR_KEYS:
            st.session_state[key] = str(value)
        elif key in RETIRE_INT_KEYS:
            st.session_state[key] = int(value)
        elif key in RETIRE_BOOL_KEYS:
            st.session_state[key] = bool(value)
        else:
            st.session_state[key] = float(value)
    budget = plan.get("budget") or {}
    st.session_state.income_items = deepcopy(budget.get("income") or DEFAULT_INCOME)
    st.session_state.expense_items = deepcopy(budget.get("expenses") or DEFAULT_EXPENSES)
    st.session_state.investment_items = deepcopy(plan.get("investments") or [])
    taxes_block = plan.get("taxes") if isinstance(plan.get("taxes"), dict) else {}
    raw_taxes = taxes_block.get("items")
    st.session_state.tax_items = deepcopy(raw_taxes if isinstance(raw_taxes, list) and raw_taxes else DEFAULT_TAXES)
    try:
        paychecks = int(taxes_block.get("paychecks_per_year") or 26)
    except (TypeError, ValueError):
        paychecks = 26
    st.session_state.tax_paychecks = paychecks if paychecks in TAX_PAYCHECK_LABELS else 26
    try:
        horizon = int(taxes_block.get("horizon") or 30)
    except (TypeError, ValueError):
        horizon = 30
    st.session_state.tax_horizon = max(1, min(50, horizon))
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
        st.session_state.setdefault(f"inv_inc_{i}", bool(item.get("include", True)))
    for i, item in enumerate(st.session_state.get("tax_items") or []):
        st.session_state.setdefault(f"tax_name_{i}", item.get("name", ""))
        st.session_state.setdefault(f"tax_amt_{i}", float(item.get("amount") or 0.0))
        freq = str(item.get("freq") or "monthly")
        st.session_state.setdefault(f"tax_freq_{i}", freq if freq in TAX_FREQ_LABELS else "monthly")
        try:
            when = int(item.get("when") or 1)
        except (TypeError, ValueError):
            when = 1
        st.session_state.setdefault(f"tax_when_{i}", max(1, min(12, when)))


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


def _esc(value: object) -> str:
    return html.escape(str(value))


def _share(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * part / total))


def _ring(percent: float, color: str, size: int = 52, stroke: int = 5, label: str | None = None) -> str:
    pct_val = max(0.0, min(100.0, float(percent)))
    radius = 18
    circ = 2 * math.pi * radius
    filled = circ * pct_val / 100.0
    text = label if label is not None else str(int(round(pct_val)))
    return (
        f'<svg class="dash-ring" width="{size}" height="{size}" viewBox="0 0 44 44" aria-hidden="true">'
        f'<circle cx="22" cy="22" r="{radius}" fill="none" stroke="#1a2f4a" stroke-width="{stroke}"/>'
        f'<circle cx="22" cy="22" r="{radius}" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-dasharray="{filled:.2f} {circ:.2f}" transform="rotate(-90 22 22)"/>'
        f'<text x="22" y="26" text-anchor="middle" fill="{color}" font-size="10" '
        f'font-family="Rajdhani, sans-serif" font-weight="700">{_esc(text)}</text>'
        f"</svg>"
    )


def _pill(label: str, value: str, tone: str = "cream") -> str:
    color = {"green": GREEN, "red": RED, "amber": AMBER, "cream": CREAM, "muted": MUTED}.get(tone, CREAM)
    return (
        f'<div class="dash-pill"><span>{_esc(label)}</span>'
        f'<strong style="color:{color}">{_esc(value)}</strong></div>'
    )


def _badge(text: str, kind: str) -> str:
    return f'<span class="dash-badge dash-badge-{kind}">{_esc(text)}</span>'


def _signal_card(title: str, value: str, detail: str, percent: float, color: str, badge: str, kind: str) -> str:
    bar = GREEN if kind == "strong" else (RED if kind == "weak" else MUTED)
    return (
        f'<div class="dash-card">'
        f'<div class="dash-card-head"><span>{_esc(title)}</span>{_badge(badge, kind)}</div>'
        f'<div class="dash-card-body">{_ring(percent, color)}'
        f'<div class="dash-card-value" style="color:{color}">{_esc(value)}</div></div>'
        f'<p class="dash-card-copy">{_esc(detail)}</p>'
        f'<div class="dash-card-bar" style="background:{bar}"></div>'
        f"</div>"
    )


def _tax_color(kind: str, index: int = 0) -> str:
    if kind in TAX_KIND_COLORS:
        return TAX_KIND_COLORS[kind]
    palette = (AMBER, "#7B8CDE", "#5DCAA5", AMBER_HOT, MUTED, CREAM)
    return palette[index % len(palette)]


def _hex_rgba(color: str, alpha: float = 0.55) -> str:
    raw = color.lstrip("#")
    if len(raw) != 6:
        return color
    red, green, blue = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


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
st.session_state.setdefault("tax_items", deepcopy(DEFAULT_TAXES))
st.session_state.setdefault("tax_paychecks", 26)
st.session_state.setdefault("tax_horizon", 30)
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
    background: transparent !important; gap: 28px; padding: 0 4px;
    border: none !important; border-radius: 0 !important;
    border-bottom: 1px solid #2a4160 !important;
}}
.stTabs [data-baseweb="tab"] {{
    color: {CREAM} !important; font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 600; font-size: 16px; letter-spacing: 0.01em; text-transform: none;
    border-radius: 0 !important; padding: 10px 8px 14px 8px !important;
    border: none !important; background: transparent !important;
    display: flex !important; align-items: center !important; gap: 8px !important;
}}
.stTabs [data-baseweb="tab"]::before,
.stTabs [role="tab"]::before {{
    content: ""; width: 18px; height: 18px; display: inline-block; flex-shrink: 0;
    background-repeat: no-repeat; background-position: center; background-size: contain;
}}
.stTabs [data-baseweb="tab"]:nth-of-type(1)::before,
.stTabs [role="tab"]:nth-of-type(1)::before {{
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'%3E%3Cellipse cx='12' cy='10.5' rx='4.2' ry='5.2' fill='%23F5A623'/%3E%3Cpath d='M4 16c2.5 2.2 5.2 3.4 8 3.4s5.5-1.2 8-3.4c-1.4 3.2-4.5 5.2-8 5.2s-6.6-2-8-5.2z' fill='%235DCAA5'/%3E%3Cpath d='M5 15.2c2.2 1.4 4.4 2.1 7 2.1s4.8-.7 7-2.1' stroke='%23F5A623' stroke-width='1.4' stroke-linecap='round'/%3E%3C/svg%3E");
}}
.stTabs [data-baseweb="tab"]:nth-of-type(2)::before,
.stTabs [role="tab"]:nth-of-type(2)::before {{
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'%3E%3Crect x='3' y='13' width='4' height='8' rx='1' fill='%235DCAA5'/%3E%3Crect x='10' y='8' width='4' height='13' rx='1' fill='%23F5A623'/%3E%3Crect x='17' y='4' width='4' height='17' rx='1' fill='%23F6F4E9'/%3E%3C/svg%3E");
}}
.stTabs [data-baseweb="tab"]:nth-of-type(3)::before,
.stTabs [role="tab"]:nth-of-type(3)::before {{
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'%3E%3Crect x='4' y='2.5' width='16' height='19' rx='2' fill='%23F6F4E9'/%3E%3Crect x='7' y='6' width='10' height='1.6' rx='0.6' fill='%23081325'/%3E%3Crect x='7' y='9.2' width='6.5' height='1.6' rx='0.6' fill='%235DCAA5'/%3E%3Crect x='7' y='12.4' width='10' height='1.6' rx='0.6' fill='%23081325'/%3E%3Ccircle cx='16.2' cy='17.2' r='4.3' fill='%23F5A623'/%3E%3Ccircle cx='14.8' cy='15.9' r='0.75' fill='%23081325'/%3E%3Ccircle cx='17.6' cy='18.5' r='0.75' fill='%23081325'/%3E%3Cpath d='M15.2 18.8 L17.8 15.6' stroke='%23081325' stroke-width='1.2' stroke-linecap='round'/%3E%3C/svg%3E");
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {AMBER} !important; background: transparent !important; border: none !important;
}}
.stTabs [aria-selected="true"] {{
    color: {CREAM} !important; background: transparent !important;
    border: none !important; box-shadow: none !important;
    border-bottom: 3px solid {AMBER_HOT} !important;
    margin-bottom: -1px !important;
}}
.stTabs [data-baseweb="tab"]:focus,
.stTabs [data-baseweb="tab"]:focus-visible {{ outline: none !important; }}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {{ display: none !important; }}
.stTabs [data-baseweb="tab-panel"] {{ background: transparent; }}
div[data-testid="stExpander"] {{
    background: {NAVY_CARD}; border: 1px solid {BORDER}; border-radius: 12px;
}}
[data-testid="stDataFrame"] tbody tr:nth-child(even),
[data-testid="stDataFrame"] [role="row"]:nth-child(even) {{
    background-color: rgba(143, 163, 200, 0.22) !important;
}}
.stButton > button {{ font-family: 'Rajdhani', sans-serif; font-weight: 600; border: 1px solid {AMBER}; }}
.aiu-header {{ display: flex; align-items: center; gap: 18px; padding: 2px 0 10px 0; border-bottom: 1px solid {BORDER}; margin-bottom: 8px; }}
.aiu-header img {{ height: 112px; width: auto; }}
.aiu-header a, .aiu-footer a {{ color: inherit; text-decoration: none; }}
.aiu-footer {{ margin-top: 40px; padding-top: 14px; border-top: 1px solid {BORDER}; font-size: 0.85rem; color: {MUTED}; }}
.aiu-footer a:hover {{ color: {AMBER}; }}
.nest-note {{ color: {MUTED}; font-size: 0.92rem; }}
.nest-card {{ background: {NAVY_CARD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 16px 18px; margin-bottom: 12px; }}
.nest-ok {{ color: {GREEN}; font-weight: 600; }}
.nest-bad {{ color: {RED}; font-weight: 600; }}
.dash-hero, .dash-band {{
    background: linear-gradient(180deg, #0d1e33 0%, #0a1728 100%);
    border: 1px solid #1e3a5f; border-radius: 14px; padding: 18px 20px; margin: 0 0 12px 0;
}}
.dash-hero-top {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }}
.dash-kicker {{ font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 1.7rem; color: {CREAM}; letter-spacing: 0.04em; line-height: 1; }}
.dash-sub {{ color: {AMBER}; font-size: 0.92rem; margin-top: 4px; }}
.dash-meta {{ color: {MUTED}; font-size: 0.78rem; margin-top: 4px; }}
.dash-price {{ font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 2.1rem; color: {CREAM}; line-height: 1; text-align: right; }}
.dash-price span {{ display: block; font-size: 0.82rem; color: {GREEN}; font-weight: 600; margin-top: 4px; }}
.dash-pills {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }}
.dash-pill {{
    background: #07111f; border: 1px solid #1e3a5f; border-radius: 10px;
    padding: 10px 14px; min-width: 110px; flex: 1 1 110px;
}}
.dash-pill span {{ display: block; font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; color: {MUTED}; font-family: 'Rajdhani', sans-serif; font-weight: 700; }}
.dash-pill strong {{ display: block; margin-top: 4px; font-size: 1.05rem; font-family: 'Rajdhani', sans-serif; }}
.dash-band {{ display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }}
.dash-band-copy {{ min-width: 160px; }}
.dash-band-copy h3 {{ margin: 0; font-family: 'Rajdhani', sans-serif; font-size: 0.95rem; letter-spacing: 0.08em; color: {MUTED}; }}
.dash-band-copy strong {{ display: block; font-size: 1.6rem; color: {CREAM}; font-family: 'Rajdhani', sans-serif; }}
.dash-band-copy p {{ margin: 4px 0 0 0; color: {MUTED}; font-size: 0.82rem; }}
.dash-section {{ font-family: 'Rajdhani', sans-serif; font-weight: 700; letter-spacing: 0.12em; color: {MUTED}; font-size: 0.8rem; margin: 8px 0 10px 0; }}
.dash-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }}
@media (max-width: 1100px) {{ .dash-grid {{ grid-template-columns: 1fr; }} }}
.dash-card {{
    background: linear-gradient(180deg, #0d1e33 0%, #0a1728 100%);
    border: 1px solid #1e3a5f; border-radius: 14px; padding: 14px 16px 12px 16px;
    position: relative; overflow: hidden; min-height: 148px;
}}
.dash-card-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px;
    font-family: 'Rajdhani', sans-serif; font-weight: 700; letter-spacing: 0.08em; color: {CREAM}; font-size: 0.86rem; }}
.dash-card-body {{ display: flex; align-items: center; gap: 12px; margin-top: 10px; }}
.dash-card-value {{ font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 1.55rem; line-height: 1; }}
.dash-card-copy {{ color: {MUTED}; font-size: 0.78rem; line-height: 1.35; margin: 10px 0 8px 0; min-height: 2.4em; }}
.dash-card-bar {{ height: 3px; border-radius: 3px; width: 100%; }}
.dash-badge {{ font-size: 0.7rem; border-radius: 999px; padding: 2px 9px; letter-spacing: 0.04em; font-weight: 700; }}
.dash-badge-strong {{ color: {GREEN}; background: rgba(0,184,122,0.12); border: 1px solid rgba(0,184,122,0.35); }}
.dash-badge-weak {{ color: #d4a0e8; background: rgba(180,80,180,0.12); border: 1px solid rgba(180,80,180,0.35); }}
.dash-badge-muted {{ color: {MUTED}; background: rgba(143,163,200,0.1); border: 1px solid #1e3a5f; }}
.dash-ring {{ display: block; flex-shrink: 0; }}
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
      Retirement, budget, and tax planner — an
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

retire_tab, budget_tab, tax_tab = st.tabs(["Retirement", "Budget", "Tax's"])

with retire_tab:
    seed_item_keys()
    inputs = {key: st.session_state[key] for key in RETIRE_KEYS}
    acc = project_accumulation(inputs)
    sav = project_savings(inputs, acc)
    inv_items = _collect_investments()
    inv = project_investments(inv_items, acc, float(inputs["inflation"]))
    ss = project_social_security(inputs, acc)
    draw = project_payout(inputs, acc, sav, inv)
    nest = combine_balance(
        acc,
        sav,
        inv,
        ss,
        include_ret=bool(st.session_state.get("include_ret", True)),
        include_sav=bool(st.session_state.get("include_sav", True)),
        include_ss=bool(st.session_state.get("include_ss", True)),
        included_investments=[bool(item.get("include", True)) for item in inv_items],
    )

    years_left = acc["years"]
    years_note = (
        f"{years_left} year until retirement" if years_left == 1 else f"{years_left} years until retirement"
    ) if years_left > 0 else "Retirement age is at or below current age"
    books = acc["final"] + sav["final"] + inv["final"] + ss["final"]
    ret_share = _share(acc["final"], books)
    ss_share = _share(ss["final"], books)
    sav_share = _share(sav["final"], books)
    inv_share = _share(inv["final"], books)
    include_ret = bool(st.session_state.get("include_ret", True))
    include_sav = bool(st.session_state.get("include_sav", True))
    include_ss = bool(st.session_state.get("include_ss", True))
    plan_title = st.session_state.get("plan_name") or "NestLab"
    stamped = datetime.now().strftime("%b %d, %Y %I:%M %p")
    ss_on = include_ss
    sav_on = include_sav
    ret_on = include_ret
    inv_on = any(bool(item.get("include", True)) for item in inv_items) if inv_items else True
    payout_ok = bool(draw.get("be_reached"))
    mix_label = f"{nest['final'] / books:.3f}" if books else "0.000"

    st.markdown(
        f"""
<div class="dash-hero">
  <div class="dash-hero-top">
    <div>
      <div class="dash-kicker">{_esc(plan_title)}</div>
      <div class="dash-sub">Retirement plan</div>
      <div class="dash-meta">Age {acc['age']} → {acc['retire']} · { _esc(years_note) } · { _esc(stamped) }</div>
    </div>
    <div class="dash-price">{_esc(money(nest["final"]))}<span>{_esc(money(nest["real"]))} in today's dollars</span></div>
  </div>
  <div class="dash-pills">
    {_pill("Social Security", money(ss["final"]), "cream")}
    {_pill("Savings", money(sav["final"]), "cream")}
    {_pill("Investments", money(inv["final"]), "cream")}
    {_pill("Salary now", money(float(st.session_state.get("salary") or 0)), "cream")}
    {_pill("You save", f"{float(st.session_state.get('save_pct') or 0):.1f}%", "green")}
    {_pill("Employer", f"{float(st.session_state.get('match_pct') or 0):.1f}%", "green")}
  </div>
</div>
<div class="dash-band">
  {_ring(max(ret_share, ss_share, sav_share, inv_share), AMBER, size=72, stroke=6, label=str(int(round(max(ret_share, ss_share, sav_share, inv_share)))))}
  <div class="dash-band-copy">
    <h3>NEST MIX</h3>
    <strong>{_esc(mix_label)}</strong>
    <p>{len(nest["parts"])} of 4 books counted in the total at {acc['retire']}</p>
  </div>
  <div class="dash-pills" style="flex:1;margin-top:0;">
    {_pill("Retirement share", f"{ret_share:.0f}%", "amber")}
    {_pill("SS share", f"{ss_share:.0f}%", "cream")}
    {_pill("Savings share", f"{sav_share:.0f}%", "green")}
    {_pill("Investments share", f"{inv_share:.0f}%", "cream")}
  </div>
</div>
<div class="dash-section">SOURCE BREAKDOWN</div>
<div class="dash-grid">
  {_signal_card("RETIREMENT", money(acc["final"]), f"{money(acc['real'])} in today's dollars. Workplace account at retirement.", ret_share, AMBER if ret_on else MUTED, "Included" if ret_on else "Excluded", "strong" if ret_on else "weak")}
  {_signal_card("SOCIAL SECURITY", money(ss["final"]), f"{money(ss['start'])} starting · {money(ss['paid'])} paid in while working · {money(ss['monthly'])} a month.", ss_share, GREEN if ss_on else MUTED, "Included" if ss_on else "Excluded", "strong" if ss_on else "weak")}
  {_signal_card("SAVINGS", money(sav["final"]), f"{money(sav['deposited'])} deposited · {money(sav['interest'])} interest.", sav_share, GREEN if sav_on else MUTED, "Included" if sav_on else "Excluded", "strong" if sav_on else "weak")}
  {_signal_card("INVESTMENTS", money(inv["final"]), f"{len(inv['details'])} named account{'s' if len(inv['details']) != 1 else ''} · {money(inv['deposited'])} added along the way.", inv_share, CREAM if inv_on else MUTED, "Included" if inv_on else "Excluded", "strong" if inv_on else "weak")}
  {_signal_card("PAY", money(float(st.session_state.get("salary") or 0)), f"Raises {float(st.session_state.get('raise_pct') or 0):.2f}% every {int(st.session_state.get('raise_every') or 1)} year(s).", 100.0, CREAM, "Active", "strong")}
  {_signal_card("PAYOUT", draw["lasts_label"], "Balance lasts at the monthly draw you set. Open payout below to change it.", 100.0 if payout_ok else 35.0, GREEN if payout_ok else RED, "Covered" if payout_ok else "Short", "strong" if payout_ok else "weak")}
</div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("Count in the total balance")
    include_labels = [
        ("include_ret", "Retirement"),
        ("include_sav", "Savings"),
        ("include_ss", "Social Security"),
    ]
    for i, item in enumerate(inv_items):
        include_labels.append((f"inv_inc_{i}", item.get("name") or f"Investment {i + 1}"))
    box_cols = st.columns(max(3, min(6, len(include_labels))))
    for i, (key, label) in enumerate(include_labels):
        box_cols[i % len(box_cols)].checkbox(label, key=key)
    if nest["parts"]:
        st.caption("Included: " + " · ".join(nest["parts"]))
    else:
        st.caption("Nothing is counted in the total. Turn a source back on above.")

    st.markdown(f"**Salary chart** · {years_note}")
    if acc["rows"]:
        table = pd.DataFrame(acc["rows"])
        show = table[["age", "salary", "you", "employer", "end", "real"]].rename(
            columns={
                "age": "Age",
                "salary": "Salary",
                "you": "You",
                "employer": "Employer",
                "end": "End balance",
                "real": "In today's $",
            }
        )
        for col in show.columns:
            if col != "Age":
                show[col] = show[col].map(lambda v: f"{v:,.0f}")
        stripe = "background-color: rgba(143, 163, 200, 0.22); color: #F6F4E9;"
        plain = "background-color: transparent; color: #F6F4E9;"
        styled = show.style.apply(
            lambda row: [stripe if int(row.name) % 2 else plain] * len(row),
            axis=1,
        )
        st.dataframe(styled, width="stretch", hide_index=True, height=420)
    else:
        st.caption("No years to project yet. Set a retirement age above your current age.")

    with st.expander("Pay, contributions, and timeline", expanded=False, key="exp_inputs"):
        pcol, ccol, tcol = st.columns(3)
        with pcol:
            st.markdown("**Pay**")
            st.number_input("Salary this year ($)", min_value=0.0, step=1000.0, key="salary")
            st.number_input("Raise each time (%)", min_value=0.0, max_value=50.0, step=0.25, key="raise_pct")
            st.segmented_control(
                "Raise arrives every",
                options=[1, 2, 3, 5],
                format_func=lambda y: "1 yr" if y == 1 else f"{y} yrs",
                key="raise_every",
            )
        with ccol:
            st.markdown("**Contributions**")
            st.number_input("You save (% of salary)", min_value=0.0, max_value=100.0, step=0.5, key="save_pct")
            st.number_input("Employer adds (% of salary)", min_value=0.0, max_value=100.0, step=0.5, key="match_pct")
        with tcol:
            st.markdown("**Timeline**")
            st.number_input("Balance today ($)", min_value=0.0, step=1000.0, key="current_savings")
            st.number_input("Age now", min_value=14, max_value=90, step=1, key="current_age")
            st.number_input("Retire at", min_value=15, max_value=100, step=1, key="retire_age")
            st.number_input("Return per year (%)", min_value=-20.0, max_value=30.0, step=0.25, key="pre_return")
            st.number_input("Inflation (%)", min_value=0.0, max_value=20.0, step=0.25, key="inflation")

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
        st.caption("Starting balance plus a monthly contribution while you work. If Social Security is checked above, this book is in the total.")
        ss1, ss2 = st.columns([0.38, 0.62], gap="large")
        with ss1:
            st.number_input("Starting balance ($)", min_value=0.0, step=500.0, key="ss_balance")
            st.number_input("Monthly contribution ($)", min_value=0.0, step=25.0, key="ss_monthly")
            st.number_input("Claim at age", min_value=62, max_value=70, step=1, key="ss_claim_age")
        with ss2:
            st.markdown(
                f"**Social Security** · claim at {ss['claim_age']}"
                + (f" · {acc['years']} working years" if acc["years"] else "")
            )
            g1, g2, g3 = st.columns(3)
            g1.metric("Paid in while working", money(ss["paid"]), f"{money(ss['monthly'])} a month", delta_color="off")
            g2.metric("Starting balance", money(ss["start"]), "today", delta_color="off")
            g3.metric(f"Balance at {acc['retire']}", money(ss["final"]), money(ss["real"]) + " in today's dollars", delta_color="off")
            st.caption("Uncheck Social Security above to leave this book out of the combined total.")

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
            st.session_state.investment_items.append(
                {"name": "New investment", "balance": 0.0, "growth": 7.0, "monthly": 0.0, "include": True}
            )
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
    need_share = _share(budget["needs"], budget["income_total"])
    want_share = _share(budget["wants"], budget["income_total"])
    save_share = _share(budget["savings"], budget["income_total"])
    surplus_kind = "strong" if budget["surplus"] >= 0 else "weak"
    housing_kind = "weak" if budget["housing_ratio"] > 0.30 else "strong"
    need_kind = "strong" if budget["needs"] <= budget["rule"]["need"] else "weak"
    want_kind = "strong" if budget["wants"] <= budget["rule"]["want"] else "weak"
    save_kind = "strong" if budget["savings"] >= budget["rule"]["save"] else "weak"
    score = round((int(need_kind == "strong") + int(want_kind == "strong") + int(save_kind == "strong") + int(housing_kind == "strong")) / 4, 3)

    st.markdown(
        f"""
<div class="dash-hero">
  <div class="dash-hero-top">
    <div>
      <div class="dash-kicker">{_esc(st.session_state.get("plan_name") or "NestLab")}</div>
      <div class="dash-sub">Monthly budget</div>
      <div class="dash-meta">{_esc(datetime.now().strftime("%b %d, %Y %I:%M %p"))}</div>
    </div>
    <div class="dash-price">{_esc(money(budget["surplus"]))}<span>left over this month</span></div>
  </div>
  <div class="dash-pills">
    {_pill("Income", money(budget["income_total"]), "cream")}
    {_pill("Spending", money(budget["expense_total"]), "cream")}
    {_pill("Savings rate", pct(budget["savings_rate"]), "green")}
    {_pill("Housing", pct(budget["housing_ratio"]), "red" if budget["housing_ratio"] > 0.30 else "green")}
    {_pill("Needs", money(budget["needs"]), "amber")}
    {_pill("Wants", money(budget["wants"]), "cream")}
  </div>
</div>
<div class="dash-band">
  {_ring(score * 100, AMBER, size=72, stroke=6, label=str(int(round(score * 100))))}
  <div class="dash-band-copy">
    <h3>50/30/20 SCORE</h3>
    <strong>{score:.3f}</strong>
    <p>Needs 50% · Wants 30% · Savings 20% · Housing under 30%</p>
  </div>
  <div class="dash-pills" style="flex:1;margin-top:0;">
    {_pill("Needs vs 50%", f"{need_share:.0f}%", "amber")}
    {_pill("Wants vs 30%", f"{want_share:.0f}%", "cream")}
    {_pill("Savings vs 20%", f"{save_share:.0f}%", "green")}
    {_pill("Housing", pct(budget["housing_ratio"]), "green" if housing_kind == "strong" else "red")}
  </div>
</div>
<div class="dash-section">SPEND BREAKDOWN</div>
<div class="dash-grid">
  {_signal_card("NEEDS", money(budget["needs"]), f"Target {money(budget['rule']['need'])} (50% of income).", need_share, AMBER if need_kind == "strong" else RED, "On target" if need_kind == "strong" else "High", need_kind)}
  {_signal_card("WANTS", money(budget["wants"]), f"Target {money(budget['rule']['want'])} (30% of income).", want_share, GREEN if want_kind == "strong" else RED, "On target" if want_kind == "strong" else "High", want_kind)}
  {_signal_card("SAVINGS", money(budget["savings"]), f"Target {money(budget['rule']['save'])} (20% of income).", save_share, GREEN if save_kind == "strong" else RED, "On target" if save_kind == "strong" else "Low", save_kind)}
  {_signal_card("HOUSING", money(budget["housing"]), "Common guideline is 30% of income or less.", _share(budget["housing"], budget["income_total"]), GREEN if housing_kind == "strong" else RED, "Ok" if housing_kind == "strong" else "High", housing_kind)}
  {_signal_card("INCOME", money(budget["income_total"]), "Money in this month.", 100.0, CREAM, "Active", "strong")}
  {_signal_card("LEFT OVER", money(budget["surplus"]), "Income minus everything tagged as spending or savings.", 100.0 if budget["surplus"] >= 0 else 20.0, GREEN if budget["surplus"] >= 0 else RED, "Surplus" if budget["surplus"] >= 0 else "Short", surplus_kind)}
</div>
        """,
        unsafe_allow_html=True,
    )

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

    with st.expander("Monthly money out", expanded=False, key="exp_money_out"):
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

with tax_tab:
    seed_item_keys()
    tax_items = _collect_taxes()
    try:
        paychecks = int(st.session_state.get("tax_paychecks") or 26)
    except (TypeError, ValueError):
        paychecks = 26
    if paychecks not in TAX_PAYCHECK_LABELS:
        paychecks = 26
    try:
        horizon = int(st.session_state.get("tax_horizon") or 30)
    except (TypeError, ValueError):
        horizon = 30
    horizon = max(1, min(50, horizon))
    taxes = project_taxes(tax_items, paychecks, horizon)
    kinds = taxes["by_kind"]
    annual = taxes["annual"]
    fed_share = _share(kinds["federal"], annual)
    state_share = _share(kinds["state"], annual)
    car_share = _share(kinds["car"], annual)
    prop_share = _share(kinds["property"], annual)
    other_share = _share(kinds["other"], annual)
    mix_top = max(fed_share, state_share, car_share, prop_share, other_share)
    pay_label = TAX_PAYCHECK_LABELS.get(paychecks, "Every 2 weeks")
    stamped = datetime.now().strftime("%b %d, %Y %I:%M %p")
    n_lines = len(taxes["details"])
    other_n = sum(1 for row in taxes["details"] if row["kind"] == "other")

    st.markdown(
        f"""
<div class="dash-hero">
  <div class="dash-hero-top">
    <div>
      <div class="dash-kicker">{_esc(st.session_state.get("plan_name") or "NestLab")}</div>
      <div class="dash-sub">Information only — not used in Retirement or Budget</div>
      <div class="dash-meta">{n_lines} line{'s' if n_lines != 1 else ''} · { _esc(pay_label.lower()) } · {horizon} year{'s' if horizon != 1 else ''} · {_esc(stamped)}</div>
    </div>
    <div class="dash-price">{_esc(money(annual))}<span>{_esc(money(taxes['monthly']))} a month · {_esc(money(taxes['paycheck']))} a paycheck</span></div>
  </div>
  <div class="dash-pills">
    {_pill("Federal", money(kinds["federal"]), "amber")}
    {_pill("State", money(kinds["state"]), "cream")}
    {_pill("Car", money(kinds["car"]), "green")}
    {_pill("Property", money(kinds["property"]), "cream")}
    {_pill("Other", money(kinds["other"]), "muted")}
    {_pill("This paycheck", money(taxes["paycheck"]), "amber")}
  </div>
</div>
<div class="dash-band">
  {_ring(mix_top, AMBER, size=72, stroke=6, label=str(int(round(mix_top))))}
  <div class="dash-band-copy">
    <h3>TAX MIX</h3>
    <strong>{_esc(money(taxes["monthly"]))}</strong>
    <p>Average cash out per month. Biggest slice is {int(round(mix_top))}% of the year.</p>
  </div>
  <div class="dash-pills" style="flex:1;margin-top:0;">
    {_pill("Federal share", f"{fed_share:.0f}%", "amber")}
    {_pill("State share", f"{state_share:.0f}%", "cream")}
    {_pill("Car share", f"{car_share:.0f}%", "green")}
    {_pill("Property share", f"{prop_share:.0f}%", "cream")}
  </div>
</div>
<div class="dash-section">TAX BREAKDOWN</div>
<div class="dash-grid">
  {_signal_card("FEDERAL", money(kinds["federal"]), "Withholding each paycheck, or the amount you set.", fed_share, AMBER, "Annual", "strong")}
  {_signal_card("STATE", money(kinds["state"]), "State income tax at the cadence you chose.", state_share, "#7B8CDE", "Annual", "strong")}
  {_signal_card("CAR", money(kinds["car"]), "Vehicle tax or registration in the month it is due.", car_share, GREEN, "Annual", "strong" if kinds["car"] else "muted")}
  {_signal_card("PROPERTY", money(kinds["property"]), "Home or land tax in the month it is due.", prop_share, AMBER_HOT, "Annual", "strong" if kinds["property"] else "muted")}
  {_signal_card("OTHER", money(kinds["other"]), f"{other_n} extra line{'s' if other_n != 1 else ''} you added.", other_share, MUTED if kinds["other"] else CREAM, "Custom" if other_n else "None", "strong" if kinds["other"] else "muted")}
  {_signal_card("THIS YEAR", money(annual), f"{money(taxes['monthly'])} a month on average · {money(taxes['years'][-1]['cumulative'])} over {horizon} years.", 100.0, CREAM, "Total", "strong")}
</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Tax's is a separate ledger of what you pay. Changing these lines does not change retirement balances, contributions, payout, or the budget split.")

    sched, years_col = st.columns([0.62, 0.38])
    with sched:
        st.segmented_control(
            "Paychecks arrive",
            options=[52, 26, 24, 12],
            format_func=lambda n: TAX_PAYCHECK_LABELS[n],
            key="tax_paychecks",
        )
    with years_col:
        st.number_input("Years to chart", min_value=1, max_value=50, step=1, key="tax_horizon")

    st.subheader("Tax lines")
    st.caption(
        "Each line is how much you pay and when. Per paycheck follows the schedule above. "
        "Yearly and quarterly lines use the due month so the calendar chart shows the real hit."
    )
    for i, item in enumerate(st.session_state.tax_items):
        vis = "visible" if i == 0 else "collapsed"
        n, a, f, w, rm = st.columns([2.6, 1.6, 1.8, 1.8, 0.9])
        n.text_input("Name", key=f"tax_name_{i}", label_visibility=vis)
        a.number_input("Amount ($)", min_value=0.0, step=25.0, key=f"tax_amt_{i}", label_visibility=vis)
        f.selectbox(
            "Paid",
            options=list(TAX_FREQ_LABELS.keys()),
            format_func=lambda k: TAX_FREQ_LABELS[k],
            key=f"tax_freq_{i}",
            label_visibility=vis,
        )
        freq_now = str(st.session_state.get(f"tax_freq_{i}") or item.get("freq") or "monthly")
        w.selectbox(
            "Due month",
            options=list(range(1, 13)),
            format_func=lambda m: TAX_MONTH_NAMES[m - 1],
            key=f"tax_when_{i}",
            label_visibility=vis,
            disabled=freq_now not in ("yearly", "quarterly"),
        )
        if rm.button("Remove", key=f"tax_del_{i}"):
            st.session_state.tax_items = _collect_taxes()
            st.session_state.tax_items.pop(i)
            _clear_item_keys()
            st.rerun()
    if st.button("Add tax line"):
        st.session_state.tax_items = _collect_taxes()
        st.session_state.tax_items.append(
            {"name": "New tax", "amount": 0.0, "freq": "monthly", "when": 1, "kind": "other"}
        )
        _clear_item_keys()
        st.rerun()

    month_labels = [name[:3] for name in TAX_MONTH_NAMES]
    this_year = go.Figure()
    if taxes["details"]:
        for idx, row in enumerate(taxes["details"]):
            this_year.add_trace(
                go.Bar(
                    name=row["name"],
                    x=month_labels,
                    y=row["year1_months"],
                    marker_color=_tax_color(row["kind"], idx),
                )
            )
        this_year.update_layout(barmode="stack")
        this_year.update_xaxes(title_text="This year")
        this_year.update_yaxes(title_text="Paid", tickprefix="$", separatethousands=True)
        st.plotly_chart(_chart_layout(this_year, 360), width="stretch")
    else:
        st.caption("Add a tax line to see when the money goes out this year.")

    over_time = go.Figure()
    if taxes["details"]:
        xs = list(range(0, taxes["horizon"] + 1))
        x_title = "Year"
        for idx, row in enumerate(taxes["details"]):
            running = 0.0
            ys = [0.0]
            for _year in range(taxes["horizon"]):
                running += row["annual"]
                ys.append(running)
            color = _tax_color(row["kind"], idx)
            over_time.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    name=row["name"],
                    stackgroup="one",
                    mode="lines",
                    line=dict(width=0.8, color=color),
                    fillcolor=_hex_rgba(color, 0.45),
                )
            )
        over_time.update_xaxes(title_text=x_title)
        over_time.update_yaxes(title_text="Paid so far", tickprefix="$", separatethousands=True)
        st.plotly_chart(_chart_layout(over_time, 420), width="stretch")

    if taxes["details"]:
        table = pd.DataFrame(
            [
                {
                    "Tax": row["name"],
                    "Each payment": row["amount"],
                    "When": TAX_FREQ_LABELS.get(row["freq"], row["freq"]),
                    "Due": TAX_MONTH_NAMES[row["when"] - 1] if row["freq"] in ("yearly", "quarterly") else "—",
                    "Times / year": row["payments"],
                    "This year": row["annual"],
                    f"Over {horizon} yrs": row["annual"] * horizon,
                }
                for row in taxes["details"]
            ]
        )
        for col in table.columns:
            if col not in ("Tax", "When", "Due", "Times / year"):
                table[col] = table[col].map(lambda v: f"{v:,.0f}")
        st.dataframe(table, width="stretch", hide_index=True)
        t1, t2, t3 = st.columns(3)
        t1.metric("This year", money(annual), f"{money(taxes['monthly'])} a month", delta_color="off")
        t2.metric("Each paycheck", money(taxes["paycheck"]), pay_label, delta_color="off")
        t3.metric(f"Paid over {horizon} years", money(taxes["years"][-1]["cumulative"]), "no growth — cash out the door", delta_color="off")

st.markdown(
    f'<div class="aiu-footer">Built by '
    f'<a href="{SITE_URL}" target="_blank" rel="noopener">AI Upscale LLC</a>'
    f" · Columbia, SC · Planning estimates only — not financial, tax, or investment advice</div>",
    unsafe_allow_html=True,
)
