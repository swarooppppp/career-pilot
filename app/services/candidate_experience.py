"""Deterministically calculate verified professional experience from Markdown."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime
from typing import Any


logger = logging.getLogger(__name__)
EXCLUDED_ROLE_PATTERN = re.compile(r"\b(?:intern(?:ship)?|trainee|apprentice|student)\b", re.IGNORECASE)
DATE_RANGE_PATTERN = re.compile(r"\s+(?:—|–|-|to)\s+", re.IGNORECASE)
DATE_FORMATS = ("%B %Y", "%b %Y", "%m/%Y", "%Y-%m", "%m-%Y")


def _parse_month(value: str, *, is_end: bool) -> date | None:
    """Parse an unambiguous month/year in one of the documented formats."""
    for format_string in DATE_FORMATS:
        try:
            parsed = datetime.strptime(value.strip(), format_string).date()
        except ValueError:
            continue
        day = calendar.monthrange(parsed.year, parsed.month)[1] if is_end else 1
        return date(parsed.year, parsed.month, day)
    return None


def _role_sections(master_text: str) -> list[tuple[str, str]]:
    """Return top-level Markdown sections; only those can represent roles."""
    sections: list[tuple[str, str]] = []
    title: str | None = None
    lines: list[str] = []
    for raw_line in master_text.splitlines():
        if raw_line.startswith("## "):
            if title is not None:
                sections.append((title, "\n".join(lines)))
            title = raw_line[3:].strip()
            lines = []
        elif title is not None:
            lines.append(raw_line.strip())
    if title is not None:
        sections.append((title, "\n".join(lines)))
    return sections


def calculate_professional_experience(master_text: str, as_of: date | None = None) -> dict[str, Any] | None:
    """Calculate total non-internship experience from dated top-level roles.

    Month-only start dates use the first day of that month; month-only end dates
    use the last day. Overlapping intervals are merged before computing the
    total, so concurrent roles are never counted twice.
    """
    as_of = as_of or date.today()
    qualifying_roles: list[dict[str, Any]] = []
    intervals: list[tuple[date, date]] = []
    for title, body in _role_sections(master_text):
        if EXCLUDED_ROLE_PATTERN.search(title):
            continue
        match = re.search(r"(?mi)^\s*-\s*Dates:\s*(.+?)\s*$", body)
        if not match:
            continue
        parts = DATE_RANGE_PATTERN.split(match.group(1).strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        start = _parse_month(parts[0], is_end=False)
        end_text = parts[1].strip()
        end = as_of if end_text.lower() == "present" else _parse_month(end_text, is_end=True)
        if start is None or end is None or end < start:
            continue
        duration_days = (end - start).days + 1
        qualifying_roles.append({
            "title": title,
            "start_date": start.isoformat(),
            "end_date": "present" if end_text.lower() == "present" else end.isoformat(),
            "years": round(duration_days / 365.2425, 2),
        })
        intervals.append((start, end))
    if not intervals:
        return None

    intervals.sort(key=lambda interval: interval[0])
    merged: list[tuple[date, date]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    total_days = sum((end - start).days + 1 for start, end in merged)
    total_years = round(total_days / 365.2425, 2)
    return {
        "non_internship_professional": total_years,
        "calculated_as_of": as_of.isoformat(),
        "qualifying_roles": qualifying_roles,
        "basis": "Top-level dated roles excluding internships and overlapping periods.",
    }


def experience_years_for_import(master_text: str, fallback_years: float, as_of: date | None = None) -> float:
    """Return verified experience, or the configured safe fallback when absent."""
    calculation = calculate_professional_experience(master_text, as_of)
    if calculation is not None:
        return float(calculation["non_internship_professional"])
    logger.warning(
        "Could not calculate qualifying professional experience from master_experience.md; "
        "using CANDIDATE_YEARS_EXPERIENCE fallback %.2f", fallback_years,
    )
    return fallback_years
