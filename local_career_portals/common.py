"""Shared date ordering and snapshot utilities for local portal fetches."""
from datetime import datetime, timezone
import html
import json
import re
from pathlib import Path


def timestamp(value):
    if isinstance(value, (int, float)):
        return value / 1000 if value > 100000000000 else value
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError):
        # Public portals also emit display dates, not just ISO timestamps.
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d %I:%M %p", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(str(value), pattern)
                return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
            except (ValueError, TypeError, OverflowError):
                continue
        return float("-inf")


def newest_first(jobs):
    # Stable ordering preserves portal order when dates are unavailable.
    return sorted(jobs, key=lambda j: timestamp(j.get("posted_date") or j.get("updated_date")), reverse=True)


def plain_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(value))).split())


def write_snapshot(path, jobs, **metadata):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({**metadata, "jobs_fetched": len(jobs), "jobs": jobs}, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)
