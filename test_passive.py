import gzip
import json
import unittest

from passive import (
    TaxAssumptions,
    cash_yield,
    loan_years,
    monthly_payment,
    highest_dividend,
    parse_dump_bytes,
    parse_freddie_csv,
    parse_heloc_html,
    parse_home_equity_html,
    parse_personal_html,
    parse_treasury_csv,
    project_carry,
    quotes_from_sources,
    rank_stocks,
    with_highest,
    tax_on_payout,
)


HEL_HTML = """
The national average home equity loan interest rate is 8.46% as of September 30, 2026, according to Bankrate.
<td>5-year home equity loan</td>
<td data-type="numeric" data-value="8.46">8.46%</td>
<td>10-year home equity loan</td>
<td data-type="numeric" data-value="8.56">8.56%</td>
<td>15-year home equity loan</td>
<td data-type="numeric" data-value="8.56">8.56%</td>
"""

HELOC_HTML = (
    "The national average HELOC interest rate is 7.29% as of September 30, 2026, "
    "according to Bankrate."
)

PERSONAL_HTML = "Updated on Sep. 30, 2026. The average of 12.53% is the typical APR."

FREDDIE = """date,pmms30,pmms30p,pmms15,pmms15p
9/24/2026,7.03,,6.42,
10/1/2026,7.28,,6.6,
"""

TREASURY = """Date,"1 Mo","3 Mo","2 Yr","10 Yr","30 Yr"
10/02/2026,4.04,4.19,4.83,5.28,5.63
10/05/2026,4.05,4.22,4.84,5.31,5.66
"""


class LoanMathTests(unittest.TestCase):
    def test_thirty_year_payment(self):
        payment = monthly_payment(100_000, 6.0, 30)
        self.assertAlmostEqual(payment, 599.55, places=2)

    def test_zero_rate_splits_evenly(self):
        self.assertAlmostEqual(monthly_payment(120_000, 0.0, 10), 1_000.0)
        rows = loan_years(120_000, 0.0, 10, "amortizing")
        self.assertAlmostEqual(sum(row["interest"] for row in rows), 0.0)
        self.assertAlmostEqual(rows[-1]["balance"], 0.0, places=2)

    def test_interest_only_does_not_pay_principal(self):
        rows = loan_years(100_000, 8.0, 10, "interest_only")
        self.assertEqual(len(rows), 10)
        self.assertAlmostEqual(rows[0]["interest"], 8_000.0)
        self.assertAlmostEqual(rows[0]["principal_paid"], 0.0)
        self.assertAlmostEqual(rows[-1]["balance"], 100_000.0)

    def test_amortizing_year_one_interest_is_below_the_coupon(self):
        rows = loan_years(100_000, 8.0, 10, "amortizing")
        self.assertLess(rows[0]["interest"], 8_000.0)
        self.assertGreater(rows[0]["principal_paid"], 0.0)
        self.assertAlmostEqual(rows[-1]["balance"], 0.0, delta=1.0)


class TaxTests(unittest.TestCase):
    def test_qualified_stacks_across_the_zero_band(self):
        bill = tax_on_payout(
            2_000,
            0,
            TaxAssumptions(filing="single", other_taxable=49_000, magi_before=49_000, qualified=True),
        )
        # $450 still inside the 0% band, $1,550 at 15%.
        self.assertAlmostEqual(bill.federal, 232.50, places=2)
        self.assertAlmostEqual(bill.niit, 0.0)

    def test_ordinary_first_bracket(self):
        bill = tax_on_payout(
            20_000,
            0,
            TaxAssumptions(filing="single", other_taxable=0, magi_before=0, qualified=False),
        )
        self.assertAlmostEqual(bill.federal, 1_240 + 7_600 * 0.12, places=2)

    def test_niit_on_the_slice_over_the_threshold(self):
        bill = tax_on_payout(
            20_000,
            0,
            TaxAssumptions(filing="single", other_taxable=0, magi_before=190_000, qualified=True),
        )
        self.assertAlmostEqual(bill.federal, 0.0)
        self.assertAlmostEqual(bill.niit, 380.0)

    def test_state_and_interest_deduction(self):
        bill = tax_on_payout(
            10_000,
            8_000,
            TaxAssumptions(
                filing="single",
                other_taxable=100_000,
                magi_before=100_000,
                qualified=True,
                state_pct=5,
                deduct_interest=True,
            ),
        )
        self.assertAlmostEqual(bill.taxable, 2_000)
        self.assertAlmostEqual(bill.federal, 300.0)
        self.assertAlmostEqual(bill.state, 100.0)

    def test_treasury_skips_state_tax(self):
        bill = tax_on_payout(
            5_000,
            0,
            TaxAssumptions(
                filing="joint",
                other_taxable=120_000,
                magi_before=120_000,
                qualified=False,
                state_pct=6,
                state_exempt=True,
            ),
        )
        self.assertAlmostEqual(bill.state, 0.0)
        self.assertGreater(bill.federal, 0.0)


class CarryTests(unittest.TestCase):
    def test_spread_after_interest_and_tax(self):
        assumptions = TaxAssumptions(
            filing="single", other_taxable=100_000, magi_before=100_000, qualified=True
        )
        plan = project_carry(100_000, 8.0, 10, 10.0, "interest_only", assumptions)
        # $10,000 dividend - $8,000 interest - 15% tax.
        self.assertAlmostEqual(plan.year1.payout, 10_000)
        self.assertAlmostEqual(plan.year1.interest, 8_000)
        self.assertAlmostEqual(plan.year1.tax, 1_500)
        self.assertAlmostEqual(plan.year1.net, 500)
        self.assertAlmostEqual(plan.year1.cash, 500)
        self.assertAlmostEqual(plan.breakeven_yield, 8.0 / 0.85, places=2)

    def test_deducting_interest_lowers_the_hurdle_to_the_loan_rate(self):
        assumptions = TaxAssumptions(
            filing="single",
            other_taxable=100_000,
            magi_before=100_000,
            qualified=True,
            deduct_interest=True,
        )
        plan = project_carry(100_000, 8.0, 5, 8.0, "interest_only", assumptions)
        self.assertAlmostEqual(plan.year1.net, 0.0, places=2)
        self.assertAlmostEqual(plan.breakeven_yield, 8.0, places=2)

    def test_payment_can_be_short_even_when_the_yield_clears_interest(self):
        assumptions = TaxAssumptions(
            filing="single", other_taxable=40_000, magi_before=40_000, qualified=True
        )
        plan = project_carry(100_000, 6.0, 5, 7.0, "amortizing", assumptions)
        self.assertGreater(plan.year1.net, 0.0)
        self.assertLess(plan.year1.cash, 0.0)


class MarketParseTests(unittest.TestCase):
    def test_bankrate_and_freddie_and_treasury(self):
        equity = parse_home_equity_html(HEL_HTML)
        self.assertEqual([(5, 8.46), (10, 8.56), (15, 8.56)], [(t, r) for t, r, _ in equity])
        self.assertEqual(equity[0][2], "2026-09-30")
        self.assertEqual(parse_heloc_html(HELOC_HTML), (7.29, "2026-09-30"))
        self.assertEqual(parse_personal_html(PERSONAL_HTML), (12.53, "2026-09-30"))
        self.assertEqual(parse_freddie_csv(FREDDIE), ("2026-10-01", 7.28, 6.6))
        asof, rates = parse_treasury_csv(TREASURY)
        self.assertEqual(asof, "2026-10-05")
        self.assertAlmostEqual(rates["t10y"], 5.31)

    def test_quotes_prefer_live_and_keep_a_saved_fallback(self):
        loans, treasuries = quotes_from_sources(
            heloc=(7.29, "2026-09-30"),
            home_equity=[(10, 8.56, "2026-09-30")],
            treasury=("2026-10-05", {"t10y": 5.31, "t1m": 4.05, "t3m": 4.22, "t2y": 4.84, "t30y": 5.66}),
        )
        by_key = {row.key: row for row in loans}
        self.assertTrue(by_key["heloc"].live)
        self.assertTrue(by_key["hel10"].live)
        self.assertFalse(by_key["hel5"].live)
        self.assertFalse(by_key["personal"].live)
        self.assertEqual(treasuries[0].group, "treasury")
        self.assertTrue(all(row.live for row in treasuries))


class DividendBoardTests(unittest.TestCase):
    def test_cash_yield_uses_dividend_over_price(self):
        self.assertAlmostEqual(cash_yield(85.65, 2.08, 2.35), 2.08 / 85.65 * 100.0)

    def test_stated_yield_wins_when_the_cash_rate_disagrees(self):
        self.assertAlmostEqual(cash_yield(4.94, 3.816, 10.94), 10.94)

    def test_zero_stated_yield_is_not_a_payer(self):
        self.assertIsNone(cash_yield(12.25, 8.0, 0.0))

    def test_dump_bytes_and_rank(self):
        payload = [
            {
                "Ticker": "KO",
                "Sector": "Consumer Defensive",
                "Price": 85.65,
                "DividendRate": 2.08,
                "DividendYieldPct": 2.35,
                "MarketCap": 381_000_000_000,
                "DividendFrequency": "Quarterly",
                "DividendPayoutRatio": 62.5,
                "_hist": {"dates": ["2026-10-02"], "close": [85.65]},
            },
            {
                "Ticker": "MO",
                "Sector": "Consumer Defensive",
                "Price": 67.35,
                "DividendRate": 4.24,
                "DividendYieldPct": 6.18,
                "MarketCap": 114_000_000_000,
                "DividendFrequency": "Quarterly",
            },
            {
                "Ticker": "TINY",
                "Sector": "Financial Services",
                "Price": 5.0,
                "DividendRate": 0.8,
                "DividendYieldPct": 16.0,
                "MarketCap": 50_000_000,
            },
        ]
        board = parse_dump_bytes(gzip.compress(json.dumps(payload).encode()))
        self.assertEqual(board["asof"], "2026-10-02")
        ranked = rank_stocks(board["rows"], min_yield=3, max_yield=12, min_cap=2_000_000_000)
        self.assertEqual([row["ticker"] for row in ranked], ["MO"])
        searched = rank_stocks(board["rows"], min_yield=0, max_yield=20, min_cap=0, query="ko")
        self.assertEqual(searched[0]["ticker"], "KO")
        self.assertEqual(highest_dividend(board["rows"])["ticker"], "TINY")
        pinned = with_highest(ranked, board["rows"])
        self.assertEqual(pinned[0]["ticker"], "TINY")
        self.assertEqual(pinned[1]["ticker"], "MO")


if __name__ == "__main__":
    unittest.main()
