const OVERVIEW_URL = "/api/v1/metrics/operations-overview?stale_after_minutes=10";

const elements = {
  serviceStatus: document.querySelector("[data-service-status]"),
  generatedAt: document.querySelector("[data-generated-at]"),
  totalRuns: document.querySelector("[data-total-runs]"),
  failedChecks: document.querySelector("[data-failed-checks]"),
  warningChecks: document.querySelector("[data-warning-checks]"),
  staleRuns: document.querySelector("[data-stale-runs]"),
  actionCount: document.querySelector("[data-action-count]"),
  actions: document.querySelector("[data-actions]"),
  pipelines: document.querySelector("[data-pipelines]"),
  quality: document.querySelector("[data-quality]"),
  stale: document.querySelector("[data-stale]"),
  refresh: document.querySelector("[data-refresh]"),
};

function formatLabel(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

function formatDate(value) {
  if (!value) {
    return "No timestamp";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function clearNode(node) {
  node.replaceChildren();
}

function statusPill(value) {
  const pill = document.createElement("span");
  pill.className = `status-pill ${value}`;
  pill.textContent = formatLabel(value);
  return pill;
}

function priorityPill(value) {
  const pill = document.createElement("span");
  pill.className = `priority-pill ${value}`;
  pill.textContent = value;
  return pill;
}

function emptyRow(message, columns) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.className = "empty-state";
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  return row;
}

function numericCell(value) {
  const cell = document.createElement("td");
  cell.className = "numeric";
  cell.textContent = value;
  return cell;
}

function textCell(value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  return cell;
}

function renderActions(actions) {
  clearNode(elements.actions);
  elements.actionCount.textContent = `${actions.length} open`;

  if (!actions.length) {
    const item = document.createElement("li");
    const copy = document.createElement("p");
    copy.className = "empty-state";
    copy.textContent = "No recommended actions.";
    item.append(copy);
    elements.actions.append(item);
    return;
  }

  for (const action of actions) {
    const item = document.createElement("li");
    const title = document.createElement("h3");
    const detail = document.createElement("p");
    title.textContent = action.title;
    detail.textContent = action.detail;
    item.append(priorityPill(action.priority), title, detail);
    elements.actions.append(item);
  }
}

function renderPipelines(pipelines) {
  clearNode(elements.pipelines);
  if (!pipelines.length) {
    elements.pipelines.append(emptyRow("No pipeline runs recorded.", 5));
    return;
  }

  for (const pipeline of pipelines) {
    const row = document.createElement("tr");
    const statusCell = document.createElement("td");
    statusCell.append(statusPill(pipeline.latest_status));
    row.append(
      textCell(pipeline.name),
      statusCell,
      numericCell(pipeline.total_runs),
      numericCell(pipeline.failed_quality_checks),
      numericCell(pipeline.warning_quality_checks),
    );
    elements.pipelines.append(row);
  }
}

function renderQuality(qualityChecks) {
  clearNode(elements.quality);
  if (!qualityChecks.length) {
    elements.quality.append(emptyRow("No quality checks recorded.", 5));
    return;
  }

  for (const check of qualityChecks) {
    const row = document.createElement("tr");
    row.append(
      textCell(formatLabel(check.severity)),
      numericCell(check.total_checks),
      numericCell(check.passed_checks),
      numericCell(check.warning_checks),
      numericCell(check.failed_checks),
    );
    elements.quality.append(row);
  }
}

function renderStaleRuns(runs) {
  clearNode(elements.stale);
  if (!runs.length) {
    elements.stale.append(emptyRow("No stale active runs.", 4));
    return;
  }

  for (const run of runs) {
    const row = document.createElement("tr");
    const statusCell = document.createElement("td");
    statusCell.append(statusPill(run.status));
    row.append(
      textCell(run.name),
      statusCell,
      numericCell(`${run.age_minutes} min`),
      textCell(run.source_system),
    );
    elements.stale.append(row);
  }
}

function renderOverview(overview) {
  elements.serviceStatus.textContent = formatLabel(overview.service_status);
  elements.serviceStatus.className = `status-pill ${overview.service_status}`;
  elements.generatedAt.textContent = formatDate(overview.generated_at);
  elements.totalRuns.textContent = overview.summary.total_runs;
  elements.failedChecks.textContent = overview.summary.failed_quality_checks;
  elements.warningChecks.textContent = overview.summary.warning_quality_checks;
  elements.staleRuns.textContent = overview.stale_pipeline_runs.length;
  renderActions(overview.recommended_actions);
  renderPipelines(overview.pipeline_health);
  renderQuality(overview.quality_checks);
  renderStaleRuns(overview.stale_pipeline_runs);
}

function renderError(error) {
  clearNode(elements.actions);
  const item = document.createElement("li");
  const copy = document.createElement("p");
  copy.className = "error-state";
  copy.textContent = `Dashboard data failed to load: ${error.message}`;
  item.append(copy);
  elements.actions.append(item);
}

async function refreshDashboard() {
  elements.refresh.disabled = true;
  try {
    const response = await fetch(OVERVIEW_URL, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    renderOverview(await response.json());
  } catch (error) {
    renderError(error);
  } finally {
    elements.refresh.disabled = false;
  }
}

elements.refresh.addEventListener("click", refreshDashboard);
refreshDashboard();