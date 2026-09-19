/* Console agent Lasme — module ES autonome.
 * Consomme /api/agent/stream (SSE typés) et rend la timeline :
 * raisonnement repliable, cartes d'outils avec résultats, réponse finale. */

const timeline = document.getElementById("timeline");
const metricsEl = document.getElementById("metrics");
const modelSelect = document.getElementById("agent-model");
const turnsSelect = document.getElementById("agent-turns");
const composer = document.getElementById("composer");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const stopBtn = document.getElementById("stop");

let controller = null;
const history = []; // {role, content} — seuls les finals deviennent history

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

function addUserMessage(text) {
  timeline.appendChild(el("div", "user-msg", text));
  timeline.scrollTop = timeline.scrollHeight;
}

function newReasoningBlock() {
  const details = el("details", "ev-reasoning");
  details.open = false;
  const summary = el("summary", null, "Raisonnement");
  const pre = el("pre");
  details.append(summary, pre);
  timeline.appendChild(details);
  return pre;
}

function newToolCard(payload) {
  const details = el("details", "ev-tool");
  const summary = el("summary");
  const title = el("span", null, `Outil : ${payload.name || "?"}`);
  const meta = el("span", "meta", "…");
  summary.append(title, meta);
  const argsPre = el("pre", "args", prettyJson(payload.arguments));
  details.append(summary, argsPre);
  timeline.appendChild(details);
  details.payloadId = payload.id;
  return { details, meta };
}

function prettyJson(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return String(raw || "");
  }
}

function updateMetrics(extra) {
  const parts = [];
  if (extra) parts.push(extra);
  metricsEl.textContent = parts.join(" · ");
}

async function streamAgent(messages, model, maxTurns) {
  controller = new AbortController();
  stopBtn.hidden = false;
  sendBtn.disabled = true;

  let reasoningPre = null;
  let turnCount = 0;
  let reasoningChars = 0;
  const started = performance.now();
  const toolCards = new Map();
  let finalText = "";

  try {
    const response = await fetch("/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, model, max_turns: maxTurns }),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }
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
        let event;
        try { event = JSON.parse(data); } catch { continue; }

        switch (event.type) {
          case "turn_start":
            turnCount = event.turn;
            timeline.appendChild(el("div", "ev-turn", `Tour ${event.turn}`));
            reasoningPre = null;
            break;
          case "reasoning_delta":
            if (!reasoningPre) reasoningPre = newReasoningBlock();
            reasoningPre.textContent += event.text || "";
            reasoningChars += (event.text || "").length;
            timeline.scrollTop = timeline.scrollHeight;
            break;
          case "tool_call": {
            const card = newToolCard(event);
            toolCards.set(event.id ?? toolCards.size, card);
            timeline.scrollTop = timeline.scrollHeight;
            break;
          }
          case "tool_result": {
            const card = toolCards.get(event.id);
            const target = card || { details: null, meta: null };
            if (event.name === "budget_retried" || !event.name) {
              updateMetrics(`budget doublé → ${event.new_budget}`);
              break;
            }
            if (target.details) {
              target.details.classList.add(event.ok ? "ok" : "ko");
              if (!event.ok) {
                target.details.querySelector("summary").firstChild.textContent =
                  `Outil : ${event.name} — échec (${event.error_code})`;
              }
              const out = el("pre", "result");
              out.textContent = event.ok
                ? (event.output || "(vide)")
                : `${event.error_code}: ${event.error}`;
              target.details.appendChild(out);
              target.details.open = !event.ok;
            }
            if (target.meta) {
              target.meta.textContent = event.ok
                ? (event.duration_ms ? `${event.duration_ms} ms` : "< 5 ms")
                : "échec";
            }
            break;
          }
          case "final": {
            finalText = event.content || "";
            const box = el("div", "ev-final");
            box.innerHTML = renderMarkdownLite(finalText);
            timeline.appendChild(box);
            break;
          }
          case "agent_error":
            timeline.appendChild(
              el("div", "ev-error", `Erreur : ${event.message || event.code}`)
            );
            break;
        }
        if (event.type === "turn_end") {
          updateMetrics(
            `tour ${event.turn} : ${event.prompt_tokens}→${event.output_tokens} tokens (${event.done_reason})`
          );
        }
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
    promptEl.focus();
    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    updateMetrics(
      `${turnCount} tour(s) · ${reasoningChars} caractères de raisonnement · ${seconds} s`
    );
    if (finalText) {
      history.push({ role: "user", content: messages.at(-1).content });
      history.push({ role: "assistant", content: finalText });
    }
  }
}

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
    modelSelect.appendChild(el("option", null, "gemma-4-12b")).value = "gemma-4-12b";
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = promptEl.value.trim();
  if (!text || controller) return;
  promptEl.value = "";
  addUserMessage(text);
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

loadModels();
