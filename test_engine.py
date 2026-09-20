import unittest

from engine import (
    inflate,
    monthly_payout_for_years,
    project_accumulation,
    project_payout,
    project_savings,
    required_nest_egg,
    summarize_budget,
)


class AccumulationTests(unittest.TestCase):
    def test_inflate(self):
        self.assertAlmostEqual(inflate(100, 0.10, 2), 121.0)

    def test_four_percent_rule(self):
        self.assertEqual(required_nest_egg(40_000), 1_000_000)

    def test_zero_return_one_year(self):
        result = project_accumulation(
            {
                "salary": 100_000,
                "raise_pct": 0,
                "raise_every": 1,
                "save_pct": 10,
                "match_pct": 4,
                "pre_return": 0,
                "inflation": 0,
                "current_savings": 0,
                "current_age": 40,
                "retire_age": 41,
            }
        )
        self.assertEqual(result["years"], 1)
        self.assertAlmostEqual(result["total_you"], 10_000)
        self.assertAlmostEqual(result["total_emp"], 4_000)
        self.assertAlmostEqual(result["final"], 14_000)
        self.assertAlmostEqual(result["rows"][0]["salary"], 100_000)

    def test_raise_on_cadence(self):
        result = project_accumulation(
            {
                "salary": 100_000,
                "raise_pct": 10,
                "raise_every": 2,
                "save_pct": 0,
                "match_pct": 0,
                "pre_return": 0,
                "inflation": 0,
                "current_savings": 0,
                "current_age": 30,
                "retire_age": 34,
            }
        )
        salaries = [row["salary"] for row in result["rows"]]
        self.assertAlmostEqual(salaries[0], 100_000)
        self.assertAlmostEqual(salaries[1], 100_000)
        self.assertAlmostEqual(salaries[2], 110_000)
        self.assertTrue(result["rows"][2]["raise"])

    def test_monthly_compounding_beats_end_of_year(self):
        result = project_accumulation(
            {
                "salary": 0,
                "raise_pct": 0,
                "raise_every": 1,
                "save_pct": 0,
                "match_pct": 0,
                "pre_return": 12,
                "inflation": 0,
                "current_savings": 100_000,
                "current_age": 40,
                "retire_age": 41,
            }
        )
        self.assertAlmostEqual(result["final"], 112_000, places=4)


class SavingsAndPayoutTests(unittest.TestCase):
    def test_savings_flat_monthly(self):
        acc = project_accumulation(
            {
                "salary": 60_000,
                "raise_pct": 0,
                "raise_every": 1,
                "save_pct": 0,
                "match_pct": 0,
                "pre_return": 0,
                "inflation": 0,
                "current_savings": 0,
                "current_age": 40,
                "retire_age": 42,
            }
        )
        sav = project_savings(
            {
                "s_balance": 0,
                "s_rate": 0,
                "s_pct": 0,
                "s_amt": 100,
                "s_freq": "monthly",
                "inflation": 0,
            },
            acc,
        )
        self.assertAlmostEqual(sav["final"], 2400)
        self.assertAlmostEqual(sav["from_flat"], 2400)

    def test_payout_depletes_with_zero_return(self):
        acc = {
            "final": 12_000,
            "start_bal": 0,
            "total_you": 12_000,
            "total_emp": 0,
            "retire": 65,
        }
        sav = {"final": 0, "deposited": 0, "start_bal": 0}
        pay = project_payout(
            {"p_amt": 1000, "p_return": 0, "p_src": "ret", "p_base": "you"},
            acc,
            sav,
        )
        self.assertEqual(pay["depleted"], 12)
        self.assertTrue(pay["be_reached"])

    def test_thirty_year_payout_rounds_sensible(self):
        monthly = monthly_payout_for_years(1_000_000, 0.0, 30)
        self.assertAlmostEqual(monthly, 1_000_000 / 360, places=4)


class BudgetMathTests(unittest.TestCase):
    def test_surplus_and_housing(self):
        summary = summarize_budget(
            [{"name": "Job", "amount": 5000}],
            [
                {"name": "Housing", "amount": 1500, "kind": "need"},
                {"name": "Fun", "amount": 500, "kind": "want"},
                {"name": "401k", "amount": 1000, "kind": "save"},
            ],
        )
        self.assertEqual(summary["income_total"], 5000)
        self.assertEqual(summary["surplus"], 2000)
        self.assertAlmostEqual(summary["housing_ratio"], 0.30)
        self.assertAlmostEqual(summary["savings_rate"], 0.20)


if __name__ == "__main__":
    unittest.main()
