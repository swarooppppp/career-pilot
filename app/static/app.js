const form = document.querySelector("#resume-form");
const textarea = document.querySelector("#job-description");
const statusText = document.querySelector("#status");
const downloadLink = document.querySelector("#download-link");
const analyseButton = document.querySelector("#analyse-button");
const generateButton = document.querySelector("#generate-button");
const matchDetails = document.querySelector("#match-details");
const jobList = document.querySelector("#job-list");
const jobStatus = document.querySelector("#job-status");
const refreshJobsButton = document.querySelector("#refresh-jobs");
const processJobsButton = document.querySelector("#process-jobs");
const masterExperience = document.querySelector("#master-experience");
const masterStatus = document.querySelector("#master-status");
const saveMasterButton = document.querySelector("#save-master-experience");

function setBusy(button, isBusy) {
  analyseButton.disabled = isBusy;
  generateButton.disabled = isBusy;
  if (isBusy) button.disabled = true;
}

function renderItems(id, items) {
  const list = document.querySelector(id);
  list.replaceChildren();
  for (const item of items) {
    const entry = document.createElement("li");
    const explanation = item.explanation ? ` — ${item.explanation}` : "";
    const source = item.evidence?.[0]?.source_type;
    const sourceLabel = source ? ` [${source.replaceAll("_", " ")}]` : "";
    entry.textContent = `${item.text}${sourceLabel}${explanation}`;
    list.append(entry);
  }
}

function renderMatch(result) {
  document.querySelector("#match-score").textContent = `${result.overall_score}%`;
  document.querySelector("#match-summary").textContent = result.summary;
  renderItems("#strong-matches", result.strong_matches);
  renderItems("#transferable-matches", result.transferable_matches);
  renderItems("#uncertain-requirements", result.uncertain_requirements);
  renderItems("#critical-gaps", result.critical_gaps);
  renderItems("#recommendations", result.recommendations.map((text) => ({ text })));
  document.querySelector("#critical-gaps-container").hidden = !result.critical_gaps.length;
  document.querySelector("#recommendations-container").hidden = !result.recommendations.length;
  matchDetails.hidden = false;
}

async function readResult(response) {
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Request failed");
  return result;
}

function jobButton(label, callback, style = "secondary") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = style;
  button.textContent = label;
  button.addEventListener("click", callback);
  return button;
}

async function updateJobStatus(jobId, status) {
  const response = await fetch(`/api/jobs/${jobId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await readResult(response);
  await loadJobs();
}

async function generateStoredResume(jobId) {
  jobStatus.textContent = "Generating tailored resume...";
  try {
    const response = await fetch(`/api/jobs/${jobId}/generate-resume`, { method: "POST" });
    const result = await readResult(response);
    downloadLink.href = result.download_url;
    downloadLink.download = result.filename;
    downloadLink.textContent = `Download ${result.filename}`;
    downloadLink.hidden = false;
    jobStatus.textContent = "Resume generated successfully.";
    await loadJobs();
  } catch (error) {
    jobStatus.textContent = `Error: ${error.message}`;
  }
}

async function retryAnalysis(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}/retry-analysis`, { method: "POST" });
    await readResult(response);
    jobStatus.textContent = "Job marked for retry. Use Analyse pending jobs when Gemini is reachable.";
    await loadJobs();
  } catch (error) {
    jobStatus.textContent = `Error: ${error.message}`;
  }
}

function renderJobs(jobs) {
  jobList.replaceChildren();
  if (!jobs.length) {
    jobList.textContent = "No eligible jobs yet. Import a portal JSON file, then refresh.";
    return;
  }
  for (const job of jobs) {
    const card = document.createElement("article");
    card.className = "job-card";
    const title = document.createElement("h3");
    title.textContent = job.job_title;
    const meta = document.createElement("p");
    meta.className = "job-meta";
    meta.textContent = `${job.company_name} · ${job.location || "Location not specified"}`;
    const details = document.createElement("p");
    details.className = "job-meta";
    const yoe = job.minimum_years_experience === null
      ? "No explicit experience requirement"
      : `${job.minimum_years_experience}+ years required`;
    details.textContent = `${yoe} · ${job.analysis_status}`;
    card.append(title, meta, details);

    if (job.match) {
      const score = document.createElement("p");
      score.className = "job-score";
      score.textContent = `${job.match_score}% match — ${job.match.summary}`;
      card.append(score);
    } else if (job.analysis_error) {
      const error = document.createElement("p");
      error.className = "job-error";
      error.textContent = `Analysis failed: ${job.analysis_error}`;
      card.append(error);
    }

    const actions = document.createElement("div");
    actions.className = "job-actions";
    if (job.application_url) {
      const apply = document.createElement("a");
      apply.href = job.application_url;
      apply.target = "_blank";
      apply.rel = "noreferrer";
      apply.className = "secondary link-button";
      apply.textContent = "View job";
      actions.append(apply);
    }
    if (job.match) {
      actions.append(jobButton("Generate resume", () => generateStoredResume(job.id)));
    }
    if (job.analysis_status === "failed") {
      actions.append(jobButton("Retry analysis", () => retryAnalysis(job.id)));
    }
    actions.append(jobButton("Save", () => updateJobStatus(job.id, "saved")));
    actions.append(jobButton("Applied", () => updateJobStatus(job.id, "applied")));
    actions.append(jobButton("Dismiss", () => updateJobStatus(job.id, "dismissed")));
    card.append(actions);
    jobList.append(card);
  }
}

async function loadJobs() {
  try {
    const response = await fetch("/api/jobs");
    const result = await readResult(response);
    renderJobs(result.jobs);
  } catch (error) {
    jobStatus.textContent = `Could not load jobs: ${error.message}`;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(analyseButton, true);
  downloadLink.hidden = true;
  matchDetails.hidden = true;
  statusText.textContent = "Analysing your match against your full experience...";

  try {
    const response = await fetch("/api/match/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_description: textarea.value }),
    });
    const result = await readResult(response);
    renderMatch(result);
    statusText.textContent = result.cached
      ? "Match analysis loaded from the local cache."
      : "Match analysis complete.";
  } catch (error) {
    statusText.textContent = `Error: ${error.message}`;
  } finally {
    setBusy(analyseButton, false);
  }
});

generateButton.addEventListener("click", async () => {
  setBusy(generateButton, true);
  downloadLink.hidden = true;
  statusText.textContent = "Generating your tailored resume... This may take a minute.";

  try {
    const response = await fetch("/api/resume/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_description: textarea.value }),
    });
    const result = await readResult(response);
    statusText.textContent = result.email_status === "sent"
      ? "Resume generated and emailed successfully."
      : "Resume generated successfully. Email is not configured.";
    downloadLink.href = result.download_url;
    downloadLink.download = result.filename;
    downloadLink.textContent = `Download ${result.filename}`;
    downloadLink.hidden = false;
  } catch (error) {
    statusText.textContent = `Error: ${error.message}`;
  } finally {
    setBusy(generateButton, false);
  }
});

refreshJobsButton.addEventListener("click", loadJobs);

processJobsButton.addEventListener("click", async () => {
  processJobsButton.disabled = true;
  jobStatus.textContent = "Analysing pending jobs. This can take a few minutes.";
  try {
    const response = await fetch("/api/jobs/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 10 }),
    });
    const result = await readResult(response);
    const destination = result.queue_backend === "kafka" ? "Kafka" : "the local worker";
    jobStatus.textContent = `Queued ${result.queued} jobs for ${destination}.`;
    await loadJobs();
  } catch (error) {
    jobStatus.textContent = `Error: ${error.message}`;
  } finally {
    processJobsButton.disabled = false;
  }
});

async function loadMasterExperience() {
  try {
    const response = await fetch("/api/profile/master-experience");
    const result = await readResult(response);
    masterExperience.value = result.content;
  } catch (error) {
    masterStatus.textContent = `Could not load master experience: ${error.message}`;
  }
}

saveMasterButton.addEventListener("click", async () => {
  saveMasterButton.disabled = true;
  masterStatus.textContent = "Saving...";
  try {
    const response = await fetch("/api/profile/master-experience", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: masterExperience.value }),
    });
    await readResult(response);
    masterStatus.textContent = "Master experience saved. Future analyses will use it.";
  } catch (error) {
    masterStatus.textContent = `Error: ${error.message}`;
  } finally {
    saveMasterButton.disabled = false;
  }
});

loadJobs();
loadMasterExperience();
