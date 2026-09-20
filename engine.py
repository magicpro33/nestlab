"""Retirement and budget math for NestLab.

Accumulation, sidecar savings, and payout follow the monthly-compounding
model in retirement-calculator.html: salary raises on a cadence, you and
the employer each save a percent of pay, then a separate savings book and
a drawdown / break-even check.
"""

from __future__ import annotations

from typing import Any


SAFE_WITHDRAWAL_RATE = 0.04


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def inflate(amount: float, rate: float, years: int) -> float:
    return amount * ((1.0 + rate) ** years)


def required_nest_egg(annual_income: float, withdrawal_rate: float = SAFE_WITHDRAWAL_RATE) -> float:
    if withdrawal_rate <= 0:
        return 0.0
    return annual_income / withdrawal_rate


def monthly_rate(annual: float) -> float:
    if annual <= -1.0:
        return 0.0
    return (1.0 + annual) ** (1.0 / 12.0) - 1.0


def project_accumulation(p: dict[str, Any]) -> dict[str, Any]:
    """Pre-retirement projection with monthly compounding and salary raises."""
    salary0 = _as_float(p.get("salary"), 75_000)
    raise_pct = _as_float(p.get("raise_pct"), 3.0) / 100.0
    raise_every = max(1, _as_int(p.get("raise_every"), 1))
    save_pct = _as_float(p.get("save_pct"), 10.0) / 100.0
    match_pct = _as_float(p.get("match_pct"), 4.0) / 100.0
    ret = _as_float(p.get("pre_return"), 7.0) / 100.0
    infl = _as_float(p.get("inflation"), 2.5) / 100.0
    balance = _as_float(p.get("current_savings"), 25_000)
    age = _as_int(p.get("current_age"), 35)
    retire = _as_int(p.get("retire_age"), 65)
    years = max(0, retire - age)
    mr = monthly_rate(ret)
    start_bal = balance
    total_you = 0.0
    total_emp = 0.0
    total_growth = 0.0
    rows: list[dict[str, Any]] = []

    for i in range(years):
        steps = i // raise_every
        salary = salary0 * ((1.0 + raise_pct) ** steps)
        you = salary * save_pct
        emp = salary * match_pct
        m_add = (you + emp) / 12.0
        opened = balance
        growth = 0.0
        for _ in range(12):
            gain = balance * mr
            growth += gain
            balance += gain + m_add
        total_you += you
        total_emp += emp
        total_growth += growth
        rows.append(
            {
                "year": i + 1,
                "age": age + i + 1,
                "salary": salary,
                "you": you,
                "employer": emp,
                "growth": growth,
                "open": opened,
                "end": balance,
                "real": balance / ((1.0 + infl) ** (i + 1)),
                "raise": raise_pct != 0 and i > 0 and i % raise_every == 0,
            }
        )

    real_final = balance / ((1.0 + infl) ** years) if years else balance
    income_4 = balance * SAFE_WITHDRAWAL_RATE
    return {
        "rows": rows,
        "years": years,
        "age": age,
        "retire": retire,
        "start_bal": start_bal,
        "final": balance,
        "real": real_final,
        "salary0": salary0,
        "total_you": total_you,
        "total_emp": total_emp,
        "total_growth": total_growth,
        "income_4": income_4,
        "raise_every": raise_every,
    }


def project_savings(p: dict[str, Any], acc: dict[str, Any]) -> dict[str, Any]:
    """Sidecar savings on the same salary timeline."""
    bal = _as_float(p.get("s_balance"), 10_000)
    rate = _as_float(p.get("s_rate"), 4.0) / 100.0
    pct = _as_float(p.get("s_pct"), 5.0) / 100.0
    amt = _as_float(p.get("s_amt"), 200.0)
    freq = str(p.get("s_freq") or "monthly")
    infl = _as_float(p.get("inflation"), 2.5) / 100.0
    if freq == "biweekly":
        flat_m = amt * 26.0 / 12.0
    elif freq == "yearly":
        flat_m = amt / 12.0
    else:
        flat_m = amt
    mr = monthly_rate(rate)
    start_bal = bal
    from_pct = 0.0
    from_flat = 0.0
    interest = 0.0
    pts = [bal]
    years = acc["years"]
    for i in range(years):
        salary = acc["rows"][i]["salary"] if acc["rows"] else acc["salary0"]
        m_add = (salary * pct) / 12.0 + flat_m
        for _ in range(12):
            gain = bal * mr
            interest += gain
            bal += gain + m_add
        from_pct += salary * pct
        from_flat += flat_m * 12.0
        pts.append(bal)
    real = bal / ((1.0 + infl) ** years) if years else bal
    return {
        "start_bal": start_bal,
        "final": bal,
        "pts": pts,
        "rate": rate,
        "deposited": from_pct + from_flat,
        "from_pct": from_pct,
        "from_flat": from_flat,
        "interest": interest,
        "real": real,
    }


def _duration_months(months: float) -> str:
    if not (months >= 0) or months == float("inf"):
        return "—"
    whole = int(round(months))
    years = whole // 12
    leftover = whole % 12
    if years <= 0:
        return f"{leftover} month" if leftover == 1 else f"{leftover} months"
    label = f"{years} yr" if years == 1 else f"{years} yrs"
    if leftover:
        label += f" {leftover} mo"
    return label


def project_payout(p: dict[str, Any], acc: dict[str, Any], sav: dict[str, Any]) -> dict[str, Any]:
    """Monthly drawdown, break-even vs money paid in, and how long the balance lasts."""
    pay = _as_float(p.get("p_amt"), 5_000)
    rate = _as_float(p.get("p_return"), 5.0) / 100.0
    both = str(p.get("p_src") or "ret") == "both"
    base_you = str(p.get("p_base") or "you") == "you"
    bal0 = acc["final"] + (sav["final"] if both else 0.0)
    if base_you:
        paid_in = acc["total_you"] + (sav["deposited"] if both else 0.0)
    else:
        paid_in = acc["start_bal"] + acc["total_you"] + acc["total_emp"]
        if both:
            paid_in += sav["start_bal"] + sav["deposited"]
    mr = monthly_rate(rate)
    bal = bal0
    received = 0.0
    depleted = None
    bal_at_be = None
    be_months = (paid_in / pay) if pay > 0 else float("inf")
    pts = [{"m": 0, "recv": 0.0, "bal": bal0}]
    cap = 720
    for m in range(1, cap + 1):
        bal = bal * (1.0 + mr) - pay
        received += pay
        if bal <= 0 and depleted is None:
            depleted = m
            received += bal
            bal = 0.0
        if bal_at_be is None and received >= paid_in:
            bal_at_be = bal
        if m % 12 == 0 or depleted == m:
            pts.append({"m": m, "recv": received, "bal": bal})
        if depleted is not None:
            break

    sustainable = bal0 * mr
    be_reached = depleted is None or (pay > 0 and be_months <= depleted)
    retire = acc["retire"]
    return {
        "P": pay,
        "annual": pay * 12.0,
        "bal0": bal0,
        "paid_in": paid_in,
        "mr": mr,
        "be_months": be_months,
        "be_label": _duration_months(be_months) if pay > 0 else "—",
        "be_age": int(retire + be_months / 12.0) if pay > 0 and be_months != float("inf") else None,
        "depleted": depleted,
        "lasts_label": "Indefinitely" if depleted is None else _duration_months(float(depleted)),
        "empty_age": None if depleted is None else int(retire + depleted / 12.0),
        "bal_at_be": bal_at_be,
        "pts": pts,
        "sustainable": sustainable,
        "both": both,
        "total_received": received,
        "be_reached": be_reached,
    }


def monthly_payout_for_years(balance: float, annual_pct: float, years: int = 30) -> float:
    months = max(1, years * 12)
    mr = monthly_rate(annual_pct / 100.0)
    if abs(mr) < 1e-15:
        return balance / months
    return balance * mr / (1.0 - (1.0 + mr) ** (-months))


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def money_cents(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def pct_of(part: float, whole: float) -> str:
    if whole <= 0:
        return "—"
    return f"{round(part / whole * 100)}%"


def summarize_budget(income: list[dict[str, Any]], expenses: list[dict[str, Any]]) -> dict[str, Any]:
    income_total = sum(_as_float(item.get("amount")) for item in income)
    expense_rows = []
    by_kind = {"need": 0.0, "want": 0.0, "save": 0.0}
    housing = 0.0

    for item in expenses:
        amount = _as_float(item.get("amount"))
        kind = str(item.get("kind") or "want").lower()
        if kind not in by_kind:
            kind = "want"
        name = str(item.get("name") or "Other")
        by_kind[kind] += amount
        if "hous" in name.lower() or "rent" in name.lower() or "mortgage" in name.lower():
            housing += amount
        expense_rows.append({"name": name, "amount": amount, "kind": kind})

    expense_total = sum(by_kind.values())
    surplus = income_total - expense_total
    savings_rate = (by_kind["save"] / income_total) if income_total else 0.0
    housing_ratio = (housing / income_total) if income_total else 0.0

    rule = {
        "need": income_total * 0.50,
        "want": income_total * 0.30,
        "save": income_total * 0.20,
    }

    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "surplus": surplus,
        "needs": by_kind["need"],
        "wants": by_kind["want"],
        "savings": by_kind["save"],
        "savings_rate": savings_rate,
        "housing": housing,
        "housing_ratio": housing_ratio,
        "rule": rule,
        "expenses": expense_rows,
    }
