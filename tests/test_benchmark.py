import unittest

from benchmarks.pos_simulator_latency import nearest_rank, summarize


class BenchmarkCalculationTests(unittest.TestCase):
    def test_nearest_rank_p95_for_twenty_samples_is_nineteenth_value(self):
        values = [float(value) for value in range(1, 21)]
        self.assertEqual(nearest_rank(values, 0.95), 19.0)
        self.assertEqual(summarize(values)["median"], 10.5)

    def test_rejects_empty_sample(self):
        with self.assertRaises(ValueError):
            nearest_rank([], 0.95)


if __name__ == "__main__":
    unittest.main()
