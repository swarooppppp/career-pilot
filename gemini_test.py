#!/usr/bin/env python3
"""Send a sample job description to Gemini and print the analysis."""

from __future__ import annotations

import os
import sys

from google import genai


SAMPLE_JOB_DESCRIPTION = """
We are looking for a Backend Software Engineer to build reliable services for
our e-commerce platform. The ideal candidate has experience with Python,
FastAPI, PostgreSQL, REST APIs, Docker, AWS, automated testing, and CI/CD.

Responsibilities include designing backend APIs, improving service
performance, writing maintainable code, debugging production issues, and
collaborating with frontend and product teams.
""".strip()


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "Error: GEMINI_API_KEY is not set. Set it before running this script, "
            "for example: export GEMINI_API_KEY='your-key'",
            file=sys.stderr,
        )
        return 1

    prompt = f"""
Analyze the following job description for a resume-tailoring workflow.

Return:
1. The role title
2. Five must-have technical skills
3. Five important responsibilities
4. Five useful ATS keywords

Do not invent requirements that are not present in the job description.

JOB DESCRIPTION:
{SAMPLE_JOB_DESCRIPTION}
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
        )
    except Exception as error:  # Keep this beginner-friendly test script readable.
        print(f"Gemini request failed: {error}", file=sys.stderr)
        return 1

    print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
