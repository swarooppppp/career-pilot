#!/usr/bin/env python3
"""Run the Phase 1 JD-analysis experiment with the local master repository."""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path

from google import genai
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
MASTER_EXPERIENCE = ROOT / "data" / "master_experience.md"
JD_ANALYZER_PROMPT = ROOT / "prompts" / "jd_analyzer.md"

# SAMPLE_JD = """
# Backend Software Engineer

# We are hiring a backend engineer to design and build scalable Java services.
# The role requires Java, Spring Boot, REST APIs, PostgreSQL, Kafka, Redis,
# Docker, distributed systems, automated testing, and CI/CD experience.
# Responsibilities include designing stateless microservices, improving API
# performance, debugging production issues, and collaborating with frontend and
# product teams.
# """.strip()

SAMPLE_JD = """
Key job responsibilities

 Deliver high-quality platform solutions supporting diverse customer and merchant use cases for Amazon Pay
 Develop and enhance web-based applications and web services that enable third-party merchants to integrate Amazon Pay
 Design and build large-scale, distributed systems to handle high-volume transactions in a 24/7 environment
 Contribute to the architecture, design, and evolution of new and existing systems focusing on reliability, scalability, and performance
 
Basic Qualifications

 2+ years of non-internship professional software development experience
 Experience programming with at least one software programming language
 Knowledge of professional software engineering & best practices for full software development life cycle, including coding standards, software architectures, code reviews, source control management, continuous deployments, testing, and operational excellence
 Experience contributing to the architecture and design (architecture, design patterns, reliability and scaling) of new and current systems

Preferred Qualifications

 Bachelor's degree in computer science or equivalent
 Experience building complex software systems that have been successfully delivered to customers
 Experience programming with at least one modern language such as Java, C++, or C# including object-oriented design 
""".strip()

OUTPUT_SCHEMA = """
{
  "summary": "A concise, truthful professional summary tailored to the JD.",
  "skills": {
    "languages": ["skill 1"],
    "frameworks_libraries": ["skill 2"],
    "tools_platforms": ["skill 3"],
    "concepts": ["skill 4"]
  },
  "experience": {
    "oracle_software_engineer": [
      "Exactly 6 JD-tailored bullets supported by the master experience."
    ],
    "oracle_project_intern": [
      "Exactly 1 JD-tailored bullet supported by the master experience."
    ],
    "distributed_rate_limiter": [
      "Exactly 2 JD-tailored bullets supported by the master experience."
    ],
    "expense_splitter": [
      "Exactly 2 JD-tailored bullets supported by the master experience."
    ]
  }
}
""".strip()

EXPECTED_BULLET_COUNTS = {
    "oracle_software_engineer": 6,
    "oracle_project_intern": 1,
    "distributed_rate_limiter": 2,
    "expense_splitter": 2,
}


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: set GEMINI_API_KEY before running this experiment.", file=sys.stderr)
        return 1

    system_prompt = JD_ANALYZER_PROMPT.read_text(encoding="utf-8")
    experience = MASTER_EXPERIENCE.read_text(encoding="utf-8")
    prompt = f"""
You are generating structured resume content for a fixed LaTeX template.

Return only valid JSON matching this exact shape:
{OUTPUT_SCHEMA}

Rules:
- Use only facts supported by MASTER EXPERIENCE.
- Never invent technologies, metrics, responsibilities, dates, employers, or achievements.
- Optimize for truthful ATS alignment: when the master experience supports a JD requirement, use the JD's exact terminology for skills, responsibilities, and domains where natural.
- Reframe verified accomplishments to emphasize JD-relevant work without changing what was actually done.
- Prefer an exact JD term over a weaker synonym when both describe the same verified experience.
- Include supported skills in the skills list and relevant bullets when natural.
- Preserve truthful metrics; never create, inflate, or move a metric between experiences.
- Never add a keyword only because it appears in the JD, and avoid awkward keyword stuffing.
- Preserve the resume structure: return exactly 11 experience bullets in total.
- Use exactly these section counts: oracle_software_engineer=6, oracle_project_intern=1, distributed_rate_limiter=2, expense_splitter=2.
- Rewrite or shorten bullets within their existing section, but do not add or remove bullets.
- Each experience key must be a stable lowercase identifier, such as "oracle" or "distributed_rate_limiter".
- Each bullet must be a complete, concise resume bullet without a leading bullet character.
- Include only experience entries with relevant, supported bullets.
- Do not include LaTeX commands or Markdown.

{system_prompt}

For context, the candidate's verified experience repository is below. Do not
assume a requirement is satisfied merely because it appears here; this run is
only analyzing the job description.

MASTER EXPERIENCE:
{experience}

JOB DESCRIPTION:
{SAMPLE_JD}
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
    except Exception as error:
        print(f"Gemini request failed: {error}", file=sys.stderr)
        return 1

    try:
        data = json.loads(response.text)
        if not isinstance(data, dict) or not isinstance(data.get("experience"), dict):
            raise ValueError("response must contain an 'experience' object")
        experience_data = data["experience"]
        if set(experience_data) != set(EXPECTED_BULLET_COUNTS):
            raise ValueError(
                "experience must contain exactly these sections: "
                + ", ".join(EXPECTED_BULLET_COUNTS)
            )
        for heading, bullets in data["experience"].items():
            if not isinstance(heading, str) or not isinstance(bullets, list):
                raise ValueError("experience must map headings to bullet lists")
            expected_count = EXPECTED_BULLET_COUNTS[heading]
            if len(bullets) != expected_count:
                raise ValueError(
                    f"{heading} must contain exactly {expected_count} bullets; "
                    f"received {len(bullets)}"
                )
            if not all(isinstance(bullet, str) and bullet.strip() for bullet in bullets):
                raise ValueError("every experience bullet must be a non-empty string")
    except json.JSONDecodeError as error:
        print(f"Gemini returned invalid JSON: {error}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Invalid Gemini response: {error}", file=sys.stderr)
        return 1

    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
