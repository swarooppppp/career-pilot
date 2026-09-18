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
from google import genai
from google.genai import types

from convert_latex_to_pdf import compile_latex
from phase1_experiment import EXPECTED_BULLET_COUNTS


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "main.tex"
MASTER_EXPERIENCE = ROOT / "data" / "master_experience.md"
PROMPT = ROOT / "prompts" / "jd_analyzer.md"


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


def response_text(response: object) -> str:
    """Extract normal text parts without triggering SDK thought-part warnings."""
    candidates = getattr(response, "candidates", None) or []
    parts = getattr(getattr(candidates[0], "content", None), "parts", []) if candidates else []
    text_parts = [part.text for part in parts if getattr(part, "text", None)]
    if text_parts:
        return "".join(text_parts)
    return getattr(response, "text", "")


def request_content(job_description: str) -> dict:
    experience = MASTER_EXPERIENCE.read_text(encoding="utf-8")
    prompt = f"""
{PROMPT.read_text(encoding="utf-8")}

Return only valid JSON with this exact structure:
{{
  "summary": "string",
  "skills": {{
    "languages": ["string"],
    "frameworks_libraries": ["string"],
    "tools_platforms": ["string"],
    "concepts": ["string"]
  }},
  "experience": {{
    "oracle_software_engineer": ["6 bullets"],
    "oracle_project_intern": ["1 bullet"],
    "distributed_rate_limiter": ["2 bullets"],
    "expense_splitter": ["2 bullets"]
  }}
}}

The output must contain exactly 11 bullets: 6, 1, 2, and 2 in the listed sections.
Use exact JD terminology when supported by the master experience, but never invent facts.

MASTER EXPERIENCE:
{experience}

JOB DESCRIPTION:
{job_description}
""".strip()

    print("\n===== PROMPT SENT TO GEMINI =====\n")
    print(prompt)
    print("\n===== END PROMPT =====\n")

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    raw_response = response_text(response)
    print("\n===== RAW GEMINI RESPONSE =====\n")
    print(raw_response)
    print("\n===== END GEMINI RESPONSE =====\n")

    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise ValueError(f"Gemini returned invalid JSON: {error}") from error

    experience_data = data.get("experience") if isinstance(data, dict) else None
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("Gemini response must contain a non-empty summary")
    expected_skill_categories = {
        "languages",
        "frameworks_libraries",
        "tools_platforms",
        "concepts",
    }
    skills_data = data.get("skills")
    if not isinstance(skills_data, dict) or set(skills_data) != expected_skill_categories:
        raise ValueError("Gemini response must contain all four skill categories")
    for category, skills in skills_data.items():
        if not isinstance(skills, list) or not all(
            isinstance(skill, str) and skill.strip() for skill in skills
        ):
            raise ValueError(f"Gemini skills category '{category}' must contain strings")
    if set(experience_data or {}) != set(EXPECTED_BULLET_COUNTS):
        raise ValueError("Gemini returned unexpected experience sections")
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


def generate_resume(job_description: str, output_dir: Path = ROOT, keep_tex: bool = False) -> Path:
    load_dotenv(ROOT / ".env")
    if not job_description.strip():
        raise ValueError("job description cannot be empty")
    if "GEMINI_API_KEY" not in os.environ or not os.environ["GEMINI_API_KEY"]:
        raise ValueError("set GEMINI_API_KEY in .env before running")

    try:
        data = request_content(job_description)
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
        print(f"Gemini JSON saved: {response_json}")

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
                print(f"Gemini bullets inserted: {len(bullets)}")
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
