// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
const streamControllers = new Map();

function currentStreamKey() {
    return currentSessionId || currentDocumentScopeId;
}

function activeControllerForCurrentConversation() {
    return streamControllers.get(currentStreamKey()) || null;
}

// ── Flux live multi-conversations ─────────────────────────────────────
// Un état par génération en cours, indexé exactement comme
// streamControllers (id de session, scope documentaire d'une nouvelle
// conversation non enregistrée, ou null pour la conversation temporaire).
// Le lecteur SSE accumule TOUJOURS chaque événement ici (source de vérité)
// et ne peint le DOM que si sa conversation est celle affichée : on peut
// changer de chat sans jamais perdre un flux. En revenant sur la
// conversation, la bulle est reconstruite depuis ce store (renderLiveTurn)
// et les événements suivants reprennent la peinture en direct (rebind).
const liveStreams = new Map();

function liveStreamHasContent(live) {
    return Boolean(
        live.answerText
        || live.reasoningText
        || live.decorations.length
        || live.imageLoading
    );
}

// Retire l'entrée du store pour une clé, uniquement si elle appartient
// bien au contrôleur donné (évite de supprimer celle d'un autre flux).
function deleteLiveStreamKey(key, controller) {
    const live = liveStreams.get(key);
    if (live && (!controller || live.controller === controller)) {
        liveStreams.delete(key);
    }
}

// Libère les timers purement DOM (phrases de réflexion, collapse programmé,
// ticker image, rendu progressif programmé) d'une bulle sur le point d'être
// abandonnée. Le store conserve tout l'état nécessaire à la reconstruction.
function releaseLiveBubbleTimers(bubble) {
    if (activeTickerInterval) {
        clearInterval(activeTickerInterval);
        activeTickerInterval = null;
    }
    if (!bubble) return;
    window.LasmeProgressiveRenderer?.cancel?.(bubble);
    bubble.querySelectorAll(".thinking-panel").forEach(panel => {
        if (panel._lasmePhraseTimer) {
            clearInterval(panel._lasmePhraseTimer);
            panel._lasmePhraseTimer = null;
        }
        if (panel._lasmeCollapseTimer) {
            clearTimeout(panel._lasmeCollapseTimer);
            panel._lasmeCollapseTimer = null;
        }
    });
}

// Libère les timers de la bulle en direct de la conversation courante
// avant un changement de vue (selectSession / startNewChat).
function releaseOutgoingLiveBubbleTimers() {
    const live = liveStreams.get(currentStreamKey());
    if (live) releaseLiveBubbleTimers(live.dom?.assistantBubble || null);
}

// Rejoue, dans l'ordre chronologique, toutes les décorations accumulées
// (activités Web, cartes d'outils agent, plan et étapes de recherche)
// dans une bulle fraîche, avec exactement les mêmes primitives que le
// handler SSE : une bulle reconstruite est identique à une bulle qui
// n'aurait jamais quitté l'écran.
function paintLiveAssistantState(bubble, live) {
    for (const item of live.decorations) {
        if (item.kind === "activity") {
            renderAssistantActivity(bubble, "web", item.state, item.title, item.detail);
        } else if (item.kind === "tool") {
            upsertLiveAgentToolCard(bubble, item.event);
        } else if (item.kind === "work-note") {
            window.LasmeAnswerStream?.foldIntoWorkNote(
                bubble,
                item.text,
                item.reason
            );
        } else if (item.kind === "plan") {
            renderResearchPlan(bubble, item.steps);
        } else if (item.kind === "step") {
            updateResearchStep(bubble, item.event);
        }
    }
    restoreThinkingPanelFromLive(bubble, live);
    if (live.imageLoading) {
        renderDalleLoaderCard(bubble);
    } else if (live.answerText) {
        renderFullAssistantMessage(
            bubble,
            live.answerText,
            live.webResults,
            live.reasoningDuration
        );
    }
    if (live.generationStats) {
        renderGenerationPerformance(bubble, live.generationStats);
    }
}

// Reconstruit le panneau Réflexion dans son état exact au moment du
// changement de vue (stream en cours, terminé, préambules archivés...).
function restoreThinkingPanelFromLive(bubble, live) {
    if (live.reasoningState === "idle" && !live.reasoningText) return;
    const panel = ensureThinkingPanel(bubble);
    const pre = panel.querySelector(".thinking-text");
    if (pre) {
        pre.textContent = live.reasoningText;
        pre.classList.toggle(
            "is-scrollable",
            pre.scrollHeight > pre.clientHeight + 4
        );
    }
    if (live.reasoningState === "streaming") {
        panel.classList.add("streaming");
        setThinkingMode(panel, "stream");
        startThinkingPhrases(panel);
        const windowEl = panel.querySelector(".thinking-window");
        if (windowEl) windowEl.scrollTop = windowEl.scrollHeight;
        return;
    }
    panel.classList.remove("streaming");
    stopThinkingPhrases(panel);
    const label = panel.querySelector(".thinking-label");
    const durationText = formatThinkingDuration(live.reasoningDuration);
    if (label) {
        label.textContent = durationText
            ? `A réfléchi pendant ${durationText}`
            : "A réfléchi";
    }
    const durationEl = panel.querySelector(".thinking-duration");
    if (durationEl) durationEl.textContent = "";
    setThinkingMode(panel, "closed");
}

// Ré-entrée dans une conversation dont le flux est toujours en cours :
// reconstruit le tour en cours (message utilisateur manquant + bulle
// assistante en streaming) puis rebranche les prochains événements SSE
// sur les nouveaux nœuds DOM via live.rebind.
function renderLiveTurn(live, userAlreadyShown) {
    streamingAutoScrollPaused = false;
    releaseLiveBubbleTimers(live.dom?.assistantBubble || null);

    let userMessageEl = null;
    if (!userAlreadyShown) {
        const userBubble = appendMessage(
            "user",
            live.userText,
            live.userImageUrl || null
        );
        userMessageEl = userBubble?.closest(".message") || null;
        conversationHistory.push({ role: "user", content: live.userText });
        if (
            live.userMessageId
            && userMessageEl
            && typeof decorateMessageActions === "function"
        ) {
            decorateMessageActions(
                userMessageEl,
                "user",
                live.userMessageId,
                live.userText
            );
        }
    } else {
        const userMessages = chatMessages
            ? chatMessages.querySelectorAll(".message.user")
            : [];
        userMessageEl = userMessages[userMessages.length - 1] || null;
    }

    const assistantBubble = appendMessage(
        "assistant",
        liveStreamHasContent(live) ? "" : "..."
    );
    const assistantMessageEl = assistantBubble.closest(".message");
    paintLiveAssistantState(assistantBubble, live);
    if (
        live.assistantMessageId
        && typeof decorateMessageActions === "function"
    ) {
        decorateMessageActions(
            assistantMessageEl,
            "assistant",
            live.assistantMessageId,
            live.answerText
        );
    }
    if (live.artifactId) {
        assistantBubble.dataset.artifactId = live.artifactId;
    }

    live.dom.userMessageEl = userMessageEl;
    live.dom.assistantBubble = assistantBubble;
    live.dom.assistantMessageEl = assistantMessageEl;
    live.rebind?.(live.dom);
    replaceTurnSpacer(userMessageEl, assistantMessageEl);
    if (live.contextMeta) {
        updateContextUsage(live.contextMeta);
    }
}

// Historique serveur indisponible (erreur réseau, message utilisateur pas
// encore persisté) : reconstruit la conversation entière depuis le
// snapshot du store pour ne pas perdre le flux en cours.
function renderLiveSessionFromStore(live) {
    (live.messages || []).forEach(message => {
        let imageUrl = null;
        let cleanText = message.content;
        if (
            message.role === "user"
            && cleanText
            && cleanText.startsWith("![")
        ) {
            const imageMatch = cleanText.match(/^!\[([^\]]*)\]\(([^)]+)\)\n\n?/);
            if (imageMatch) {
                imageUrl = imageMatch[2];
                cleanText = cleanText
                    .replace(imageMatch[0], "")
                    .trim();
            }
        }
        appendMessage(message.role, cleanText, imageUrl);
        conversationHistory.push({
            role: message.role,
            content: message.content,
        });
    });
    renderLiveTurn(live, true);
}


function replaceTurnSpacer(userMessage, assistantMessage) {
    activeTurnSpacer?.remove();
    activeTurnSpacer = document.createElement("div");
    activeTurnSpacer.className = "conversation-turn-spacer";
    activeTurnSpacer.setAttribute("aria-hidden", "true");
    chatMessages.appendChild(activeTurnSpacer);
    resizeTurnSpacer(userMessage, assistantMessage);
}

function resizeTurnSpacer(userMessage, assistantMessage) {
    if (!activeTurnSpacer?.isConnected || !chatMessages) return;
    const turnHeight = (
        Number(userMessage?.offsetHeight || 0)
        + Number(assistantMessage?.offsetHeight || 0)
    );
    const available = chatMessages.clientHeight - turnHeight - 96;
    const spacerHeight = Math.max(
        88,
        Math.min(chatMessages.clientHeight * 0.68, available)
    );
    activeTurnSpacer.style.height = `${Math.round(spacerHeight)}px`;
}

function positionTurnAtViewportTop(userMessage) {
    if (!chatMessages || !userMessage) return;
    requestAnimationFrame(() => {
        const containerRect = chatMessages.getBoundingClientRect();
        const messageRect = userMessage.getBoundingClientRect();
        const targetTop = (
            chatMessages.scrollTop
            + messageRect.top
            - containerRect.top
            - 20
        );
        const reduceMotion = window.matchMedia?.(
            "(prefers-reduced-motion: reduce)"
        )?.matches;
        chatMessages.scrollTo({
            top: Math.max(0, targetTop),
            behavior: reduceMotion ? "auto" : "smooth",
        });
    });
}

function followStreamingResponse(userMessage, assistantMessage) {
    resizeTurnSpacer(userMessage, assistantMessage);
    if (
        streamingAutoScrollPaused
        || !chatMessages
        || !assistantMessage
    ) {
        return;
    }
    requestAnimationFrame(() => {
        const containerRect = chatMessages.getBoundingClientRect();
        const assistantRect = assistantMessage.getBoundingClientRect();
        const overflow = assistantRect.bottom - containerRect.bottom + 28;
        if (overflow > 0) {
            chatMessages.scrollTo({
                top: chatMessages.scrollTop + overflow,
                behavior: "auto",
            });
        }
    });
}

function refreshSendButtonState() {
    setSendButtonState(
        activeControllerForCurrentConversation() ? "stop" : "send"
    );
}

function setSendButtonState(state) {
    if (!sendChatBtn) return;
    if (state === "stop") {
        sendChatBtn.classList.add("stop-mode");
        sendChatBtn.title = "Arrêter la génération";
        sendChatBtn.setAttribute("aria-label", "Arrêter la génération");
        sendChatBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <rect x="5" y="5" width="14" height="14" rx="3"></rect>
            </svg>
        `;
    } else {
        sendChatBtn.classList.remove("stop-mode");
        sendChatBtn.title = "Envoyer";
        sendChatBtn.setAttribute("aria-label", "Envoyer le message");
        sendChatBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5"></line>
                <polyline points="5 12 12 5 19 12"></polyline>
            </svg>
        `;
    }
}

// Chat Sending Logic
if (sendChatBtn) {
    sendChatBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        const controller = activeControllerForCurrentConversation();
        if (controller) {
            controller.abort();
            streamControllers.delete(currentStreamKey());
            refreshSendButtonState();
            return;
        }
        sendChatMessage();
    });
}

if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (activeControllerForCurrentConversation()) return;
            sendChatMessage();
        }
    });
}

function renderAssistantProgressively(
    bubble,
    text,
    webResults,
    reasoningDuration,
    options = {}
) {
    const final = Boolean(options.final);
    const render = (container, latestText) => {
        renderFullAssistantMessage(
            container,
            latestText,
            webResults,
            reasoningDuration
        );
    };
    if (window.LasmeProgressiveRenderer) {
        window.LasmeProgressiveRenderer.schedule(
            bubble,
            text,
            render,
            {
                final,
                onPaint: options.onPaint,
                onComplete: options.onComplete,
            }
        );
    } else {
        render(bubble, text);
        options.onPaint?.(bubble, text);
        if (final) options.onComplete?.(bubble);
    }
}

async function sendChatMessage(options = {}) {
    const replayExistingLastUser = Boolean(options.replayExistingLastUser);
    const replayMessage = replayExistingLastUser
        ? [...conversationHistory].reverse().find(item => item.role === "user")
        : null;
    const text = replayExistingLastUser
        ? String(replayMessage?.content || "").trim()
        : chatInput.value.trim();
    const requestSelectedFileIds = selectedDocumentFileIdsForRequest();
    if (
        !text
        && !attachedImageBase64Items.length
        && !requestSelectedFileIds.length
    ) return;
    const requestIsTemporary = temporaryChatEnabled;

    const currentImageB64Items = replayExistingLastUser
        ? []
        : [...attachedImageBase64Items];
    const currentImageDataUrls = replayExistingLastUser
        ? []
        : [...attachedImageDataUrls];

    // Reset attached image UI
    if (!replayExistingLastUser && clearImageBtn) clearImageBtn.click();
    if (!replayExistingLastUser) resetDocumentAttachment();

    if (!replayExistingLastUser) {
        chatInput.value = "";
        autoResizeTextarea(chatInput);
    }
    
    // Clear hero welcome if present
    const hero = chatMessages.querySelector(".chatgpt-welcome-hero");
    if (hero) hero.remove();

    // Track target session ID for background execution
    const streamSessionId = currentSessionId;
    const initialStreamKey = streamSessionId || currentDocumentScopeId;
    if (streamControllers.has(initialStreamKey)) return;
    streamingAutoScrollPaused = false;

    // Append User Message with Image Preview
    const userPromptText = text || (
        currentImageB64Items.length
            ? "Analyse cette image."
            : "Analyse le document joint."
    );
    const existingUserMessages = chatMessages.querySelectorAll(".message.user");
    const userBubble = replayExistingLastUser
        ? existingUserMessages[existingUserMessages.length - 1]?.querySelector(".bubble")
        : appendMessage("user", userPromptText, currentImageDataUrls[0] || null);
    if (
        requestIsTemporary
        && userBubble
        && typeof decorateMessageActions === "function"
    ) {
        decorateMessageActions(
            userBubble.closest(".message"),
            "user",
            null,
            userPromptText
        );
    }
    
    const userMsgObj = { role: "user", content: userPromptText };
    if (currentImageB64Items.length) {
        userMsgObj.images = currentImageB64Items;
    }
    if (!replayExistingLastUser) conversationHistory.push(userMsgObj);
    const streamConversationHistory = conversationHistory;

    // Append Assistant Container with Animated Pulsing Dots
    let assistantBubble = appendMessage("assistant", "...");
    let userMessage = userBubble?.closest(".message") || null;
    let assistantMessage = assistantBubble.closest(".message");
    replaceTurnSpacer(userMessage, assistantMessage);
    positionTurnAtViewportTop(userMessage);
    let fullResponse = "";
    let webResultsMeta = [];
    let generationStatsMeta = null;
    
    let reasoningDuration = null;
    const agentToolEvents = [];

    const streamController = new AbortController();
    let streamKey = initialStreamKey;
    streamControllers.set(streamKey, streamController);
    refreshSendButtonState();

    // ── État live de CE flux (source de vérité multi-conversations) ──
    const live = {
        key: streamKey,
        controller: streamController,
        startedAt: Date.now(),
        done: false,
        messages: [
            ...streamConversationHistory.map(m => ({ ...m })),
            userMsgObj
        ],
        userText: userPromptText,
        userImageUrl: currentImageDataUrls[0] || null,
        userMessageId: null,
        assistantMessageId: null,
        answerText: "",
        reasoningText: "",
        reasoningDuration: null,
        reasoningState: "idle",
        decorations: [],
        webResults: webResultsMeta,
        generationStats: null,
        imageLoading: false,
        artifactId: null,
        contextMeta: null,
        dom: {
            userMessageEl: userMessage,
            assistantBubble: assistantBubble,
            assistantMessageEl: assistantMessage
        }
    };
    liveStreams.set(streamKey, live);
    // Indirection DOM : renderLiveTurn peut remplacer ces nœuds (ré-entrée
    // dans la conversation) sans toucher au corps du handler SSE.
    live.rebind = (dom) => {
        assistantBubble = dom.assistantBubble;
        assistantMessage = dom.assistantMessageEl;
        userMessage = dom.userMessageEl;
    };
    // Activités Web : toujours accumulées dans le store, peintes seulement
    // si le flux est visible.
    const trackAssistantActivity = (bubble, kind, state, title, detail = "") => {
        live.decorations.push({ kind: "activity", state, title, detail });
        if (isStreamVisible()) {
            renderAssistantActivity(bubble, kind, state, title, detail);
        }
    };

    let activeSessionIdForStream = currentSessionId;
    const isStreamVisible = () => {
        if (activeSessionIdForStream) {
            return currentSessionId === activeSessionIdForStream;
        }
        if (streamSessionId) {
            return currentSessionId === streamSessionId;
        }
        return (
            currentSessionId === null
            && currentDocumentScopeId === initialStreamKey
        );
    };
    if (activeSessionIdForStream) {
        activeStreamingSessions.add(activeSessionIdForStream);
        loadSessions();
    }

    try {
        // Strip heavy base64 image strings from older turns to keep HTTP payload light
        const cleanHistory = streamConversationHistory.map((m, idx) => {
            if (idx === streamConversationHistory.length - 1) return m;
            const { images, ...rest } = m;
            return rest;
        });

        const selectedModel = inputModelSelect ? inputModelSelect.value : "gemma-4-12b";
        const activeWebMode = webSearchBtn
            ? (webSearchBtn.dataset.mode || "auto")
            : "auto";
        const isDeepResearch = activeWebMode === "deep";
        const endpoint = isDeepResearch
            ? `${API_BASE}/research/stream`
            : `${API_BASE}/chat/stream`;
        const requestBody = isDeepResearch
            ? {
                session_id: streamSessionId,
                project_id: currentProjectId,
                question: userPromptText,
                model: selectedModel,
                intelligence_level: reasoningLevelSelect ? reasoningLevelSelect.value : "high",
                selected_file_ids: requestSelectedFileIds,
                temporary: requestIsTemporary
            }
            : {
                session_id: streamSessionId,
                project_id: currentProjectId,
                document_scope_id: currentDocumentScopeId,
                selected_file_ids: requestSelectedFileIds,
                model: selectedModel,
                messages: cleanHistory,
                intelligence_level: reasoningLevelSelect ? reasoningLevelSelect.value : "high",
                web_search_enabled: webSearchToggle.checked,
                web_search_mode: activeWebMode,
                persist_user_message: (
                    !requestIsTemporary
                    && !replayExistingLastUser
                ),
                temporary: requestIsTemporary
            };
        const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: streamController.signal,
            body: JSON.stringify(requestBody)
        });

        if (!resp.ok) {
            let detail = `HTTP ${resp.status}`;
            try {
                const errorPayload = await resp.json();
                detail = errorPayload.detail || detail;
            } catch (_) {}
            throw new Error(detail);
        }
        if (!resp.body) throw new Error("Streaming response body is unavailable.");

        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let sseBuffer = "";  // Buffer for incomplete SSE lines split across chunks

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            sseBuffer += decoder.decode(value, { stream: true });

            const lines = sseBuffer.split("\n");
            sseBuffer = lines.pop() || "";

            for (const line of lines) {
                const trimmedLine = line.trim();
                if (!trimmedLine.startsWith("data: ")) continue;

                const dataStr = trimmedLine.slice(6).trim();
                if (dataStr === "[DONE]") break;

                try {
                    const parsed = JSON.parse(dataStr);
                    if (parsed.session_id) {
                        activeSessionIdForStream = parsed.session_id;
                        activeStreamingSessions.add(parsed.session_id);
                        if (streamKey !== parsed.session_id) {
                            if (streamControllers.get(streamKey) === streamController) {
                                streamControllers.delete(streamKey);
                            }
                            deleteLiveStreamKey(streamKey, streamController);
                            streamKey = parsed.session_id;
                            live.key = streamKey;
                            liveStreams.set(streamKey, live);
                            streamControllers.set(streamKey, streamController);
                        }
                        const shouldActivateSession = streamSessionId
                            ? currentSessionId === streamSessionId
                            : (
                                currentSessionId === null
                                && currentDocumentScopeId === initialStreamKey
                            );
                        if (shouldActivateSession) {
                            currentSessionId = parsed.session_id;
                            currentDocumentScopeId = currentProjectId;
                            localStorage.setItem("active_session_id", parsed.session_id);
                            refreshSendButtonState();
                        }
                        loadSessions();
                    }
                    if (parsed.user_message_id) {
                        live.userMessageId = parsed.user_message_id;
                        if (isStreamVisible() && userMessage) {
                            decorateMessageActions(
                                userMessage,
                                "user",
                                parsed.user_message_id,
                                userPromptText
                            );
                        }
                    }
                    if (parsed.type === "message_saved" && parsed.message_id) {
                        live.assistantMessageId = parsed.message_id;
                        if (isStreamVisible()) {
                            decorateMessageActions(
                                assistantMessage,
                                "assistant",
                                parsed.message_id,
                                fullResponse
                            );
                        }
                    }
                    if (parsed.type === "research_plan") {
                        live.decorations.push({ kind: "plan", steps: parsed.steps || [] });
                        if (isStreamVisible()) {
                            renderResearchPlan(assistantBubble, parsed.steps || []);
                        }
                    }
                    if (parsed.type === "research_step") {
                        live.decorations.push({ kind: "step", event: parsed });
                        if (isStreamVisible()) {
                            updateResearchStep(assistantBubble, parsed);
                        }
                    }
                    if (parsed.type === "research_synthesis") {
                        if (parsed.web_results) {
                            webResultsMeta = parsed.web_results;
                            live.webResults = webResultsMeta;
                        }
                        trackAssistantActivity(
                            assistantBubble,
                            "web",
                            "active",
                            "Synthèse des recherches",
                            `${parsed.result_count || 0} source(s) recoupée(s)`
                        );
                    }
                    if (parsed.type === "research_done") {
                        if (parsed.web_results) {
                            webResultsMeta = parsed.web_results;
                            live.webResults = webResultsMeta;
                        }
                        trackAssistantActivity(
                            assistantBubble,
                            "web",
                            "done",
                            "Recherche approfondie terminée",
                            `${parsed.result_count || 0} source(s) retenue(s)`
                        );
                        if (parsed.artifact_id) {
                            live.artifactId = parsed.artifact_id;
                            if (
                                isStreamVisible()
                                && typeof openCanvasArtifact === "function"
                            ) {
                                assistantBubble.dataset.artifactId = parsed.artifact_id;
                            }
                        }
                    }
                    if (parsed.type === "session" && parsed.context_meta) {
                        live.contextMeta = parsed.context_meta;
                        if (isStreamVisible()) {
                            updateContextUsage(parsed.context_meta);
                        }
                    }
                    if (parsed.web_results && parsed.web_results.length > 0) {
                        webResultsMeta = parsed.web_results;
                        live.webResults = webResultsMeta;
                    }
                    if (parsed.type === "web_search_done") {
                        if (parsed.web_results) {
                            webResultsMeta = parsed.web_results;
                            live.webResults = webResultsMeta;
                        }
                        const webContextAvailable = (
                            parsed.status === "ok"
                            || parsed.status === "cached"
                        );
                        const evidenceInsufficient = (
                            parsed.status === "insufficient_evidence"
                        );
                        trackAssistantActivity(
                            assistantBubble,
                            "web",
                            webContextAvailable ? "done" : "warning",
                            parsed.status === "cached"
                                ? (
                                    parsed.message
                                    || "Contexte Web vérifié réutilisé"
                                )
                                : parsed.status === "ok"
                                ? (
                                    parsed.answer_mode === "provider"
                                        ? "Sources Web vérifiées"
                                        : `${parsed.result_count} source${parsed.result_count > 1 ? "s" : ""} pertinente${parsed.result_count > 1 ? "s" : ""}`
                                )
                                : evidenceInsufficient
                                ? (
                                    parsed.message
                                    || "Aucun fait suffisamment vérifié"
                                )
                                : "Recherche Web indisponible",
                            parsed.answer_mode === "provider"
                                ? `${parsed.result_count || 0} source${parsed.result_count > 1 ? "s" : ""} citée${parsed.result_count > 1 ? "s" : ""}`
                                : (
                                    webContextAvailable
                                    || evidenceInsufficient
                                ) && parsed.candidate_count
                                ? `${parsed.candidate_count} résultats évalués · ${parsed.search_query || ""}`
                                : parsed.search_query || ""
                        );
                    }
                    if (parsed.type === "session" && parsed.web_search) {
                        // « ready » et « disabled » sont des états normaux :
                        // outils prêts, ou volontairement absents (salutation,
                        // mode Web off). Seul « unavailable » demande une
                        // action de l'utilisateur (aucun moteur configuré) —
                        // c'est le seul cas qui mérite un bandeau.
                        if (parsed.web_search.status === "unavailable") {
                            trackAssistantActivity(
                                assistantBubble,
                                "web",
                                "warning",
                                "Recherche Web non configurée"
                            );
                        }
                    }
                    if (parsed.type === "reasoning_start") {
                        if (live.reasoningText) live.reasoningText += "\n\n";
                        live.reasoningState = "streaming";
                        if (isStreamVisible()) {
                            handleReasoningStart(assistantBubble);
                        }
                    }
                    if (parsed.type === "reasoning_delta") {
                        live.reasoningText += String(parsed.text || "");
                        if (isStreamVisible()) {
                            appendReasoningDelta(assistantBubble, parsed.text);
                        }
                    }
                    if (parsed.type === "reasoning_done") {
                        reasoningDuration = parsed.duration;
                        live.reasoningDuration = parsed.duration;
                        live.reasoningState = "done";
                        if (isStreamVisible()) {
                            handleReasoningDone(assistantBubble, parsed.duration);
                        }
                    }
                    if (parsed.type === "content_reset") {
                        // Jamais d'effacement : le brouillon streamé se
                        // range en note de travail dépliable (work-note),
                        // rejouable en multitâche via live.decorations.
                        fullResponse = "";
                        live.answerText = "";
                        live.reasoningState = "done";
                        live.decorations.push({
                            kind: "work-note",
                            text: String(parsed.text || ""),
                            reason: parsed.reason || "tool_call",
                        });
                        if (isStreamVisible()) {
                            archiveStreamedAnswer(
                                assistantBubble,
                                String(parsed.text || ""),
                                parsed.reason || "tool_call"
                            );
                        }
                    }
                    if (parsed.type === "content_replace") {
                        // Version de service assainie (chiffres non étayés
                        // assagis, citations [n] vérifiées, section
                        // « Sources » retirée) : elle remplace le flux brut
                        // déjà affiché pour que le texte visible soit
                        // exactement celui qui est persisté. Affichage d'un
                        // bloc : une correction ne se retape pas.
                        fullResponse = cleanModelText(String(parsed.text || ""));
                        live.answerText = fullResponse;
                        if (isStreamVisible()) {
                            renderAssistantProgressively(
                                assistantBubble,
                                fullResponse,
                                webResultsMeta,
                                reasoningDuration,
                                {
                                    replace: true,
                                    onPaint: () => followStreamingResponse(
                                        userMessage,
                                        assistantMessage
                                    ),
                                }
                            );
                        }
                    }
                    if (parsed.type === "agent_tool_call") {
                        agentToolEvents.push(parsed);
                        live.decorations.push({ kind: "tool", event: parsed });
                        if (isStreamVisible()) {
                            upsertLiveAgentToolCard(assistantBubble, parsed);
                        }
                    }
                    if (parsed.type === "agent_tool_result") {
                        agentToolEvents.push(parsed);
                        live.decorations.push({ kind: "tool", event: parsed });
                        if (isStreamVisible()) {
                            upsertLiveAgentToolCard(assistantBubble, parsed);
                        }
                    }
                    if (parsed.type === "generation_stats") {
                        generationStatsMeta = parsed;
                        live.generationStats = parsed;
                    }
                    if (parsed.type === "error") {
                        const message = parsed.message || "La génération a été interrompue.";
                        live.error = message;
                        fullResponse = fullResponse
                            ? `${fullResponse}\n\n*${message}*`
                            : `*${message}*`;
                        live.answerText = fullResponse;
                        if (isStreamVisible()) {
                            renderFullAssistantMessage(
                                assistantBubble,
                                fullResponse,
                                webResultsMeta,
                                reasoningDuration
                            );
                            followStreamingResponse(
                                userMessage,
                                assistantMessage
                            );
                        }
                    }
                    if (parsed.type === "image_start") {
                        live.imageLoading = true;
                        if (isStreamVisible()) {
                            renderDalleLoaderCard(assistantBubble);
                            followStreamingResponse(
                                userMessage,
                                assistantMessage
                            );
                        }
                    }
                    if (parsed.type === "image_done" && parsed.image_url) {
                        fullResponse = `![${parsed.prompt}](${parsed.image_url})`;
                        live.answerText = fullResponse;
                        live.imageLoading = false;
                        if (isStreamVisible()) {
                            renderGeneratedImageCard(assistantBubble, parsed.image_url, parsed.prompt);
                            followStreamingResponse(
                                userMessage,
                                assistantMessage
                            );
                        }
                    }
                    if (parsed.content) {
                        fullResponse = cleanModelText(fullResponse + parsed.content);
                        live.answerText = fullResponse;
                        // Provisoire jusqu'à la fin de flux : badge
                        // « Rédaction en cours », jamais présenté comme la
                        // réponse finale (qui seule s'affiche engagée).
                        window.LasmeAnswerStream?.setDrafting(assistantBubble, true);
                    
                        // Only render to active UI if user is still on this conversation
                        if (isStreamVisible()) {
                            renderAssistantProgressively(
                                assistantBubble,
                                fullResponse,
                                webResultsMeta,
                                reasoningDuration,
                                {
                                    onPaint: () => followStreamingResponse(
                                        userMessage,
                                        assistantMessage
                                    ),
                                }
                            );
                        }
                    }
                } catch (err) {
                    sseBuffer = line + "\n" + sseBuffer;
                }
            }
        }

        const remaining = decoder.decode();
        if (remaining) {
            sseBuffer += remaining;
        }

        if (!fullResponse.trim() && !live.imageLoading && !live.error) {
            fullResponse = "Je n’ai pas réussi à produire une réponse. Tu peux réessayer ou reformuler ta demande.";
            live.answerText = fullResponse;
            if (isStreamVisible()) {
                renderFullAssistantMessage(
                    assistantBubble,
                    fullResponse,
                    webResultsMeta,
                    reasoningDuration
                );
            }
        }

        // Le titre est généré en parallèle côté serveur dès le début du
        // flux : on rafraîchit la sidebar à la fin pour l'afficher live,
        // avec deux reprises si la génération du titre déborde un peu.
        void loadSessions();
        window.setTimeout(() => void loadSessions(), 2000);
        window.setTimeout(() => void loadSessions(), 5000);

        if (isStreamVisible()) {
            // Fin de flux : le texte affiché devient la réponse finale
            // (le badge « Rédaction en cours » disparaît).
            window.LasmeAnswerStream?.setDrafting(assistantBubble, false);
            renderAssistantProgressively(
                assistantBubble,
                fullResponse,
                webResultsMeta,
                reasoningDuration,
                {
                    final: true,
                    onPaint: () => followStreamingResponse(
                        userMessage,
                        assistantMessage
                    ),
                    onComplete: () => {
                        if (generationStatsMeta) {
                            renderGenerationPerformance(
                                assistantBubble,
                                generationStatsMeta
                            );
                        }
                        if (agentToolEvents.length) {
                            renderAgentToolsSummary(
                                assistantBubble,
                                agentToolEvents
                            );
                        }
                        followStreamingResponse(
                            userMessage,
                            assistantMessage
                        );
                    },
                }
            );
        }
        // The [n] citation markers are intentionally KEPT in the persisted
        // content: together with the message's web_results metadata they
        // allow the marker-based chips to be re-rendered on history load.
        if (conversationHistory === streamConversationHistory) {
            streamConversationHistory.push({ role: "assistant", content: fullResponse });
        }
        if (
            requestIsTemporary
            && fullResponse
            && isStreamVisible()
            && typeof decorateMessageActions === "function"
        ) {
            decorateMessageActions(
                assistantBubble.closest(".message"),
                "assistant",
                null,
                fullResponse
            );
        }
        if (activeSessionIdForStream && fullResponse) {
            void loadSuggestedQuestions(
                activeSessionIdForStream,
                inputModelSelect ? inputModelSelect.value : "gemma-4-12b",
                assistantBubble
            );
        }

    } catch (err) {
        window.LasmeProgressiveRenderer?.cancel?.(assistantBubble);
        window.LasmeAnswerStream?.setDrafting(assistantBubble, false);
        if (err.name === "AbortError") {
            if (fullResponse) {
                fullResponse += "\n\n*(Génération arrêtée par l'utilisateur)*";
            } else {
                fullResponse = "*(Génération arrêtée par l'utilisateur)*";
            }
            live.answerText = fullResponse;
            if (isStreamVisible()) {
                renderFullAssistantMessage(assistantBubble, fullResponse, webResultsMeta, reasoningDuration);
                if (agentToolEvents.length) {
                    renderAgentToolsSummary(assistantBubble, agentToolEvents);
                }
            }
            if (conversationHistory === streamConversationHistory) {
                streamConversationHistory.push({ role: "assistant", content: fullResponse });
            }
        } else {
            if (isStreamVisible()) {
                assistantBubble.textContent = `Erreur : ${err.message || "connexion au serveur local impossible"}`;
                assistantBubble.style.color = "#EF4444";
            }
        }
    } finally {
        if (activeSessionIdForStream) {
            activeStreamingSessions.delete(activeSessionIdForStream);
        }
        if (streamControllers.get(streamKey) === streamController) {
            streamControllers.delete(streamKey);
        }
        if (streamControllers.get(initialStreamKey) === streamController) {
            streamControllers.delete(initialStreamKey);
        }
        deleteLiveStreamKey(streamKey, streamController);
        if (initialStreamKey !== streamKey) {
            deleteLiveStreamKey(initialStreamKey, streamController);
        }
        refreshSendButtonState();
        loadSessions();
    }
}

// Append Message with optional image attachment
