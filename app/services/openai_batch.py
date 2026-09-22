"""OpenAI Batch submission and result collection for job matching."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from app.services.job_matching import (
    MATCH_RESPONSE_SCHEMA,
    MATCHING_PROMPT_VERSION,
    MATCHING_SCHEMA_VERSION,
    MATCHING_DEVELOPER_INSTRUCTIONS,
    MODEL_NAME,
    build_analysis_result,
    build_match_profile_context,
    candidate_profile,
)
from app.services.job_store import (
    active_analysis_batches,
    batch_item_custom_id,
    batch_job_ids,
    record_analysis_batch,
    release_batch_jobs,
    reserve_pending_jobs_for_batch,
    save_analysis,
    save_analysis_error,
    update_analysis_batch,
)


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def _client() -> Any:
    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("set OPENAI_API_KEY in .env before submitting a match batch")
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("install dependencies with pip install -r requirements.txt") from error
    return OpenAI()


def request_line(job: dict[str, Any], batch_id: str) -> dict[str, Any]:
    profile = candidate_profile()
    profile_context = build_match_profile_context(profile)
    cache_key = f"job-match-{profile.get('source_hash', 'unknown')[:16]}-{MATCHING_PROMPT_VERSION}"
    return {
        "custom_id": batch_item_custom_id(batch_id, job["id"]), "method": "POST", "url": "/v1/responses",
        "body": {
            "model": os.getenv("OPENAI_MODEL", MODEL_NAME),
            "reasoning": {"effort": os.getenv("OPENAI_REASONING_EFFORT", "low")},
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": MATCHING_DEVELOPER_INSTRUCTIONS}]},
                {"role": "user", "content": [{
                    "type": "input_text", "text": profile_context,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }]},
                {"role": "user", "content": f"JOB DESCRIPTION (the only job-specific input):\n{job['job_description']}"},
            ],
            "text": {"format": {"type": "json_schema", "name": "job_match", "strict": True, "schema": MATCH_RESPONSE_SCHEMA}},
            "prompt_cache_key": cache_key,
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        },
    }


def _output_json(body: dict[str, Any]) -> dict[str, Any]:
    for output in body.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                return json.loads(content["text"])
    if isinstance(body.get("output_text"), str):
        return json.loads(body["output_text"])
    raise ValueError("Batch response contains no structured output text")


def submit_pending_batch(limit: int) -> dict[str, Any]:
    jobs = reserve_pending_jobs_for_batch(limit)
    if not jobs:
        return {"submitted": 0, "batch_id": None}
    client = _client()
    # The same job may be retried in a later Batch. Use one locally generated
    # identifier for the whole submission so every line can be mapped back
    # unambiguously without reusing an old OpenAI custom_id.
    batch_id = str(uuid4())
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as handle:
            temp_path = Path(handle.name)
            for job in jobs:
                handle.write(json.dumps(request_line(job, batch_id), ensure_ascii=False) + "\n")
        with temp_path.open("rb") as handle:
            input_file = client.files.create(file=handle, purpose="batch")
        provider_batch = client.batches.create(
            input_file_id=input_file.id, endpoint="/v1/responses", completion_window="24h",
            metadata={"workflow": "job_match", "schema": MATCHING_SCHEMA_VERSION, "prompt": MATCHING_PROMPT_VERSION},
        )
        record_analysis_batch(provider_batch.id, input_file.id, [job["id"] for job in jobs], batch_id=batch_id)
        logger.info("Submitted OpenAI batch %s with %s jobs", provider_batch.id, len(jobs))
        return {"submitted": len(jobs), "batch_id": batch_id, "provider_batch_id": provider_batch.id}
    except Exception as error:
        release_batch_jobs([job["id"] for job in jobs], str(error))
        raise
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def poll_openai_batches() -> dict[str, int]:
    counts = {"checked": 0, "completed": 0, "failed": 0, "jobs_completed": 0, "jobs_failed": 0}
    batches = active_analysis_batches()
    if not batches:
        logger.info("No active OpenAI analysis batches to poll")
        return counts
    client = _client()
    for stored in batches:
        counts["checked"] += 1
        remote = client.batches.retrieve(stored["provider_batch_id"])
        status = remote.status
        if status != "completed":
            update_analysis_batch(stored["id"], status, error=str(getattr(remote, "errors", None) or "") or None)
            if status in {"failed", "expired", "cancelled"}:
                counts["failed"] += 1
                for job_id in batch_job_ids(stored["id"]).values():
                    save_analysis_error(job_id, RuntimeError(f"OpenAI Batch {status}"))
            continue
        output_file_id = remote.output_file_id
        if not output_file_id:
            raise RuntimeError(f"completed batch {remote.id} has no output file")
        outputs = client.files.content(output_file_id).text.splitlines()
        job_ids = batch_job_ids(stored["id"])
        seen: set[str] = set()
        for line in outputs:
            item = json.loads(line)
            custom_id = item.get("custom_id")
            job_id = job_ids.get(custom_id)
            if not job_id:
                continue
            seen.add(custom_id)
            try:
                response = item.get("response") or {}
                if response.get("status_code") != 200:
                    raise RuntimeError(str(item.get("error") or response.get("body") or "Batch request failed"))
                from app.services.job_store import get_job
                job = get_job(job_id)
                if not job:
                    raise ValueError("job no longer exists")
                save_analysis(job_id, build_analysis_result(job["job_description"], _output_json(response["body"])))
                counts["jobs_completed"] += 1
            except Exception as error:
                save_analysis_error(job_id, error)
                counts["jobs_failed"] += 1
        for custom_id, job_id in job_ids.items():
            if custom_id not in seen:
                save_analysis_error(job_id, RuntimeError("Batch output omitted this job"))
                counts["jobs_failed"] += 1
        update_analysis_batch(stored["id"], "completed", output_file_id=output_file_id)
        counts["completed"] += 1
    return counts
