"""Orchestrates the durable job lifecycle.

PostgreSQL stores the source of truth. LangGraph coordinates the work around one
job: decide whether it is eligible to run, call the match evaluator, and save
either the completed analysis or a retryable failure.
"""

from __future__ import annotations

import time
import os
import random
import logging
from typing import Any, TypedDict

from app.services.job_matching import analyse_job
from app.services.job_store import save_analysis, save_analysis_error

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph

    JOB_GRAPH_AVAILABLE = True
except ImportError:
    JOB_GRAPH_AVAILABLE = False


class JobState(TypedDict, total=False):
    job: dict[str, Any]
    next_step: str
    analysis: dict[str, Any]
    error: str


def check_job(state: JobState) -> JobState:
    """Guard against processing jobs which are already terminal or ineligible."""
    job = state["job"]
    is_ready = (
        job["experience_eligible"]
        and job["analysis_status"] == "processing"
        and job["user_status"] == "new"
    )
    next_step = "analyse" if is_ready else "skip"
    logger.info("Job %s state check: %s", job["id"], next_step)
    return {"next_step": next_step}


def evaluate_match(state: JobState) -> JobState:
    last_error: Exception | None = None
    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
    for attempt in range(max_retries + 1):
        try:
            logger.info("Job %s Gemini analysis attempt %s/%s", state["job"]["id"], attempt + 1, max_retries + 1)
            return {
                "analysis": analyse_job(state["job"]["job_description"]),
                "next_step": "persist",
            }
        except Exception as error:
            last_error = error
            is_transient = "429" in str(error) or "503" in str(error)
            if not is_transient or attempt == max_retries:
                logger.exception("Job %s analysis failed", state["job"]["id"])
                break
            # Jitter prevents several parallel workers retrying in lockstep.
            wait_seconds = (2 ** attempt) + random.uniform(0, 1)
            logger.warning("Job %s received transient Gemini error; retrying in %.2fs", state["job"]["id"], wait_seconds)
            time.sleep(wait_seconds)
    return {"error": str(last_error), "next_step": "failed"}


def persist_match(state: JobState) -> JobState:
    logger.info("Persisting completed analysis for job %s", state["job"]["id"])
    save_analysis(state["job"]["id"], state["analysis"])
    return {}


def persist_failure(state: JobState) -> JobState:
    logger.error("Persisting failed analysis for job %s: %s", state["job"]["id"], state["error"])
    save_analysis_error(state["job"]["id"], RuntimeError(state["error"]))
    return {}


def route_after_check(state: JobState) -> str:
    return state["next_step"]


def route_after_evaluation(state: JobState) -> str:
    return state["next_step"]


def build_job_graph() -> Any:
    """Build the LangGraph state machine when the optional dependency is installed."""
    if not JOB_GRAPH_AVAILABLE:
        return None
    graph = StateGraph(JobState)
    graph.add_node("check", check_job)
    graph.add_node("analyse", evaluate_match)
    graph.add_node("persist", persist_match)
    graph.add_node("failed", persist_failure)
    graph.add_edge(START, "check")
    graph.add_conditional_edges("check", route_after_check, {"analyse": "analyse", "skip": END})
    graph.add_conditional_edges(
        "analyse", route_after_evaluation, {"persist": "persist", "failed": "failed"}
    )
    graph.add_edge("persist", END)
    graph.add_edge("failed", END)
    return graph.compile()


def process_job(job: dict[str, Any]) -> str:
    """Run one job through LangGraph, or its equivalent local fallback."""
    if JOB_GRAPH_AVAILABLE:
        result = build_job_graph().invoke({"job": job})
        if result.get("error"):
            return "failed"
        return "processed" if result.get("analysis") else "skipped"

    # The fallback preserves the exact state transitions while a VPN prevents
    # installing LangGraph. It is intentionally small and mirrors the graph.
    state = check_job({"job": job})
    if state["next_step"] == "skip":
        return "skipped"
    state = {"job": job, **evaluate_match({"job": job})}
    if state["next_step"] == "failed":
        persist_failure(state)
        return "failed"
    persist_match(state)
    return "processed"
