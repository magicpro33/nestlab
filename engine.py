"""Retirement and budget math for NestLab.

Accumulation, sidecar savings, Social Security contributions, named
investments, and payout follow the monthly-compounding model in
retirement-calculator.html: salary raises on a cadence, you and the
employer each save a percent of pay, then separate books for savings,
payroll tax, other accounts, and a drawdown / break-even check.
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


def project_social_security(p: dict[str, Any], acc: dict[str, Any]) -> dict[str, Any]:
    """Starting SS balance plus a flat monthly contribution while working."""
    start = _as_float(p.get("ss_balance"))
    monthly = _as_float(p.get("ss_monthly"), 400.0)
    claim = _as_int(p.get("ss_claim_age"), 67)
    infl = _as_float(p.get("inflation"), 2.5) / 100.0
    years = acc["years"]
    paid = monthly * 12.0 * years
    final = start + paid
    real = final / ((1.0 + infl) ** years) if years else final
    return {
        "start": start,
        "paid": paid,
        "monthly": monthly,
        "final": final,
        "real": real,
        "claim_age": claim,
        "nest_egg": final,
        "nest_egg_today": real,
    }


def combine_balance(
    acc: dict[str, Any],
    sav: dict[str, Any],
    inv: dict[str, Any],
    ss: dict[str, Any],
    include_ret: bool = True,
    include_sav: bool = True,
    include_ss: bool = True,
    included_investments: list[bool] | None = None,
) -> dict[str, Any]:
    """Sum selected books into one nest egg.

    Social Security is starting balance plus monthly contributions while working.
    """
    total = 0.0
    real = 0.0
    contributed = 0.0
    parts: list[str] = []

    if include_ret:
        total += _as_float(acc.get("final"))
        real += _as_float(acc.get("real"))
        contributed += _as_float(acc.get("total_you")) + _as_float(acc.get("total_emp"))
        parts.append("retirement")
    if include_sav:
        total += _as_float(sav.get("final"))
        real += _as_float(sav.get("real"))
        contributed += _as_float(sav.get("deposited"))
        parts.append("savings")

    details = list(inv.get("details") or [])
    flags = included_investments if included_investments is not None else [True] * len(details)
    for detail, on in zip(details, flags):
        if not on:
            continue
        total += _as_float(detail.get("final"))
        real += _as_float(detail.get("real"))
        contributed += _as_float(detail.get("deposited"))
        parts.append(str(detail.get("name") or "investment"))

    if include_ss:
        ss_total = _as_float(ss.get("final"), _as_float(ss.get("nest_egg")))
        ss_real = _as_float(ss.get("real"), _as_float(ss.get("nest_egg_today")))
        total += ss_total
        real += ss_real
        contributed += _as_float(ss.get("start")) + _as_float(ss.get("paid"))
        parts.append("social security")

    return {
        "final": total,
        "real": real,
        "contributed": contributed,
        "income_4": total * SAFE_WITHDRAWAL_RATE,
        "parts": parts,
    }


def project_investments(items: list[dict[str, Any]], acc: dict[str, Any], inflation_pct: float) -> dict[str, Any]:
    """Named outside accounts, each with its own growth rate and monthly add."""
    infl = inflation_pct / 100.0
    years = acc["years"]
    details = []
    total_start = 0.0
    total_final = 0.0
    total_deposited = 0.0
    total_growth = 0.0
    combined = [0.0] * (years + 1)

    for item in items:
        name = str(item.get("name") or "Investment")
        bal = _as_float(item.get("balance"))
        growth_pct = _as_float(item.get("growth"), 7.0) / 100.0
        monthly = _as_float(item.get("monthly"))
        mr = monthly_rate(growth_pct)
        start = bal
        deposited = 0.0
        growth = 0.0
        combined[0] += bal
        for i in range(years):
            for _ in range(12):
                gain = bal * mr
                growth += gain
                bal += gain + monthly
            deposited += monthly * 12.0
            combined[i + 1] += bal
        details.append(
            {
                "name": name,
                "start": start,
                "deposited": deposited,
                "growth": growth,
                "final": bal,
                "real": bal / ((1.0 + infl) ** years) if years else bal,
            }
        )
        total_start += start
        total_final += bal
        total_deposited += deposited
        total_growth += growth

    real = total_final / ((1.0 + infl) ** years) if years else total_final
    return {
        "details": details,
        "start_bal": total_start,
        "final": total_final,
        "deposited": total_deposited,
        "growth": total_growth,
        "real": real,
        "pts": combined,
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


def project_payout(p: dict[str, Any], acc: dict[str, Any], sav: dict[str, Any], inv: dict[str, Any] | None = None) -> dict[str, Any]:
    """Monthly drawdown, break-even vs money paid in, and how long the balance lasts."""
    pay = _as_float(p.get("p_amt"), 5_000)
    rate = _as_float(p.get("p_return"), 5.0) / 100.0
    src = str(p.get("p_src") or "ret")
    use_sav = src in ("both", "all")
    use_inv = src == "all"
    inv = inv or {"final": 0.0, "deposited": 0.0, "start_bal": 0.0}
    base_you = str(p.get("p_base") or "you") == "you"
    bal0 = acc["final"]
    if use_sav:
        bal0 += sav["final"]
    if use_inv:
        bal0 += inv["final"]
    if base_you:
        paid_in = acc["total_you"]
        if use_sav:
            paid_in += sav["deposited"]
        if use_inv:
            paid_in += inv["deposited"]
    else:
        paid_in = acc["start_bal"] + acc["total_you"] + acc["total_emp"]
        if use_sav:
            paid_in += sav["start_bal"] + sav["deposited"]
        if use_inv:
            paid_in += inv["start_bal"] + inv["deposited"]
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
        "both": use_sav,
        "use_inv": use_inv,
        "src": src,
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


TAX_KINDS = ("federal", "state", "car", "property", "other")
TAX_FREQS = ("paycheck", "monthly", "quarterly", "yearly")
TAX_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def tax_kind(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").strip().lower()
    if kind in TAX_KINDS:
        return kind
    name = str(item.get("name") or "").lower()
    if "federal" in name:
        return "federal"
    if "state" in name:
        return "state"
    if any(word in name for word in ("car", "vehicle", "auto", "registration")):
        return "car"
    if any(word in name for word in ("property", "home", "house", "real estate")):
        return "property"
    return "other"


def _paycheck_hits(paychecks: int) -> dict[int, int]:
    n = max(1, _as_int(paychecks, 26))
    if n <= 12:
        return {m: 1 for m in range(1, 13)}
    if n == 24:
        return {m: 2 for m in range(1, 13)}
    if n == 26:
        hits = {m: 2 for m in range(1, 13)}
        hits[3] = 3
        hits[8] = 3
        return hits
    if n == 52:
        hits = {m: 4 for m in range(1, 13)}
        for m in (1, 4, 7, 10):
            hits[m] = 5
        return hits
    base, extra = divmod(n, 12)
    hits = {m: base for m in range(1, 13)}
    for m in range(1, extra + 1):
        hits[m] += 1
    return hits


def tax_month_hits(freq: str, when: int, paychecks: int) -> dict[int, int]:
    due = max(1, min(12, _as_int(when, 1)))
    f = str(freq or "monthly").lower()
    if f in ("yearly", "annual", "year"):
        return {due: 1}
    if f in ("quarterly", "quarter"):
        return {((due - 1 + i * 3) % 12) + 1: 1 for i in range(4)}
    if f in ("paycheck", "per paycheck"):
        return _paycheck_hits(paychecks)
    return {m: 1 for m in range(1, 13)}


def project_taxes(
    items: list[dict[str, Any]] | None,
    paychecks_per_year: int = 26,
    horizon: int = 10,
    start_age: int | None = None,
) -> dict[str, Any]:
    """Convert named tax lines into monthly hits, yearly totals, and a cumulative book."""
    checks = max(1, _as_int(paychecks_per_year, 26))
    years = max(1, _as_int(horizon, 10))
    age0 = _as_int(start_age, 0)
    details = []
    year1 = [0.0] * 12
    annual_total = 0.0
    by_kind = {kind: 0.0 for kind in TAX_KINDS}
    stacked: dict[str, list[float]] = {}

    for item in items or []:
        name = str(item.get("name") or "Tax").strip() or "Tax"
        amount = _as_float(item.get("amount"))
        freq = str(item.get("freq") or "monthly").lower()
        if freq not in TAX_FREQS:
            freq = "monthly"
        when = max(1, min(12, _as_int(item.get("when"), 1)))
        kind = tax_kind(item)
        hits = tax_month_hits(freq, when, checks)
        payments = sum(hits.values())
        annual = amount * payments
        months = [amount * hits.get(m, 0) for m in range(1, 13)]
        unique = name
        n = 2
        while unique in stacked:
            unique = f"{name} ({n})"
            n += 1
        stacked[unique] = [annual] * years
        details.append(
            {
                "name": unique,
                "amount": amount,
                "freq": freq,
                "when": when,
                "kind": kind,
                "payments": payments,
                "annual": annual,
                "monthly": annual / 12.0,
                "paycheck": annual / checks if checks else annual,
                "year1_months": months,
            }
        )
        annual_total += annual
        by_kind[kind] += annual
        for i, paid in enumerate(months):
            year1[i] += paid

    yearly_rows = []
    running = 0.0
    cumulative = [0.0]
    for i in range(years):
        running += annual_total
        cumulative.append(running)
        yearly_rows.append(
            {
                "year": i + 1,
                "age": (age0 + i + 1) if age0 else None,
                "annual": annual_total,
                "cumulative": running,
                "by_name": {name: values[i] for name, values in stacked.items()},
            }
        )

    timeline = []
    running_m = 0.0
    for i in range(years * 12):
        month = (i % 12) + 1
        paid = year1[month - 1]
        running_m += paid
        timeline.append({"month": i + 1, "calendar": month, "paid": paid, "cumulative": running_m})

    return {
        "details": details,
        "annual": annual_total,
        "monthly": annual_total / 12.0,
        "paycheck": annual_total / checks if checks else annual_total,
        "by_kind": by_kind,
        "year1_months": year1,
        "years": yearly_rows,
        "cumulative": cumulative,
        "stacked": stacked,
        "timeline": timeline,
        "paychecks_per_year": checks,
        "horizon": years,
        "other": by_kind["other"],
    }


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
