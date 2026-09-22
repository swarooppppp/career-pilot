#!/usr/bin/env python3
"""Generate a JD-tailored resume PDF from a job-description text file."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from convert_latex_to_pdf import compile_latex
ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "main.tex"
MASTER_EXPERIENCE = ROOT / "data" / "master_experience.md"
RESUME_PROMPT_VERSION = "2026-09-21-match-context-v1"
EXPECTED_BULLET_COUNTS = {
    "oracle_software_engineer": 6,
    "oracle_project_intern": 1,
    "distributed_rate_limiter": 2,
    "expense_splitter": 2,
}

RESUME_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "skills": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "languages": {"type": "array", "items": {"type": "string"}},
                "frameworks_libraries": {"type": "array", "items": {"type": "string"}},
                "tools_platforms": {"type": "array", "items": {"type": "string"}},
                "concepts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["languages", "frameworks_libraries", "tools_platforms", "concepts"],
        },
        "experience": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                key: {"type": "array", "items": {"type": "string"}, "minItems": count, "maxItems": count}
                for key, count in EXPECTED_BULLET_COUNTS.items()
            },
            "required": list(EXPECTED_BULLET_COUNTS),
        },
    },
    "required": ["summary", "skills", "experience"],
}

RESUME_DEVELOPER_INSTRUCTIONS = """
Generate truthful, ATS-friendly resume content for the fixed resume template.
Use only the supplied candidate facts and cited evidence. Never invent a skill,
metric, employer, date, responsibility, or achievement. Do not add a keyword
merely because it appears in a job requirement. Use the job-match terminology
only where it is supported by the evidence. Return only the requested JSON.

The output must contain exactly 11 complete, concise, plain-text experience
bullets: 6 for oracle_software_engineer, 1 for oracle_project_intern, 2 for
distributed_rate_limiter, and 2 for expense_splitter. Do not use Markdown or
LaTeX commands. Keep the four skill lists truthful and concise.
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a tailored resume PDF.")
    parser.add_argument("job_description", type=Path, help="Text file containing the JD")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=ROOT, help="Directory for the PDF"
    )
    parser.add_argument(
        "--keep-tex",
        action="store_true",
        help="Keep the generated LaTeX file beside the output PDF for inspection",
    )
    return parser.parse_args()


def _response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) in {"output_text", "text"} and getattr(content, "text", None):
                return content.text
    raise ValueError("OpenAI response contains no output text")


def _resume_context(job_description: str, match_analysis: dict | None, job_title: str | None) -> str:
    """Use already-validated match evidence when a dashboard job is available."""
    if match_analysis:
        requirements = match_analysis.get("requirements")
        if not isinstance(requirements, list):
            raise ValueError("stored job analysis has no requirements")
        evidence_by_id: dict[str, dict] = {}
        compact_requirements = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            evidence = []
            for item in requirement.get("evidence", []):
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                resolved = {
                    "id": item["id"], "title": item.get("title", ""),
                    "text": item.get("text", ""), "source_type": item.get("source_type", "unverified"),
                }
                evidence_by_id[resolved["id"]] = resolved
                evidence.append(resolved["id"])
            compact_requirements.append({
                "id": requirement.get("id"), "text": requirement.get("text"),
                "category": requirement.get("category"), "importance": requirement.get("importance"),
                "support_level": requirement.get("support_level"), "explanation": requirement.get("explanation", ""),
                "evidence_ids": evidence,
            })
        return "\n".join((
            "JOB MATCH CONTEXT (already extracted and evidence-validated):",
            json.dumps({
                "job_title": job_title or "", "summary": match_analysis.get("summary", ""),
                "requirements": compact_requirements,
                "recommendations": match_analysis.get("recommendations", []),
            }, ensure_ascii=False),
            "CITED CANDIDATE EVIDENCE (the only source for factual resume claims):",
            json.dumps(list(evidence_by_id.values()), ensure_ascii=False),
        ))

    # The standalone paste-a-JD screen has no first-pass result to reuse.
    # Retain it as a useful direct workflow, but make that larger input explicit.
    return "\n".join((
        "JOB DESCRIPTION:", job_description,
        "MASTER EXPERIENCE (source of truth):", MASTER_EXPERIENCE.read_text(encoding="utf-8"),
    ))


def request_content(job_description: str, match_analysis: dict | None = None, job_title: str | None = None) -> dict:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("install dependencies with pip install -r requirements.txt") from error
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("set OPENAI_API_KEY in .env before generating a resume")

    context = _resume_context(job_description, match_analysis, job_title)
    model = os.getenv("RESUME_OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6-luna"))
    response = OpenAI().responses.create(
        model=model,
        reasoning={"effort": os.getenv("RESUME_OPENAI_REASONING_EFFORT", "low")},
        input=[
            {"role": "developer", "content": RESUME_DEVELOPER_INSTRUCTIONS},
            {"role": "user", "content": context},
        ],
        text={"format": {"type": "json_schema", "name": "tailored_resume", "strict": True, "schema": RESUME_RESPONSE_SCHEMA}},
    )
    raw_response = _response_text(response)

    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise ValueError(f"OpenAI returned invalid JSON: {error}") from error

    experience_data = data.get("experience") if isinstance(data, dict) else None
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("OpenAI response must contain a non-empty summary")
    expected_skill_categories = {
        "languages",
        "frameworks_libraries",
        "tools_platforms",
        "concepts",
    }
    skills_data = data.get("skills")
    if not isinstance(skills_data, dict) or set(skills_data) != expected_skill_categories:
        raise ValueError("OpenAI response must contain all four skill categories")
    for category, skills in skills_data.items():
        if not isinstance(skills, list) or not all(
            isinstance(skill, str) and skill.strip() for skill in skills
        ):
            raise ValueError(f"OpenAI skills category '{category}' must contain strings")
    if set(experience_data or {}) != set(EXPECTED_BULLET_COUNTS):
        raise ValueError("OpenAI returned unexpected experience sections")
    for section, count in EXPECTED_BULLET_COUNTS.items():
        bullets = experience_data[section]
        if not isinstance(bullets, list) or len(bullets) != count:
            raise ValueError(f"{section} must contain exactly {count} bullets")
        if not all(isinstance(bullet, str) and bullet.strip() for bullet in bullets):
            raise ValueError(f"{section} contains an empty or invalid bullet")
    return data


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in value.strip())


def highlight_text(value: str, keywords: list[str] | None = None) -> str:
    """Escape text and apply restrained emphasis to metrics and key skills."""
    escaped = latex_escape(value)
    patterns = [
        r"\b\d{1,3}(?:,\d{3})+(?:\+|\\%|%|ms|s)?(?=\W|$)",
        r"\b\d+(?:\.\d+)?(?:\+|\\%|%|ms|s)(?=\W|$)",
    ]
    for pattern in patterns:
        escaped = re.sub(pattern, lambda match: r"\textbf{" + match.group(0) + "}", escaped)

    for keyword in sorted(set(keywords or []), key=len, reverse=True):
        escaped_keyword = latex_escape(keyword)
        if len(escaped_keyword) < 3:
            continue
        escaped = re.sub(
            rf"(?<![A-Za-z])({re.escape(escaped_keyword)})(?![A-Za-z])",
            lambda match: r"\textbf{" + match.group(1) + "}",
            escaped,
            flags=re.IGNORECASE,
        )
    return escaped


def replace_resume_items(
    template: str, bullets: list[str], keywords: list[str] | None = None
) -> str:
    # Match active resume-item commands only. This excludes the command
    # definition and the commented-out examples in the canonical template.
    marker = r"(?m)^[ \t]*\\resumeItem\s*\{"
    positions = [match.start() for match in re.finditer(marker, template)]
    if len(positions) != len(bullets):
        raise ValueError(
            f"template contains {len(positions)} resume items; expected {len(bullets)}"
        )

    result = template
    for start, bullet in reversed(list(zip(positions, bullets))):
        opening = result.find("{", start)
        if opening == -1:
            raise ValueError("could not find resume item opening brace")
        depth = 0
        closing = None
        for index in range(opening, len(result)):
            if result[index] == "{":
                depth += 1
            elif result[index] == "}":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            raise ValueError("could not find resume item closing brace")
        result = result[: opening + 1] + highlight_text(bullet, keywords) + result[closing:]
    return result


def replace_summary(template: str, summary: str, keywords: list[str] | None = None) -> str:
    pattern = re.compile(
        r"(\\section\{Professional Summary\}\s*)(.*?)(\n\n%-----------EDUCATION-----------)",
        re.DOTALL,
    )
    def replacement(match: re.Match[str]) -> str:
        return match.group(1) + highlight_text(summary, keywords) + match.group(3)

    result, replacements = pattern.subn(replacement, template, count=1)
    if replacements != 1:
        raise ValueError("could not find Professional Summary section")
    return result


def replace_skills(template: str, skills: dict[str, list[str]]) -> str:
    labels = {
        "languages": "Languages",
        "frameworks_libraries": "Frameworks / Libraries",
        "tools_platforms": "Tools & Platforms",
        "concepts": "Concepts",
    }
    result = template
    for key, label in labels.items():
        values = ", ".join(latex_escape(skill) for skill in skills[key])
        pattern = re.compile(
            rf"(\\textbf\{{{re.escape(latex_escape(label))}\}}\{{:\s*)(.*?)(\}}\s*(?:\\\\|\n\s*\}}\}}))",
            re.DOTALL,
        )
        replacement = lambda match, values=values: match.group(1) + values + match.group(3)
        result, replacements = pattern.subn(replacement, result, count=1)
        if replacements != 1:
            raise ValueError(f"could not find Technical Skills subsection: {label}")
    return result


def generate_resume(
    job_description: str,
    output_dir: Path = ROOT,
    keep_tex: bool = False,
    match_analysis: dict | None = None,
    job_title: str | None = None,
) -> Path:
    load_dotenv(ROOT / ".env")
    if not job_description.strip():
        raise ValueError("job description cannot be empty")
    try:
        data = request_content(job_description, match_analysis, job_title)
        bullets = [
            bullet
            for section in EXPECTED_BULLET_COUNTS
            for bullet in data["experience"][section]
        ]
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_pdf = output_dir.resolve() / f"Swaroop_SWE_{timestamp}.pdf"
        response_json = output_pdf.with_suffix(".json")
        response_json.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"OpenAI resume JSON saved: {response_json}")

        with tempfile.TemporaryDirectory(prefix="resume-generation-") as directory:
            generated_tex = Path(directory) / "resume.tex"
            template = TEMPLATE.read_text(encoding="utf-8")
            keyword_values = [
                skill
                for category in data["skills"].values()
                for skill in category
            ]
            generated_source = replace_summary(template, data["summary"], keyword_values)
            generated_source = replace_skills(generated_source, data["skills"])
            generated_source = replace_resume_items(generated_source, bullets, keyword_values)
            if generated_source == template:
                raise ValueError("Gemini output did not change the LaTeX template")
            missing_bullets = [
                bullet
                for bullet in bullets
                if highlight_text(bullet, keyword_values) not in generated_source
            ]
            if missing_bullets:
                raise ValueError(
                    f"{len(missing_bullets)} Gemini bullets were not found in generated LaTeX"
                )
            generated_tex.write_text(generated_source, encoding="utf-8")
            result = compile_latex(generated_tex, output_pdf, "pdflatex")
            if result == 0 and keep_tex:
                kept_tex = output_pdf.with_suffix(".tex")
                kept_tex.write_text(generated_source, encoding="utf-8")
                print(f"Generated LaTeX kept: {kept_tex}")
            if result == 0:
                print(f"OpenAI resume bullets inserted: {len(bullets)}")
            if result != 0:
                raise RuntimeError("LaTeX compilation failed")
            return output_pdf
    except Exception as error:
        raise RuntimeError(f"resume generation failed: {error}") from error


def main() -> int:
    args = parse_args()
    jd_path = args.job_description.expanduser().resolve()
    if not jd_path.is_file():
        print(f"Error: job description does not exist: {jd_path}", file=sys.stderr)
        return 1
    try:
        generate_resume(jd_path.read_text(encoding="utf-8"), args.output_dir, args.keep_tex)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
