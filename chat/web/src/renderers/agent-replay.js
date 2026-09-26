// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
const agentRunReplayCache = new Map();

function buildAgentReplaySummaryLabel(agentMeta) {
    const parts = [];
    const turns = Number(agentMeta?.turns);
    if (Number.isFinite(turns) && turns > 0) {
        parts.push(`${turns} tour${turns > 1 ? "s" : ""}`);
    }
    const tools = Array.isArray(agentMeta?.tools)
        ? agentMeta.tools.length
        : Number(agentMeta?.tools);
    if (Number.isFinite(tools) && tools > 0) {
        parts.push(`${tools} outil${tools > 1 ? "s" : ""}`);
    }
    return parts.length
        ? `Déroulé agent · ${parts.join(" · ")}`
        : "Déroulé agent";
}

function addAgentReplayAction(messageElement, agentMeta) {
    if (!messageElement || !agentMeta?.run_id) return;
    const actions = messageElement.querySelector(".message-actions");
    if (!actions || actions.querySelector("[data-action=\"agent-replay\"]")) {
        return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "message-action-btn";
    button.dataset.action = "agent-replay";
    button.dataset.tooltip = "Déroulé agent";
    button.title = "Déroulé agent";
    button.setAttribute("aria-label", "Déroulé agent");
    button.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"></path>
        </svg>
        <span class="sr-only">Déroulé agent</span>
    `;
    button.addEventListener("click", () => {
        void toggleAgentReplayPanel(messageElement, agentMeta);
    });
    actions.appendChild(button);
}

async function toggleAgentReplayPanel(messageElement, agentMeta) {
    const bubble = messageElement.querySelector(".bubble");
    if (!bubble) return;
    const existing = bubble.querySelector(".replay-panel");
    if (existing) {
        existing.remove();
        return;
    }
    const panel = document.createElement("details");
    panel.className = "replay-panel";
    panel.open = true;
    const summary = document.createElement("summary");
    summary.textContent = buildAgentReplaySummaryLabel(agentMeta);
    const body = document.createElement("div");
    body.className = "replay-panel-body";
    body.innerHTML = `
        <div class="replay-panel-status">
            <span class="tool-spinner" aria-hidden="true"></span>
            Chargement du déroulé…
        </div>
    `;
    panel.append(summary, body);
    bubble.appendChild(panel);

    const runId = String(agentMeta.run_id);
    // window.fetch is globally wrapped (top of app.js): the X-Lasme-Token
    // header is injected automatically for same-origin /api/ requests.
    let events = agentRunReplayCache.get(runId);
    if (!events) {
        try {
            const resp = await fetch(
                `${API_BASE}/agent/runs/${encodeURIComponent(runId)}`
            );
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const run = await resp.json();
            events = Array.isArray(run?.events) ? run.events : [];
            agentRunReplayCache.set(runId, events);
        } catch (err) {
            if (!panel.isConnected) return;
            body.textContent = "";
            const errorLine = document.createElement("div");
            errorLine.className = "replay-panel-status replay-panel-error";
            errorLine.textContent = `Déroulé indisponible (${
                err.message || "erreur réseau"
            })`;
            body.appendChild(errorLine);
            return;
        }
    }
    if (!panel.isConnected) return;
    renderAgentReplayEvents(body, events);
}

function renderAgentReplayEvents(body, events) {
    body.textContent = "";
    const cards = new Map();
    let rendered = 0;
    for (const event of Array.isArray(events) ? events : []) {
        if (event.type === "turn_start") {
            const row = document.createElement("div");
            row.className = "replay-turn";
            row.textContent = `Tour ${event.turn ?? "?"}`;
            body.appendChild(row);
            rendered++;
            continue;
        }
        if (event.type === "tool_call") {
            const card = document.createElement("details");
            card._lasmeCall = event;
            fillAgentToolCard(card, event, null);
            // Unresolved call in a stored run: no spinner, neutral meta.
            card.classList.remove("pending");
            const spinner = card.querySelector(".tool-spinner");
            spinner?.remove();
            const meta = card.querySelector(".agent-tool-meta");
            if (meta) meta.textContent = "—";
            cards.set(event.id ?? `call-${cards.size}`, card);
            body.appendChild(card);
            rendered++;
            continue;
        }
        if (event.type === "tool_result") {
            let card = null;
            if (event.id !== undefined && event.id !== null) {
                card = cards.get(event.id) || null;
            }
            if (!card) {
                card = [...cards.values()].find(
                    (candidate) => !candidate._lasmeResult
                ) || null;
            }
            if (!card) {
                card = document.createElement("details");
                body.appendChild(card);
            }
            card._lasmeResult = event;
            fillAgentToolCard(
                card,
                card._lasmeCall || { name: event.name },
                event
            );
            rendered++;
        }
        // "final" (and any other event) is ignored: the message already
        // displays the assistant's answer.
    }
    if (!rendered) {
        body.textContent = "Aucun événement enregistré pour ce run.";
    }
}

