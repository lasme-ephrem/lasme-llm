/* Console agent Lasme — module ES autonome.
 * Live via /api/agent/stream (SSE typés) et replay des runs persistés
 * (/api/agent/runs) via le même TimelineRenderer. */

const timeline = document.getElementById("timeline");
const metricsEl = document.getElementById("metrics");
const modelSelect = document.getElementById("agent-model");
const turnsSelect = document.getElementById("agent-turns");
const composer = document.getElementById("composer");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const stopBtn = document.getElementById("stop");
const historyList = document.getElementById("historyList");
const newRunBtn = document.getElementById("newRunBtn");
const historyToggle = document.getElementById("historyToggle");

let controller = null;
let replayMode = false;
const history = []; // {role, content} — seuls les finals alimentent le contexte

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderMarkdownLite(text) {
  const codeBlocks = [];
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
    return `\u0000${codeBlocks.length - 1}\u0000`;
  });
  html = html
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\n/g, "<br>");
  html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => codeBlocks[Number(i)]);
  return html;
}

function prettyJson(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return String(raw || "");
  }
}

class TimelineRenderer {
  constructor() {
    this.reset();
  }

  reset() {
    this.reasoningPre = null;
    this.toolCards = new Map();
    this.turnCount = 0;
    this.reasoningChars = 0;
    this.finalText = "";
  }

  addUserMessage(text) {
    timeline.appendChild(el("div", "user-msg", text));
    timeline.scrollTop = timeline.scrollHeight;
  }

  _newReasoningBlock() {
    const details = el("details", "ev-reasoning");
    details.open = false;
    const pre = el("pre");
    details.append(el("summary", null, "Raisonnement"), pre);
    timeline.appendChild(details);
    return pre;
  }

  _newToolCard(payload) {
    const details = el("details", "ev-tool");
    const summary = el("summary");
    summary.append(el("span", null, `Outil : ${payload.name || "?"}`));
    const meta = el("span", "meta", "…");
    summary.append(meta);
    details.append(summary, el("pre", "args", prettyJson(payload.arguments)));
    timeline.appendChild(details);
    return { details, meta };
  }

  apply(event) {
    switch (event.type) {
      case "turn_start":
        this.turnCount = event.turn;
        timeline.appendChild(el("div", "ev-turn", `Tour ${event.turn}`));
        this.reasoningPre = null;
        break;
      case "reasoning_delta":
        if (!this.reasoningPre) this.reasoningPre = this._newReasoningBlock();
        this.reasoningPre.textContent += event.text || "";
        this.reasoningChars += (event.text || "").length;
        timeline.scrollTop = timeline.scrollHeight;
        break;
      case "tool_call": {
        const card = this._newToolCard(event);
        this.toolCards.set(event.id ?? this.toolCards.size, card);
        timeline.scrollTop = timeline.scrollHeight;
        break;
      }
      case "tool_result": {
        if (!event.name && event.new_budget) {
          this._metric(`budget doublé → ${event.new_budget}`);
          break;
        }
        const card = this.toolCards.get(event.id) || {};
        if (card.details) {
          card.details.classList.add(event.ok ? "ok" : "ko");
          if (!event.ok) {
            card.details.querySelector("summary").firstChild.textContent =
              `Outil : ${event.name} — échec (${event.error_code})`;
          }
          const out = el("pre", "result");
          out.textContent = event.ok
            ? (event.output || "(vide)")
            : `${event.error_code}: ${event.error}`;
          card.details.appendChild(out);
          if (!event.ok) card.details.open = true;
        }
        if (card.meta) {
          card.meta.textContent = event.ok
            ? (event.duration_ms ? `${event.duration_ms} ms` : "< 5 ms")
            : "échec";
        }
        break;
      }
      case "content_delta":
        /* contenu final : rendu en bloc à l'événement final */
        break;
      case "final": {
        this.finalText = event.content || "";
        const box = el("div", "ev-final");
        box.innerHTML = renderMarkdownLite(this.finalText);
        timeline.appendChild(box);
        timeline.scrollTop = timeline.scrollHeight;
        break;
      }
      case "agent_error":
        timeline.appendChild(
          el("div", "ev-error", `Erreur : ${event.message || event.code}`)
        );
        break;
    }
  }

  _metric(extra) {
    metricsEl.textContent = extra;
  }

  summarize(seconds) {
    const suffix = seconds != null ? ` · ${seconds.toFixed ? seconds.toFixed(1) : seconds} s` : "";
    metricsEl.textContent =
      `${this.turnCount} tour(s) · ${this.reasoningChars} caractères de raisonnement${suffix}`;
  }
}

function clearTimeline() {
  timeline.innerHTML = "";
  metricsEl.textContent = "";
}

/* ------------------------------------------------------------- live runs */

async function streamAgent(messages, model, maxTurns) {
  controller = new AbortController();
  stopBtn.hidden = false;
  sendBtn.disabled = true;
  const renderer = new TimelineRenderer();
  const started = performance.now();

  try {
    const response = await fetch("/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, model, max_turns: maxTurns }),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const line = raw.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const data = line.slice(6);
        if (data === "[DONE]") continue;
        try { renderer.apply(JSON.parse(data)); } catch { /* chunk partiel */ }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      timeline.appendChild(el("div", "ev-error", `Connexion interrompue : ${error.message}`));
    }
  } finally {
    controller = null;
    stopBtn.hidden = true;
    sendBtn.disabled = false;
    renderer.summarize((performance.now() - started) / 1000);
    if (renderer.finalText) {
      history.push({ role: "user", content: messages.at(-1).content });
      history.push({ role: "assistant", content: renderer.finalText });
    }
    loadHistory();
  }
}

/* ------------------------------------------------------------- replay */

async function replayRun(runId) {
  replayMode = true;
  try {
    const response = await fetch(`/api/agent/runs/${runId}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const run = await response.json();
    clearTimeline();
    const renderer = new TimelineRenderer();
    renderer.addUserMessage(run.prompt || "(mission)");
    for (const event of run.events || []) renderer.apply(event);
    renderer.summarize(null);
  } catch (error) {
    metricsEl.textContent = `Replay impossible : ${error.message}`;
  }
}

async function loadHistory() {
  try {
    const response = await fetch("/api/agent/runs?limit=25");
    const data = await response.json();
    historyList.innerHTML = "";
    for (const run of data.runs || []) {
      const item = el("div", "history-item");
      const title = el("div", "history-title", run.prompt || "(sans titre)");
      const meta = el("div", "history-meta",
        `${(run.model || "").replace("gemma-4-", "")} · ${run.turns} tour(s)`);
      item.append(title, meta);
      item.addEventListener("click", () => {
        document.querySelectorAll(".history-item.selected")
          .forEach(node => node.classList.remove("selected"));
        item.classList.add("selected");
        replayRun(run.id);
      });
      historyList.appendChild(item);
    }
  } catch {
    historyList.textContent = "Historique indisponible.";
  }
}

/* ------------------------------------------------------------- bootstrap */

async function loadModels() {
  try {
    const response = await fetch("/api/models");
    const data = await response.json();
    const preferred = ["gemma-4-12b", "gemma-4-e4b", "gemma-4-e2b", "gemma-4-12b-256k"];
    const models = (data.models || [])
      .map((m) => m.name || m.model)
      .filter(Boolean)
      .sort((a, b) => preferred.indexOf(a) - preferred.indexOf(b));
    for (const name of models) {
      const option = el("option", null, name);
      option.value = name;
      modelSelect.appendChild(option);
    }
    modelSelect.value = models.includes("gemma-4-12b")
      ? "gemma-4-12b"
      : models[0] || "gemma-4-12b";
  } catch {
    modelSelect.value = "gemma-4-12b";
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = promptEl.value.trim();
  if (!text || controller) return;
  replayMode = false;
  promptEl.value = "";
  clearTimeline();
  const renderer = new TimelineRenderer();
  renderer.addUserMessage(text);
  const messages = [...history, { role: "user", content: text }];
  streamAgent(messages, modelSelect.value, Number(turnsSelect.value));
});

promptEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

stopBtn.addEventListener("click", () => {
  if (controller) controller.abort();
});

newRunBtn.addEventListener("click", () => {
  replayMode = false;
  clearTimeline();
  history.length = 0;
  promptEl.focus();
});

historyToggle?.addEventListener("click", () => {
  document.querySelector(".agent-history")?.classList.toggle("open");
});

loadModels();
loadHistory();
