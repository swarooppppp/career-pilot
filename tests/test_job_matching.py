import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import job_matching
from app.services.job_matching import (
    build_candidate_profile,
    calculate_score,
    retrieve_evidence,
)


MASTER_EXPERIENCE = """
## Candidate
- Name: Test Candidate
- Location: Hyderabad, India

## Software Engineer
- Employer: Example Corp
- Built Java and Spring Boot REST services.
- Designed a distributed system using Redis under concurrent load.

## Projects
### Example Project
- Built a Java service using Redis.

## Education
- Bachelor of Technology in Computer Science

## Skills explicitly present in the resume
- Java, Python, and Redis.

## Facts requiring confirmation or enrichment
- An unverified Kubernetes certification.
""".strip()


class JobMatchingTests(unittest.TestCase):
    def setUp(self):
        self.profile = build_candidate_profile(MASTER_EXPERIENCE)

    def test_profile_preserves_searchable_evidence(self):
        self.assertEqual(self.profile["candidate"]["name"], "Test Candidate")
        self.assertIn("java", self.profile["skills"])
        self.assertTrue(self.profile["roles"])
        self.assertTrue(self.profile["education"])
        self.assertGreaterEqual(len(self.profile["evidence_chunks"]), 3)

    def test_profile_classifies_evidence_sources_from_markdown_structure(self):
        sources = {chunk["title"]: chunk["source_type"] for chunk in self.profile["evidence_chunks"]}

        self.assertEqual(sources["Software Engineer"], "work_experience")
        self.assertEqual(sources["Example Project"], "project")
        self.assertEqual(sources["Education"], "education")
        self.assertEqual(sources["Skills explicitly present in the resume"], "skills_summary")
        self.assertEqual(sources["Facts requiring confirmation or enrichment"], "unverified")

    def test_profile_adds_citeable_verified_experience_from_dated_work(self):
        profile = build_candidate_profile("""
## Software Engineer
- Dates: June 2024 — Present
- Built Java services.

## Project Intern
- Dates: May 2023 — July 2023
- Built an internal tool.
""".strip())

        self.assertIsInstance(profile["years_of_experience"]["non_internship_professional"], float)
        evidence = next(item for item in profile["evidence_chunks"] if item["title"] == "Verified professional experience")
        self.assertEqual(evidence["source_type"], "work_experience")
        prompt = job_matching.build_match_profile_context(profile)
        self.assertIn("non_internship_professional", prompt)

    def test_retrieval_finds_related_experience(self):
        evidence = retrieve_evidence("Build REST APIs with Java and Spring Boot", self.profile)
        self.assertTrue(evidence)
        self.assertIn("Spring Boot", evidence[0]["text"])

    def test_postgresql_and_postgres_are_bidirectional_aliases(self):
        postgres_profile = build_candidate_profile(
            """
## Software Engineer
- Tuned Postgres queries for a high-traffic service.
""".strip()
        )
        postgresql_profile = build_candidate_profile(
            """
## Software Engineer
- Tuned PostgreSQL queries for a high-traffic service.
""".strip()
        )

        self.assertTrue(retrieve_evidence("PostgreSQL database experience", postgres_profile))
        self.assertTrue(retrieve_evidence("Postgres database experience", postgresql_profile))

    def test_aliases_do_not_match_inside_unrelated_words(self):
        self.assertFalse(job_matching._contains_alias("interest in backend work", "rest"))

    def test_no_evidence_receives_no_credit(self):
        score = calculate_score(
            [
                {
                    "category": "required_skill",
                    "importance": 10,
                    "match_strength": 1.0,
                },
                {
                    "category": "required_skill",
                    "importance": 10,
                    "match_strength": 0.0,
                },
            ]
        )
        self.assertEqual(score, 50)

    def test_score_uses_evidence_source_factor(self):
        work_score = calculate_score([{"category": "required_skill", "importance": 10, "match_strength": 1.0}])
        project_score = calculate_score([{"category": "required_skill", "importance": 10, "match_strength": 0.85}])
        education_score = calculate_score([{"category": "required_skill", "importance": 10, "match_strength": 0.65}])

        self.assertEqual(work_score, 100)
        self.assertEqual(project_score, 85)
        self.assertEqual(education_score, 65)

    def test_batch_response_scores_deterministically(self):
        requirements = [
            {"id": "req-1", "text": "Build Java APIs", "category": "required_skill", "importance": 10,
             "is_genuine_hard_constraint": False, "support_level": "direct",
             "evidence_ids": ["evidence-2"], "explanation": "Java API evidence exists."},
            {"id": "req-2", "text": "Kubernetes experience", "category": "preferred_skill", "importance": 4,
             "is_genuine_hard_constraint": False, "support_level": "no_evidence",
             "evidence_ids": [], "explanation": "Not mentioned in the source."},
        ]
        with patch.object(job_matching, "candidate_profile", return_value=self.profile):
            first = job_matching.build_analysis_result("A role building Java APIs with Kubernetes preferred.", {
                "requirements": requirements, "summary": "Good backend match.", "recommendations": [],
            })

        self.assertEqual(first["overall_score"], 86)
        self.assertFalse(first["cached"])

    def test_positive_support_without_retrieved_citation_is_downgraded(self):
        response = {
            "requirements": [{
                "id": "req-1", "support_level": "direct",
                "text": "Java experience", "category": "required_skill", "importance": 10,
                "is_genuine_hard_constraint": False,
                "evidence_ids": ["evidence-unknown"],
                "explanation": "Claims support without supplied evidence.",
            }],
            "summary": "", "recommendations": [],
        }
        evaluations, _, _ = job_matching.validate_match_response(response, self.profile)

        self.assertEqual(evaluations[0]["support_level"], "no_evidence")
        self.assertEqual(evaluations[0]["support_factor"], 0.0)
        self.assertEqual(evaluations[0]["evidence_ids"], [])

    def test_duplicate_requirement_ids_fail_one_call_validation(self):
        response = {
            "requirements": [
                {"id": "req-1", "text": "Java", "category": "required_skill", "importance": 5,
                 "support_level": "no_evidence", "evidence_ids": []},
                {"id": "req-1", "text": "Python", "category": "required_skill", "importance": 5,
                 "support_level": "no_evidence", "evidence_ids": []},
            ]
        }
        with self.assertRaisesRegex(ValueError, "invalid job requirement"):
            job_matching.validate_match_response(response, self.profile)

    def test_prompt_limits_scored_requirements_and_excludes_hiring_boilerplate(self):
        prompt = job_matching.build_match_prompt("Build Java services.", self.profile)

        self.assertIn("Return 4 to 10 scored requirements", prompt)
        self.assertIn("employer background/security checks", prompt)
        self.assertIn("generic soft skills", prompt)
        self.assertEqual(job_matching.MATCH_RESPONSE_SCHEMA["properties"]["requirements"]["maxItems"], 10)

    def test_candidate_material_precedes_the_job_description_for_cache_reuse(self):
        prompt = job_matching.build_match_prompt("Build Java services.", self.profile)

        self.assertLess(prompt.index("CANDIDATE PROFILE:"), prompt.index("JOB DESCRIPTION"))
        self.assertLess(prompt.index("EVIDENCE CHUNKS:"), prompt.index("JOB DESCRIPTION"))

    def test_old_schema_cache_key_is_not_reused(self):
        description = "A sufficiently detailed Java role description for cache testing."
        old_cache_key = job_matching._sha256(self.profile["source_hash"] + description)
        new_cache_key = job_matching._sha256(job_matching.MATCHING_SCHEMA_VERSION + job_matching.MATCHING_PROMPT_VERSION + job_matching.MODEL_NAME + self.profile["source_hash"] + description)
        self.assertNotEqual(old_cache_key, new_cache_key)

    def test_analysis_applies_the_strongest_valid_evidence_source(self):
        project = next(chunk for chunk in self.profile["evidence_chunks"] if chunk["source_type"] == "project")
        evaluations = [{
            "id": "req-1", "text": "Java service", "category": "required_skill",
            "importance": 10, "is_genuine_hard_constraint": False,
            "support_level": "direct", "support_factor": 1.0,
            "evidence_ids": [project["id"]], "explanation": "Project evidence.",
        }]
        with patch.object(job_matching, "candidate_profile", return_value=self.profile):
            result = job_matching.build_analysis_result("A sufficiently detailed Java service role description.", {
                "requirements": evaluations, "summary": "", "recommendations": [],
            })

        requirement = result["requirements"][0]
        self.assertEqual(result["overall_score"], 85)
        self.assertEqual(requirement["evidence_source_factor"], 0.85)
        self.assertEqual(requirement["evidence"][0]["source_type"], "project")


if __name__ == "__main__":
    unittest.main()
