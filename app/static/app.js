const form = document.querySelector("#resume-form");
const textarea = document.querySelector("#job-description");
const statusText = document.querySelector("#status");
const directResumeResult = document.querySelector("#direct-resume-result");
const downloadLink = document.querySelector("#download-link");
const jobResumeResult = document.querySelector("#job-resume-result");
const jobDownloadLink = document.querySelector("#job-download-link");
const generationProgress = document.querySelector("#generation-progress");
const analyseButton = document.querySelector("#analyse-button");
const generateButton = document.querySelector("#generate-button");
const matchDetails = document.querySelector("#match-details");
const jobList = document.querySelector("#job-list");
const jobStatus = document.querySelector("#job-status");
const fetchJobsButton = document.querySelector("#fetch-jobs");
let fetchStarting = false;
let collectionRunning = false;
const refreshJobsButton = document.querySelector("#refresh-jobs");
const processJobsButton = document.querySelector("#process-jobs");
const masterExperience = document.querySelector("#master-experience");
const masterStatus = document.querySelector("#master-status");
const saveMasterButton = document.querySelector("#save-master-experience");
const companyFilterSummary = document.querySelector("#company-filter-summary");
const companyFilterOptions = document.querySelector("#company-filter-options");
const clearCompanyFilterButton = document.querySelector("#clear-company-filter");
const COMPANY_FILTER_KEY = "career-pilot-company-filter";
let resumeGenerating = false;
let dashboardJobs = [];
let showingSaved = false;
let jobsRequest = 0;
const selectedJobIds = new Set();
let bulkDeleting = false;
const selectAllJobs = document.querySelector("#select-all-jobs");
const deleteSelectedJobs = document.querySelector("#delete-selected-jobs");
const selectedJobCount = document.querySelector("#selected-job-count");
let selectedCompanies;
try { selectedCompanies = new Set(JSON.parse(localStorage.getItem(COMPANY_FILTER_KEY) || "[]")); }
catch { selectedCompanies = new Set(); }

function setTab(tabName) {
  if (tabName !== "direct") {
    showingSaved = tabName === "saved";
    selectedJobIds.clear();
    document.querySelector("#jobs-view-title").textContent = showingSaved ? "Saved jobs" : "Job dashboard";
    loadJobs();
  }
  for (const panel of document.querySelectorAll(".tab-panel")) panel.hidden = panel.id !== `${tabName === "saved" ? "dashboard" : tabName}-panel`;
  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.tab === tabName;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  }
}
function clearResumeResults() { directResumeResult.hidden = true; jobResumeResult.hidden = true; }
function setResumeBusy(isBusy) {
  resumeGenerating = isBusy;
  for (const button of document.querySelectorAll("[data-resume-action]")) button.disabled = isBusy;
  generationProgress.hidden = !isBusy;
}
function setBusy(button, isBusy) { analyseButton.disabled = isBusy; if (!isBusy) button.disabled = false; }
function saveCompanyFilter() { localStorage.setItem(COMPANY_FILTER_KEY, JSON.stringify([...selectedCompanies])); }
function visibleJobs() {
  return dashboardJobs.filter((job) => !selectedCompanies.size || selectedCompanies.has(job.company_name));
}
function renderCompanyControls() {
  const companies = [...new Set(dashboardJobs.map((job) => job.company_name).filter(Boolean))].sort();
  selectedCompanies = new Set([...selectedCompanies].filter((company) => companies.includes(company)));
  saveCompanyFilter();
  companyFilterOptions.replaceChildren();
  for (const company of companies) {
    const label = document.createElement("label");
    label.className = "company-filter-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedCompanies.has(company);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedCompanies.add(company);
      else selectedCompanies.delete(company);
      saveCompanyFilter();
      updateCompanyFilterSummary(companies);
      renderJobs(visibleJobs());
    });
    const name = document.createElement("span");
    name.textContent = company;
    label.append(checkbox, name);
    companyFilterOptions.append(label);
  }
  updateCompanyFilterSummary(companies);
}
function updateCompanyFilterSummary(companies) {
  const selectedCount = selectedCompanies.size;
  companyFilterSummary.textContent = !selectedCount || selectedCount === companies.length
    ? "All companies"
    : `${selectedCount} ${selectedCount === 1 ? "company" : "companies"}`;
  clearCompanyFilterButton.hidden = !selectedCount;
}
function renderItems(id, items) {
  const list = document.querySelector(id); list.replaceChildren();
  for (const item of items) {
    const entry = document.createElement("li");
    const explanation = item.explanation ? ` — ${item.explanation}` : "";
    const source = item.evidence?.[0]?.source_type;
    entry.textContent = `${item.text}${source ? ` [${source.replaceAll("_", " ")}]` : ""}${explanation}`;
    list.append(entry);
  }
}
function renderMatch(result) {
  document.querySelector("#match-score").textContent = `${result.overall_score}%`;
  document.querySelector("#match-summary").textContent = result.summary;
  renderItems("#strong-matches", result.strong_matches); renderItems("#transferable-matches", result.transferable_matches);
  renderItems("#uncertain-requirements", result.uncertain_requirements); renderItems("#critical-gaps", result.critical_gaps);
  renderItems("#recommendations", result.recommendations.map((text) => ({ text })));
  document.querySelector("#critical-gaps-container").hidden = !result.critical_gaps.length;
  document.querySelector("#recommendations-container").hidden = !result.recommendations.length;
  matchDetails.hidden = false;
}
async function readResult(response) { const result = await response.json(); if (!response.ok) throw new Error(result.detail || "Request failed"); return result; }
function jobButton(label, callback, style = "secondary", isResume = false) {
  const button = document.createElement("button"); button.type = "button"; button.className = style; button.textContent = label;
  if (isResume) button.dataset.resumeAction = ""; button.addEventListener("click", callback); return button;
}
async function updateJobStatus(jobId, status) {
  try {
    await readResult(await fetch(`/api/jobs/${jobId}/action`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }));
    await loadJobs();
  } catch (error) { jobStatus.textContent = `Could not update job: ${error.message}`; }
}
async function generateStoredResume(jobId) {
  clearResumeResults(); setResumeBusy(true); jobStatus.textContent = "Generating tailored resume… This may take a minute.";
  try {
    const result = await readResult(await fetch(`/api/jobs/${jobId}/generate-resume`, { method: "POST" }));
    jobStatus.textContent = "Resume generation started in the background."; await loadJobs();
  } catch (error) { jobStatus.textContent = `Error: ${error.message}`; } finally { setResumeBusy(false); }
}
async function retryAnalysis(jobId) {
  try { await readResult(await fetch(`/api/jobs/${jobId}/retry-analysis`, { method: "POST" })); jobStatus.textContent = "Job marked for retry. Use Analyse pending jobs when the batch service is reachable."; await loadJobs(); }
  catch (error) { jobStatus.textContent = `Error: ${error.message}`; }
}
function updateBulkControls() {
  const visible = visibleJobs();
  const count = visible.filter(job => selectedJobIds.has(job.id)).length;
  selectAllJobs.checked = visible.length > 0 && count === visible.length;
  selectAllJobs.indeterminate = count > 0 && count < visible.length;
  selectAllJobs.disabled = bulkDeleting || !visible.length;
  deleteSelectedJobs.disabled = bulkDeleting || !count;
  deleteSelectedJobs.textContent = bulkDeleting ? "Deleting…" : "Delete selected";
  selectedJobCount.textContent = `${count} selected`;
}
function renderJobs(jobs) {
  const visibleIds = new Set(jobs.map(job => job.id));
  for (const id of selectedJobIds) if (!visibleIds.has(id)) selectedJobIds.delete(id);
  updateBulkControls();
  jobList.replaceChildren();
  if (!jobs.length) {
    jobList.textContent = dashboardJobs.length
      ? "No jobs match the selected company filter."
      : (showingSaved ? "No saved jobs yet. Save a job from the dashboard to find it here." : "No eligible jobs yet. Use Fetch jobs now to collect jobs.");
    return;
  }
  for (const job of jobs) {
    const card = document.createElement("article"); card.className = "job-card";
    const title = document.createElement("h3"); title.textContent = job.job_title;
    const meta = document.createElement("p"); meta.className = "job-meta"; meta.textContent = `${job.company_name} · ${job.location || "Location not specified"}`;
    const details = document.createElement("p"); details.className = "job-meta";
    details.textContent = `${job.minimum_years_experience === null ? "No explicit experience requirement" : `${job.minimum_years_experience}+ years required`} · ${job.analysis_status}`;
    const heading = document.createElement("div"); heading.className = "job-heading";
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.className = "job-select";
    checkbox.setAttribute("aria-label", `Select ${job.job_title} at ${job.company_name}`);
    checkbox.checked = selectedJobIds.has(job.id); checkbox.disabled = bulkDeleting;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedJobIds.add(job.id); else selectedJobIds.delete(job.id);
      updateBulkControls();
    });
    heading.append(checkbox, title);
    card.append(heading, meta, details);
    if (job.match) { const score = document.createElement("p"); score.className = "job-score"; score.textContent = `${job.match_score}% match — ${job.match.summary}`; card.append(score); }
    else if (job.analysis_error) { const error = document.createElement("p"); error.className = "job-error"; error.textContent = `Analysis failed: ${job.analysis_error}`; card.append(error); }
    const actions = document.createElement("div"); actions.className = "job-actions";
    if (job.application_url) { const apply = document.createElement("a"); apply.href = job.application_url; apply.target = "_blank"; apply.rel = "noreferrer"; apply.className = "secondary link-button"; apply.textContent = "View job"; actions.append(apply); }
    const resumeButton = jobButton(job.resume_status === "generating" ? "Generating resume…" : "Generate resume", () => generateStoredResume(job.id), "", true);
    resumeButton.disabled = !job.match || job.resume_status === "generating";
    actions.append(resumeButton);
    if (job.resume_status === "completed" && job.resume_filename) {
      const download = document.createElement("a");
      download.href = `/api/resume/download/${job.id}/${encodeURIComponent(job.resume_filename)}`;
      download.textContent = "Download resume"; download.className = "secondary link-button"; actions.append(download);
    }
    if (job.resume_error) { const error = document.createElement("p"); error.textContent = job.resume_error; card.append(error); }
    if (job.analysis_status === "failed") actions.append(jobButton("Retry analysis", () => retryAnalysis(job.id)));
    actions.append(jobButton(showingSaved ? "Unsave" : "Save job", () => updateJobStatus(job.id, showingSaved ? "new" : "saved")), jobButton("Applied", () => updateJobStatus(job.id, "applied")), jobButton("Delete", async () => {
      try { await readResult(await fetch(`/api/jobs/${job.id}`, { method: "DELETE" })); await loadJobs(); }
      catch (error) { jobStatus.textContent = error.message; }
    }));
    card.append(actions); jobList.append(card);
  }
}
async function loadJobs() {
  const request = ++jobsRequest;
  try {
    const result = await readResult(await fetch(`/api/jobs?saved=${showingSaved}`));
    if (request !== jobsRequest) return;
    dashboardJobs = result.jobs;
    renderCompanyControls();
    renderJobs(visibleJobs());
  } catch (error) { jobStatus.textContent = `Could not load jobs: ${error.message}`; }
}
form.addEventListener("submit", async (event) => {
  event.preventDefault(); setBusy(analyseButton, true); directResumeResult.hidden = true; matchDetails.hidden = true; statusText.textContent = "Analysing your match against your full experience…";
  try { const result = await readResult(await fetch("/api/match/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_description: textarea.value }) })); renderMatch(result); statusText.textContent = result.cached ? "Match analysis loaded from the local cache." : "Match analysis complete."; }
  catch (error) { statusText.textContent = `Error: ${error.message}`; } finally { setBusy(analyseButton, false); }
});
generateButton.addEventListener("click", async () => {
  clearResumeResults(); setResumeBusy(true); statusText.textContent = "Generating your tailored resume… This may take a minute.";
  try { const result = await readResult(await fetch("/api/resume/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_description: textarea.value }) })); statusText.textContent = result.email_status === "sent" ? "Resume generated and emailed successfully." : "Resume generated successfully. Email is not configured."; downloadLink.href = result.download_url; downloadLink.download = result.filename; downloadLink.textContent = `Download ${result.filename}`; directResumeResult.hidden = false; }
  catch (error) { statusText.textContent = `Error: ${error.message}`; } finally { setResumeBusy(false); }
});
refreshJobsButton.addEventListener("click", loadJobs);
clearCompanyFilterButton.addEventListener("click", () => {
  selectedCompanies.clear();
  saveCompanyFilter();
  renderCompanyControls();
  renderJobs(visibleJobs());
});
processJobsButton.addEventListener("click", async () => {
  processJobsButton.disabled = true; jobStatus.textContent = "Submitting pending jobs to the analysis batch…";
  try { const result = await readResult(await fetch("/api/jobs/process", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 10 }) })); jobStatus.textContent = result.submitted ? `Submitted ${result.submitted} jobs to the analysis batch. Refresh after it completes.` : "No eligible pending jobs were available for batch submission."; await loadJobs(); }
  catch (error) { jobStatus.textContent = `Error: ${error.message}`; } finally { processJobsButton.disabled = false; }
});
async function loadMasterExperience() { try { masterExperience.value = (await readResult(await fetch("/api/profile/master-experience"))).content; } catch (error) { masterStatus.textContent = `Could not load master experience: ${error.message}`; } }
saveMasterButton.addEventListener("click", async () => { saveMasterButton.disabled = true; masterStatus.textContent = "Saving…"; try { await readResult(await fetch("/api/profile/master-experience", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: masterExperience.value }) })); masterStatus.textContent = "Master experience saved. Future analyses will use it."; } catch (error) { masterStatus.textContent = `Error: ${error.message}`; } finally { saveMasterButton.disabled = false; } });
for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => setTab(tab.dataset.tab));
loadJobs(); loadMasterExperience(); window.setInterval(loadJobs, 15_000);

async function loadSourceStatus() {
  try {
    const state = await readResult(await fetch("/api/jobs/sources/status"));
    collectionRunning = Boolean(state.is_running);
    fetchJobsButton.disabled = fetchStarting || collectionRunning;
    fetchJobsButton.textContent = collectionRunning ? "Fetching jobs…" : "Fetch jobs now";
    const stats = document.querySelector("#collection-stats");
    stats.replaceChildren();
    const total = document.createElement("strong");
    total.textContent = `${state.statistics?.new_eligible_jobs_total || 0} new eligible jobs added`;
    const run = document.createElement("p");
    const runAt = state.run_at || state.last_slot;
    const slot = runAt ? new Date(runAt).toLocaleString("en-IN", {timeZone: "Asia/Kolkata"}) + " IST" : "Not run yet";
    run.textContent = `${state.status === "running" ? "Current run" : "Last run"}${state.trigger === "manual" ? " (manual)" : ""}: ${slot} · ${state.statistics?.companies_completed || 0}/${state.statistics?.companies_total || 0} companies processed`;
    const note = document.createElement("p"); note.textContent = `${dashboardJobs.length} eligible jobs in this view (excluding Applied/deleted). ${state.statistics?.new_jobs_total || 0} total new records imported. New eligible counts exclude updates and duplicates.`;
    stats.append(total, run, note);
    const panel = document.querySelector("#source-status");
    panel.replaceChildren();
    const summary = document.createElement("summary"); summary.textContent = `Portal collection: ${state.status || "waiting"} · ${state.schedule_enabled ? "scheduled collection enabled" : "manual collection only"}`; panel.append(summary);
    for (const [slug, source] of Object.entries(state.sources || {})) {
      const line = document.createElement("p");
      line.textContent = `${source.company || slug}: ${source.status} · ${source.new_eligible_jobs || 0} new eligible · ${source.jobs_count || 0} fetched · last success: ${source.last_success_at || "none"}${source.error ? " · " + source.error : ""}`;
      panel.append(line);
    }
  } catch (_) { /* Keep the last source report during temporary connection loss. */ }
}
loadSourceStatus(); window.setInterval(loadSourceStatus, 15_000);

selectAllJobs.addEventListener("change", () => {
  for (const job of visibleJobs()) {
    if (selectAllJobs.checked) selectedJobIds.add(job.id); else selectedJobIds.delete(job.id);
  }
  renderJobs(visibleJobs());
});
deleteSelectedJobs.addEventListener("click", async () => {
  const ids = visibleJobs().filter(job => selectedJobIds.has(job.id)).map(job => job.id);
  if (!ids.length || bulkDeleting) return;
  bulkDeleting = true; renderJobs(visibleJobs());
  let deleted = 0;
  try {
    for (let offset = 0; offset < ids.length; offset += 1000) {
      const result = await readResult(await fetch("/api/jobs/bulk-delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: ids.slice(offset, offset + 1000) }),
      }));
      deleted += result.deleted;
      for (const id of ids.slice(offset, offset + 1000)) selectedJobIds.delete(id);
    }
    jobStatus.textContent = `Deleted ${deleted} ${deleted === 1 ? "job" : "jobs"}.`;
  } catch (error) { jobStatus.textContent = `Deleted ${deleted} jobs. ${error.message}`; }
  finally { bulkDeleting = false; await loadJobs(); updateBulkControls(); }
});

fetchJobsButton.addEventListener("click", async () => {
  if (fetchStarting || collectionRunning) return;
  fetchStarting = true; fetchJobsButton.disabled = true; fetchJobsButton.textContent = "Starting…";
  try {
    await readResult(await fetch("/api/jobs/sources/fetch", {method: "POST"}));
    collectionRunning = true;
    jobStatus.textContent = "Fetching jobs from all connected companies. New eligible jobs will appear as each company finishes.";
  } catch (error) { jobStatus.textContent = `Could not start collection: ${error.message}`; }
  finally {
    fetchStarting = false;
    fetchJobsButton.disabled = collectionRunning;
    fetchJobsButton.textContent = collectionRunning ? "Fetching jobs…" : "Fetch jobs now";
    await loadSourceStatus();
  }
});
