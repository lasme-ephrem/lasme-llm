// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
function sourceFallbackIcon() {
    return `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
             aria-hidden="true">
            <circle cx="12" cy="12" r="11" fill="currentColor" stroke="none" opacity=".14"></circle>
            <circle cx="12" cy="12" r="8.5"></circle>
            <path d="M3.8 12h16.4M12 3.5c2.2 2.35 3.3 5.18 3.3 8.5S14.2 18.15 12 20.5M12 3.5C9.8 5.85 8.7 8.68 8.7 12s1.1 6.15 3.3 8.5"></path>
        </svg>
    `;
}

// Shared domain/favicon resolution for the sources drawer AND the inline
// source chips (multi-part public suffixes such as co.uk are handled here).
const MULTI_PART_TLD_SUFFIXES = new Set([
    "co.uk", "org.uk", "com.au", "com.br",
    "co.jp", "co.kr", "com.cn", "com.mx", "co.in"
]);

function buildSourceMeta(result) {
    const safeUrl = safeHttpUrl(result?.url);
    if (!safeUrl) return null;
    try {
        const parsedUrl = new URL(safeUrl, window.location.origin);
        const domain = parsedUrl.hostname.replace(/^www\./, "");
        const domainParts = domain.split(".");
        const lastTwoLabels = domainParts.slice(-2).join(".");
        const registrableLabelCount = (
            MULTI_PART_TLD_SUFFIXES.has(lastTwoLabels) ? 3 : 2
        );
        const faviconDomain = domainParts.length > registrableLabelCount
            ? domainParts.slice(-registrableLabelCount).join(".")
            : domain;
        return {
            result,
            safeUrl,
            domain,
            faviconDomain,
            faviconUrl: `/favicons/${encodeURIComponent(faviconDomain)}`,
            initial: (faviconDomain[0] || "S").toUpperCase()
        };
    } catch (error) {
        return null;
    }
}

const SOURCE_CHIP_OPEN_DELAY_MS = 120;
const SOURCE_CHIP_CLOSE_DELAY_MS = 200;
const FINE_POINTER_QUERY = typeof window.matchMedia === "function"
    ? window.matchMedia("(hover: hover) and (pointer: fine)")
    : null;
let activeSourceChipPopover = null;

// One citation token: [7], or a compact list/range the model sometimes
// emits instead of adjacent markers ([2,5], [2-5]); every captured number
// maps to webResults[number - 1].
const CITATION_TOKEN_PATTERN = /\[([0-9]{1,2}(?:\s*[,–-]\s*[0-9]{1,2})*)\]/g;

// Text inside these elements keeps its literal [n] characters: code samples,
// maths, mermaid sources, document-citation buttons, generated-image cards
// and existing links (if the model still emits a markdown link, it stays).
const CITATION_SKIP_SELECTOR = [
    "code", "pre", "a", ".katex", ".mermaid",
    ".document-citation", ".source-chip-group",
    ".generated-image-card", "script", "style", "textarea"
].join(", ");

// Punctuation glued right after a run of markers moves BEFORE the chip, so
// "étude[1]." renders as "étude.◉" (ChatGPT typography).
const CITATION_TRAILING_PUNCTUATION = /[.,;:!?…]/;

function sourceChipHoverCapable() {
    return FINE_POINTER_QUERY ? FINE_POINTER_QUERY.matches : true;
}

// Replace the citation markers of one text node by text + chip groups.
// `sourceSlots[i]` is the meta of source number i + 1 (possibly null when
// that result has no usable URL — its marker then behaves as invalid).
function replaceCitationTokensInTextNode(textNode, sourceSlots) {
    const value = textNode.nodeValue;
    if (!value || !value.includes("[")) return;

    const tokens = Array.from(value.matchAll(CITATION_TOKEN_PATTERN));
    if (!tokens.length) return;

    const fragment = document.createDocumentFragment();
    let cursor = 0;
    let runStart = -1;        // index of the first marker of the current run
    let runEnd = -1;          // index just past the last marker of the run
    let runMetas = [];        // deduplicated source metas of the run
    let runNumbers = [];      // valid marker numbers, kept for data-lasme-cited
    let runSeen = new Set();  // numbers already taken in the run

    const flushRun = () => {
        if (runStart < 0) return;
        let lead = value.slice(cursor, runStart);
        // Absorb a single space glued before the markers: the chip carries
        // its own 2px margin, "mot ●" reads better than "mot  ●".
        if (/[ \t]$/.test(lead)) lead = lead.slice(0, -1);
        if (lead) fragment.appendChild(document.createTextNode(lead));

        let tail = "";
        if (runEnd < value.length && CITATION_TRAILING_PUNCTUATION.test(value[runEnd])) {
            tail = value[runEnd];
        }
        if (tail) fragment.appendChild(document.createTextNode(tail));
        if (runMetas.length) {
            const group = createSourceChipGroup(runMetas);
            group.dataset.lasmeCited = runNumbers.join(",");
            fragment.appendChild(group);
        }

        cursor = runEnd + (tail ? 1 : 0);
        runStart = -1;
        runEnd = -1;
        runMetas = [];
        runNumbers = [];
        runSeen = new Set();
    };

    for (const token of tokens) {
        if (runStart >= 0 && token.index !== runEnd) flushRun();

        const numbers = (token[1].match(/[0-9]+/g) || []).map(Number);
        if (runStart < 0) runStart = token.index;
        runEnd = token.index + token[0].length;
        numbers.forEach(number => {
            if (number < 1 || number > sourceSlots.length) return;
            if (runSeen.has(number)) return;
            const meta = sourceSlots[number - 1];
            if (!meta) return;
            runSeen.add(number);
            runMetas.push(meta);
            runNumbers.push(number);
        });
    }
    flushRun();

    const rest = value.slice(cursor);
    if (rest) fragment.appendChild(document.createTextNode(rest));
    textNode.replaceWith(fragment);
}

function renderCitationMarkerChips(answerDiv, webResults) {
    if (!answerDiv) return;

    // Close a stale popover whose anchor chip was wiped by a re-render.
    const host = answerDiv.parentElement;
    const existingPopover = host?.querySelector(":scope > .source-chip-popover");
    if (
        existingPopover
        && existingPopover._lasmeChip
        && !existingPopover._lasmeChip.isConnected
    ) {
        hideSourceChipPopover(existingPopover);
    }

    // Slot array keeps positions intact: webResults[i] is ALWAYS source
    // number i + 1, even when a result must be skipped for a bad URL.
    const sourceSlots = (Array.isArray(webResults) ? webResults : [])
        .map(result => buildSourceMeta(result));

    // Snapshot first, mutate after: the walker is closed before any
    // replacement, so a single pass cannot re-enter or double-render.
    const walker = document.createTreeWalker(answerDiv, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) {
        if (
            node.nodeValue
            && node.nodeValue.includes("[")
            && !node.parentElement?.closest(CITATION_SKIP_SELECTOR)
        ) {
            textNodes.push(node);
        }
    }
    if (!textNodes.length) return;
    textNodes.forEach(textNode => {
        replaceCitationTokensInTextNode(textNode, sourceSlots);
    });
}

function createSourceChipGroup(sources) {
    const primary = sources[0];
    const extraCount = Math.max(0, sources.length - 1);

    const group = document.createElement("span");
    group.className = "source-chip-group";
    group._lasmeSources = sources;

    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "source-chip";
    chip.setAttribute("aria-haspopup", "dialog");
    chip.setAttribute("aria-expanded", "false");
    chip.title = primary.result?.title || primary.domain;

    const faviconShell = document.createElement("span");
    faviconShell.className = "source-favicon-shell source-chip-favicon";
    faviconShell.title = primary.domain;
    faviconShell.innerHTML = `
        <span class="source-favicon-fallback">${sourceFallbackIcon()}</span>
        <img class="source-favicon" src="${escapeHtml(primary.faviconUrl)}" alt="">
    `;
    faviconShell.querySelector(".source-favicon")?.addEventListener(
        "error",
        event => {
            const image = event.currentTarget;
            image.src = "/source-fallback.svg";
            image.classList.add("generic");
        },
        { once: true }
    );

    // ChatGPT-style: the chip shows ONLY the favicon (+N badge when the
    // paragraph cites several sources). Domain and title live in the
    // hover card, the chip title and the aria labels.
    chip.appendChild(faviconShell);

    if (extraCount > 0) {
        const extra = document.createElement("span");
        extra.className = "source-chip-extra";
        extra.textContent = `+${extraCount}`;
        chip.appendChild(extra);
    }

    chip.addEventListener("mouseenter", () => {
        if (!sourceChipHoverCapable()) return;
        scheduleSourcePopoverOpen(chip);
    });
    chip.addEventListener("mouseleave", () => {
        scheduleSourcePopoverClose(chip);
    });
    // Desktop: toggles as well (pins the card); touch: tap toggles the card.
    chip.addEventListener("click", event => {
        event.preventDefault();
        toggleSourcePopoverForChip(chip);
    });

    group.appendChild(chip);
    return group;
}

function sourceChipHostFor(chip) {
    return chip.closest(".bubble") || chip.closest(".answer-content");
}

function ensureSourceChipPopover(host) {
    if (!host) return null;
    let popover = host.querySelector(":scope > .source-chip-popover");
    if (!popover) {
        popover = document.createElement("div");
        popover.className = "source-chip-popover";
        popover.setAttribute("role", "dialog");
        popover.setAttribute("aria-label", "Source citée");
        popover.hidden = true;
        popover.addEventListener("mouseenter", () => {
            clearTimeout(popover._lasmeCloseTimer);
        });
        popover.addEventListener("mouseleave", () => {
            scheduleSourcePopoverClose(null, popover);
        });
        host.appendChild(popover);
    }
    return popover;
}

function scheduleSourcePopoverOpen(chip) {
    const popover = ensureSourceChipPopover(sourceChipHostFor(chip));
    if (!popover) return;
    clearTimeout(popover._lasmeOpenTimer);
    clearTimeout(popover._lasmeCloseTimer);
    popover._lasmeOpenTimer = setTimeout(() => {
        openSourceChipPopover(chip);
    }, SOURCE_CHIP_OPEN_DELAY_MS);
}

function scheduleSourcePopoverClose(chip, popoverOverride) {
    const popover = popoverOverride
        || (chip ? ensureSourceChipPopover(sourceChipHostFor(chip)) : null);
    if (!popover) return;
    // Cancel a pending open even if the card was never shown yet.
    clearTimeout(popover._lasmeOpenTimer);
    if (popover.hidden) return;
    clearTimeout(popover._lasmeCloseTimer);
    popover._lasmeCloseTimer = setTimeout(() => {
        hideSourceChipPopover(popover);
    }, SOURCE_CHIP_CLOSE_DELAY_MS);
}

function toggleSourcePopoverForChip(chip) {
    const popover = ensureSourceChipPopover(sourceChipHostFor(chip));
    if (!popover) return;
    if (!popover.hidden && popover._lasmeChip === chip) {
        hideSourceChipPopover(popover);
        return;
    }
    clearTimeout(popover._lasmeOpenTimer);
    clearTimeout(popover._lasmeCloseTimer);
    openSourceChipPopover(chip);
}

function openSourceChipPopover(chip) {
    const group = chip.closest(".source-chip-group");
    const sources = group?._lasmeSources;
    if (!sources || !sources.length) return;
    const popover = ensureSourceChipPopover(sourceChipHostFor(chip));
    if (!popover) return;

    clearTimeout(popover._lasmeOpenTimer);
    clearTimeout(popover._lasmeCloseTimer);
    if (activeSourceChipPopover && activeSourceChipPopover !== popover) {
        hideSourceChipPopover(activeSourceChipPopover);
    }

    popover._lasmeChip = chip;
    popover._lasmeSources = sources;
    popover._lasmeIndex = 0;
    renderSourceChipPopover(popover);
    popover.hidden = false;
    positionSourceChipPopover(popover);
    requestAnimationFrame(() => {
        if (!popover.hidden) popover.classList.add("visible");
    });
    chip.classList.add("open");
    chip.setAttribute("aria-expanded", "true");
    activeSourceChipPopover = popover;
}

function renderSourceChipPopover(popover) {
    const sources = popover._lasmeSources || [];
    const index = popover._lasmeIndex || 0;
    const meta = sources[index];
    if (!meta) return;
    const title = String(meta.result?.title || "").trim() || meta.domain;

    let navHtml = "";
    if (sources.length > 1) {
        const dots = sources.map((item, dotIndex) => `
            <button type="button"
                    class="source-chip-popover-dot${dotIndex === index ? " active" : ""}"
                    data-source-index="${dotIndex}"
                    aria-label="Source ${dotIndex + 1} : ${escapeHtml(item.domain)}"
                    title="${escapeHtml(item.domain)}"></button>
        `).join("");
        navHtml = `
            <div class="source-chip-popover-nav">
                <button type="button" class="source-chip-popover-arrow"
                        data-source-step="-1" aria-label="Source précédente"
                        ${index === 0 ? "disabled" : ""}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="2.4" stroke-linecap="round"
                         stroke-linejoin="round"><path d="m15 6-6 6 6 6"></path></svg>
                </button>
                <span class="source-chip-popover-dots">${dots}</span>
                <button type="button" class="source-chip-popover-arrow"
                        data-source-step="1" aria-label="Source suivante"
                        ${index === sources.length - 1 ? "disabled" : ""}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="2.4" stroke-linecap="round"
                         stroke-linejoin="round"><path d="m9 6 6 6-6 6"></path></svg>
                </button>
                <span class="source-chip-popover-counter">${index + 1}/${sources.length}</span>
            </div>
        `;
    }

    popover.innerHTML = `
        <a class="source-chip-popover-link"
           href="${escapeHtml(meta.safeUrl)}"
           target="_blank"
           rel="noopener noreferrer">
            <span class="source-chip-popover-head">
                <span class="source-favicon-shell source-chip-popover-favicon">
                    <span class="source-favicon-fallback">${sourceFallbackIcon()}</span>
                    <img class="source-favicon" src="${escapeHtml(meta.faviconUrl)}" alt="">
                </span>
                <span class="source-chip-popover-domain">${escapeHtml(meta.domain)}</span>
            </span>
            <span class="source-chip-popover-title">${escapeHtml(title)}</span>
        </a>
        ${navHtml}
    `;

    popover.querySelectorAll(".source-favicon").forEach(image => {
        image.addEventListener("error", () => {
            image.src = "/source-fallback.svg";
            image.classList.add("generic");
        }, { once: true });
    });
    const goTo = nextIndex => {
        if (nextIndex < 0 || nextIndex >= sources.length) return;
        popover._lasmeIndex = nextIndex;
        renderSourceChipPopover(popover);
        positionSourceChipPopover(popover);
    };
    popover.querySelectorAll(".source-chip-popover-dot").forEach(dot => {
        dot.addEventListener("click", () => {
            goTo(Number(dot.dataset.sourceIndex) || 0);
        });
    });
    popover.querySelectorAll(".source-chip-popover-arrow").forEach(arrow => {
        arrow.addEventListener("click", () => {
            goTo((popover._lasmeIndex || 0) + (Number(arrow.dataset.sourceStep) || 0));
        });
    });
}

function positionSourceChipPopover(popover) {
    const chip = popover._lasmeChip;
    if (!chip || !chip.isConnected) return;
    const rect = chip.getBoundingClientRect();
    const margin = 8;
    const gap = 8;
    const width = popover.offsetWidth || 288;
    const height = popover.offsetHeight || 120;

    let left = rect.left + rect.width / 2 - width / 2;
    left = Math.min(
        Math.max(left, margin),
        Math.max(margin, window.innerWidth - width - margin)
    );

    // Prefer above the chip; flip below when there is no room.
    const below = rect.top < height + gap + 12;
    let top = below ? rect.bottom + gap : rect.top - height - gap;
    top = Math.min(
        Math.max(top, margin),
        Math.max(margin, window.innerHeight - height - margin)
    );

    popover.classList.toggle("below", below);
    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(top)}px`;
    const caretX = Math.round(
        Math.min(
            Math.max(rect.left + rect.width / 2 - left - 5, 14),
            Math.max(14, width - 24)
        )
    );
    popover.style.setProperty("--source-caret-x", `${caretX}px`);
}

function hideSourceChipPopover(popover) {
    if (!popover) return;
    clearTimeout(popover._lasmeOpenTimer);
    clearTimeout(popover._lasmeCloseTimer);
    const chip = popover._lasmeChip;
    if (chip) {
        chip.classList.remove("open");
        if (chip.isConnected) chip.setAttribute("aria-expanded", "false");
    }
    popover._lasmeChip = null;
    popover._lasmeSources = null;
    popover.classList.remove("visible", "below");
    popover.hidden = true;
    if (activeSourceChipPopover === popover) activeSourceChipPopover = null;
}

// Global dismissal + repositioning for whichever popover is currently open.
document.addEventListener("pointerdown", event => {
    if (!activeSourceChipPopover) return;
    if (activeSourceChipPopover.contains(event.target)) return;
    const chip = activeSourceChipPopover._lasmeChip;
    if (chip && chip.contains(event.target)) return;
    hideSourceChipPopover(activeSourceChipPopover);
});
document.addEventListener("keydown", event => {
    if (event.key === "Escape" && activeSourceChipPopover) {
        hideSourceChipPopover(activeSourceChipPopover);
    }
});
window.addEventListener("resize", () => {
    if (activeSourceChipPopover) positionSourceChipPopover(activeSourceChipPopover);
});
window.addEventListener("scroll", () => {
    if (!activeSourceChipPopover) return;
    const chip = activeSourceChipPopover._lasmeChip;
    if (!chip || !chip.isConnected) hideSourceChipPopover(activeSourceChipPopover);
    else positionSourceChipPopover(activeSourceChipPopover);
}, true);

