import unittest
from unittest.mock import patch

from app.services import gemini_rate_limiter


class LocalGeminiRateLimiterTests(unittest.TestCase):
    def setUp(self):
        gemini_rate_limiter._local_slots.clear()

    def tearDown(self):
        gemini_rate_limiter._local_slots.clear()

    def test_local_limiter_grants_only_configured_slots_in_window(self):
        with patch.object(gemini_rate_limiter.time, "monotonic", return_value=100.0):
            gemini_rate_limiter._acquire_local(2)
            gemini_rate_limiter._acquire_local(2)

        self.assertEqual(list(gemini_rate_limiter._local_slots), [100.0, 100.0])

    def test_local_limiter_waits_until_oldest_slot_expires(self):
        gemini_rate_limiter._local_slots.extend([100.0, 101.0])
        clock = {"value": 100.0}

        def advance(seconds):
            clock["value"] += seconds

        with patch.object(gemini_rate_limiter.time, "monotonic", side_effect=lambda: clock["value"]), \
                patch.object(gemini_rate_limiter.time, "sleep", side_effect=advance) as sleep:
            gemini_rate_limiter._acquire_local(2)

        sleep.assert_called_once_with(60.0)
        self.assertEqual(list(gemini_rate_limiter._local_slots), [101.0, 160.0])


if __name__ == "__main__":
    unittest.main()
