const OVERVIEW_URL = "/api/v1/metrics/operations-overview?stale_after_minutes=10";
const ALERT_DELIVERIES_URL = "/api/v1/alerts/deliveries?limit=5";

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
  alertDeliveries: document.querySelector("[data-alert-deliveries]"),
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

function formatDurationMinutes(value) {
  if (!value) {
    return "Not set";
  }
  if (value % 1440 === 0) {
    const days = value / 1440;
    return `${days} ${days === 1 ? "day" : "days"}`;
  }
  if (value % 60 === 0) {
    const hours = value / 60;
    return `${hours} ${hours === 1 ? "hr" : "hrs"}`;
  }
  return `${value} min`;
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

function linkCell(url) {
  const cell = document.createElement("td");
  if (!url) {
    cell.textContent = "None";
    return cell;
  }

  const link = document.createElement("a");
  link.className = "table-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Open";
  cell.append(link);
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
    elements.pipelines.append(emptyRow("No pipeline runs recorded.", 7));
    return;
  }

  for (const pipeline of pipelines) {
    const row = document.createElement("tr");
    const statusCell = document.createElement("td");
    statusCell.append(statusPill(pipeline.latest_status));
    row.append(
      textCell(pipeline.name),
      textCell(pipeline.owner || "Unassigned"),
      statusCell,
      textCell(formatDurationMinutes(pipeline.expected_cadence_minutes)),
      numericCell(pipeline.failed_quality_checks),
      numericCell(pipeline.warning_quality_checks),
      linkCell(pipeline.runbook_url),
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
    elements.stale.append(emptyRow("No stale active runs.", 6));
    return;
  }

  for (const run of runs) {
    const row = document.createElement("tr");
    const statusCell = document.createElement("td");
    statusCell.append(statusPill(run.status));
    row.append(
      textCell(run.name),
      textCell(run.owner || "Unassigned"),
      statusCell,
      numericCell(`${run.age_minutes} min`),
      numericCell(formatDurationMinutes(run.stale_after_minutes)),
      linkCell(run.runbook_url),
    );
    elements.stale.append(row);
  }
}

function renderAlertDeliveries(deliveries) {
  clearNode(elements.alertDeliveries);
  if (!deliveries.length) {
    elements.alertDeliveries.append(emptyRow("No alert deliveries recorded.", 5));
    return;
  }

  for (const delivery of deliveries) {
    const row = document.createElement("tr");
    const statusCell = document.createElement("td");
    statusCell.append(statusPill(delivery.status));
    row.append(
      textCell(formatLabel(delivery.event_type)),
      textCell(delivery.receiver),
      statusCell,
      numericCell(delivery.http_status_code ?? "none"),
      textCell(formatDate(delivery.created_at)),
    );
    elements.alertDeliveries.append(row);
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
    const [overview, alertDeliveries] = await Promise.all([
      fetchJson(OVERVIEW_URL),
      fetchJson(ALERT_DELIVERIES_URL),
    ]);
    renderOverview(overview);
    renderAlertDeliveries(alertDeliveries);
  } catch (error) {
    renderError(error);
  } finally {
    elements.refresh.disabled = false;
  }
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

elements.refresh.addEventListener("click", refreshDashboard);
refreshDashboard();