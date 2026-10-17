# Career Pilot

Career Pilot analyses a job description against a candidate's complete master
experience, then can generate a tailored resume PDF.

## Local setup

## Render deployment

`render.yaml` defines a web service, managed Postgres database, and a LinkedIn ingestion cron job that runs every six hours (00:00, 06:00, 12:00, and 18:00 UTC). Create a Render Blueprint from this repository, then set `APP_PASSWORD`, `OPENAI_API_KEY`, and `LINKEDIN_JOBS_URL` for both services. Render supplies `DATABASE_URL` and `SESSION_SECRET`.

The cron job runs `python run_ingestion.py` and exits after one fetch/import cycle. It uses eight LinkedIn 429 retries with a 960-second maximum delay.

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 run_local.py
```

Set `OPENAI_API_KEY` in `.env`, then open <http://127.0.0.1:8000>. Resume generation retains its separate Gemini configuration.

This default local mode uses SQLite and does not need Docker, PostgreSQL, or
Kafka. Job matching is submitted asynchronously to the OpenAI Batch API using
GPT-5.6 Luna, then collected when the batch completes.

The app polls active batches every five minutes and submits eligible pending jobs
immediately at startup and then every hour by default. Configure `OPENAI_BATCH_POLL_INTERVAL_MINUTES`,
`OPENAI_BATCH_SUBMIT_INTERVAL_MINUTES`, and `OPENAI_BATCH_SUBMIT_LIMIT` in
`.env`.

To fetch/import configured sources before opening the app, use one command:

```bash
python3 run_local.py --sync-jobs
```

Set `GOOGLE_CAREERS_URL` in `.env` to your saved Google Careers search URL.
Set `FETCH_AMAZON="true"` and `AMAZON_JOBS_URL` to include Amazon's saved
Amazon Jobs search URL. Its public JSON search API returns full job details in
each result; the default retrieves ten 10-result pages (up to 100 jobs).
Set `FETCH_SALESFORCE="true"` and `SALESFORCE_JOBS_URL` to include Salesforce.
Its careers page uses two public static job datasets; the adapter merges them,
applies the search URL's filters locally, and writes up to 50 matching jobs.
Set `FETCH_INTUIT="true"` and `INTUIT_JOBS_URL` to include Intuit. The adapter
uses its public paginated search and job-detail pages, and applies an additional
deterministic `INTUIT_COUNTRY="India"` check before fetching job descriptions.
Set `FETCH_ATLASSIAN="true"` and `ATLASSIAN_JOBS_URL` to include Atlassian.
Its public listings API is fetched once, then team, location, and search terms
from the careers URL are applied locally before importing up to 50 jobs.
Set `FETCH_APPLE="true"` and `APPLE_JOBS_URL` to include Apple. Its public
search and job-detail hydration data are used to retrieve complete descriptions
for up to 50 jobs from the India-filtered URL.
Set `FETCH_META="true"` and `META_JOBS_URL` to include Meta. It uses an
isolated Playwright browser session because Meta search relies on ephemeral
browser tokens. A valid zero-result filter writes an empty snapshot rather than
failing the sync.
Set `FETCH_DATABRICKS="true"` and `DATABRICKS_JOBS_URL` to include Databricks.
Its public Greenhouse board returns complete job descriptions in one request;
the adapter applies the department, location, and search filters from the URL.
Set `FETCH_ADOBE="true"` and `ADOBE_JOBS_URL` to include Adobe. Its public
server-rendered category/search data is followed by public job-detail pages so
each imported role has a complete description. Configure `ADOBE_MAX_JOBS` and
`ADOBE_DELAY` to control the number of detail requests and their pacing.
Set `FETCH_UBER="true"` and `UBER_JOBS_URL` to include Uber's public careers
search. The adapter opens a temporary Playwright browser context and retrieves
up to ten API pages (50 normalized jobs by default), including each job's full
description and canonical detail URL. Install Chromium once after installing
Python dependencies:

```bash
python3 -m playwright install chromium
```

The browser context is isolated and does not use your existing browser cookies.
If Uber presents a verification challenge, retry the script manually with
`--headed` so the browser is visible; the normal sync reports that source as a
failure rather than importing challenge HTML.
`UBER_HEADED="true"` is the local-sync default because Uber commonly blocks
headless Chromium. It opens a browser window for the fetch; set it to `false`
only for a display-less/cloud environment (where Uber may be blocked again).
Set `FETCH_MICROSOFT="true"` to include Microsoft with the configured query and
location. Microsoft requests are spaced one second apart by default and retry
HTTP 429 rate limits up to four times, using `Retry-After` when Microsoft sends
it. Configure `MICROSOFT_DELAY`, `MICROSOFT_MAX_RETRIES`, and
`MICROSOFT_BACKOFF_SECONDS` in `.env` if needed. Existing portal job IDs are
deduplicated during every sync.

The initial configuration fetches at most 50 jobs from Google and Microsoft,
and 100 from Amazon. Google requests three 20-job pages and keeps the first 50
date-sorted jobs; Microsoft requests five 10-job pages; Amazon requests ten
10-job pages. Change the portal-specific `*_MAX_JOBS` settings when you want
broader coverage.

## Cloud / Kafka mode

On the other machine, after Docker Desktop is installed:

```bash
docker compose up -d
cp .env.cloud.example .env
python3 -m pip install -r requirements.txt
python3 run.py             # terminal 1: web application
python3 worker.py          # terminals 2–5: four identical Kafka match workers
python3 outbox_relay.py    # terminal 6: retries unpublished Kafka events
```

Cloud mode uses PostgreSQL for durable state and Kafka for asynchronous events.
The job topic has eight partitions; run four workers in the same consumer group.
PostgreSQL shares the configured Gemini request limit between worker replicas.

## Match analysis design

The match feature is intentionally recall-first. It does not reject a role
because a single keyword is missing from the resume.

1. GPT-5.6 Luna receives the job description plus the complete structured master
   profile and source-labelled evidence chunks in one call.
2. It returns requirements, evidence IDs, and a support level for each.
3. Python validates citations and calculates the final percentage from fixed
   category, support, and evidence-source factors.
4. The result is cached by the job description, master experience, model, and
   prompt version.

Work-experience citations receive full credit, projects receive 85%, and
education/skills-summary citations receive 65%. Unknown or invalid citations
receive no credit. LangChain splitting and lexical retrieval remain available
for a future large-profile retrieval path, but are not an LLM gate now.

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
shared local dashboard with a two-year experience buffer:

```bash
python3 ingest_jobs.py google_jobs.json --source google
python3 ingest_jobs.py microsoft_jobs.json --source microsoft
```

The importer calculates qualifying non-internship professional experience from
dated top-level roles in `data/master_experience.md` and uses that value for the
experience filter. Accepted month formats include `June 2024`, `Jun 2024`,
`06/2024`, and `2024-06`; internships are excluded. `CANDIDATE_YEARS_EXPERIENCE`
is used only if the resume has no parseable qualifying role dates. A job with no
explicit experience requirement is eligible. Where requirements are present,
the highest explicit years value must be at most candidate YOE + 2.
Jobs are deduplicated by portal and portal job ID. Clicking **Analyse pending
jobs** queues Kafka work and returns immediately. The worker stores final
results in PostgreSQL and an unchanged completed job is never sent to Gemini
again. The dashboard keeps it until you save, apply, dismiss, or generate a
resume for it.

For a large backlog, submit a deliberate OpenAI Batch rather than processing jobs
automatically during import:

```bash
python3 batch_jobs.py submit --limit 500
python3 batch_jobs.py poll
```

Configured portal fetches run concurrently up to `JOB_FETCH_CONCURRENCY`
(default `4`), while each portal script retains its own request pacing.
Successful snapshots import serially so SQLite filtering and de-duplication
remain safe. If one source fails, successful sources are still imported and the
sync exits with a failure summary.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```
