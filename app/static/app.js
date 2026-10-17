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
let selectedCompanies;
try { selectedCompanies = new Set(JSON.parse(localStorage.getItem(COMPANY_FILTER_KEY) || "[]")); }
catch { selectedCompanies = new Set(); }

function setTab(tabName) {
  for (const panel of document.querySelectorAll(".tab-panel")) panel.hidden = panel.id !== `${tabName}-panel`;
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
  await readResult(await fetch(`/api/jobs/${jobId}/action`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }));
  await loadJobs();
}
async function generateStoredResume(jobId) {
  clearResumeResults(); setResumeBusy(true); jobStatus.textContent = "Generating tailored resume… This may take a minute.";
  try {
    const result = await readResult(await fetch(`/api/jobs/${jobId}/generate-resume`, { method: "POST" }));
    jobDownloadLink.href = result.download_url; jobDownloadLink.download = result.filename; jobDownloadLink.textContent = `Download ${result.filename}`;
    jobResumeResult.hidden = false; jobStatus.textContent = "Resume generated successfully."; await loadJobs();
  } catch (error) { jobStatus.textContent = `Error: ${error.message}`; } finally { setResumeBusy(false); }
}
async function retryAnalysis(jobId) {
  try { await readResult(await fetch(`/api/jobs/${jobId}/retry-analysis`, { method: "POST" })); jobStatus.textContent = "Job marked for retry. Use Analyse pending jobs when the batch service is reachable."; await loadJobs(); }
  catch (error) { jobStatus.textContent = `Error: ${error.message}`; }
}
function renderJobs(jobs) {
  jobList.replaceChildren();
  if (!jobs.length) {
    jobList.textContent = dashboardJobs.length
      ? "No jobs match the selected company filter."
      : "No eligible jobs yet. Import a portal JSON file, then refresh.";
    return;
  }
  for (const job of jobs) {
    const card = document.createElement("article"); card.className = "job-card";
    const title = document.createElement("h3"); title.textContent = job.job_title;
    const meta = document.createElement("p"); meta.className = "job-meta"; meta.textContent = `${job.company_name} · ${job.location || "Location not specified"}`;
    const details = document.createElement("p"); details.className = "job-meta";
    details.textContent = `${job.minimum_years_experience === null ? "No explicit experience requirement" : `${job.minimum_years_experience}+ years required`} · ${job.analysis_status}`;
    card.append(title, meta, details);
    if (job.match) { const score = document.createElement("p"); score.className = "job-score"; score.textContent = `${job.match_score}% match — ${job.match.summary}`; card.append(score); }
    else if (job.analysis_error) { const error = document.createElement("p"); error.className = "job-error"; error.textContent = `Analysis failed: ${job.analysis_error}`; card.append(error); }
    const actions = document.createElement("div"); actions.className = "job-actions";
    if (job.application_url) { const apply = document.createElement("a"); apply.href = job.application_url; apply.target = "_blank"; apply.rel = "noreferrer"; apply.className = "secondary link-button"; apply.textContent = "View job"; actions.append(apply); }
    if (job.match) {
      const resumeButton = jobButton("Generate resume", () => generateStoredResume(job.id), "", true);
      resumeButton.disabled = resumeGenerating;
      actions.append(resumeButton);
    }
    if (job.analysis_status === "failed") actions.append(jobButton("Retry analysis", () => retryAnalysis(job.id)));
    actions.append(jobButton("Save", () => updateJobStatus(job.id, "saved")), jobButton("Applied", () => updateJobStatus(job.id, "applied")), jobButton("Dismiss", () => updateJobStatus(job.id, "dismissed")));
    card.append(actions); jobList.append(card);
  }
}
async function loadJobs() {
  try {
    dashboardJobs = (await readResult(await fetch("/api/jobs"))).jobs;
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
loadJobs(); loadMasterExperience(); window.setInterval(loadJobs, 60_000);
