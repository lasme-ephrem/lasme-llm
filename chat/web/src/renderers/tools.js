// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
const TOOL_ICONS = {
    web_research: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10" cy="10.2" r="6.2"></circle><path d="m14.6 14.8 4.9 4.7"></path><circle cx="7.7" cy="9.2" r="0.9"></circle><circle cx="11.8" cy="8.6" r="0.9"></circle><circle cx="10" cy="12.3" r="0.9"></circle></svg>`,
    web_read: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3.5H7.2A1.7 1.7 0 0 0 5.5 5.2v13.6A1.7 1.7 0 0 0 7.2 20.5h9.6a1.7 1.7 0 0 0 1.7-1.7V8z"></path><path d="M14 3.5V8h4.5"></path><path d="M12 11v5"></path><path d="m9.5 14.2 2.5 2.5 2.5-2.5"></path></svg>`,
    library_docs: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4.5h14.2a1 1 0 0 1 1 1V8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1z"></path><path d="M5 10.2h14.2a1 1 0 0 1 1 1v2.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-2.5a1 1 0 0 1 1-1z"></path><path d="M5 15.8h14.2a1 1 0 0 1 1 1v2.2a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-2.2a1 1 0 0 1 1-1z"></path><path d="M8 4.5v4.5M8 10.2v4.5M8 15.8V20"></path></svg>`,
    github_search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M8.6 8.7 7.5 6.2l1.9.8M15.4 8.7l1.1-2.5-1.9.8"></path><circle cx="12" cy="11.3" r="2.9"></circle><path d="M10.7 11.05h.4M13.3 11.05h.4"></path><path d="M10.8 12.7c.35.4.75.6 1.2.6s.85-.2 1.2-.6"></path><path d="M9.5 15.2c.45 1.7 1.35 2.6 2.5 2.6s2.05-.9 2.5-2.6"></path></svg>`,
    github_read_file: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4.2h4.4L13 6.8v10.6a1.3 1.3 0 0 1-1.3 1.3H6A1.3 1.3 0 0 1 4.7 17.4V5.5A1.3 1.3 0 0 1 6 4.2z"></path><path d="M10.4 4.3V6.9H13"></path><path d="M6.7 10.4h3.2M6.7 13h2"></path><circle cx="19.3" cy="5.4" r="1.4"></circle><circle cx="19.3" cy="18.5" r="1.4"></circle><circle cx="15.8" cy="12" r="1.4"></circle><path d="M19.3 6.8v10.3"></path><path d="M19.3 8.5c-1.2 1-2.1 2-2.1 3.5"></path></svg>`,
    repo_status: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="5.5" r="2.15"></circle><circle cx="6" cy="18.5" r="2.15"></circle><circle cx="18" cy="12" r="2.15"></circle><path d="M6 7.65v8.7"></path><path d="M6 9.6c3.6.2 6.4 1 9.85 2.4"></path></svg>`,
    workspace_list: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8.2V6.4A1.5 1.5 0 0 1 5.5 4.9h2.8l1.6 1.7H19a1.5 1.5 0 0 1 1.5 1.6"></path><path d="M3.4 8.6h17.4l-1.5 8.6a1.6 1.6 0 0 1-1.6 1.3H6.4a1.6 1.6 0 0 1-1.6-1.3z"></path></svg>`,
    workspace_read: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="3.5" width="14" height="17" rx="2"></rect><path d="M8 8.2h8M8 12h8M8 15.8h5"></path></svg>`,
    workspace_search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 8V6.3A1.4 1.4 0 0 1 4.6 4.9h2.4l1.5 1.6h3.3"></path><path d="M3.2 8h8.2l-.8 8.2a1.4 1.4 0 0 1-1.4 1.3H5.3a1.4 1.4 0 0 1-1.4-1.4z"></path><circle cx="16.7" cy="15.2" r="3.1"></circle><path d="m19 17.5 2.5 2.5"></path></svg>`,
    query_data: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="6.5" rx="7" ry="2.6"></ellipse><path d="M5 6.5v11c0 1.45 3.1 2.6 7 2.6s7-1.15 7-2.6v-11"></path><path d="M5 12c0 1.45 3.1 2.6 7 2.6s7-1.15 7-2.6"></path></svg>`,
    render_chart: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.2h16.5"></path><rect x="6" y="11.2" width="3.1" height="8" rx="0.5"></rect><rect x="10.45" y="6.4" width="3.1" height="12.8" rx="0.5"></rect><rect x="14.9" y="13.4" width="3.1" height="5.8" rx="0.5"></rect></svg>`,
    convert_time: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="12" r="5.6"></circle><path d="M9 9.2V12l2 1.3"></path><path d="M15.7 8.7h5.3"></path><path d="m18.8 6.6 2.2 2.1-2.2 2.1"></path></svg>`,
    python_run: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4 17 6-6-6-6"></path><path d="M12 19h8"></path></svg>`,
    calculate: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 4H6l6 8-6 8h12"></path></svg>`,
    analyze_image: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"></path><circle cx="12" cy="12" r="3"></circle></svg>`,
    artifact_create: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"></path><path d="M14 3v5h5"></path><path d="M12 12v6M9 15h6"></path></svg>`,
    artifact_update: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l4 4v3.5"></path><path d="M14 3v5h5"></path><path d="m12.5 18.5 6-6 2 2-6 6h-2z"></path></svg>`,
    artifacts_list: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M7 13h6"></path></svg>`,
    rag_search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"></path></svg>`,
    files_list: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path></svg>`,
    files_read_text: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"></path><path d="M14 3v5h5"></path><path d="M9 13h6M9 17h4"></path></svg>`,
    current_time: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>`,
    echo: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12h3l3-8 4 16 3-11 2 3h5"></path></svg>`
};
// web_search / fetch_pages : mêmes pictogrammes que les outils renommés.
TOOL_ICONS.web_search = TOOL_ICONS.web_research;
TOOL_ICONS.fetch_pages = TOOL_ICONS.web_read;

const TOOL_ICON_DEFAULT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>`;

const TOOL_LABELS = {
    web_research: "Recherche web",
    web_read: "Lecture de pages",
    library_docs: "Documentation",
    github_search: "GitHub",
    github_read_file: "Fichier GitHub",
    repo_status: "Dépôt Git",
    workspace_list: "Dossier de travail",
    workspace_read: "Fichier local",
    workspace_search: "Recherche de fichiers",
    query_data: "Données",
    render_chart: "Graphique",
    convert_time: "Fuseau horaire",
    python_run: "Python",
    calculate: "Calcul",
    analyze_image: "Vision",
    artifact_create: "Nouvel artefact",
    artifact_update: "Artefact",
    artifacts_list: "Artefacts",
    rag_search: "Documents",
    files_list: "Fichiers du projet",
    files_read_text: "Lecture projet",
    current_time: "Heure",
    echo: "Écho"
};
TOOL_LABELS.web_search = TOOL_LABELS.web_research;
TOOL_LABELS.fetch_pages = TOOL_LABELS.web_read;

const TOOL_CATEGORIES = {
    web_research: "network",
    web_read: "network",
    web_search: "network",
    fetch_pages: "network",
    github_search: "network",
    github_read_file: "network",
    library_docs: "knowledge",
    rag_search: "knowledge",
    python_run: "code",
    repo_status: "code",
    echo: "code",
    query_data: "data",
    calculate: "data",
    render_chart: "data",
    workspace_list: "files",
    workspace_read: "files",
    workspace_search: "files",
    files_list: "files",
    files_read_text: "files",
    artifact_create: "files",
    artifact_update: "files",
    artifacts_list: "files",
    current_time: "time",
    convert_time: "time",
    analyze_image: "vision"
};

function toolIconSvg(name) {
    return TOOL_ICONS[String(name || "").trim()] || TOOL_ICON_DEFAULT;
}

function toolLabel(name) {
    const key = String(name || "").trim();
    return TOOL_LABELS[key] || key || "?";
}

function toolCategory(name) {
    const key = String(name || "").trim();
    if (TOOL_CATEGORIES[key]) return TOOL_CATEGORIES[key];
    if (
        key.startsWith("workspace_")
        || key.startsWith("files_")
        || key.startsWith("artifact")
    ) {
        return "files";
    }
    return "";
}

function extractToolOutputExtras(raw) {
    const source = raw == null ? "" : String(raw);
    const engines = [];
    let intent = "";
    const kept = [];
    for (const line of source.split(/\r?\n/)) {
        const trimmed = line.trim();
        const enginesMatch = /^Moteurs\s*:\s*(.*)$/.exec(trimmed);
        if (enginesMatch) {
            for (const part of enginesMatch[1].split(/\s*[\u00b7\u2022\u2219]\s*/)) {
                const engine = part.trim();
                if (engine && !engines.includes(engine)) engines.push(engine);
            }
            continue;
        }
        const intentMatch = /^Intention\s*:\s*(.*)$/.exec(trimmed);
        if (intentMatch) {
            const value = intentMatch[1].trim();
            if (value && !intent) intent = value;
            continue;
        }
        kept.push(line);
    }
    return {
        engines,
        intent,
        text: kept.join("\n").replace(/^\n+|\n+$/g, "")
    };
}

function isToolChartHost(hostname) {
    const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
    if (
        host === "mdn.alipayobjects.com"
        || host.endsWith(".mdn.alipayobjects.com")
    ) {
        return true;
    }
    return host.split(".").some((label) => (
        label.includes("antv") || label.includes("quickchart")
    ));
}

function findToolChartUrl(raw) {
    const source = raw == null ? "" : String(raw);
    const matches = source.match(/https:\/\/[^\s<>]+/gi);
    if (!matches) return "";
    for (const candidate of matches) {
        const cleaned = candidate.replace(/[)\].,;:!?»«"'`]+$/g, "");
        let url;
        try {
            url = new URL(cleaned);
        } catch {
            continue;
        }
        if (url.protocol !== "https:") continue;
        const path = url.pathname.toLowerCase();
        const isImage = /\.(?:png|jpe?g|svg|webp)$/.test(path);
        if (!isImage && !isToolChartHost(url.hostname)) continue;
        return cleaned;
    }
    return "";
}

function appendToolChart(card, raw) {
    const src = findToolChartUrl(raw);
    if (!src) return;
    const image = document.createElement("img");
    image.className = "agent-tool-chart";
    image.alt = "Graphique";
    image.addEventListener("error", () => image.remove());
    image.src = src;
    card.appendChild(image);
}

function fillAgentToolCard(card, call, result) {
    card.textContent = "";
    if (call?.id !== undefined && call?.id !== null) {
        card.dataset.toolId = String(call.id);
    }
    card.className = "agent-tool-card " + (
        result ? (result.ok ? "ok settled" : "ko settled") : "pending"
    );

    const toolName = String(call?.name || "").trim();
    const category = toolCategory(toolName);
    if (category) card.dataset.category = category;
    else delete card.dataset.category;

    const summary = document.createElement("summary");
    const iconSpan = document.createElement("span");
    iconSpan.className = "agent-tool-icon";
    iconSpan.setAttribute("aria-hidden", "true");
    if (category) iconSpan.dataset.category = category;
    iconSpan.innerHTML = toolIconSvg(toolName);
    summary.appendChild(iconSpan);
    if (!result) {
        const spinner = document.createElement("span");
        spinner.className = "tool-spinner";
        spinner.setAttribute("aria-hidden", "true");
        summary.appendChild(spinner);
    }
    const heading = document.createElement("span");
    heading.className = "agent-tool-heading";
    const nameSpan = document.createElement("span");
    nameSpan.className = "agent-tool-name";
    nameSpan.textContent = toolLabel(toolName);
    const idSpan = document.createElement("span");
    idSpan.className = "agent-tool-id";
    idSpan.textContent = toolName || "?";
    heading.append(nameSpan, idSpan);
    const metaSpan = document.createElement("span");
    metaSpan.className = "agent-tool-meta";
    metaSpan.textContent = result
        ? (result.ok
            ? (result.duration_ms ? `${result.duration_ms} ms` : "< 5 ms")
            : (result.error_code || "échec"))
        : "en cours…";
    summary.append(heading, document.createTextNode(" — "), metaSpan);
    card.appendChild(summary);

    const args = document.createElement("pre");
    args.className = "agent-tool-args";
    try {
        args.textContent = JSON.stringify(
            JSON.parse(call?.arguments || "{}"), null, 2
        );
    } catch {
        args.textContent = call?.arguments || "";
    }
    card.appendChild(args);

    if (result) {
        if (result.ok) {
            const extras = extractToolOutputExtras(result.output);
            if (extras.engines.length || extras.intent) {
                const chips = document.createElement("div");
                chips.className = "agent-tool-chips";
                for (const engine of extras.engines) {
                    const chip = document.createElement("span");
                    chip.className = "tool-engine";
                    chip.textContent = engine;
                    chips.appendChild(chip);
                }
                if (extras.intent) {
                    const intentChip = document.createElement("span");
                    intentChip.className = "tool-intent";
                    intentChip.textContent = extras.intent;
                    chips.appendChild(intentChip);
                }
                summary.appendChild(chips);
            }
            if (extras.text || (!extras.engines.length && !extras.intent)) {
                const output = document.createElement("pre");
                output.className = "agent-tool-output";
                output.textContent = extras.text || "(vide)";
                card.appendChild(output);
            }
            appendToolChart(card, result.output);
        } else {
            const output = document.createElement("pre");
            output.className = "agent-tool-output";
            output.textContent = `${result.error_code || "erreur"} : ${result.error || ""}`;
            card.appendChild(output);
            card.open = true;
        }
    }
    return card;
}

function ensureAgentToolsGroup(container) {
    let group = container.querySelector(":scope > .agent-tools-group");
    if (!group) {
        const typingIndicator = container.querySelector(".typing-indicator");
        if (typingIndicator) typingIndicator.remove();
        group = document.createElement("div");
        group.className = "agent-tools-group";
        const label = document.createElement("div");
        label.className = "agent-tools-label";
        label.textContent = "Outils";
        group.appendChild(label);
        container.prepend(group);
    }
    return group;
}

// Live rendering: one card per agent_tool_call, updated in place as soon as
// the matching agent_tool_result arrives. The canonical rebuild still happens
// in renderAgentToolsSummary at onComplete (after the final message render).
function upsertLiveAgentToolCard(container, event) {
    const group = ensureAgentToolsGroup(container);
    if (event.type === "agent_tool_call") {
        const card = document.createElement("details");
        card._lasmeCall = event;
        fillAgentToolCard(card, event, null);
        group.appendChild(card);
        return;
    }
    let card = null;
    if (event.id !== undefined && event.id !== null) {
        card = group.querySelector(
            `.agent-tool-card[data-tool-id="${CSS.escape(String(event.id))}"]`
        );
    }
    if (!card) {
        card = group.querySelector(".agent-tool-card.pending");
    }
    if (!card) {
        card = document.createElement("details");
        group.appendChild(card);
    }
    const call = card._lasmeCall || { name: event.name };
    fillAgentToolCard(card, call, event);
    // Completion feedback: soft pop on success, light shake on failure.
    // Only on the live update path, never on the canonical rebuild.
    card.classList.add(event.ok ? "anim-pop" : "anim-shake");
    card.addEventListener(
        "animationend",
        () => card.classList.remove("anim-pop", "anim-shake"),
        { once: true }
    );
}

function renderAgentToolsSummary(container, events) {
    container.querySelector(".agent-tools-group")?.remove();
    const calls = new Map();
    for (const event of events) {
        if (event.type === "agent_tool_call") {
            calls.set(event.id ?? calls.size, { call: event, result: null });
        } else if (event.type === "agent_tool_result") {
            const entry = calls.get(event.id)
                || [...calls.values()].find((candidate) => !candidate.result);
            if (entry) entry.result = event;
        }
    }
    if (!calls.size) return;
    const group = document.createElement("div");
    group.className = "agent-tools-group no-anim";
    const label = document.createElement("div");
    label.className = "agent-tools-label";
    label.textContent = "Outils";
    group.appendChild(label);
    for (const { call, result } of calls.values()) {
        group.appendChild(
            fillAgentToolCard(document.createElement("details"), call, result)
        );
    }
    container.querySelector(".assistant-activity[data-kind=\"tools\"]")?.remove();
    container.prepend(group);
}

