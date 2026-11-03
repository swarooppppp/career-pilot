"""Conservative output checks; never infer location or function from descriptions."""
import json
import re

INDIA = re.compile(r"\b(?:india|bengaluru|bangalore|hyderabad|pune|mumbai|chennai|gurugram|gurgaon|noida|new delhi|delhi|kolkata|ahmedabad|kochi|coimbatore|trivandrum|thiruvananthapuram|gift city|gandhinagar)\b", re.I)
ENGINEERING = re.compile(r"\b(?:engineer(?:ing)?|developer|architect|sre|sdet|devops|mts|member(?:s)? of technical staff)\b", re.I)
NON_ENGINEERING = re.compile(r"\b(?:sales|presales|pre-sales|customer success|technical support|support engineer|solutions engineer|solution engineer|recruiter)\b", re.I)


def location_text(job):
    values = [job.get(k) for k in ("location", "locations", "country", "jobLocation", "standardizedLocations", "offices") if job.get(k)]
    return json.dumps(values, ensure_ascii=False)


def in_india(job):
    return bool(INDIA.search(location_text(job)))


def engineering_title(job):
    title = str(job.get("title") or job.get("name") or "")
    return bool(ENGINEERING.search(title)) and not NON_ENGINEERING.search(title)


def apply_policy(jobs, policy):
    kept = []
    for job in jobs:
        if not in_india(job):
            continue
        if policy["engineering"] == "title" and not engineering_title(job):
            continue
        kept.append(job)
    return kept
