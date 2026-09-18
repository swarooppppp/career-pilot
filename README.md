# Career Pilot

Career Pilot analyses a job description against a candidate's complete master
experience, then can generate a tailored resume PDF.

## Local setup

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 run_local.py
```

Set `GEMINI_API_KEY` in `.env`, then open <http://127.0.0.1:8000>.

This default local mode uses SQLite and does not need Docker, PostgreSQL, or
Kafka. It still processes matching asynchronously: the web application queues
the work and `local_worker.py` performs it in a separate process.

To fetch/import configured sources before opening the app, use one command:

```bash
python3 run_local.py --sync-jobs
```

Set `GOOGLE_CAREERS_URL` in `.env` to your saved Google Careers search URL.
Set `FETCH_MICROSOFT="true"` to include Microsoft with the configured query and
location. Microsoft requests are spaced one second apart by default and retry
HTTP 429 rate limits up to four times, using `Retry-After` when Microsoft sends
it. Configure `MICROSOFT_DELAY`, `MICROSOFT_MAX_RETRIES`, and
`MICROSOFT_BACKOFF_SECONDS` in `.env` if needed. Existing portal job IDs are
deduplicated during every sync.

## Cloud / Kafka mode

On the other machine, after Docker Desktop is installed:

```bash
docker compose up -d
cp .env.cloud.example .env
python3 -m pip install -r requirements.txt
python3 run.py             # terminal 1: web application
python3 worker.py          # terminal 2: Kafka match worker
python3 outbox_relay.py    # terminal 3: retries unpublished Kafka events
```

Cloud mode uses PostgreSQL for durable state and Kafka for asynchronous events.

## Match analysis design

The match feature is intentionally recall-first. It does not reject a role
because a single keyword is missing from the resume.

1. Gemini extracts weighted requirements from the job description.
2. Python retrieves relevant evidence passages from `data/master_experience.md`.
3. Gemini classifies each requirement using that evidence only.
4. Python calculates the final percentage from fixed category weights and match
   strengths.
5. The result is cached by the job description and master-experience hash.

This is a small retrieval-augmented generation (RAG) workflow: only evidence
passages relevant to each requirement are passed to the evaluator. If installed,
LangChain's `RecursiveCharacterTextSplitter` splits longer master-experience
sections before retrieval. The app still has a built-in fallback so it remains
usable while a VPN blocks package installation.

LangGraph orchestrates the actual stored-job lifecycle:

```text
pending job → eligibility/state check → Gemini evaluation → persist match
                                              └→ persist retryable failure
```

LangGraph controls job-state transitions in both modes. In cloud mode,
PostgreSQL is the durable record and Kafka keeps Gemini work off the web request
path. A database transaction also creates an outbox event, so work remains
recorded if Kafka is temporarily unavailable.

The result distinguishes direct matches, transferable experience, uncertainty,
and genuine hard-constraint gaps. It uses a 30-second Gemini timeout.

`data/master_experience.md` is the source of truth. Update it as your career
grows; cached analyses automatically become invalid when it changes.

## API

`POST /api/match/analyze`

```json
{"job_description": "Paste a full job description here."}
```

`POST /api/resume/generate` generates the tailored PDF and returns a download
URL. Email is optional and uses the SMTP values in `.env`.

## Job pipeline

Portal scripts write their raw JSON independently. Import their output into the
shared local dashboard with a 1-year experience buffer:

```bash
python3 ingest_jobs.py google_jobs.json --source google
python3 ingest_jobs.py microsoft_jobs.json --source microsoft
```

The importer reads `CANDIDATE_YEARS_EXPERIENCE` from `.env` (default `2`). A
job requiring 3+ years is therefore eligible; a job requiring 4+ years is not.
Jobs are deduplicated by portal and portal job ID. Clicking **Analyse pending
jobs** queues Kafka work and returns immediately. The worker stores final
results in PostgreSQL and an unchanged completed job is never sent to Gemini
again. The dashboard keeps it until you save, apply, dismiss, or generate a
resume for it.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```
