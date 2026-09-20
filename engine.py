"""Retirement and budget math for NestLab."""

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


def project_retirement(p: dict[str, Any]) -> dict[str, Any]:
    """Year-by-year nest-egg projection.

    Ages are inclusive of the current year and exclusive of life expectancy
    as a living-to age (last modeled birthday is life_expectancy - 1).
    """
    current_age = _as_int(p.get("current_age"), 35)
    retire_age = _as_int(p.get("retire_age"), 65)
    life_expectancy = _as_int(p.get("life_expectancy"), 90)
    balance = _as_float(p.get("current_savings"))
    monthly_contribution = _as_float(p.get("monthly_contribution"))
    employer_annual = _as_float(p.get("employer_annual"))
    pre_return = _as_float(p.get("pre_return"), 7.0) / 100.0
    post_return = _as_float(p.get("post_return"), 5.0) / 100.0
    inflation = _as_float(p.get("inflation"), 2.5) / 100.0
    contrib_growth = _as_float(p.get("contrib_growth"), 2.0) / 100.0
    desired_income = _as_float(p.get("desired_annual_income"))
    healthcare = _as_float(p.get("healthcare_annual"))
    ss_annual = _as_float(p.get("ss_annual"))
    ss_start = _as_int(p.get("ss_start_age"), 67)
    pension_annual = _as_float(p.get("pension_annual"))
    pension_start = _as_int(p.get("pension_start_age"), retire_age)
    other_income = _as_float(p.get("other_income"))

    if retire_age < current_age:
        retire_age = current_age
    if life_expectancy <= retire_age:
        life_expectancy = retire_age + 1

    rows: list[dict[str, Any]] = []
    nest_egg_at_retirement = None
    depleted_age = None
    total_contributed = 0.0
    peak_balance = balance

    for age in range(current_age, life_expectancy):
        years_out = age - current_age
        start = balance
        infl = inflate(1.0, inflation, years_out)

        if age < retire_age:
            contrib = (monthly_contribution * 12.0 + employer_annual) * inflate(1.0, contrib_growth, years_out)
            growth = start * pre_return
            withdrawal = 0.0
            spend = 0.0
            ss = 0.0
            pension = 0.0
            other = 0.0
            gap = 0.0
            balance = max(0.0, start + growth + contrib)
            total_contributed += contrib
            phase = "saving"
        else:
            if nest_egg_at_retirement is None:
                nest_egg_at_retirement = start
            contrib = 0.0
            spend = (desired_income + healthcare) * infl
            ss = ss_annual * infl if age >= ss_start else 0.0
            pension = pension_annual * infl if age >= pension_start else 0.0
            other = other_income * infl
            withdrawal = max(0.0, spend - ss - pension - other)
            growth = start * post_return
            balance = start + growth - withdrawal
            if balance < 0:
                gap = -balance
                balance = 0.0
                if depleted_age is None:
                    depleted_age = age
            else:
                gap = 0.0
            phase = "retired"

        peak_balance = max(peak_balance, balance)
        rows.append(
            {
                "age": age,
                "year": years_out,
                "phase": phase,
                "start_balance": start,
                "growth": growth,
                "contribution": contrib,
                "withdrawal": withdrawal,
                "spend": spend,
                "social_security": ss,
                "pension": pension,
                "other_income": other,
                "end_balance": balance,
                "shortfall": gap,
                "inflation_factor": infl,
            }
        )

    if nest_egg_at_retirement is None:
        nest_egg_at_retirement = balance

    years_to_retire = max(0, retire_age - current_age)
    target_today = required_nest_egg(desired_income + healthcare)
    target_future = inflate(target_today, inflation, years_to_retire)
    withdrawal_rate = 0.0
    if nest_egg_at_retirement > 0 and desired_income + healthcare > 0:
        first_retire_spend = (desired_income + healthcare) * inflate(1.0, inflation, years_to_retire)
        withdrawal_rate = first_retire_spend / nest_egg_at_retirement

    years_funded = 0
    for row in rows:
        if row["phase"] == "retired" and row["end_balance"] > 0 and row["shortfall"] == 0:
            years_funded += 1

    retirement_years = max(0, life_expectancy - retire_age)
    final_balance = rows[-1]["end_balance"] if rows else balance
    success = depleted_age is None and (retirement_years == 0 or years_funded >= retirement_years)

    return {
        "rows": rows,
        "nest_egg_at_retirement": nest_egg_at_retirement,
        "target_today": target_today,
        "target_future": target_future,
        "gap_at_retirement": target_future - nest_egg_at_retirement,
        "withdrawal_rate": withdrawal_rate,
        "depleted_age": depleted_age,
        "years_funded": years_funded,
        "retirement_years": retirement_years,
        "years_to_retire": years_to_retire,
        "total_contributed": total_contributed,
        "peak_balance": peak_balance,
        "final_balance": final_balance,
        "success": success,
        "life_expectancy": life_expectancy,
        "retire_age": retire_age,
    }


def required_monthly_contribution(p: dict[str, Any], lo: float = 0.0, hi: float = 25000.0) -> float:
    """Smallest monthly contribution that funds retirement through life expectancy."""
    probe = dict(p)
    if project_retirement(probe)["success"] and _as_float(p.get("monthly_contribution")) <= 0:
        return 0.0

    hi_probe = dict(p)
    hi_probe["monthly_contribution"] = hi
    if not project_retirement(hi_probe)["success"]:
        return hi

    for _ in range(28):
        mid = (lo + hi) / 2.0
        trial = dict(p)
        trial["monthly_contribution"] = mid
        if project_retirement(trial)["success"]:
            hi = mid
        else:
            lo = mid
    return hi


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


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def money_cents(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"
