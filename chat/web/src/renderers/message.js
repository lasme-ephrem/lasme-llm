// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
function renderAssistantActivity(container, kind, state, title, detail = "") {
    const selector = `.assistant-activity[data-kind="${kind}"]`;
    let activity = container.querySelector(selector);
    if (!activity) {
        const typingIndicator = container.querySelector(".typing-indicator");
        if (typingIndicator) typingIndicator.remove();

        activity = document.createElement("div");
        activity.className = "assistant-activity";
        activity.dataset.kind = kind;
        container.prepend(activity);
    }

    activity.dataset.state = state;
    const icon = kind === "web" ? "◎" : "✦";
    const spinner = state === "active"
        ? `<span class="activity-spinner" aria-hidden="true"></span>`
        : "";
    const safeDetail = escapeHtml(detail || "");
    activity.innerHTML = `
        <div class="assistant-activity-title">
            <span class="assistant-activity-icon">${icon}</span>
            <span>${escapeHtml(title)}</span>
            ${spinner}
        </div>
        ${safeDetail ? `<div class="assistant-activity-detail">${safeDetail}</div>` : ""}
    `;
}

// ---------------------------------------------------------------------------
// Streaming reasoning panel ("Réflexion").
// One <details class="thinking-panel"> per assistant bubble, created on
// reasoning_start, fed by reasoning_delta, auto-collapsed on reasoning_done.
// content_reset moves the wrongly-streamed answer text into the same panel.
// ---------------------------------------------------------------------------

function renderFullAssistantMessage(container, rawText, webResults, thinkingDuration = null) {
    rawText = cleanModelText(rawText);
    container._lasmeRawContent = rawText;
    let thinkingContent = "";
    let mainAnswer = (rawText || "")
        .replace(/<think>[\s\S]*?<\/think>/gi, "")
        .replace(/<think>[\s\S]*$/gi, "")
        .trim();
    let isThinkingActive = false;

    // Strip raw text "### Références" block at the end if the model outputted one
    mainAnswer = mainAnswer.replace(/(###?\s*(Références|Sources)[\s\S]*)/i, "").trim();

    // Extract <think> ... </think> or active <think>
    if (false && rawText.includes("<think>")) {
        if (rawText.includes("</think>")) {
            const parts = rawText.split("</think>");
            thinkingContent = parts[0].replace("<think>", "").trim();
            mainAnswer = parts.slice(1).join("</think>").trim();
            mainAnswer = mainAnswer.replace(/(###?\s*(Références|Sources)[\s\S]*)/i, "").trim();

            // FAILSAFE: If mainAnswer is empty because the model put its entire response inside <think>...</think>, fallback thinkingContent to mainAnswer so the answer is NEVER blank
            if (!mainAnswer && thinkingContent) {
                mainAnswer = thinkingContent;
                thinkingContent = "";
            }
        } else {
            isThinkingActive = true;
            thinkingContent = rawText.replace("<think>", "").trim();
            mainAnswer = "";
        }
    }

    // 1. Render or Update Thinking Container
    if (thinkingContent || isThinkingActive) {
        let thinkingContainer = container.querySelector(".thinking-container");
        let headerDiv = null;
        let bodyDiv = null;

        if (!thinkingContainer) {
            container.innerHTML = "";
            thinkingContainer = document.createElement("div");
            thinkingContainer.className = `thinking-container ${isThinkingActive ? "" : "collapsed"}`;

            headerDiv = document.createElement("div");
            headerDiv.className = "thinking-header";

            bodyDiv = document.createElement("div");
            bodyDiv.className = `thinking-body ${isThinkingActive ? "" : "faded-out"}`;

            headerDiv.addEventListener("click", () => {
                thinkingContainer.classList.toggle("collapsed");
            });

            thinkingContainer.appendChild(headerDiv);
            thinkingContainer.appendChild(bodyDiv);
            container.appendChild(thinkingContainer);
        } else {
            headerDiv = thinkingContainer.querySelector(".thinking-header");
            bodyDiv = thinkingContainer.querySelector(".thinking-body");
        }

        if (isThinkingActive) {
            if (!headerDiv.dataset.state || headerDiv.dataset.state !== "active") {
                headerDiv.dataset.state = "active";
                headerDiv.innerHTML = `<span>Réflexion en cours</span> <div class="typing-indicator" style="display:inline-flex; transform:scale(0.85);"><span></span><span></span><span></span></div> <span class="chevron">▼</span>`;
                thinkingContainer.classList.remove("collapsed");
                bodyDiv.classList.remove("faded-out");
            }
        } else {
            if (headerDiv.dataset.state !== "done") {
                headerDiv.dataset.state = "done";
                const durationText = thinkingDuration ? `${thinkingDuration} s` : `quelques secondes`;
                headerDiv.innerHTML = `<span>Pensé pendant ${durationText}</span> <span class="chevron">▼</span>`;
                thinkingContainer.classList.add("collapsed");
                bodyDiv.classList.add("faded-out");
            }
        }

        renderRichContent(bodyDiv, thinkingContent, []);
    } else {
        const thinkingContainer = container.querySelector(".thinking-container");
        if (thinkingContainer && !rawText.includes("<think>")) {
            thinkingContainer.remove();
        }
    }

    // 2. Render or Update Main Answer Content
    if (mainAnswer || (!thinkingContent && !isThinkingActive)) {
        let answerDiv = container.querySelector(".answer-content");
        if (!answerDiv) {
            if (!container.querySelector(".thinking-container")) {
                const typingIndicator = container.querySelector(".typing-indicator");
                if (typingIndicator) typingIndicator.remove();
            }
            answerDiv = document.createElement("div");
            answerDiv.className = "answer-content";
            container.appendChild(answerDiv);
        }
        renderRichContent(answerDiv, mainAnswer, webResults);

        // ChatGPT-style inline citation chips (idempotent pass, safe to run
        // on every render: streaming paints and history loads share this
        // path). The [n] markers written by the model are replaced in place
        // by favicon chips bound to webResults[n - 1] — the sources live
        // ONLY here, there is deliberately no bottom sources drawer.
        renderCitationMarkerChips(answerDiv, webResults);
    }
}

// Rich content renderer (Markdown + resilient KaTeX rendering).
function renderRichContent(container, text, webResults) {
    if (!text) {
        container.innerHTML = "";
        return;
    }

    // The [n] citation markers are NOT stripped here: they must survive the
    // markdown pass so renderCitationMarkerChips can replace them in the
    // rendered DOM (markers sitting in code/pre/links stay untouched there).
    text = text.replace(/[ \t]+([,.;:!?])/g, "$1");

    const preparedMath = window.LasmeMath
        ? window.LasmeMath.prepareForMarkdown(text)
        : { text, math: [] };
    let html = typeof marked !== "undefined"
        ? marked.parse(preparedMath.text)
        : escapeHtml(preparedMath.text);
    if (window.LasmeMath) {
        html = window.LasmeMath.restoreAfterMarkdown(
            html,
            preparedMath.math,
            escapeHtml
        );
    }

    container.innerHTML = sanitizeHtml(html);
    container.querySelectorAll('a[target="_blank"]').forEach(link => {
        link.setAttribute("rel", "noopener noreferrer");
    });

    // ── STEP 7: Generated image cards ─────────────────────────────────────
    const genImgs = container.querySelectorAll("img[src*='/generated_images/']");
    genImgs.forEach(img => {
        if (!img.closest(".generated-image-card") && !img.classList.contains("user-attached-image")) {
            const src = img.getAttribute("src");
            const alt = img.getAttribute("alt") || "Image générée";
            const safeSrc = safeHttpUrl(src);
            if (!safeSrc) {
                img.remove();
                return;
            }
            const cardDiv = document.createElement("div");
            cardDiv.className = "generated-image-card";
            cardDiv.innerHTML = sanitizeHtml(`
                <img src="${escapeHtml(safeSrc)}" alt="${escapeHtml(alt)}">
                <div class="generated-image-overlay">
                    <span style="color:#FFF; font-size:0.8rem; font-weight:500; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; max-width:170px;">${escapeHtml(alt)}</span>
                    <div class="image-card-actions">
                        <button type="button" class="img-action-btn image-zoom-btn">
                            🔍 Zoom
                        </button>
                        <a href="${escapeHtml(safeSrc)}" download class="img-action-btn">
                            📥 Télécharger HD
                        </a>
                    </div>
                </div>
            `);
            const cardImage = cardDiv.querySelector("img");
            const cardZoom = cardDiv.querySelector(".image-zoom-btn");
            if (cardImage) cardImage.addEventListener("click", () => openImageViewer(safeSrc));
            if (cardZoom) cardZoom.addEventListener("click", () => openImageViewer(safeSrc));
            if (img.parentNode && img.parentNode.tagName === "P" && img.parentNode.childNodes.length === 1) {
                img.parentNode.replaceWith(cardDiv);
            } else {
                img.replaceWith(cardDiv);
            }
        }
    });

    // ── STEP 8: KaTeX render on DOM ───────────────────────────────────────
    if (typeof renderMathInElement !== "undefined") {
        try {
            const mathDelimiters = [
                { left: "\\[", right: "\\]", display: true },
                { left: "$$", right: "$$", display: true },
                { left: "\\(", right: "\\)", display: false }
            ];
            const mathIgnoredTags = ["script", "noscript", "style", "textarea", "pre", "code"];
            // Le passage markdown peut fragmenter une formule (italique dans
            // un \(...\), placeholders restaurés à cheval sur des nœuds) : le
            // premier auto-render en traite une partie, le second rattrape
            // les fragments devenus accessibles. Boucle jusqu'à stabilité.
            for (let mathPass = 0; mathPass < 3; mathPass++) {
                const before = container.querySelectorAll(".katex").length;
                renderMathInElement(container, {
                    delimiters: mathDelimiters,
                    throwOnError: false,
                    errorColor: "#6B7280",
                    strict: false,
                    trust: false,
                    // Copie mutable OBLIGATOIRE : KaTeX ajoute des macros internes (\cr pour
        // les \ des matrices) ; l'objet gelé de math-renderer ferait throw
        // « Cannot add property » et avorterait tout le pass de rendu.
                macros: { ...(window.LasmeMath ? window.LasmeMath.KATEX_MACROS : {}) },
                    ignoredTags: mathIgnoredTags
                });
                if (container.querySelectorAll(".katex").length === before) break;
            }
        } catch (error) {
            console.warn("Unable to render a LaTeX fragment:", error);
        }
    }


    // STEP 6: Code Blocks Header & Copy Button
    container.querySelectorAll("pre code").forEach((codeBlock) => {
        if (codeBlock.parentElement.classList.contains("code-wrapped")) return;
        
        const pre = codeBlock.parentElement;
        const wrapper = document.createElement("div");
        wrapper.className = "code-wrapper code-wrapped";
        
        const langClass = Array.from(codeBlock.classList).find(c => c.startsWith("language-"));
        const langName = langClass ? langClass.replace("language-", "").toUpperCase() : "CODE";

        const header = document.createElement("div");
        header.className = "code-header";
        header.innerHTML = `<span>${langName}</span><button type="button" class="copy-code-btn">Copier</button>`;
        
        const copyBtn = header.querySelector(".copy-code-btn");
        copyBtn.addEventListener("click", (e) => {
            if (e) e.preventDefault();
            navigator.clipboard.writeText(codeBlock.innerText);
            copyBtn.textContent = "Copié !";
            setTimeout(() => copyBtn.textContent = "Copier", 2000);
        });

        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });

    enhanceResponseTables(container);
    linkDocumentCitations(container);

    // STEP 7: Mermaid Diagrams Rendering
    if (typeof mermaid !== "undefined") {
        container.querySelectorAll("pre code.language-mermaid").forEach((block) => {
            const mermaidCode = block.innerText;
            const mermaidDiv = document.createElement("div");
            mermaidDiv.className = "mermaid";
            mermaidDiv.textContent = mermaidCode;
            block.parentElement.parentElement.replaceWith(mermaidDiv);
            try {
                mermaid.run({ nodes: [mermaidDiv] });
            } catch (err) {}
        });
    }

    // Step 8: Replace Unicode Country Flag Emojis with Twemoji SVGs for Windows
    replaceFlagsWithSvg(container);
}

// ── Inline citation chips rendered from the [n] markers (ChatGPT-style) ────
//
// The model cites its web sources with bracket markers ([1], [2][5], …)
// placed at the end of the cited sentence/paragraph, and webResults[i - 1]
// is source number i (position in the array is the source of truth). After
// the markdown answer is rendered, every marker found in the text nodes of
// .answer-content is replaced IN PLACE by a compact favicon chip:
//   - one marker            → a single-source chip (favicon only),
//   - a run of adjacent     → ONE multi-source group (first favicon
//     markers [2][5]          + "+N" badge) at that same spot,
//   - an out-of-range/      → the marker is removed silently,
//     unknown number
//   - no web results at all → every marker is removed silently.
// Hovering (desktop) or tapping (touch) a chip opens the shared preview
// popover, anchored above the chip (flipped below when clipped).
//
// Idempotence: the pass snapshots the matching text nodes BEFORE mutating
// anything, so one call can never re-enter or double-render; and since the
// replacements contain no markers, re-running it on the same DOM is a
// no-op. During streaming, renderRichContent rebuilds the subtree on every
// paint, so each paint re-runs the pass on fresh markers — no duplication.

