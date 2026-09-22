"""One-call, evidence-cited candidate-to-job matching."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from app.services.candidate_experience import calculate_professional_experience

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # Allows the rest of the local app to run before pip install.
    RecursiveCharacterTextSplitter = None


ROOT = Path(__file__).resolve().parents[2]
MASTER_EXPERIENCE = ROOT / "data" / "master_experience.md"
CACHE_DIR = ROOT / "data" / "match_cache"
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
logger = logging.getLogger(__name__)

MATCHING_SCHEMA_VERSION = "openai-batch-one-call-evidence-weighted-v1"
MATCHING_PROMPT_VERSION = "2026-09-21-cacheable-experience-v1"
SUPPORT_FACTORS = {
    "direct": 1.0,
    "strong_transferable": 0.82,
    "weak_transferable": 0.60,
    "no_evidence": 0.0,
    "hard_contradiction": 0.0,
}
POSITIVE_SUPPORT_LEVELS = {"direct", "strong_transferable", "weak_transferable"}
SOURCE_FACTORS = {
    "work_experience": 1.0,
    "project": 0.85,
    "education": 0.65,
    "skills_summary": 0.65,
    "overview": 0.65,
    "unverified": 0.0,
}
CATEGORY_WEIGHTS = {
    "core_responsibility": 35,
    "required_skill": 25,
    "seniority_scope": 15,
    "preferred_skill": 10,
    "domain": 5,
    "hard_constraint": 5,
    "education": 3,
    "nice_to_have": 2,
}
VALID_CATEGORIES = set(CATEGORY_WEIGHTS)

# These aliases help retrieval recognize equivalent wording. They are limited
# to spelling variants, abbreviations, and direct product/framework names; they
# do not treat related technologies as interchangeable (for example, Kafka and
# RabbitMQ remain distinct). They do not claim the candidate has every item in
# an alias group: Gemini still judges the retrieved evidence.
SKILL_ALIASES = {
    # Languages and query languages.
    "java": ("java", "java se", "jdk", "openjdk"),
    "python": ("python", "python3"),
    "c++": ("c++", "c/c++", "cpp", "c plus plus", "modern c++", "c++11", "c++14", "c++17", "c++20"),
    "javascript": ("javascript", "java script", "ecmascript"),
    "html/css": ("html/css", "html", "html5", "css", "css3"),
    "sql": ("sql", "structured query language", "ansi sql", "relational query", "relational queries"),
    "postgresql": ("postgresql", "postgres", "psql"),
    "mysql": ("mysql", "my sql"),

    # Frameworks and APIs.
    "spring boot": ("spring boot", "springboot", "spring boot framework", "spring framework"),
    "react": ("react", "react.js", "reactjs"),
    "flask": ("flask", "flask framework"),
    "node.js": ("node.js", "nodejs", "node js"),
    "junit": ("junit", "junit 4", "junit 5"),
    "jpa": ("jpa", "java persistence api", "jakarta persistence"),
    "rest api": ("rest api", "rest apis", "restful api", "restful apis", "restful service", "restful services", "rest architecture"),
    "api design": ("api design", "api design patterns"),

    # Distributed systems, data, and infrastructure.
    "distributed systems": ("distributed system", "distributed systems", "distributed service", "distributed services", "distributed architecture"),
    "microservices": ("microservice", "microservices", "microservice architecture"),
    "event-driven architecture": ("event-driven", "event driven", "event-driven architecture", "event driven architecture"),
    "stateless architecture": ("stateless", "stateless architecture", "stateless services"),
    "redis": ("redis", "redis cache", "redis caching", "redis incr", "redis expire"),
    "kafka": ("kafka", "apache kafka", "kafka streams"),
    "docker": ("docker", "docker container", "docker containers", "containerization"),
    "aws": ("aws", "amazon web services"),
    "database optimization": ("database optimization", "database performance", "query optimization", "sql optimization"),

    # Engineering practices and security.
    "git": ("git", "git scm", "git version control"),
    "ci/cd": ("ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"),
    "jwt": ("jwt", "json web token", "json web tokens"),
    "oauth 2.0": ("oauth2", "oauth 2", "oauth 2.0"),
    "concurrency": ("concurrency", "concurrent programming", "thread safety", "thread-safe", "race condition", "optimistic locking"),
    "system design": ("system design", "systems design", "software system design"),
    "data structures and algorithms": ("data structures and algorithms", "data structures", "algorithms", "dsa"),

    # AI work explicitly described in the master experience.
    "llm integration": ("llm", "large language model", "large language models", "llm integration", "ai agent", "ai agents", "inference pipeline", "context caching"),
}


@dataclass(frozen=True)
class EvidenceChunk:
    id: str
    title: str
    text: str
    source_type: str


def _split_evidence(text: str) -> list[str]:
    """Use LangChain when installed to keep large master-experience sections searchable."""
    if RecursiveCharacterTextSplitter is None:
        return [text]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1_000,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#./-]+", value.lower()))


def _contains_alias(text: str, alias: str) -> bool:
    """Match an alias as a phrase, without allowing substring false positives."""
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])", text.lower()))


def build_candidate_profile(master_text: str) -> dict[str, Any]:
    """Create stable, searchable evidence passages from the master experience."""
    candidate: dict[str, str] = {}
    chunks: list[EvidenceChunk] = []
    current_title = "Candidate overview"
    current_source_type = "overview"
    current_lines: list[str] = []

    def save_chunk() -> None:
        if current_lines:
            for chunk_text in _split_evidence("\n".join(current_lines)):
                chunks.append(
                    EvidenceChunk(
                        id=f"evidence-{len(chunks) + 1}",
                        title=current_title,
                        text=chunk_text,
                        source_type=current_source_type,
                    )
                )

    def source_type_for_heading(heading: str) -> str:
        normalized = heading.lower()
        if normalized == "candidate":
            return "overview"
        if normalized == "projects":
            return "project"
        if "education" in normalized:
            return "education"
        if "skills" in normalized:
            return "skills_summary"
        if "requiring confirmation" in normalized or "unverified" in normalized:
            return "unverified"
        return "work_experience"

    for raw_line in master_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            save_chunk()
            current_title = line.lstrip("# ")
            current_source_type = source_type_for_heading(current_title)
            current_lines = []
        elif line.startswith("### "):
            save_chunk()
            current_title = line.lstrip("# ")
            current_lines = []
        elif line.startswith("- "):
            current_lines.append(line[2:])

            if current_title == "Candidate" and ":" in line:
                key, value = line[2:].split(":", 1)
                candidate[key.strip().lower().replace(" ", "_")] = value.strip()
    save_chunk()

    searchable_text = "\n".join(chunk.text for chunk in chunks).lower()
    known_skills = sorted(
        canonical
        for canonical, aliases in SKILL_ALIASES.items()
        if any(_contains_alias(searchable_text, alias) for alias in aliases)
    )
    roles = [
        {"title": chunk.title, "evidence_id": chunk.id}
        for chunk in chunks
        if chunk.source_type == "work_experience"
    ]
    projects = [
        {"name": chunk.title, "evidence_id": chunk.id}
        for chunk in chunks
        if chunk.source_type == "project"
    ]
    education = [chunk.__dict__ for chunk in chunks if chunk.source_type == "education"]
    responsibilities = [
        line
        for chunk in chunks
        if chunk.source_type != "education"
        for line in chunk.text.splitlines()
    ]
    achievements = [
        line
        for line in responsibilities
        if re.search(r"\b\d+(?:,\d{3})*(?:\.\d+)?(?:%|\+|ms| seconds| requests| users| clients| tables)?\b", line)
    ]
    domain_terms = {
        "human resources": ("workforce", "compensation", "hr use case", "manager"),
        "backend platforms": ("rest", "microservice", "rate-limiting", "distributed"),
        "ai systems": ("llm", "ai agent", "inference"),
    }
    domains = [
        domain for domain, terms in domain_terms.items() if any(term in searchable_text for term in terms)
    ]
    years_of_experience = calculate_professional_experience(master_text)
    if years_of_experience:
        experience_text = (
            f"Verified non-internship professional experience: "
            f"{years_of_experience['non_internship_professional']:.2f} years as of "
            f"{years_of_experience['calculated_as_of']}. "
            f"Basis: {years_of_experience['basis']}"
        )
        chunks.append(EvidenceChunk(
            id=f"evidence-{len(chunks) + 1}", title="Verified professional experience",
            text=experience_text, source_type="work_experience",
        ))
    return {
        "candidate": candidate,
        "years_of_experience": years_of_experience or {
            "non_internship_professional": None,
            "calculation_status": "unavailable",
        },
        "skills": known_skills,
        "roles": roles,
        "responsibilities": responsibilities,
        "domains": domains,
        "projects": projects,
        "achievements": achievements,
        "education": education,
        "certifications": [],
        "constraints": {
            "location": candidate.get("location", "not explicitly stated"),
            "work_authorization": "not explicitly stated",
        },
        "evidence_chunks": [chunk.__dict__ for chunk in chunks],
        "source_hash": _sha256(master_text),
    }


@lru_cache(maxsize=1)
def candidate_profile() -> dict[str, Any]:
    return build_candidate_profile(MASTER_EXPERIENCE.read_text(encoding="utf-8"))


def retrieve_evidence(requirement: str, profile: dict[str, Any], limit: int = 3) -> list[dict[str, str]]:
    """Retrieve evidence without spending tokens; this can later use embeddings."""
    requirement_lower = requirement.lower()
    requirement_tokens = _tokens(requirement)
    relevant_aliases = [
        alias
        for aliases in SKILL_ALIASES.values()
        if any(_contains_alias(requirement_lower, candidate) for candidate in aliases)
        for alias in aliases
    ]
    scored: list[tuple[int, dict[str, str]]] = []
    for chunk in profile["evidence_chunks"]:
        text_lower = chunk["text"].lower()
        overlap = len(requirement_tokens & _tokens(text_lower))
        alias_hits = sum(_contains_alias(text_lower, alias) for alias in relevant_aliases)
        score = overlap + (alias_hits * 3)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]


MATCHING_DEVELOPER_INSTRUCTIONS = """
Analyse a job description against the candidate material supplied in subsequent messages.
Return only the requested structured JSON.

Return exactly this structure:
{
  "requirements": [{
  "id": "req-1",
  "text": "concise requirement",
  "category": "core_responsibility | required_skill | seniority_scope | preferred_skill | domain | hard_constraint | education | nice_to_have",
  "importance": 1,
  "is_genuine_hard_constraint": false,
  "support_level": "direct | strong_transferable | weak_transferable | no_evidence | hard_contradiction",
  "evidence_ids": ["evidence-1"],
  "explanation": "brief explanation grounded in cited evidence"
  }],
  "summary": "one or two sentence assessment",
  "recommendations": ["up to three truthful recommendations"]
}

Rules:
- Return 4 to 10 scored requirements. Prefer 6 to 8 for a straightforward
  role. Do not fill the limit merely because the JD has many bullets.
- Merge overlapping statements into one requirement. Do not score backend
  services, distributed systems, scalability, reliability, and cloud operations
  as separate requirements when they describe the same core capability.
- Include only concrete technical skills, domain knowledge, role
  responsibilities, education, and explicit years-of-experience requirements.
- Do NOT include or score generic soft skills or culture statements, including
  communication, collaboration, teamwork, mentoring, feedback, growth mindset,
  adaptability, or working through ambiguity.
- Do NOT include or score administrative, legal, or hiring boilerplate,
  including employer background/security checks, office-attendance or
  work-location policy, equal-opportunity language, export-control paperwork,
  citizenship/residency documentation, or application instructions.
  Those are application eligibility notices, not evidence-based match criteria.
- Importance is an integer from 1 to 10.
- Only mark a genuine role-specific, evidence-based non-negotiable condition as
  a hard constraint. Do not use hard_constraint for excluded boilerplate.
- A technology or years-of-experience phrase is normally not a hard constraint.
- Positive support (direct, strong_transferable, weak_transferable) MUST cite at
  least one evidence ID from EVIDENCE CHUNKS.
- Use no_evidence when the profile does not support a requirement. Missing
  evidence is not a contradiction.
- Use hard_contradiction only when cited evidence contradicts a genuine hard constraint.
- Do not invent skills, dates, qualifications, or evidence.
""".strip()


def build_match_profile_context(profile: dict[str, Any]) -> str:
    """Return the stable, cacheable candidate prefix shared by every job."""
    return f"""
CANDIDATE PROFILE:
{json.dumps({
    "candidate": profile["candidate"],
    "years_of_experience": profile.get("years_of_experience", {"calculation_status": "unavailable"}),
    "skills": profile["skills"],
    "roles": profile["roles"],
    "projects": profile["projects"],
    "domains": profile["domains"],
    "education": profile["education"],
    "constraints": profile["constraints"],
}, ensure_ascii=False)}

EVIDENCE CHUNKS:
{json.dumps(profile["evidence_chunks"], ensure_ascii=False)}
""".strip()


def build_match_prompt(job_description: str, profile: dict[str, Any]) -> str:
    """Build a readable full request, ordered for reusable-prefix caching."""
    return f"""
{MATCHING_DEVELOPER_INSTRUCTIONS}

{build_match_profile_context(profile)}

JOB DESCRIPTION (the only job-specific input):
{job_description}
""".strip()


MATCH_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "requirements": {
            "type": "array", "maxItems": 10,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"}, "text": {"type": "string"},
                    "category": {"type": "string", "enum": sorted(VALID_CATEGORIES)},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 10},
                    "is_genuine_hard_constraint": {"type": "boolean"},
                    "support_level": {"type": "string", "enum": sorted(SUPPORT_FACTORS)},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                },
                "required": ["id", "text", "category", "importance", "is_genuine_hard_constraint", "support_level", "evidence_ids", "explanation"],
            },
        },
        "summary": {"type": "string"},
        "recommendations": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["requirements", "summary", "recommendations"],
}


def validate_match_response(data: dict[str, Any], profile: dict[str, Any]) -> tuple[list[dict[str, Any]], str, list[str]]:
    """Validate model output before deterministic evidence/source scoring."""
    requirements = data.get("requirements") if isinstance(data, dict) else None
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("model did not return job requirements")
    if len(requirements) > 10:
        raise ValueError("model returned too many job requirements")
    evidence_by_id = {item["id"]: item for item in profile["evidence_chunks"]}
    validated = []
    requirement_ids: set[str] = set()
    for item in requirements:
        if not isinstance(item, dict):
            raise ValueError("a job requirement is not an object")
        requirement_id = item.get("id")
        text = item.get("text")
        category = item.get("category")
        importance = item.get("importance")
        support_level = item.get("support_level")
        evidence_ids = item.get("evidence_ids", [])
        if (
            not isinstance(requirement_id, str)
            or not requirement_id.strip()
            or requirement_id in requirement_ids
            or not isinstance(text, str)
            or not text.strip()
            or category not in VALID_CATEGORIES
            or support_level not in SUPPORT_FACTORS
            or not isinstance(evidence_ids, list)
            or not all(isinstance(evidence_id, str) for evidence_id in evidence_ids)
        ):
            raise ValueError("model returned an invalid job requirement")
        if not isinstance(importance, int) or not 1 <= importance <= 10:
            raise ValueError("model returned an invalid requirement importance")
        requirement_ids.add(requirement_id)
        valid_evidence_ids = [evidence_id for evidence_id in evidence_ids if evidence_id in evidence_by_id]
        if support_level in POSITIVE_SUPPORT_LEVELS and not valid_evidence_ids:
            support_level = "no_evidence"
        validated.append(
            {
                "id": requirement_id,
                "text": text.strip(),
                "category": category,
                "importance": importance,
                "is_genuine_hard_constraint": bool(item.get("is_genuine_hard_constraint")),
                "support_level": support_level,
                "support_factor": SUPPORT_FACTORS[support_level],
                "evidence_ids": valid_evidence_ids,
                "explanation": str(item.get("explanation", "")).strip(),
            }
        )
    summary = str(data.get("summary", "")).strip()
    recommendations = data.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    return validated, summary, [str(item) for item in recommendations[:3]]


def calculate_score(evaluations: list[dict[str, Any]]) -> int:
    total_weight = sum(CATEGORY_WEIGHTS[item["category"]] * item["importance"] for item in evaluations)
    if not total_weight:
        return 0
    score = sum(
        CATEGORY_WEIGHTS[item["category"]] * item["importance"] * item["match_strength"]
        for item in evaluations
    ) / total_weight
    return round(score * 100)


def _group_matches(evaluations: list[dict[str, Any]], levels: set[str]) -> list[dict[str, Any]]:
    return [item for item in evaluations if item["support_level"] in levels]


def build_analysis_result(job_description: str, data: dict[str, Any]) -> dict[str, Any]:
    """Turn a validated Batch response into the persisted deterministic result."""
    profile = candidate_profile()
    model = os.getenv("OPENAI_MODEL", MODEL_NAME)
    cache_key = _sha256(
        MATCHING_SCHEMA_VERSION + MATCHING_PROMPT_VERSION + model + profile["source_hash"] + job_description
    )
    evaluations, summary, recommendations = validate_match_response(data, profile)
    evidence_by_id = {item["id"]: item for item in profile["evidence_chunks"]}
    for evaluation in evaluations:
        evaluation["evidence"] = [
            evidence_by_id[item] for item in evaluation.pop("evidence_ids") if item in evidence_by_id
        ]
        source_factors = [SOURCE_FACTORS[item["source_type"]] for item in evaluation["evidence"]]
        evaluation["evidence_source_factor"] = max(source_factors, default=0.0)
        evaluation["match_strength"] = round(
            evaluation["support_factor"] * evaluation["evidence_source_factor"], 4
        )
    critical_gaps = [
        item
        for item in evaluations
        if item["support_level"] == "hard_contradiction" and item["is_genuine_hard_constraint"]
    ]
    result = {
        "match_id": cache_key[:16],
        "cached": False,
        "overall_score": calculate_score(evaluations),
        "summary": summary,
        "strong_matches": _group_matches(evaluations, {"direct"}),
        "transferable_matches": _group_matches(
            evaluations, {"strong_transferable", "weak_transferable"}
        ),
        "uncertain_requirements": _group_matches(evaluations, {"no_evidence"}),
        "critical_gaps": critical_gaps,
        "recommendations": recommendations,
        "requirements": evaluations,
    }
    logger.info("Batch match complete (%s): score=%s requirements=%s", cache_key[:16], result["overall_score"], len(evaluations))
    return result


def analyse_job(job_description: str) -> dict[str, Any]:
    """Interactive matching is intentionally disabled: use the Batch workflow."""
    if len(job_description.strip()) < 20:
        raise ValueError("job description must contain at least 20 characters")
    raise RuntimeError("Direct matching is disabled. Submit stored jobs through the OpenAI Batch workflow.")
