import unittest

from engine import inflate, project_retirement, required_monthly_contribution, required_nest_egg, summarize_budget


class RetirementMathTests(unittest.TestCase):
    def test_inflate(self):
        self.assertAlmostEqual(inflate(100, 0.10, 2), 121.0)

    def test_four_percent_rule(self):
        self.assertEqual(required_nest_egg(40_000), 1_000_000)

    def test_projection_grows_while_saving(self):
        result = project_retirement(
            {
                "current_age": 40,
                "retire_age": 45,
                "life_expectancy": 50,
                "current_savings": 100_000,
                "monthly_contribution": 0,
                "employer_annual": 0,
                "pre_return": 10.0,
                "post_return": 0.0,
                "inflation": 0.0,
                "contrib_growth": 0.0,
                "desired_annual_income": 0,
                "healthcare_annual": 0,
                "ss_annual": 0,
                "ss_start_age": 67,
                "pension_annual": 0,
                "pension_start_age": 45,
                "other_income": 0,
            }
        )
        self.assertGreater(result["nest_egg_at_retirement"], 100_000)
        self.assertTrue(result["success"])

    def test_depletes_when_spend_is_huge(self):
        result = project_retirement(
            {
                "current_age": 64,
                "retire_age": 65,
                "life_expectancy": 80,
                "current_savings": 50_000,
                "monthly_contribution": 0,
                "employer_annual": 0,
                "pre_return": 0.0,
                "post_return": 0.0,
                "inflation": 0.0,
                "contrib_growth": 0.0,
                "desired_annual_income": 40_000,
                "healthcare_annual": 0,
                "ss_annual": 0,
                "ss_start_age": 67,
                "pension_annual": 0,
                "pension_start_age": 65,
                "other_income": 0,
            }
        )
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["depleted_age"])

    def test_required_contribution_is_finite(self):
        needed = required_monthly_contribution(
            {
                "current_age": 30,
                "retire_age": 65,
                "life_expectancy": 90,
                "current_savings": 10_000,
                "monthly_contribution": 0,
                "employer_annual": 0,
                "pre_return": 7.0,
                "post_return": 5.0,
                "inflation": 2.5,
                "contrib_growth": 0.0,
                "desired_annual_income": 40_000,
                "healthcare_annual": 0,
                "ss_annual": 0,
                "ss_start_age": 67,
                "pension_annual": 0,
                "pension_start_age": 65,
                "other_income": 0,
            }
        )
        self.assertGreater(needed, 0)
        self.assertLess(needed, 25_000)


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
