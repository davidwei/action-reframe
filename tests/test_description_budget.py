import unittest
from description_comparison import explanation_budget

class DescriptionBudgetTests(unittest.TestCase):
    def test_bounds_and_rounding(self):
        for words,expected in [(0,40),(10,40),(80,40),(81,41),(112,56),(160,80),(300,80)]:
            self.assertEqual(explanation_budget(' '.join(['word']*words)),expected)
