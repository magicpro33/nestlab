"""Passive income tab: loan cost versus a dividend or Treasury payout."""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import money, money_cents
from passive import (
    FILING_LABELS,
    TaxAssumptions,
    assumptions_for,
    load_dividends,
    load_market,
    project_carry,
    quotes_from_sources,
    rank_stocks,
)

NAVY = "#081325"
NAVY_MID = "#0d1d38"
AMBER = "#F5A623"
CREAM = "#F6F4E9"
MUTED = "#8FA3C8"
GREEN = "#00b87a"
RED = "#e05252"
BORDER = "#1a2f4a"


def _esc(value: object) -> str:
    return html.escape(str(value))


def _tone(value: float) -> str:
    if value > 1:
        return GREEN
    if value < -1:
        return RED
    return CREAM


def _pill(label: str, value: str, color: str) -> str:
    return (
        f'<div class="dash-pill"><span>{_esc(label)}</span>'
        f'<strong style="color:{color}">{_esc(value)}</strong></div>'
    )


def _card(title: str, value: str, detail: str, color: str, kind: str) -> str:
    badge = {"strong": "Clears", "weak": "Short", "muted": "Set"}.get(kind, kind)
    return (
        f'<div class="dash-card">'
        f'<div class="dash-card-head"><span>{_esc(title)}</span>'
        f'<span class="dash-badge dash-badge-{kind}">{_esc(badge)}</span></div>'
        f'<div class="dash-card-body"><div class="dash-card-value" style="color:{color}">{_esc(value)}</div></div>'
        f'<p class="dash-card-copy">{_esc(detail)}</p>'
        f'<div class="dash-card-bar" style="background:{color}"></div>'
        f"</div>"
    )


def _chart(fig: go.Figure, height: int = 380) -> go.Figure:
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


def _fallback_market() -> dict:
    loans, treasuries = quotes_from_sources()
    return {
        "fetched_at": "",
        "notes": ["Live rates could not be loaded. Showing the saved survey."],
        "loans": [row.__dict__ for row in loans],
        "treasuries": [row.__dict__ for row in treasuries],
    }


def _market() -> dict:
    if st.session_state.get("pi_market_force"):
        st.session_state.pi_market_force = False
        with st.spinner("Checking Treasury, Freddie Mac, and Bankrate…"):
            try:
                st.session_state.pi_market = load_market(force=True)
            except Exception as exc:
                st.session_state.pi_market = _fallback_market()
                st.session_state.pi_market["notes"] = [f"Rate refresh failed ({exc.__class__.__name__})."]
    if "pi_market" not in st.session_state:
        with st.spinner("Loading current loan rates and Treasury yields…"):
            try:
                st.session_state.pi_market = load_market()
            except Exception as exc:
                st.session_state.pi_market = _fallback_market()
                st.session_state.pi_market["notes"] = [f"Rate load failed ({exc.__class__.__name__})."]
    return st.session_state.pi_market


def _dividends() -> dict | None:
    if st.session_state.get("pi_div_force"):
        st.session_state.pi_div_force = False
        with st.spinner("Downloading the nightly stock dump and ranking dividend payers…"):
            try:
                st.session_state.pi_dividends = load_dividends(force=True)
                st.session_state.pi_div_error = ""
            except Exception as exc:
                st.session_state.pi_div_error = f"Nightly dump unavailable ({exc.__class__.__name__})."
    if "pi_dividends" not in st.session_state and not st.session_state.get("pi_div_error"):
        with st.spinner("Reading the nightly stock dump for dividend payers…"):
            try:
                st.session_state.pi_dividends = load_dividends()
                st.session_state.pi_div_error = ""
            except Exception as exc:
                st.session_state.pi_div_error = f"Nightly dump unavailable ({exc.__class__.__name__})."
                st.session_state.pi_dividends = None
    return st.session_state.get("pi_dividends")


def _cap(value: float | None) -> str:
    if not value:
        return "—"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    return f"${value:,.0f}"


def _sync_loan() -> None:
    catalog = {row["key"]: row for row in st.session_state.get("pi_loan_rows") or []}
    chosen = catalog.get(st.session_state.get("pi_loan_key"))
    if not chosen:
        return
    st.session_state.pi_rate = float(chosen["rate"])
    st.session_state.pi_term = int(chosen["term_years"])
    st.session_state.pi_style = chosen["style"] if chosen["style"] in ("interest_only", "amortizing") else "amortizing"


def _preset_high() -> None:
    st.session_state.pi_min_yield = 3.0
    st.session_state.pi_max_yield = 12.0
    st.session_state.pi_min_cap = 2.0


def _preset_steady() -> None:
    st.session_state.pi_min_yield = 2.0
    st.session_state.pi_max_yield = 7.0
    st.session_state.pi_min_cap = 50.0


def render_passive_tab() -> None:
    market = _market()
    loans = list(market.get("loans") or [])
    treasuries = list(market.get("treasuries") or [])
    if not loans:
        loans = _fallback_market()["loans"]
    st.session_state.pi_loan_rows = loans
    loan_keys = [row["key"] for row in loans]
    if st.session_state.get("pi_loan_key") not in loan_keys:
        st.session_state.pi_loan_key = "heloc" if "heloc" in loan_keys else loan_keys[0]
        _sync_loan()
    st.session_state.setdefault("pi_amount", 100_000.0)
    st.session_state.setdefault("pi_rate", 7.29)
    st.session_state.setdefault("pi_term", 10)
    st.session_state.setdefault("pi_style", "interest_only")
    st.session_state.setdefault("pi_filing", "single")
    st.session_state.setdefault("pi_other", 80_000.0)
    st.session_state.setdefault("pi_magi", 80_000.0)
    st.session_state.setdefault("pi_qualified", "qualified")
    st.session_state.setdefault("pi_state", 0.0)
    st.session_state.setdefault("pi_deduct", False)
    st.session_state.setdefault("pi_custom_yield", 6.0)
    st.session_state.setdefault("pi_min_yield", 3.0)
    st.session_state.setdefault("pi_max_yield", 12.0)
    st.session_state.setdefault("pi_min_cap", 2.0)
    st.session_state.setdefault("pi_query", "")

    by_loan = {row["key"]: row for row in loans}
    chosen_loan = by_loan[st.session_state.pi_loan_key]

    st.caption(
        "Borrowing against the house to buy a payout is a leverage sketch. "
        "A Treasury held to maturity has a set yield. A stock dividend is whatever the company last paid — it can be cut. "
        "This is not a quote and not tax advice."
    )

    left, right = st.columns([0.58, 0.42], gap="large")
    with left:
        st.number_input(
            "Amount to borrow and invest ($)",
            min_value=0.0,
            step=5_000.0,
            key="pi_amount",
        )
        st.selectbox(
            "Loan",
            options=loan_keys,
            format_func=lambda key: by_loan[key]["label"],
            key="pi_loan_key",
            on_change=_sync_loan,
        )
        st.caption(chosen_loan.get("note") or "")
        r1, r2 = st.columns(2)
        r1.number_input("Rate (%)", min_value=0.0, max_value=40.0, step=0.01, format="%.2f", key="pi_rate")
        r2.number_input("Term (years)", min_value=1, max_value=40, step=1, key="pi_term")
        st.segmented_control(
            "Payments",
            options=["interest_only", "amortizing"],
            format_func=lambda value: "Interest only" if value == "interest_only" else "Principal and interest",
            key="pi_style",
        )
    with right:
        st.selectbox(
            "Filing status",
            options=list(FILING_LABELS),
            format_func=lambda key: FILING_LABELS[key],
            key="pi_filing",
        )
        st.number_input(
            "Other taxable income ($)",
            min_value=0.0,
            step=1_000.0,
            key="pi_other",
            help="Taxable income before this payout, after the standard deduction or itemized deductions. The payout stacks on top.",
        )
        st.number_input(
            "MAGI before this payout ($)",
            min_value=0.0,
            step=1_000.0,
            key="pi_magi",
            help="The 3.8% net investment income tax uses MAGI, which is usually higher than taxable income. Under $200,000 single / $250,000 joint, the surtax is zero.",
        )
        st.segmented_control(
            "Dividend tax treatment",
            options=["qualified", "ordinary"],
            format_func=lambda value: "Qualified" if value == "qualified" else "Ordinary",
            key="pi_qualified",
        )
        st.number_input(
            "State tax on this income (%)",
            min_value=0.0,
            max_value=15.0,
            step=0.1,
            format="%.1f",
            key="pi_state",
            help="Flat state rate on the payout. Treasury interest is left at zero state tax, which is the federal rule.",
        )
        st.checkbox(
            "Deduct loan interest against the payout",
            key="pi_deduct",
            help="Off by default. Mortgage interest is generally deductible only when the money improves the home. Interest on money borrowed to buy investments can be an itemized investment-interest deduction, limited to investment income.",
        )

    amount = float(st.session_state.pi_amount or 0.0)
    rate = float(st.session_state.pi_rate or 0.0)
    term = int(st.session_state.pi_term or 1)
    style = st.session_state.pi_style if st.session_state.pi_style in ("interest_only", "amortizing") else "amortizing"
    base_tax = TaxAssumptions(
        filing=st.session_state.pi_filing,
        other_taxable=float(st.session_state.pi_other or 0.0),
        magi_before=float(st.session_state.pi_magi or 0.0),
        qualified=st.session_state.pi_qualified == "qualified",
        state_pct=float(st.session_state.pi_state or 0.0),
        deduct_interest=bool(st.session_state.pi_deduct),
    )

    board = _dividends()
    ranked: list[dict] = []
    if board and board.get("rows"):
        ranked = rank_stocks(
            board["rows"],
            min_yield=float(st.session_state.pi_min_yield),
            max_yield=float(st.session_state.pi_max_yield),
            min_cap=float(st.session_state.pi_min_cap) * 1_000_000_000,
            query=str(st.session_state.pi_query or ""),
            limit=40,
        )

    picks: list[tuple[str, str, str, float]] = [("custom", "Type a yield", "stock", float(st.session_state.pi_custom_yield))]
    for quote in treasuries:
        picks.append((f"treasury:{quote['key']}", f"{quote['label']} · {quote['rate']:.2f}%", "treasury", float(quote["rate"])))
    for row in ranked:
        picks.append((f"stock:{row['ticker']}", f"{row['ticker']} · {row['yield_pct']:.2f}%", "stock", float(row["yield_pct"])))
    pick_ids = [item[0] for item in picks]
    if st.session_state.get("pi_pick") not in pick_ids:
        preferred = f"stock:{ranked[0]['ticker']}" if ranked else "treasury:t10y"
        st.session_state.pi_pick = preferred if preferred in pick_ids else pick_ids[0]
    by_pick = {item[0]: item for item in picks}

    st.selectbox(
        "Run this loan against",
        options=pick_ids,
        format_func=lambda key: by_pick[key][1],
        key="pi_pick",
    )
    kind = by_pick[st.session_state.pi_pick][2]
    yield_pct = float(by_pick[st.session_state.pi_pick][3])
    if st.session_state.pi_pick == "custom":
        st.number_input(
            "Yield you want to test (%)",
            min_value=0.0,
            max_value=40.0,
            step=0.05,
            format="%.2f",
            key="pi_custom_yield",
        )
        yield_pct = float(st.session_state.pi_custom_yield or 0.0)
        by_pick["custom"] = ("custom", "Type a yield", "stock", yield_pct)

    assumptions = assumptions_for(base_tax, kind)
    plan = project_carry(amount, rate, term, yield_pct, style, assumptions)
    year1 = plan.year1
    label = by_pick[st.session_state.pi_pick][1]
    clears = year1.net >= 0
    covers_bill = year1.cash >= 0
    style_label = "interest only" if style == "interest_only" else "principal and interest"
    tax_label = "ordinary federal, no state tax" if kind == "treasury" else (
        "qualified dividends" if base_tax.qualified else "ordinary dividends"
    )
    verdict = (
        f"Year 1 clears interest and tax by {money(year1.net)}."
        if clears
        else f"Year 1 is short {money(abs(year1.net))} after interest and tax."
    )
    bill_line = (
        "The payout also covers the full payment."
        if covers_bill
        else f"The full payment still needs {money(abs(year1.cash))} from somewhere else."
    )
    if style == "interest_only":
        bill_line = f"Interest-only, so the {money(amount)} principal is still owed at the end. " + bill_line

    stamped = market.get("fetched_at") or datetime.now().isoformat(timespec="seconds")
    try:
        stamped_label = datetime.fromisoformat(stamped).strftime("%b %d, %Y %I:%M %p")
    except ValueError:
        stamped_label = stamped

    st.markdown(
        f"""
<div class="dash-hero">
  <div class="dash-hero-top">
    <div>
      <div class="dash-kicker">Passive income</div>
      <div class="dash-sub">{_esc(label)} against {_esc(chosen_loan['label'])}</div>
      <div class="dash-meta">{_esc(money(amount))} · {rate:.2f}% · {term} yrs · {_esc(style_label)} · {_esc(tax_label)} · {_esc(stamped_label)}</div>
    </div>
    <div class="dash-price" style="color:{_tone(year1.net)}">{_esc(money(year1.net))}<span>left in year 1 after interest and tax</span></div>
  </div>
  <div class="dash-pills">
    {_pill("Payout / year", money(year1.payout), CREAM)}
    {_pill("Interest / year", money(year1.interest), AMBER)}
    {_pill("Tax / year", money(year1.tax), AMBER)}
    {_pill("Payment / month", money_cents(plan.monthly_payment), CREAM)}
    {_pill("Yield you need", f"{plan.breakeven_yield:.2f}%", GREEN if yield_pct + 1e-9 >= plan.breakeven_yield else RED)}
    {_pill("This yield", f"{yield_pct:.2f}%", GREEN if clears else RED)}
  </div>
</div>
<div class="dash-section">YEAR 1</div>
<div class="dash-grid">
  {_card("AFTER INTEREST + TAX", money(year1.net), verdict, _tone(year1.net), "strong" if clears else "weak")}
  {_card("AFTER THE PAYMENT + TAX", money(year1.cash), bill_line, _tone(year1.cash), "strong" if covers_bill else "weak")}
  {_card("TAX DUE", money(year1.tax), "Federal, plus the 3.8% surtax when MAGI is over the line, plus state if you set one.", AMBER, "muted")}
  {_card("INTEREST", money(year1.interest), f"{money(plan.total_interest)} of interest over {term} years if the rate stays put.", AMBER, "muted")}
  {_card("PAYOUT", money(year1.payout), f"{money(plan.total_payout)} over {term} years if the yield never changes.", CREAM, "muted")}
  {_card("OVER THE FULL TERM", money(plan.total_net), "Dividends or interest received, minus loan interest, minus tax. Principal you pay back is not counted as a loss.", _tone(plan.total_net), "strong" if plan.total_net >= 0 else "weak")}
</div>
        """,
        unsafe_allow_html=True,
    )
    if kind == "treasury":
        st.caption("Treasury interest is taxed as ordinary income. State tax is left at zero. The yield assumes you hold to maturity.")
    else:
        st.caption(
            "Qualified treatment needs the holding-period rule. "
            "The hurdle yield is the payout that covers this year's interest and the tax on that payout."
        )

    if plan.years:
        fig = go.Figure()
        xs = [row.year for row in plan.years]
        fig.add_trace(go.Bar(name="Payout", x=xs, y=[row.payout for row in plan.years], marker_color="#5DCAA5"))
        fig.add_trace(go.Bar(name="Interest", x=xs, y=[row.interest for row in plan.years], marker_color=AMBER))
        fig.add_trace(go.Bar(name="Tax", x=xs, y=[row.tax for row in plan.years], marker_color="#E07070"))
        fig.add_trace(
            go.Scatter(
                name="After interest and tax",
                x=xs,
                y=[row.net for row in plan.years],
                mode="lines+markers",
                line=dict(color=CREAM, width=2.5),
            )
        )
        fig.update_layout(barmode="group")
        fig.update_xaxes(title_text="Year", dtick=1 if term <= 15 else 5)
        st.plotly_chart(_chart(fig), width="stretch")

    st.markdown('<div class="dash-section">SAME PAYOUT, EVERY LOAN</div>', unsafe_allow_html=True)
    st.caption("Catalog rates, not the edited rate above. This is the menu: HELOC, second mortgage, cash-out mortgage, personal loan.")
    compare_rows = []
    for quote in loans:
        sample = project_carry(
            amount,
            float(quote["rate"]),
            int(quote["term_years"]),
            yield_pct,
            quote["style"],
            assumptions,
        )
        first = sample.year1
        compare_rows.append(
            {
                "Loan": quote["label"],
                "Rate": f"{float(quote['rate']):.2f}%",
                "As of": quote.get("asof") or "—",
                "Source": quote.get("source") or "",
                "Payment / mo": money_cents(sample.monthly_payment),
                "Interest yr 1": money(first.interest),
                "Tax yr 1": money(first.tax),
                "After interest + tax": money(first.net),
                "After payment + tax": money(first.cash),
                "Clears interest": "Yes" if first.net >= 0 else "No",
            }
        )
    if compare_rows:
        st.dataframe(pd.DataFrame(compare_rows), width="stretch", hide_index=True)

    rate_head, rate_btn = st.columns([0.8, 0.2])
    rate_head.markdown('<div class="dash-section">RATES JUST LOADED</div>', unsafe_allow_html=True)
    if rate_btn.button("Refresh rates", key="pi_refresh_rates"):
        st.session_state.pi_market_force = True
        st.session_state.pop("pi_market", None)
        st.rerun()
    notes = market.get("notes") or []
    if notes:
        st.caption(" · ".join(str(note) for note in notes))
    live_rows = []
    for quote in list(loans) + list(treasuries):
        live_rows.append(
            {
                "Rate": quote["label"],
                "Percent": f"{float(quote['rate']):.2f}%",
                "As of": quote.get("asof") or "—",
                "Source": quote.get("source") or "",
                "Live": "Yes" if quote.get("live") else "Saved",
            }
        )
    st.dataframe(pd.DataFrame(live_rows), width="stretch", hide_index=True)
    st.caption(
        "Home equity and HELOC averages are Bankrate’s lender survey. "
        "Mortgage averages are Freddie Mac’s weekly survey. "
        "Treasury yields are the Treasury’s daily par curve. Your own offer will differ with credit, equity, and points."
    )

    st.markdown('<div class="dash-section">SET PAYOUT — TREASURIES</div>', unsafe_allow_html=True)
    st.caption(
        "These are the closest thing to a guaranteed nominal payout: the U.S. Treasury sets the yield if you hold to maturity. "
        "Borrowing at a home-equity rate to buy them usually loses, because the loan costs more than the bond pays. "
        "The price of a note can fall if you sell before maturity."
    )
    treasury_rows = []
    for quote in treasuries:
        sample = project_carry(
            amount,
            rate,
            term,
            float(quote["rate"]),
            style,
            assumptions_for(base_tax, "treasury"),
        )
        first = sample.year1
        treasury_rows.append(
            {
                "Treasury": quote["label"],
                "Yield": f"{float(quote['rate']):.2f}%",
                "As of": quote.get("asof") or "—",
                "Payout / yr": money(first.payout),
                "Tax / yr": money(first.tax),
                "After interest + tax": money(first.net),
                "After payment + tax": money(first.cash),
            }
        )
    if treasury_rows:
        st.dataframe(pd.DataFrame(treasury_rows), width="stretch", hide_index=True)

    st.markdown('<div class="dash-section">HIGHEST HISTORICAL DIVIDENDS</div>', unsafe_allow_html=True)
    st.caption(
        "From the nightly stock dump. Yield is the annual cash dividend divided by the price in that file. "
        "Nothing here is guaranteed. Yields above 12% are hidden unless you raise the cap — those are often a fallen price, a special dividend, or a foreign dividend recorded in the wrong currency."
    )
    if st.session_state.get("pi_div_error"):
        st.error(st.session_state.pi_div_error)
    meta_col, dump_btn = st.columns([0.8, 0.2])
    if board:
        meta_col.caption(
            f"Dump as of {board.get('asof') or '—'} · {len(board.get('rows') or [])} names with a dividend · "
            f"{board.get('note') or ''}".strip()
        )
    else:
        meta_col.caption("Dividend list has not loaded.")
    if dump_btn.button("Reload dump", key="pi_reload_dump"):
        st.session_state.pi_div_force = True
        st.session_state.pop("pi_dividends", None)
        st.session_state.pi_div_error = ""
        st.rerun()

    f1, f2, f3 = st.columns(3)
    f1.number_input("Minimum yield (%)", min_value=0.0, max_value=30.0, step=0.25, key="pi_min_yield")
    f2.number_input("Maximum yield (%)", min_value=0.5, max_value=60.0, step=0.5, key="pi_max_yield")
    f3.number_input("Minimum size ($ billions)", min_value=0.0, max_value=500.0, step=1.0, key="pi_min_cap")
    st.text_input("Find a ticker or sector", key="pi_query", placeholder="MO, utilities, realty")
    p1, p2 = st.columns(2)
    p1.button("Highest yields", key="pi_preset_high", on_click=_preset_high)
    p2.button("Large steadier payers", key="pi_preset_steady", on_click=_preset_steady)

    if ranked:
        stock_rows = []
        for row in ranked:
            sample = project_carry(amount, rate, term, float(row["yield_pct"]), style, assumptions_for(base_tax, "stock"))
            first = sample.year1
            stock_rows.append(
                {
                    "Ticker": row["ticker"],
                    "Sector": row.get("sector") or "",
                    "Price": f"{float(row['price']):,.2f}" if row.get("price") else "—",
                    "Yield": f"{float(row['yield_pct']):.2f}%",
                    "Paid": row.get("frequency") or "—",
                    "Payout %": f"{float(row['payout']):.0f}" if row.get("payout") is not None else "—",
                    "Size": _cap(row.get("market_cap")),
                    "Income / yr": money(first.payout),
                    "Tax": money(first.tax),
                    "After interest + tax": money(first.net),
                    "After payment + tax": money(first.cash),
                }
            )
        st.dataframe(pd.DataFrame(stock_rows), width="stretch", hide_index=True, height=480)
        st.caption(
            "Payout % is the dividend divided by accounting earnings in the dump. "
            "REITs and partnerships often print over 100% and still keep paying. "
            "A common corporation over 100% is spending more than it earns. "
            "Pick a ticker in “Run this loan against” to put it on the chart."
        )
    elif board:
        st.caption("Nothing in the dump matches those filters. Widen the yield cap or lower the size minimum.")
