// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
let activeTickerInterval = null;

function renderDalleLoaderCard(bubbleDiv) {
    if (activeTickerInterval) clearInterval(activeTickerInterval);
    bubbleDiv.innerHTML = `
        <div class="dalle-loader-card">
            <div class="image-shimmer-canvas">
                <div class="image-scan-line"></div>
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="rgba(16, 185, 129, 0.6)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
                </svg>
            </div>
            <div class="image-status-ticker">
                <div class="image-ticker-spinner"></div>
                <span class="ticker-text">Génération de l'image en cours...</span>
            </div>
        </div>
    `;

    const statusMessages = [
        "Génération de l'image en cours...",
        "Création de la composition visuelle...",
        "Application des textures et lumières...",
        "Finalisation du rendu HD..."
    ];
    let msgIdx = 0;
    const tickerTextSpan = bubbleDiv.querySelector(".ticker-text");
    activeTickerInterval = setInterval(() => {
        msgIdx = (msgIdx + 1) % statusMessages.length;
        if (tickerTextSpan) tickerTextSpan.textContent = statusMessages[msgIdx];
    }, 2500);
}

function renderGeneratedImageCard(bubbleDiv, imageUrl, promptText) {
    if (activeTickerInterval) {
        clearInterval(activeTickerInterval);
        activeTickerInterval = null;
    }
    const safeImageUrl = safeHttpUrl(imageUrl);
    if (!safeImageUrl) {
        bubbleDiv.textContent = "URL d’image invalide.";
        return;
    }
    bubbleDiv.innerHTML = sanitizeHtml(`
        <div class="generated-image-card">
            <img src="${escapeHtml(safeImageUrl)}" alt="${escapeHtml(promptText)}">
            <div class="generated-image-overlay">
                <span style="color:#FFF; font-size:0.8rem; font-weight:500; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; max-width:200px;">${escapeHtml(promptText)}</span>
                <div class="image-card-actions">
                    <button type="button" class="img-action-btn image-zoom-btn">
                        🔍 Zoom
                    </button>
                    <a href="${escapeHtml(safeImageUrl)}" download class="img-action-btn">
                        📥 Télécharger
                    </a>
                </div>
            </div>
        </div>
    `);
    const image = bubbleDiv.querySelector("img");
    const zoomButton = bubbleDiv.querySelector(".image-zoom-btn");
    if (image) image.addEventListener("click", () => openImageViewer(safeImageUrl));
    if (zoomButton) zoomButton.addEventListener("click", () => openImageViewer(safeImageUrl));
}

