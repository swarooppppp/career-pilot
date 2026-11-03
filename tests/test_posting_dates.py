import unittest
from app.services.posting_dates import parse_posting_date, publication_date


class PostingDateTests(unittest.TestCase):
    def test_supported_formats_and_precision(self):
        for value, precision in [("2026-10-01", "date"), ("October 01, 2026", "date"),
                                 ("2026-10-01T00:00:00Z", "timestamp"),
                                 (1790812800, "timestamp"), (1790812800000, "timestamp")]:
            parsed, actual = parse_posting_date(value)
            self.assertIsNotNone(parsed)
            self.assertEqual(actual, precision)
            self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_unavailable_and_relative_dates_remain_unknown(self):
        for value in [None, "", "Posted yesterday", float("nan"), True, -1, {}, "invalid"]:
            self.assertEqual(parse_posting_date(value), (None, None))
        self.assertEqual(publication_date({"updated_date": "2026-10-01"}, "google"), (None, None))

    def test_legacy_update_dates_are_not_used_as_publication(self):
        for source in ["databricks", "atlassian"]:
            raw = {"posted_date": "2026-10-01"}
            self.assertEqual(publication_date(raw, source), (None, None))
            raw["posting_date_source"] = "first_published"
            self.assertIsNotNone(publication_date(raw, source)[0])
