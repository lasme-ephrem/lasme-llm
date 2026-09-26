// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
function formatThinkingDuration(duration) {
    const seconds = Number(duration);
    if (!Number.isFinite(seconds) || seconds <= 0) return "";
    return `${String(Math.round(seconds * 10) / 10).replace(".", ",")} s`;
}

const THINKING_CHEVRON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 6 15 12 9 18"></polyline></svg>`;

function ensureThinkingPanel(bubble) {
    let panel = bubble.querySelector(":scope > .thinking-panel");
    if (panel) return panel;
    const typingIndicator = bubble.querySelector(".typing-indicator");
    if (typingIndicator) typingIndicator.remove();

    panel = document.createElement("div");
    panel.className = "thinking-panel streaming";
    panel.dataset.mode = "stream";

    const header = document.createElement("button");
    header.type = "button";
    header.className = "thinking-header";
    const chevron = document.createElement("span");
    chevron.className = "thinking-chevron";
    chevron.innerHTML = THINKING_CHEVRON;
    const label = document.createElement("span");
    label.className = "thinking-label";
    label.textContent = "Réflexion…";
    const duration = document.createElement("span");
    duration.className = "thinking-duration";
    header.append(chevron, label, duration);

    const window_ = document.createElement("div");
    window_.className = "thinking-window";
    const pre = document.createElement("pre");
    pre.className = "thinking-text";
    window_.appendChild(pre);

    header.addEventListener("click", () => {
        if (panel.classList.contains("streaming")) return;
        // The user takes over: cancel any pending auto-collapse.
        if (panel._lasmeCollapseTimer) {
            clearTimeout(panel._lasmeCollapseTimer);
            panel._lasmeCollapseTimer = null;
        }
        setThinkingMode(
            panel,
            panel.dataset.mode === "full" ? "closed" : "full"
        );
    });
    panel.append(header, window_);

    // Panel sits above the answer content, below the live tool cards.
    const toolsGroup = bubble.querySelector(":scope > .agent-tools-group");
    if (toolsGroup) {
        toolsGroup.after(panel);
    } else {
        const answer = bubble.querySelector(":scope > .answer-content");
        if (answer) answer.before(panel);
        else bubble.prepend(panel);
    }
    return panel;
}

function setThinkingMode(panel, mode) {
    panel.dataset.mode = mode;
}

function startThinkingPhrases(panel) {
    const label = panel.querySelector(".thinking-label");
    if (label) label.textContent = "Réflexion…";
}

function stopThinkingPhrases(panel) {
    if (panel._lasmePhraseTimer) {
        window.clearInterval(panel._lasmePhraseTimer);
        panel._lasmePhraseTimer = null;
    }
}

function handleReasoningStart(bubble) {
    const panel = ensureThinkingPanel(bubble);
    if (panel._lasmeCollapseTimer) {
        clearTimeout(panel._lasmeCollapseTimer);
        panel._lasmeCollapseTimer = null;
    }
    panel.classList.add("streaming");
    setThinkingMode(panel, "stream");
    startThinkingPhrases(panel);
    const pre = panel.querySelector(".thinking-text");
    // A second reasoning run in the same bubble: keep prior text, add a gap.
    if (pre && pre.textContent) pre.textContent += "\n\n";
}

function appendReasoningDelta(bubble, text) {
    const value = String(text || "");
    if (!value) return;
    const panel = ensureThinkingPanel(bubble);
    const window_ = panel.querySelector(".thinking-window");
    const pre = panel.querySelector(".thinking-text");
    if (!pre || !window_) return;
    // Follow the stream only if the user did not scroll away.
    const follow = window_.scrollTop + window_.clientHeight
        >= window_.scrollHeight - 24;
    pre.textContent += value;
    pre.classList.toggle(
        "is-scrollable",
        pre.scrollHeight > pre.clientHeight + 4
    );
    if (follow) window_.scrollTop = window_.scrollHeight;
}

function handleReasoningDone(bubble, duration) {
    const panel = bubble.querySelector(":scope > .thinking-panel");
    if (!panel) return;
    panel.classList.remove("streaming");
    stopThinkingPhrases(panel);
    const label = panel.querySelector(".thinking-label");
    const durationText = formatThinkingDuration(duration);
    if (label) {
        label.textContent = durationText
            ? `A réfléchi pendant ${durationText}`
            : "A réfléchi";
    }
    const durationEl = panel.querySelector(".thinking-duration");
    if (durationEl) durationEl.textContent = "";
    const pre = panel.querySelector(".thinking-text");
    const delay = pre && pre.textContent.length > 240 ? 350 : 1600;
    if (panel._lasmeCollapseTimer) {
        clearTimeout(panel._lasmeCollapseTimer);
    }
    panel._lasmeCollapseTimer = window.setTimeout(() => {
        panel._lasmeCollapseTimer = null;
        // Full collapse: only the header ("Réflexion · X,X s") stays visible;
        // the answer takes over the conversation flow.
        setThinkingMode(panel, "closed");
    }, delay);
}

// content_reset: the streamed text so far was NOT the final response
// (draft before tool calls, answer rejected by the harness, retried turn).
// UX guarantee: it is NEVER erased from the screen — LasmeAnswerStream
// folds it into a collapsible work note, and only the final answer takes
// the answer zone.
function archiveStreamedAnswer(bubble, draftText, reason) {
    window.LasmeProgressiveRenderer?.cancel(bubble);
    if (window.LasmeAnswerStream) {
        window.LasmeAnswerStream.foldIntoWorkNote(bubble, draftText, reason);
    } else {
        bubble.querySelector(".answer-content")?.remove();
    }
    bubble.querySelector(".generation-performance")?.remove();
    bubble.querySelector(".generated-image-card")?.remove();
    bubble.querySelector(".dalle-loader-card")?.remove();

    const panel = ensureThinkingPanel(bubble);
    if (panel._lasmeCollapseTimer) {
        clearTimeout(panel._lasmeCollapseTimer);
        panel._lasmeCollapseTimer = null;
    }
    stopThinkingPhrases(panel);
    panel.classList.remove("streaming");
    const label = panel.querySelector(".thinking-label");
    if (label) label.textContent = "A réfléchi";
    // The draft lives in the work note now (no "— préambule —" duplicate):
    // back to the collapsed state.
    setThinkingMode(panel, "closed");
}

// Inline SVG icons per agent tool (stroke: currentColor, round joins).
