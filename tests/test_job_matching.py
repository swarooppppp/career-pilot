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

    def test_analysis_scores_and_caches_without_repeating_llm_work(self):
        requirements = [
            {
                "id": "req-1",
                "text": "Build Java APIs",
                "category": "required_skill",
                "importance": 10,
                "is_genuine_hard_constraint": False,
            },
            {
                "id": "req-2",
                "text": "Kubernetes experience",
                "category": "preferred_skill",
                "importance": 4,
                "is_genuine_hard_constraint": False,
            },
        ]
        evaluations = [
            {**requirements[0], "support_level": "direct", "support_factor": 1.0,
             "evidence_ids": ["evidence-2"], "explanation": "Java API evidence exists."},
            {**requirements[1], "support_level": "no_evidence", "support_factor": 0.0,
             "evidence_ids": [], "explanation": "Not mentioned in the source."},
        ]
        with TemporaryDirectory() as directory, patch.object(job_matching, "CACHE_DIR", Path(directory)), \
                patch.object(job_matching, "candidate_profile", return_value=self.profile), \
                patch.object(job_matching, "extract_requirements", return_value=requirements) as extract, \
                patch.object(job_matching, "evaluate_requirements", return_value=(evaluations, "Good backend match.", [])):
            first = job_matching.analyse_job("A role building Java APIs with Kubernetes preferred.")
            second = job_matching.analyse_job("A role building Java APIs with Kubernetes preferred.")

        self.assertEqual(first["overall_score"], 86)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(extract.call_count, 1)

    def test_positive_support_without_retrieved_citation_is_downgraded(self):
        requirements = [{
            "id": "req-1", "text": "Java experience", "category": "required_skill",
            "importance": 10, "is_genuine_hard_constraint": False,
        }]
        response = {
            "evaluations": [{
                "id": "req-1", "support_level": "direct",
                "evidence_ids": ["evidence-1", "evidence-unknown"],
                "explanation": "Claims support without supplied evidence.",
            }],
            "summary": "", "recommendations": [],
        }
        with patch.object(job_matching, "_json_response", return_value=response):
            evaluations, _, _ = job_matching.evaluate_requirements(requirements, self.profile)

        self.assertEqual(evaluations[0]["support_level"], "no_evidence")
        self.assertEqual(evaluations[0]["support_factor"], 0.0)
        self.assertEqual(evaluations[0]["evidence_ids"], [])

    def test_old_schema_cache_key_is_not_reused(self):
        requirements = [{
            "id": "req-1", "text": "Java experience", "category": "required_skill",
            "importance": 10, "is_genuine_hard_constraint": False,
        }]
        evaluations = [{
            **requirements[0], "support_level": "no_evidence", "support_factor": 0.0,
            "evidence_ids": [], "explanation": "",
        }]
        description = "A sufficiently detailed Java role description for cache testing."
        old_cache_key = job_matching._sha256(self.profile["source_hash"] + description)
        with TemporaryDirectory() as directory, patch.object(job_matching, "CACHE_DIR", Path(directory)), \
                patch.object(job_matching, "candidate_profile", return_value=self.profile), \
                patch.object(job_matching, "extract_requirements", return_value=requirements) as extract, \
                patch.object(job_matching, "evaluate_requirements", return_value=(evaluations, "", [])):
            Path(directory, f"{old_cache_key}.json").write_text('{"cached": "old"}', encoding="utf-8")
            result = job_matching.analyse_job(description)

        self.assertFalse(result["cached"])
        self.assertEqual(extract.call_count, 1)

    def test_analysis_applies_the_strongest_valid_evidence_source(self):
        requirements = [{
            "id": "req-1", "text": "Java service", "category": "required_skill",
            "importance": 10, "is_genuine_hard_constraint": False,
        }]
        project = next(chunk for chunk in self.profile["evidence_chunks"] if chunk["source_type"] == "project")
        evaluations = [{
            **requirements[0], "support_level": "direct", "support_factor": 1.0,
            "evidence_ids": [project["id"]], "explanation": "Project evidence.",
        }]
        with TemporaryDirectory() as directory, patch.object(job_matching, "CACHE_DIR", Path(directory)), \
                patch.object(job_matching, "candidate_profile", return_value=self.profile), \
                patch.object(job_matching, "extract_requirements", return_value=requirements), \
                patch.object(job_matching, "evaluate_requirements", return_value=(evaluations, "", [])):
            result = job_matching.analyse_job("A sufficiently detailed Java service role description.")

        requirement = result["requirements"][0]
        self.assertEqual(result["overall_score"], 85)
        self.assertEqual(requirement["evidence_source_factor"], 0.85)
        self.assertEqual(requirement["evidence"][0]["source_type"], "project")


if __name__ == "__main__":
    unittest.main()
