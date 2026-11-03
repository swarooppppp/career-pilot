"""Conservative parsing of publication dates; never substitute update times."""
from datetime import date, datetime, timezone
import math


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def parse_posting_date(value):
    """Return (UTC datetime, date|timestamp precision), or (None, None)."""
    if isinstance(value, datetime):
        return utc(value), "timestamp"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), timezone.utc), "date"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if not math.isfinite(value) or value <= 0:
                return None, None
            seconds = value / 1000 if value > 100_000_000_000 else value
            return datetime.fromtimestamp(seconds, timezone.utc), "timestamp"
        except (ValueError, OverflowError, OSError):
            return None, None
    if not isinstance(value, str) or not value.strip():
        return None, None
    value = value.strip()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return utc(result), "date" if len(value) == 10 else "timestamp"
    except ValueError:
        pass
    for pattern, precision in (("%B %d, %Y", "date"), ("%b %d, %Y", "date"),
                               ("%Y-%m-%d %I:%M %p", "timestamp"),
                               ("%Y-%m-%dT%H:%M:%S.%f%z", "timestamp"),
                               ("%Y-%m-%dT%H:%M:%S%z", "timestamp")):
        try:
            return utc(datetime.strptime(value, pattern)), precision
        except ValueError:
            continue
    # "Posted yesterday" cannot be resolved without a trustworthy fetch date.
    return None, None


def publication_date(raw_job, source):
    for key in ("posted_date", "datePosted", "publishedAt", "first_published", "postedTs", "posted_at", "startDate", "releasedDate"):
        if key == "posted_date" and source.casefold() in {"databricks", "atlassian"} and not raw_job.get("posting_date_source"):
            # Older adapters mislabeled updated_at/updatedDate as publication.
            continue
        result = parse_posting_date(raw_job.get(key))
        if result[0] is not None:
            return result
    return None, None
