// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
function cleanModelText(value) {
    const replacements = new Map([
        ["â€™", "’"],
        ["â€˜", "‘"],
        ["â€œ", "“"],
        ["â€", "”"],
        ["â€“", "–"],
        ["â€”", "—"],
        ["Â·", "·"],
        ["Â", ""],
    ]);
    let text = String(value || "").normalize("NFC").replaceAll("\uFFFD", "");
    replacements.forEach((replacement, broken) => {
        text = text.replaceAll(broken, replacement);
    });
    return Array.from(text).filter(character => {
        if (/[\n\r\t]/u.test(character)) return true;
        if (/[\p{Cc}\p{Cf}]/u.test(character)) return false;
        if (/\p{L}/u.test(character)) {
            // Greek letters are valid mathematical symbols (α, β, ε, …).
            return /[A-Za-z\u00C0-\u024F\u0370-\u03FF\u1E00-\u1EFF]/u.test(character);
        }
        return true;
    }).join("");
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function safeHttpUrl(value) {
    try {
        const parsed = new URL(String(value || ""), window.location.origin);
        if (!["http:", "https:"].includes(parsed.protocol)) return "";
        return parsed.origin === window.location.origin
            ? `${parsed.pathname}${parsed.search}${parsed.hash}`
            : parsed.href;
    } catch (_) {
        return "";
    }
}

function sanitizeHtml(value) {
    if (window.DOMPurify) {
        return window.DOMPurify.sanitize(String(value || ""), {
            USE_PROFILES: { html: true },
            ADD_ATTR: ["target", "download"],
        });
    }
    return escapeHtml(value);
}

