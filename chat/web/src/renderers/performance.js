// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
function formatPerformanceNumber(value, maximumFractionDigits = 1) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    return new Intl.NumberFormat("fr-FR", {
        maximumFractionDigits,
        minimumFractionDigits: 0
    }).format(number);
}

function renderGenerationPerformance(container, rawStats) {
    if (!container) return;
    container
        .querySelector('.assistant-activity[data-kind="generation"]')
        ?.remove();
    container.querySelector(".generation-performance")?.remove();

    const stats = rawStats && typeof rawStats === "object"
        ? rawStats
        : null;
    if (!stats) return;

    const speed = Number(stats.tokens_per_second || 0);
    const outputTokens = Number(stats.output_tokens || 0);
    const totalSeconds = Number(
        stats.total_seconds || stats.generation_seconds || 0
    );
    const firstTokenSeconds = Number(stats.time_to_first_token || 0);
    const promptTokens = Number(stats.prompt_tokens || 0);
    if (!speed && !outputTokens && !totalSeconds) return;

    const performance = document.createElement("div");
    performance.className = "generation-performance";
    performance.setAttribute("aria-label", "Performances de génération");

    const visibleMetrics = [];
    if (speed > 0) {
        visibleMetrics.push(`
            <span class="generation-performance-primary">
                ${formatPerformanceNumber(speed)} tok/s
            </span>
        `);
    }
    if (outputTokens > 0) {
        visibleMetrics.push(`
            <span>${formatPerformanceNumber(outputTokens, 0)} tokens</span>
        `);
    }
    if (totalSeconds > 0) {
        visibleMetrics.push(`
            <span>${formatPerformanceNumber(totalSeconds)} s</span>
        `);
    }

    const detailParts = [];
    if (firstTokenSeconds > 0) {
        detailParts.push(
            `premier token en ${formatPerformanceNumber(firstTokenSeconds, 2)} s`
        );
    }
    if (promptTokens > 0) {
        detailParts.push(
            `${formatPerformanceNumber(promptTokens, 0)} tokens en entrée`
        );
    }
    if (stats.model) {
        const modelKey = String(stats.model || "").toLowerCase();
        const modelLabel = modelKey.includes("256k")
            ? "Gemma 4 12B · 256K"
            : modelKey.includes("e4b")
            ? "Gemma 4 E4B"
            : modelKey.includes("e2b")
            ? "Gemma 4 E2B"
            : "Gemma 4 12B";
        detailParts.push(modelLabel);
    }
    performance.title = detailParts.length
        ? `Détails : ${detailParts.join(" · ")}`
        : "Performances de la réponse";

    performance.innerHTML = `
        <span class="generation-performance-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5.15 18.5a8.25 8.25 0 1 1 13.7 0"></path>
                <path d="m12 13 3.65-3.15"></path>
                <circle cx="12" cy="13" r="1.35"></circle>
                <path d="M6.55 14.1h1M8.1 9.55l.7.7M12 7v1M15.9 9.55l-.7.7M16.45 14.1h1"></path>
            </svg>
        </span>
        ${visibleMetrics
            .map((metric, index) => (
                `${index ? '<span class="generation-performance-separator" aria-hidden="true"></span>' : ""}${metric}`
            ))
            .join("")}
    `;
    container.appendChild(performance);
}

// Render only the final answer. Raw chain-of-thought is intentionally hidden;
// the UI receives structured activity events and a short process summary.
