import unittest
from datetime import date

from app.services.candidate_experience import (
    calculate_professional_experience,
    experience_years_for_import,
)


def role(title: str, dates: str) -> str:
    return f"## {title}\n- Dates: {dates}\n- Built services."


class CandidateExperienceTests(unittest.TestCase):
    AS_OF = date(2026, 9, 21)

    def test_supported_month_formats_normalize_to_the_same_duration(self):
        values = ["June 2024", "Jun 2024", "06/2024", "2024-06", "06-2024"]
        results = [
            calculate_professional_experience(role("Software Engineer", f"{value} — Present"), self.AS_OF)
            for value in values
        ]

        self.assertTrue(all(result is not None for result in results))
        self.assertEqual({result["non_internship_professional"] for result in results}, {2.31})
        self.assertTrue(all(result["qualifying_roles"][0]["start_date"] == "2024-06-01" for result in results))

    def test_internship_is_excluded_and_overlapping_roles_are_not_double_counted(self):
        master = "\n\n".join((
            role("Software Engineer", "June 2024 — Present"),
            role("Backend Engineer", "January 2025 — Present"),
            role("Project Intern", "May 2023 — July 2023"),
        ))
        result = calculate_professional_experience(master, self.AS_OF)

        self.assertEqual(result["non_internship_professional"], 2.31)
        self.assertEqual([item["title"] for item in result["qualifying_roles"]], [
            "Software Engineer", "Backend Engineer",
        ])

    def test_invalid_dates_are_not_guessed_and_import_uses_fallback(self):
        master = role("Software Engineer", "Summer 2024 — Present")

        self.assertIsNone(calculate_professional_experience(master, self.AS_OF))
        with self.assertLogs("app.services.candidate_experience", "WARNING"):
            self.assertEqual(experience_years_for_import(master, 2.0, self.AS_OF), 2.0)

