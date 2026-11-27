import random
import unittest
from collections import Counter

from tools.holdout import draw_holdout
from tools.ime_benchmark import operation_of, trial_cases


class HoldoutTests(unittest.TestCase):
    def cases(self):
        return [{"id": f"{source}:{operation}:{number}", "source_id": source, "noise_ops": [{"type": operation}] if operation != "clean" else []}
                for source in "ab" for operation in ("clean", "drop", "nasal") for number in range(10)]

    def test_the_holdout_shares_no_case_with_the_first_set_and_covers_every_cell_in_turn(self):
        cases = self.cases()
        first = trial_cases(cases, 12, random.Random(1))
        holdout = draw_holdout(cases, [row["id"] for row in first], 30, random.Random(2))
        self.assertEqual(len(holdout), 30)
        self.assertFalse({row["id"] for row in holdout} & {row["id"] for row in first})
        self.assertEqual(Counter(row["source_id"] for row in holdout), {"a": 15, "b": 15})
        self.assertEqual(Counter(operation_of(row) for row in holdout), {"clean": 10, "drop": 10, "nasal": 10})

    def test_the_same_seed_draws_the_same_holdout_and_a_size_past_the_pool_is_short(self):
        cases = self.cases()
        first = [row["id"] for row in trial_cases(cases, 12, random.Random(1))]
        self.assertEqual(draw_holdout(cases, first, 20, random.Random(3)), draw_holdout(cases, first, 20, random.Random(3)))
        self.assertEqual(len(draw_holdout(cases, first, 500, random.Random(3))), len(cases) - len(first))


if __name__ == "__main__":
    unittest.main()
