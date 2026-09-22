import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from generate_resume import _resume_context, generate_resume


TAILORED_RESPONSE = {
    "summary": "Software Engineer building scalable Java and Spring Boot services.",
    "skills": {
        "languages": ["Java", "Python", "SQL"],
        "frameworks_libraries": ["Spring Boot", "React.js"],
        "tools_platforms": ["Docker", "Kafka", "Redis"],
        "concepts": ["Distributed Systems", "REST APIs", "CI/CD"],
    },
    "experience": {
        "oracle_software_engineer": [
            "Migrated Workforce Compensation to a REST architecture for 900+ enterprise clients.",
            "Redesigned a session-based worksheet as a stateless service and reduced memory use by 40%.",
            "Implemented append-only compensation deltas to support concurrent writes without blocking.",
            "Built a Java SQL rewriter with row-level access controls across 30+ tables.",
            "Shipped AI agents adopted by 120+ client organizations within three months.",
            "Reduced LLM token usage by 75% and average latency from 15s to 5s.",
        ],
        "oracle_project_intern": [
            "Improved Oracle Digital Assistant resolution accuracy from 61% to 88% across 15+ HR use cases.",
        ],
        "distributed_rate_limiter": [
            "Built a distributed Java and Spring Boot rate limiter using Redis at 1,000 requests per second.",
            "Implemented token bucket and sliding-window controls with zero over-admission across 10,000+ requests.",
        ],
        "expense_splitter": [
            "Built an event-driven expense platform using Spring Boot, Kafka, and PostgreSQL for 5,000 users.",
            "Used Redis caching and optimistic locking to reduce reads by 60% and prevent race conditions.",
        ],
    },
}


class ResumeGenerationTests(unittest.TestCase):
    def test_structured_response_becomes_a_real_pdf(self):
        with TemporaryDirectory() as directory, patch(
            "generate_resume.request_content", return_value=TAILORED_RESPONSE
        ):
            output = generate_resume(
                "Software Engineer role requiring Java, Spring Boot, and distributed systems.",
                Path(directory),
                keep_tex=True,
            )
            generated_tex = output.with_suffix(".tex")

            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 10_000)
            self.assertTrue(generated_tex.is_file())
            source = generated_tex.read_text(encoding="utf-8")
            self.assertIn(r"\textbf{Java}", source)
            self.assertIn("900+", source)

    def test_completed_job_context_reuses_match_evidence_not_the_raw_jd(self):
        analysis = {
            "summary": "Strong backend fit.",
            "requirements": [{
                "id": "req-1", "text": "Java services", "category": "required_skill",
                "importance": 9, "support_level": "direct", "explanation": "Supported.",
                "evidence": [{
                    "id": "evidence-1", "title": "Oracle", "source_type": "work_experience",
                    "text": "Built Java REST services.",
                }],
            }],
            "recommendations": ["Emphasize Java."],
        }
        context = _resume_context("A raw JD that must not be sent again.", analysis, "Software Engineer")

        self.assertIn("JOB MATCH CONTEXT", context)
        self.assertIn("Built Java REST services.", context)
        self.assertNotIn("A raw JD that must not be sent again.", context)


if __name__ == "__main__":
    unittest.main()
