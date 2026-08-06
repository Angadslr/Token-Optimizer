const SESSION_KEY = "slashtoken.browserSessionId";
const RUN_KEY = "slashtoken.activeRunId";
const THREAD_KEY = "slashtoken.threadId";

const storedSessionId = sessionStorage.getItem(SESSION_KEY) || crypto.randomUUID();
sessionStorage.setItem(SESSION_KEY, storedSessionId);

const state = {
  decision: null,
  socket: null,
  sessionId: storedSessionId,
  runId: sessionStorage.getItem(RUN_KEY),
  threadId: sessionStorage.getItem(THREAD_KEY),
  runStatus: "idle",
  liveness: "active",
  lastEventAtMs: null,
  silenceWarningSeconds: 120,
  idleDiagnosticSeconds: 300,
  approvals: new Map(),
  reconnectTimer: null,
};

const $ = (id) => document.getElementById(id);
const output = $("output");
const terminalStatuses = new Set(["completed", "failed", "interrupted"]);

function setMessage(text, error = false) {
  const message = $("message");
  message.textContent = text;
  message.classList.toggle("message-error", error);
}

function updatePromptGutter() {
  const lineCount = Math.max(1, $("prompt").value.split("\n").length);
  $("promptGutter").textContent = Array.from(
    { length: lineCount },
    (_, index) => index + 1,
  ).join("\n");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function effectivePayload() {
  return {
    prompt: $("prompt").value,
    target_model: $("model").value,
    project_path: $("project").value,
    session_id: state.sessionId,
    workload_mode: $("mode").value,
  };
}

async function saveSessionSettings(values, scope = "session") {
  return requestJson("/api/settings", {
    method: "PATCH",
    body: JSON.stringify({
      scope,
      values,
      project_path: $("project").value,
      session_id: state.sessionId,
    }),
  });
}

async function syncControls() {
  await saveSessionSettings({
    language_optimization: $("languageOptimization").checked,
    output_optimization: $("outputOptimization").checked,
    workload_mode: $("mode").value,
  });
}

async function optimize() {
  try {
    if (!$("model").value) throw new Error("Select a Codex model first.");
    if (!$("prompt").value.trim()) throw new Error("Enter a prompt first.");
    $("optimize").disabled = true;
    setMessage("Analyzing language, risk, protected content, and routing economics…");
    await syncControls();
    const decision = await requestJson("/api/optimize", {
      method: "POST",
      body: JSON.stringify(effectivePayload()),
    });
    state.decision = decision;
    renderDecision(decision);
    if (decision.should_auto_run) submit("candidate");
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    $("optimize").disabled = false;
  }
}

function renderDecision(decision) {
  $("decision").classList.remove("hidden");
  $("originalPrompt").textContent = $("prompt").value;
  $("candidatePrompt").value = decision.candidate_prompt || "No candidate was produced.";
  $("candidatePrompt").disabled = !decision.candidate_prompt;
  $("useCandidate").disabled = decision.status !== "candidate";
  $("originalTokens").textContent = `${decision.original_tokens.tokens} ${decision.original_tokens.exact ? "exact" : "estimated"} tokens`;
  $("candidateTokens").textContent = decision.candidate_tokens
    ? `${decision.candidate_tokens.tokens} ${decision.candidate_tokens.exact ? "exact" : "estimated"} tokens`
    : "Not generated";
  const decisionStatus = $("decisionStatus");
  decisionStatus.textContent = `[status] ${decision.status.replaceAll("_", ".")}`;
  decisionStatus.className = `decision-state decision-state-${decision.status}`;
  $("receipt").textContent = decision.receipt;
  const metrics = [
    ["lang.source", decision.source_language],
    ["lang.candidate", decision.candidate_language?.detected_language || "not_checked"],
    ["lang.confidence", decision.candidate_language
      ? decision.candidate_language.confidence.toFixed(3)
      : "not_checked"],
    ["lang.detector", decision.candidate_language?.detector || "not_checked"],
    ["token.savings", decision.token_savings],
    ["savings.pct", `${decision.token_savings_percent}%`],
    ["protected.spans", decision.protected_span_count],
    ["cost.optimizer", decision.optimizer_cost_available ? `$${decision.optimizer_cost_usd}` : "not_configured"],
    ["auto_run.eligible", decision.auto_run_eligible ? "true" : "false"],
    ["threshold.ver", decision.threshold_version],
  ];
  $("decisionMetrics").replaceChildren(...metrics.flatMap(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    return [term, detail];
  }));
  setMessage(decision.receipt, decision.status === "failed");
}

function submit(selection) {
  if (!state.decision) return;
  if (!sendSocket({
    action: "submit",
    decision_id: state.decision.decision_id,
    selection,
    edited_prompt: selection === "candidate" ? $("candidatePrompt").value : null,
    thread_id: state.threadId,
  })) {
    setMessage("Codex App Server is not connected.", true);
    return;
  }
  output.textContent = "Submitting one approved prompt to Codex…\n";
  state.approvals.clear();
  renderApprovals();
  $("interrupt").disabled = false;
}

function sendSocket(payload) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return false;
  state.socket.send(JSON.stringify(payload));
  return true;
}

function appendEvent(event) {
  const method = event.method || "event";
  const params = event.params || {};
  if (event.id !== undefined) {
    appendOutput(`\n[${method}: awaiting input]\n`);
    return;
  }
  const delta = params.delta || params.text || params.message;
  if (typeof delta === "string") {
    appendOutput(delta);
  } else if (["turn/started", "turn/completed", "item/started", "item/completed"].includes(method)) {
    appendOutput(`\n[${method}]\n`);
  }
}

function appendOutput(text) {
  output.textContent += text;
  output.scrollTop = output.scrollHeight;
}

function applyRun(run) {
  if (!run) return;
  state.runId = run.run_id;
  state.runStatus = run.status;
  state.liveness = run.liveness || "active";
  state.lastEventAtMs = run.last_event_at_ms || state.lastEventAtMs;
  if (run.thread_id) {
    state.threadId = run.thread_id;
    sessionStorage.setItem(THREAD_KEY, state.threadId);
  }
  if (state.runId) sessionStorage.setItem(RUN_KEY, state.runId);
  state.approvals.clear();
  (run.pending_approvals || []).forEach((approval) => {
    state.approvals.set(String(approval.request_id), approval);
  });
  $("runInspector").classList.remove("hidden");
  $("runStatus").textContent = runStatusLabel(run);
  $("runStatus").className =
    run.status === "running" && run.liveness === "unresponsive"
      ? "run-state run-state-warning"
      : `run-state run-state-${run.status}`;
  $("interrupt").disabled = terminalStatuses.has(run.status);
  renderApprovals();
  renderUsage(run.usage || {});
}

function runStatusLabel(run) {
  if (run.status === "waiting_for_approval") return "waiting for approval";
  if (run.status === "failed" && run.failure_code) return `failed · ${run.failure_code}`;
  if (run.status === "running" && run.liveness === "unresponsive") {
    return "running · unresponsive";
  }
  return run.status.replaceAll("_", " ");
}

function renderApprovals() {
  const container = $("approvals");
  const panel = $("approvalPanel");
  container.replaceChildren();
  const approvals = [...state.approvals.values()];
  panel.classList.toggle("hidden", approvals.length === 0);
  $("runInspector").classList.toggle("with-approvals", approvals.length > 0);
  approvals.forEach((approval) => container.append(approvalCard(approval)));
}

function approvalCard(approval) {
  const card = document.createElement("article");
  card.className = "approval-card";

  const heading = document.createElement("div");
  heading.className = "approval-heading";
  const title = document.createElement("h3");
  title.textContent = `${approval.kind.replaceAll("_", " ")} approval`;
  const countdown = document.createElement("span");
  countdown.className = "approval-countdown";
  countdown.textContent = approvalCountdown(approval);
  heading.append(title, countdown);
  card.append(heading);

  const details = document.createElement("dl");
  details.className = "approval-details";
  const rows = approvalRows(approval);
  rows.forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    details.append(term, detail);
  });
  card.append(details);

  const actions = document.createElement("div");
  actions.className = "approval-actions";
  const labels = {
    accept: "accept once",
    acceptForSession: "accept for session",
    decline: "decline",
    cancel: "cancel turn",
  };
  (approval.available_decisions || []).forEach((decision) => {
    const button = document.createElement("button");
    button.textContent = labels[decision] || decision;
    button.className = decision === "accept" || decision === "acceptForSession"
      ? "primary"
      : decision === "cancel" ? "danger" : "secondary";
    button.disabled = approval.response_decision !== null;
    button.addEventListener("click", () => respondToApproval(approval, decision));
    actions.append(button);
  });
  if (approval.response_decision) {
    const status = document.createElement("span");
    status.className = "approval-response-status";
    status.textContent = `response sent: ${approval.response_decision}; waiting for Codex confirmation`;
    actions.append(status);
  }
  card.append(actions);
  return card;
}

function approvalRows(approval) {
  const rows = [];
  if (approval.reason) rows.push(["reason", approval.reason]);
  if (approval.command) rows.push(["command", approval.command]);
  if (approval.cwd) rows.push(["working directory", approval.cwd]);
  if (approval.grant_root) rows.push(["write root", approval.grant_root]);
  if (approval.network_context) {
    const context = approval.network_context;
    const destination = [context.protocol, context.host, context.port]
      .filter((value) => value !== undefined && value !== null)
      .join(" · ");
    rows.push(["network destination", destination || "managed network request"]);
  }
  if (!rows.length) rows.push(["request", approval.method]);
  return rows;
}

function approvalCountdown(approval) {
  if (approval.response_decision) return "responding";
  const remaining = Math.max(0, Math.ceil((approval.expires_at_ms - Date.now()) / 1000));
  const minutes = Math.floor(remaining / 60);
  const seconds = String(remaining % 60).padStart(2, "0");
  return `auto-cancel in ${minutes}:${seconds}`;
}

function respondToApproval(approval, decision) {
  if (!state.runId || approval.response_decision) return;
  approval.response_decision = decision;
  renderApprovals();
  if (!sendSocket({
    action: "approval_response",
    run_id: state.runId,
    request_id: approval.request_id,
    decision,
  })) {
    approval.response_decision = null;
    renderApprovals();
    setMessage("Approval could not be sent while Codex is disconnected.", true);
  }
}

function renderUsage(usage) {
  const groups = [
    ["this run", usage.run_total],
    ["thread total", usage.thread_total],
    ["last model call", usage.last_call],
  ];
  const container = $("usageCards");
  container.replaceChildren();
  groups.forEach(([title, values]) => {
    const card = document.createElement("article");
    card.className = "usage-card";
    const heading = document.createElement("h3");
    heading.textContent = title;
    card.append(heading);
    if (!values) {
      const unavailable = document.createElement("p");
      unavailable.textContent = "Unavailable: no reliable baseline.";
      unavailable.className = "usage-unavailable";
      card.append(unavailable);
    } else {
      const list = document.createElement("dl");
      [
        ["total", values.total_tokens],
        ["input", values.input_tokens],
        ["cached input", values.cached_input_tokens],
        ["cache write", values.cache_write_input_tokens],
        ["output", values.output_tokens],
        ["reasoning output", values.reasoning_output_tokens],
      ].forEach(([label, value]) => {
        const term = document.createElement("dt");
        term.textContent = label;
        const detail = document.createElement("dd");
        detail.textContent = formatNumber(value);
        list.append(term, detail);
      });
      card.append(list);
    }
    container.append(card);
  });
  if (usage.model_context_window !== undefined && usage.model_context_window !== null) {
    const context = document.createElement("p");
    context.className = "context-window";
    context.textContent = `model context window: ${formatNumber(usage.model_context_window)}`;
    container.append(context);
  }
}

function formatNumber(value) {
  return Number.isFinite(value) ? value.toLocaleString() : "—";
}

function handleMessage(message) {
  if (message.type === "connected") {
    $("connection").textContent = "codex.attaching";
    $("connection").className = "status status-warn";
    sendSocket({
      action: "attach",
      session_id: state.sessionId,
      run_id: state.runId,
    });
  } else if (message.type === "attached") {
    state.silenceWarningSeconds = message.silence_warning_seconds || 120;
    state.idleDiagnosticSeconds = message.idle_diagnostic_seconds || 300;
    $("connection").textContent = "codex.connected";
    $("connection").className = "status status-ok";
    sendSocket({ action: "models" });
  } else if (message.type === "models") {
    renderModels(message.models || []);
  } else if (message.type === "submitted") {
    state.runId = message.run_id;
    sessionStorage.setItem(RUN_KEY, state.runId);
  } else if (message.type === "codex_event") {
    state.lastEventAtMs = Date.now();
    state.liveness = "active";
    appendEvent(message.event);
  } else if (message.type === "run_snapshot") {
    output.textContent = message.replay_truncated ? "[earlier activity omitted]\n" : "";
    (message.events || []).forEach((item) => appendEvent(item.event || item));
    applyRun(message.run);
  } else if (message.type === "run_status") {
    applyRun(message.run);
  } else if (message.type === "approval_required") {
    state.approvals.set(String(message.approval.request_id), message.approval);
    state.runStatus = "waiting_for_approval";
    renderApprovals();
  } else if (message.type === "approval_resolved") {
    state.approvals.delete(String(message.request_id));
    renderApprovals();
    appendOutput(`\n[approval resolved: ${message.decision || "cleared"}]\n`);
  } else if (message.type === "turn_complete") {
    state.threadId = message.thread_id || state.threadId;
    if (state.threadId) sessionStorage.setItem(THREAD_KEY, state.threadId);
    state.runStatus = message.status;
    state.approvals.clear();
    renderApprovals();
    renderUsage(message.usage || {});
    $("interrupt").disabled = true;
    const detail = message.failure_code ? `; code=${message.failure_code}` : "";
    appendOutput(`\n[turn/completed: ${message.status}${detail}]\n`);
  } else if (message.type === "error") {
    setMessage(message.message, true);
    appendOutput(`\nERROR: ${message.message}\n`);
  }
}

function renderModels(models) {
  const selected = $("model").value;
  $("model").replaceChildren();
  models.forEach((model) => {
    const id = model.id || model.model || model.slug;
    const label = model.displayName || model.name || id;
    const option = document.createElement("option");
    option.value = id;
    option.textContent = label;
    $("model").append(option);
  });
  if (!models.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No models available";
    $("model").append(option);
  } else if (selected && models.some((model) => (model.id || model.model || model.slug) === selected)) {
    $("model").value = selected;
  }
}

function connectCodex() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/codex`);
  state.socket = socket;
  socket.onmessage = ({ data }) => handleMessage(JSON.parse(data));
  socket.onclose = () => {
    $("connection").textContent = state.runId && !terminalStatuses.has(state.runStatus)
      ? "codex.reconnecting · run preserved"
      : "codex.disconnected";
    $("connection").className = "status status-warn";
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(connectCodex, 1500);
  };
}

$("optimize").addEventListener("click", optimize);
$("prompt").addEventListener("input", updatePromptGutter);
$("useOriginal").addEventListener("click", () => submit("original"));
$("useCandidate").addEventListener("click", () => submit("candidate"));
$("interrupt").addEventListener("click", () => {
  if (state.runId) sendSocket({ action: "interrupt", run_id: state.runId });
});
$("autoSession").addEventListener("click", async () => {
  await saveSessionSettings({ approval_policy: "auto_verified" });
  setMessage("Auto-run is enabled for calibrated, verified candidates in this session.");
});
$("autoProject").addEventListener("click", async () => {
  await saveSessionSettings({ approval_policy: "auto_verified" }, "project");
  setMessage("Auto-run consent was saved locally for this project.");
});

setInterval(() => {
  if (
    state.runStatus === "running"
    && state.lastEventAtMs
    && Date.now() - state.lastEventAtMs > state.silenceWarningSeconds * 1000
  ) {
    const minutes = Math.floor((Date.now() - state.lastEventAtMs) / 60000);
    const prefix = state.liveness === "unresponsive" ? "running · unresponsive" : "running";
    $("runStatus").textContent = `${prefix} · no event for ${minutes}m`;
    $("runStatus").className = "run-state run-state-warning";
  }
  if (state.approvals.size) renderApprovals();
}, 1000);

updatePromptGutter();
connectCodex();
