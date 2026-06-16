import unittest

from dynamic_threshold import RollingMadThreshold


class RollingMadThresholdTest(unittest.TestCase):
    def test_static_fallback_until_min_samples(self):
        threshold = RollingMadThreshold(
            static_threshold=100,
            window_samples=5,
            min_samples=3,
            k=6,
            enabled=True,
        )

        self.assertEqual(threshold.evaluate(50)["mode"], "warmup")
        self.assertEqual(threshold.evaluate(60)["mode"], "warmup")

    def test_dynamic_threshold_after_min_samples(self):
        threshold = RollingMadThreshold(
            static_threshold=100,
            window_samples=5,
            min_samples=3,
            k=6,
            enabled=True,
        )
        threshold.evaluate(50)
        threshold.evaluate(55)
        threshold.evaluate(60)

        info = threshold.threshold()
        self.assertIn(info["mode"], {"dynamic", "dynamic_floor"})
        self.assertGreaterEqual(info["value"], 100)

    def test_freeze_skips_update(self):
        threshold = RollingMadThreshold(
            static_threshold=100,
            window_samples=5,
            min_samples=2,
            k=6,
            enabled=True,
        )
        threshold.evaluate(50)
        threshold.evaluate(60, update=False)

        self.assertEqual(threshold.threshold()["sample_count"], 1)


if __name__ == "__main__":
    unittest.main()
