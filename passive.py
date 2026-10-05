"""Borrow-to-earn math for the Passive income tab.

A loan payment, the interest inside it, and federal tax on the payout are
kept separate so you can see whether a dividend or a Treasury yield still
clears the cost of the money. Stock dividends are historical. Treasury
yields are the set payout if the bond is held to maturity.
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).parent / "data"
DUMP_URL = "https://raw.githubusercontent.com/magicpro33/stock/main/data/stock_data.json.gz"
FREDDIE_URL = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"
HEL_URL = "https://www.bankrate.com/home-equity/home-equity-loan-rates/"
HELOC_URL = "https://www.bankrate.com/home-equity/heloc-rates/"
PERSONAL_URL = "https://www.bankrate.com/loans/personal-loans/rates/"
CACHE_HOURS = 12
BOARD_VERSION = 3

# 2026 brackets, IRS Rev. Proc. 2025-32. Each pair is the top of that bracket.
_ORDINARY = {
    "single": (
        (12_400, 0.10),
        (50_400, 0.12),
        (105_700, 0.22),
        (201_775, 0.24),
        (256_225, 0.32),
        (640_600, 0.35),
        (float("inf"), 0.37),
    ),
    "joint": (
        (24_800, 0.10),
        (100_800, 0.12),
        (211_400, 0.22),
        (403_550, 0.24),
        (512_450, 0.32),
        (768_700, 0.35),
        (float("inf"), 0.37),
    ),
    "hoh": (
        (17_700, 0.10),
        (67_450, 0.12),
        (105_700, 0.22),
        (201_750, 0.24),
        (256_200, 0.32),
        (640_600, 0.35),
        (float("inf"), 0.37),
    ),
    "separate": (
        (12_400, 0.10),
        (50_400, 0.12),
        (105_700, 0.22),
        (201_775, 0.24),
        (256_225, 0.32),
        (384_350, 0.35),
        (float("inf"), 0.37),
    ),
}
# Tops of the 0% and 15% qualified-dividend bands. Dollars above the second are 20%.
_QUALIFIED = {
    "single": (49_450, 545_500),
    "joint": (98_900, 613_700),
    "hoh": (66_200, 579_600),
    "separate": (49_450, 306_850),
}
_NIIT = {"single": 200_000, "joint": 250_000, "hoh": 200_000, "separate": 125_000}
_NIIT_RATE = 0.038

FILING_LABELS = {
    "single": "Single",
    "joint": "Married filing jointly",
    "hoh": "Head of household",
    "separate": "Married filing separately",
}

# Published survey used only when a live page cannot be read.
_FALLBACK_ASOF = "2026-09-30"
_FALLBACK_RATES = {
    "heloc": 7.29,
    "hel5": 8.46,
    "hel10": 8.56,
    "hel15": 8.56,
    "personal": 12.53,
    "mtg30": 7.28,
    "mtg15": 6.60,
}
_FALLBACK_TREASURY = {
    "t1m": 4.05,
    "t3m": 4.22,
    "t2y": 4.84,
    "t10y": 5.31,
    "t30y": 5.66,
}


@dataclass(frozen=True)
class Quote:
    key: str
    label: str
    rate: float
    term_years: int
    style: str
    group: str
    source: str
    asof: str
    live: bool
    note: str = ""


@dataclass(frozen=True)
class TaxAssumptions:
    filing: str = "single"
    other_taxable: float = 80_000.0
    magi_before: float = 80_000.0
    qualified: bool = True
    state_pct: float = 0.0
    deduct_interest: bool = False
    state_exempt: bool = False


@dataclass(frozen=True)
class TaxBill:
    federal: float
    state: float
    niit: float
    taxable: float
    deducted: float

    @property
    def total(self) -> float:
        return self.federal + self.state + self.niit


@dataclass(frozen=True)
class CarryYear:
    year: int
    payout: float
    interest: float
    principal_paid: float
    payment: float
    tax: float
    net: float
    cash: float
    balance: float


@dataclass(frozen=True)
class CarryPlan:
    monthly_payment: float
    years: tuple[CarryYear, ...]
    breakeven_yield: float

    @property
    def year1(self) -> CarryYear:
        return self.years[0]

    @property
    def total_interest(self) -> float:
        return sum(row.interest for row in self.years)

    @property
    def total_tax(self) -> float:
        return sum(row.tax for row in self.years)

    @property
    def total_payout(self) -> float:
        return sum(row.payout for row in self.years)

    @property
    def total_net(self) -> float:
        return sum(row.net for row in self.years)

    @property
    def total_cash(self) -> float:
        return sum(row.cash for row in self.years)


def monthly_payment(principal: float, annual_pct: float, years: int) -> float:
    """Fixed payment that amortizes principal over whole years."""
    months = max(0, int(years)) * 12
    if principal <= 0 or months <= 0:
        return 0.0
    monthly = annual_pct / 100.0 / 12.0
    if abs(monthly) < 1e-15:
        return principal / months
    growth = (1.0 + monthly) ** months
    return principal * monthly * growth / (growth - 1.0)


def loan_years(principal: float, annual_pct: float, years: int, style: str) -> list[dict[str, float]]:
    """One row per year: interest, principal paid, payment, and ending balance."""
    span = max(1, int(years))
    balance = max(0.0, float(principal))
    rate = annual_pct / 100.0
    if style == "interest_only":
        interest = balance * rate
        return [
            {
                "year": i + 1,
                "interest": interest,
                "principal_paid": 0.0,
                "payment": interest,
                "balance": balance,
            }
            for i in range(span)
        ]

    payment = monthly_payment(balance, annual_pct, span)
    monthly = rate / 12.0
    rows = []
    for year in range(1, span + 1):
        interest = 0.0
        principal_paid = 0.0
        for _ in range(12):
            if balance <= 0.005:
                break
            due = balance * monthly
            toward = min(balance, max(0.0, payment - due))
            interest += due
            principal_paid += toward
            balance = max(0.0, balance - toward)
        rows.append(
            {
                "year": year,
                "interest": interest,
                "principal_paid": principal_paid,
                "payment": interest + principal_paid,
                "balance": balance,
            }
        )
    return rows


def _bands(assumptions: TaxAssumptions) -> tuple[tuple[float, float], ...]:
    filing = assumptions.filing if assumptions.filing in _ORDINARY else "single"
    if assumptions.qualified:
        zero, mid = _QUALIFIED[filing]
        return ((zero, 0.0), (mid, 0.15), (float("inf"), 0.20))
    return _ORDINARY[filing]


def _slice_tax(amount: float, already: float, bands: tuple[tuple[float, float], ...]) -> float:
    if amount <= 0:
        return 0.0
    tax = 0.0
    cursor = max(0.0, already)
    end = cursor + amount
    for ceiling, rate in bands:
        if cursor >= end:
            break
        if ceiling <= cursor:
            continue
        chunk = min(end, ceiling) - cursor
        tax += chunk * rate
        cursor += chunk
    return tax


def tax_on_payout(payout: float, interest: float, assumptions: TaxAssumptions) -> TaxBill:
    """Federal tax on a payout stacked on other taxable income, plus state and NIIT.

    When investment interest is deducted, it offsets the payout first. Qualified
    dividends that are used this way are no longer taxed as qualified income,
    which is the usual election, so the offset dollars simply drop out.
    """
    payout = max(0.0, float(payout))
    interest = max(0.0, float(interest))
    deducted = min(interest, payout) if assumptions.deduct_interest else 0.0
    taxable = max(0.0, payout - deducted)
    filing = assumptions.filing if assumptions.filing in _NIIT else "single"
    federal = _slice_tax(taxable, max(0.0, assumptions.other_taxable), _bands(assumptions))
    state_rate = 0.0 if assumptions.state_exempt else max(0.0, assumptions.state_pct) / 100.0
    state = taxable * state_rate
    excess = max(0.0, assumptions.magi_before) + payout - deducted - _NIIT[filing]
    niit = _NIIT_RATE * min(taxable, max(0.0, excess))
    return TaxBill(federal=federal, state=state, niit=niit, taxable=taxable, deducted=deducted)


def project_carry(
    principal: float,
    annual_pct: float,
    years: int,
    yield_pct: float,
    style: str,
    assumptions: TaxAssumptions,
) -> CarryPlan:
    """Flat annual payout versus the loan, one year at a time."""
    principal = max(0.0, float(principal))
    payout = principal * max(0.0, float(yield_pct)) / 100.0
    schedule = loan_years(principal, annual_pct, years, style)
    rows: list[CarryYear] = []
    for item in schedule:
        bill = tax_on_payout(payout, item["interest"], assumptions)
        net = payout - item["interest"] - bill.total
        cash = payout - item["payment"] - bill.total
        rows.append(
            CarryYear(
                year=int(item["year"]),
                payout=payout,
                interest=item["interest"],
                principal_paid=item["principal_paid"],
                payment=item["payment"],
                tax=bill.total,
                net=net,
                cash=cash,
                balance=item["balance"],
            )
        )
    plan_years = tuple(rows)
    return CarryPlan(
        monthly_payment=_monthly_from_style(principal, annual_pct, years, style, plan_years),
        years=plan_years,
        breakeven_yield=_breakeven(principal, annual_pct, years, style, assumptions),
    )


def _monthly_from_style(
    principal: float,
    annual_pct: float,
    years: int,
    style: str,
    rows: tuple[CarryYear, ...],
) -> float:
    if style == "interest_only":
        return (rows[0].interest / 12.0) if rows else 0.0
    return monthly_payment(principal, annual_pct, years)


def _breakeven(
    principal: float,
    annual_pct: float,
    years: int,
    style: str,
    assumptions: TaxAssumptions,
) -> float:
    """Yield where year-1 payout equals year-1 interest plus tax on that payout."""
    if principal <= 0:
        return 0.0
    interest = loan_years(principal, annual_pct, years, style)[0]["interest"]

    def net_at(yield_pct: float) -> float:
        payout = principal * yield_pct / 100.0
        bill = tax_on_payout(payout, interest, assumptions)
        return payout - interest - bill.total

    if net_at(0.0) >= -0.01:
        return 0.0
    lo, hi = 0.0, 100.0
    if net_at(hi) < 0:
        return hi
    for _ in range(48):
        mid = (lo + hi) / 2.0
        if net_at(mid) >= 0:
            hi = mid
        else:
            lo = mid
    return hi


def assumptions_for(base: TaxAssumptions, kind: str) -> TaxAssumptions:
    """Treasuries are ordinary income and are exempt from state income tax."""
    if kind == "treasury":
        return replace(base, qualified=False, state_exempt=True)
    return replace(base, state_exempt=False)


def cash_yield(price: Any, rate: Any, stated: Any) -> float | None:
    """Dividend yield in percent.

    When the dump's own yield and the cash dividend divided by price agree, use the
    cash figure. When they disagree, keep the dump's yield. A dividend rate in
    another currency would otherwise look like a huge payout.
    """
    implied = None
    try:
        px = float(price)
        cash = float(rate)
        if px > 0 and cash > 0:
            implied = cash / px * 100.0
    except (TypeError, ValueError):
        implied = None
    if implied is not None and not (0 < implied < 80):
        implied = None
    stated_pct = None
    try:
        stated_pct = float(stated)
    except (TypeError, ValueError):
        stated_pct = None
    # A recorded zero means the dump found no dividend yield. Do not replace it
    # with a cash rate that is in another currency.
    if stated_pct is not None and stated_pct <= 0:
        return None
    if stated_pct is not None and not (0 < stated_pct < 80):
        stated_pct = None
    if stated_pct is None:
        return implied
    if implied is None:
        return stated_pct
    gap = abs(stated_pct - implied) / max(stated_pct, 0.5)
    if gap <= 0.25:
        return implied
    return stated_pct


def parse_dump_payload(data: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    asof = ""
    if data:
        dates = (data[0].get("_hist") or {}).get("dates") or []
        if dates:
            asof = str(dates[-1])[:10]
    for rec in data:
        ticker = str(rec.get("Ticker") or "").strip().upper()
        if not ticker:
            continue
        price = rec.get("Price")
        rate = rec.get("DividendRate")
        stated = rec.get("DividendYieldPct")
        yld = cash_yield(price, rate, stated)
        if yld is None:
            continue
        try:
            cap = float(rec.get("MarketCap"))
        except (TypeError, ValueError):
            cap = None
        try:
            payout = float(rec.get("DividendPayoutRatio"))
        except (TypeError, ValueError):
            payout = None
        try:
            px = float(price)
        except (TypeError, ValueError):
            px = None
        try:
            cash = float(rate) if rate is not None else None
        except (TypeError, ValueError):
            cash = None
        rows.append(
            {
                "ticker": ticker,
                "sector": str(rec.get("Sector") or ""),
                "price": px,
                "dividend": cash,
                "yield_pct": yld,
                "market_cap": cap,
                "frequency": str(rec.get("DividendFrequency") or ""),
                "payout": payout,
                "ex_date": str(rec.get("ExDividendDate") or ""),
            }
        )
    rows.sort(key=lambda row: row["yield_pct"], reverse=True)
    return {
        "asof": asof,
        "source": DUMP_URL,
        "rows": rows,
    }


def parse_dump_bytes(blob: bytes) -> dict[str, Any]:
    payload = json.loads(gzip.decompress(blob).decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Nightly dump is not a list of stocks.")
    return parse_dump_payload(payload)


def highest_dividend(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The name with the largest cash yield in the dump, filters aside."""
    best: dict[str, Any] | None = None
    best_yield = -1.0
    for row in rows:
        try:
            yld = float(row.get("yield_pct") or 0.0)
        except (TypeError, ValueError):
            continue
        if yld > best_yield:
            best = row
            best_yield = yld
    return best


def with_highest(ranked: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a filtered list, but never drop the single highest yield."""
    top = highest_dividend(rows)
    if top is None:
        return ranked
    rest = [row for row in ranked if row.get("ticker") != top.get("ticker")]
    return [top, *rest]


def rank_stocks(
    rows: list[dict[str, Any]],
    *,
    min_yield: float,
    max_yield: float,
    min_cap: float,
    query: str = "",
    limit: int = 40,
) -> list[dict[str, Any]]:
    needle = query.strip().upper()
    matched = []
    for row in rows:
        yld = float(row.get("yield_pct") or 0.0)
        if yld < min_yield or yld > max_yield:
            continue
        cap = row.get("market_cap")
        if min_cap > 0 and (cap is None or float(cap) < min_cap):
            continue
        if needle and needle not in str(row.get("ticker") or "") and needle not in str(row.get("sector") or "").upper():
            continue
        matched.append(row)
    matched.sort(key=lambda row: float(row["yield_pct"]), reverse=True)
    return matched[: max(1, int(limit))]


def _parse_us_date(text: str) -> str:
    cleaned = text.strip().replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return text.strip()


def parse_home_equity_html(html: str) -> list[tuple[int, float, str]]:
    """(term years, average rate, as-of date) from a Bankrate home-equity page."""
    asof = ""
    dated = re.search(
        r"national average home equity loan interest rate is [\d.]+% as of ([A-Za-z]+ \d{1,2}, \d{4})",
        html,
        flags=re.I,
    )
    if dated:
        asof = _parse_us_date(dated.group(1))
    found = re.findall(
        r"(\d+)-year home equity loan</td>.*?data-value=\"([\d.]+)\"",
        html,
        flags=re.I | re.S,
    )
    rows = []
    for term, rate in found:
        rows.append((int(term), float(rate), asof))
    return rows


def parse_heloc_html(html: str) -> tuple[float, str] | None:
    match = re.search(
        r"national average HELOC interest rate is ([\d.]+)% as of ([A-Za-z]+ \d{1,2}, \d{4})",
        html,
        flags=re.I,
    )
    if not match:
        return None
    return float(match.group(1)), _parse_us_date(match.group(2))


def parse_personal_html(html: str) -> tuple[float, str] | None:
    rate_match = re.search(r"average of ([\d.]+)%", html, flags=re.I)
    if not rate_match:
        return None
    updated = re.search(r"Updated on ([A-Za-z]+\.? \d{1,2}, \d{4})", html, flags=re.I)
    asof = _parse_us_date(updated.group(1)) if updated else ""
    return float(rate_match.group(1)), asof


def parse_freddie_csv(text: str) -> tuple[str, float, float] | None:
    latest: tuple[date, float, float] | None = None
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4 or parts[0].lower() == "date":
            continue
        try:
            stamp = datetime.strptime(parts[0], "%m/%d/%Y").date()
            y30 = float(parts[1])
            y15 = float(parts[3])
        except ValueError:
            continue
        if latest is None or stamp > latest[0]:
            latest = (stamp, y30, y15)
    if latest is None:
        return None
    return latest[0].isoformat(), latest[1], latest[2]


def parse_treasury_csv(text: str) -> tuple[str, dict[str, float]] | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    header = [col.strip().strip('"') for col in lines[0].split(",")]
    wanted = {"1 Mo": "t1m", "3 Mo": "t3m", "2 Yr": "t2y", "10 Yr": "t10y", "30 Yr": "t30y"}
    index = {name: header.index(label) for label, name in wanted.items() if label in header}
    if "t10y" not in index:
        return None
    latest: tuple[date, dict[str, float]] | None = None
    for line in lines[1:]:
        parts = [part.strip().strip('"') for part in line.split(",")]
        try:
            stamp = datetime.strptime(parts[0], "%m/%d/%Y").date()
        except ValueError:
            continue
        rates: dict[str, float] = {}
        for name, idx in index.items():
            if idx >= len(parts) or not parts[idx]:
                continue
            try:
                rates[name] = float(parts[idx])
            except ValueError:
                continue
        if "t10y" not in rates:
            continue
        if latest is None or stamp > latest[0]:
            latest = (stamp, rates)
    if latest is None:
        return None
    return latest[0].isoformat(), latest[1]


def _quote(
    key: str,
    label: str,
    rate: float,
    term: int,
    style: str,
    group: str,
    source: str,
    asof: str,
    live: bool,
    note: str = "",
) -> Quote:
    return Quote(key, label, round(float(rate), 2), int(term), style, group, source, asof, live, note)


def quotes_from_sources(
    *,
    heloc: tuple[float, str] | None = None,
    home_equity: list[tuple[int, float, str]] | None = None,
    personal: tuple[float, str] | None = None,
    freddie: tuple[str, float, float] | None = None,
    treasury: tuple[str, dict[str, float]] | None = None,
) -> tuple[list[Quote], list[Quote]]:
    """Loan menu and Treasury payouts. Missing live reads fall back to the saved survey."""
    loans: list[Quote] = []
    if heloc:
        rate, asof = heloc
        loans.append(
            _quote(
                "heloc",
                "HELOC — tap home equity",
                rate,
                10,
                "interest_only",
                "home",
                "Bankrate national average",
                asof,
                True,
                "Variable rate. Figure is interest-only, which is the usual draw period. The principal is still owed.",
            )
        )
    else:
        loans.append(
            _quote(
                "heloc",
                "HELOC — tap home equity",
                _FALLBACK_RATES["heloc"],
                10,
                "interest_only",
                "home",
                "Bankrate national average (saved survey)",
                _FALLBACK_ASOF,
                False,
                "Live page unavailable. Variable rate, interest-only draw. The principal is still owed.",
            )
        )

    equity = {term: (rate, asof) for term, rate, asof in (home_equity or [])}
    for term, key, fallback_note in (
        (5, "hel5", "5-year second mortgage / home equity loan"),
        (10, "hel10", "10-year second mortgage / home equity loan"),
        (15, "hel15", "15-year second mortgage / home equity loan"),
    ):
        if term in equity:
            rate, asof = equity[term]
            loans.append(
                _quote(
                    key,
                    f"{term}-year home equity loan (second mortgage)",
                    rate,
                    term,
                    "amortizing",
                    "home",
                    "Bankrate national average",
                    asof,
                    True,
                    "Fixed rate, lump sum, paid off over the term. Same idea as a second mortgage.",
                )
            )
        else:
            loans.append(
                _quote(
                    key,
                    f"{term}-year home equity loan (second mortgage)",
                    _FALLBACK_RATES[key],
                    term,
                    "amortizing",
                    "home",
                    "Bankrate national average (saved survey)",
                    _FALLBACK_ASOF,
                    False,
                    fallback_note + ". Live page unavailable.",
                )
            )

    if freddie:
        asof, y30, y15 = freddie
        loans.append(
            _quote(
                "mtg15",
                "15-year fixed mortgage",
                y15,
                15,
                "amortizing",
                "mortgage",
                "Freddie Mac PMMS",
                asof,
                True,
                "First-mortgage average, useful if a cash-out refinance is the way you pull equity out.",
            )
        )
        loans.append(
            _quote(
                "mtg30",
                "30-year fixed mortgage",
                y30,
                30,
                "amortizing",
                "mortgage",
                "Freddie Mac PMMS",
                asof,
                True,
                "First-mortgage average, not a second lien. Cash-out refinances are priced off this market.",
            )
        )
    else:
        loans.append(
            _quote(
                "mtg15",
                "15-year fixed mortgage",
                _FALLBACK_RATES["mtg15"],
                15,
                "amortizing",
                "mortgage",
                "Freddie Mac PMMS (saved)",
                "2026-10-01",
                False,
                "Live Freddie Mac file unavailable.",
            )
        )
        loans.append(
            _quote(
                "mtg30",
                "30-year fixed mortgage",
                _FALLBACK_RATES["mtg30"],
                30,
                "amortizing",
                "mortgage",
                "Freddie Mac PMMS (saved)",
                "2026-10-01",
                False,
                "Live Freddie Mac file unavailable.",
            )
        )

    if personal:
        rate, asof = personal
        loans.append(
            _quote(
                "personal",
                "Personal loan",
                rate,
                5,
                "amortizing",
                "personal",
                "Bankrate average",
                asof or _FALLBACK_ASOF,
                True,
                "Unsecured. Usually the most expensive way to fund a stock purchase.",
            )
        )
    else:
        loans.append(
            _quote(
                "personal",
                "Personal loan",
                _FALLBACK_RATES["personal"],
                5,
                "amortizing",
                "personal",
                "Bankrate average (saved survey)",
                _FALLBACK_ASOF,
                False,
                "Live page unavailable. Unsecured, and usually a poor rate for this comparison.",
            )
        )

    treasuries: list[Quote] = []
    treasury_rates = treasury[1] if treasury else _FALLBACK_TREASURY
    treasury_asof = treasury[0] if treasury else "2026-10-05"
    treasury_live = treasury is not None
    treasury_source = "U.S. Treasury daily yield curve" if treasury_live else "U.S. Treasury (saved 2026-10-05)"
    catalog = (
        ("t1m", "1-month Treasury", 1, "Bill. Set payout if held to maturity. You roll it when it matures."),
        ("t3m", "3-month Treasury", 1, "Bill. Set payout if held to maturity."),
        ("t2y", "2-year Treasury", 2, "Note. The yield is the set annual payout if you hold to maturity."),
        ("t10y", "10-year Treasury", 10, "Note. The yield is locked if you hold to maturity. Price moves if you sell early."),
        ("t30y", "30-year Treasury", 30, "Bond. Yield is set if held to maturity. A long bond's price can swing a lot before then."),
    )
    for key, label, term, note in catalog:
        if key not in treasury_rates:
            continue
        treasuries.append(
            _quote(
                key,
                label,
                treasury_rates[key],
                term,
                "interest_only",
                "treasury",
                treasury_source,
                treasury_asof,
                treasury_live,
                note + " Treasury interest is taxed as ordinary income and is exempt from state tax.",
            )
        )
    return loans, treasuries


def treasury_url(today: date | None = None) -> str:
    stamp = today or date.today()
    ym = stamp.strftime("%Y%m")
    return (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/all/{ym}?type=daily_treasury_yield_curve"
        f"&field_tdr_date_value_month={ym}&page&_format=csv"
    )


def _http_get(url: str, timeout: float = 20.0) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NestLab/1.0; +https://aiupscalellc.netlify.app/)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _http_bytes(url: str, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NestLab/1.0; +https://aiupscalellc.netlify.app/)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _quote_to_dict(quote: Quote) -> dict[str, Any]:
    return asdict(quote)


def _quote_from_dict(raw: dict[str, Any]) -> Quote:
    return Quote(
        key=str(raw["key"]),
        label=str(raw["label"]),
        rate=float(raw["rate"]),
        term_years=int(raw["term_years"]),
        style=str(raw["style"]),
        group=str(raw["group"]),
        source=str(raw["source"]),
        asof=str(raw["asof"]),
        live=bool(raw["live"]),
        note=str(raw.get("note") or ""),
    )


def load_market(force: bool = False, today: date | None = None) -> dict[str, Any]:
    """Current loan rates and Treasury yields. Cached on disk for half a day."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "market_rates.json"
    if not force and cache.is_file():
        age = datetime.now().timestamp() - cache.stat().st_mtime
        if age < CACHE_HOURS * 3600:
            try:
                return _read_market_cache(cache)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

    notes: list[str] = []
    urls = {
        "treasury": treasury_url(today),
        "freddie": FREDDIE_URL,
        "hel": HEL_URL,
        "heloc": HELOC_URL,
        "personal": PERSONAL_URL,
    }
    texts: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_map = {pool.submit(_http_get, url): name for name, url in urls.items()}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                texts[name] = future.result()
            except Exception as exc:
                notes.append(f"{name} unavailable ({exc.__class__.__name__})")

    heloc = parse_heloc_html(texts["heloc"]) if "heloc" in texts else None
    equity = parse_home_equity_html(texts["hel"]) if "hel" in texts else None
    personal = parse_personal_html(texts["personal"]) if "personal" in texts else None
    freddie = parse_freddie_csv(texts["freddie"]) if "freddie" in texts else None
    treasury = parse_treasury_csv(texts["treasury"]) if "treasury" in texts else None
    if treasury is None:
        # Early in a new month the current file can be empty. Try the previous month.
        stamp = today or date.today()
        year, month = stamp.year, stamp.month - 1
        if month == 0:
            month, year = 12, year - 1
        try:
            treasury = parse_treasury_csv(_http_get(treasury_url(date(year, month, 1))))
        except Exception as exc:
            notes.append(f"prior-month treasury unavailable ({exc.__class__.__name__})")
    if not equity:
        notes.append("home equity table fell back to the saved Bankrate survey")
    if heloc is None:
        notes.append("HELOC rate fell back to the saved Bankrate survey")

    loans, treasuries = quotes_from_sources(
        heloc=heloc,
        home_equity=equity,
        personal=personal,
        freddie=freddie,
        treasury=treasury,
    )
    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "notes": notes,
        "loans": [_quote_to_dict(quote) for quote in loans],
        "treasuries": [_quote_to_dict(quote) for quote in treasuries],
    }
    try:
        cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
    return payload


def _read_market_cache(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["loans"] = [_quote_to_dict(_quote_from_dict(row)) for row in payload["loans"]]
    payload["treasuries"] = [_quote_to_dict(_quote_from_dict(row)) for row in payload["treasuries"]]
    return payload


def load_dividends(force: bool = False) -> dict[str, Any]:
    """Slim dividend board from the nightly magicpro33 stock dump."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "dividend_board.json"
    gz_path = DATA_DIR / "stock_data.json.gz"
    if not force and cache.is_file():
        age = datetime.now().timestamp() - cache.stat().st_mtime
        gz_newer = gz_path.is_file() and gz_path.stat().st_mtime > cache.stat().st_mtime
        if age < CACHE_HOURS * 3600 and not gz_newer:
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = None
            if isinstance(cached, dict) and cached.get("version") == BOARD_VERSION:
                return cached

    note = ""
    need_download = force or not gz_path.is_file()
    if gz_path.is_file() and not force:
        age = datetime.now().timestamp() - gz_path.stat().st_mtime
        need_download = age > CACHE_HOURS * 3600
    if need_download:
        try:
            gz_path.write_bytes(_http_bytes(DUMP_URL))
        except Exception as exc:
            if not gz_path.is_file():
                raise
            note = f"Could not refresh the dump ({exc.__class__.__name__}). Using the copy already on disk."
    board = parse_dump_bytes(gz_path.read_bytes())
    board["version"] = BOARD_VERSION
    board["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    board["note"] = note
    try:
        cache.write_text(json.dumps(board), encoding="utf-8")
    except OSError:
        pass
    return board
