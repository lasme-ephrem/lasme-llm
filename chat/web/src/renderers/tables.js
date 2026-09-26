// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
function tableToTsv(table) {
    return Array.from(table.rows)
        .map(row => Array.from(row.cells)
            .map(cell => cell.innerText.replace(/\s+/g, " ").trim())
            .join("\t"))
        .join("\n");
}

function tableToCsv(table) {
    const quote = value => `"${String(value).replace(/"/g, '""')}"`;
    return Array.from(table.rows)
        .map(row => Array.from(row.cells)
            .map(cell => quote(cell.innerText.replace(/\s+/g, " ").trim()))
            .join(","))
        .join("\r\n");
}

function enhanceResponseTables(container) {
    container.querySelectorAll("table").forEach((table, index) => {
        if (table.closest(".response-table-artifact")) return;
        const shell = document.createElement("section");
        shell.className = "response-table-artifact";
        const toolbar = document.createElement("header");
        toolbar.className = "response-table-toolbar";
        const label = document.createElement("span");
        label.textContent = `Tableau ${index + 1}`;
        const actions = document.createElement("span");
        actions.className = "response-table-actions";
        const copy = document.createElement("button");
        copy.type = "button";
        copy.title = "Copier le tableau";
        copy.textContent = "Copier";
        copy.addEventListener("click", async () => {
            await navigator.clipboard.writeText(tableToTsv(table));
            copy.textContent = "Copié";
            setTimeout(() => { copy.textContent = "Copier"; }, 1600);
        });
        const exportButton = document.createElement("button");
        exportButton.type = "button";
        exportButton.title = "Exporter au format CSV";
        exportButton.textContent = "CSV";
        exportButton.addEventListener("click", () => {
            const blob = new Blob(["\uFEFF", tableToCsv(table)], {
                type: "text/csv;charset=utf-8"
            });
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `tableau-${index + 1}.csv`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 0);
        });
        actions.append(copy, exportButton);
        toolbar.append(label, actions);
        const scroll = document.createElement("div");
        scroll.className = "response-table-scroll";
        table.parentNode.insertBefore(shell, table);
        scroll.appendChild(table);
        shell.append(toolbar, scroll);
    });
}

function linkDocumentCitations(container) {
    const pattern = /\[Document\s*:\s*([^,\]\n]+?)(?:\s*,\s*p(?:age)?\.?\s*(\d+))?\]\s*(?:\{file:([a-zA-Z0-9:_-]+)\})?/gi;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let node;
    while ((node = walker.nextNode())) {
        if (
            node.nodeValue
            && pattern.test(node.nodeValue)
            && !node.parentElement?.closest("code, pre, .document-citation")
        ) {
            nodes.push(node);
        }
        pattern.lastIndex = 0;
    }
    nodes.forEach(textNode => {
        const source = textNode.nodeValue;
        const fragment = document.createDocumentFragment();
        let cursor = 0;
        pattern.lastIndex = 0;
        let match;
        while ((match = pattern.exec(source))) {
            fragment.appendChild(document.createTextNode(source.slice(cursor, match.index)));
            const button = document.createElement("button");
            button.type = "button";
            button.className = "document-citation";
            button.textContent = match[2]
                ? `${match[1].trim()} · p. ${match[2]}`
                : match[1].trim();
            button.title = "Ouvrir le document source";
            button.addEventListener("click", () => {
                const page = match[2] ? Number(match[2]) : null;
                const opened = match[3]
                    ? window.LasmeWorkspace?.openFile?.(match[3], page)
                    : false;
                if (!opened) {
                    window.LasmeWorkspace?.openFileByName?.(
                        match[1].trim(),
                        page
                    );
                }
            });
            fragment.appendChild(button);
            cursor = pattern.lastIndex;
        }
        fragment.appendChild(document.createTextNode(source.slice(cursor)));
        textNode.replaceWith(fragment);
    });
    pattern.lastIndex = 0;
}

// Deterministic country-code badge for Windows and offline installations.
function replaceFlagsWithSvg(container) {
    if (!container) return;
    const flagRegex = /([\uD83C][\uDDE6-\uDDFF][\uD83C][\uDDE6-\uDDFF])/g;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) {
        if (node.nodeValue && flagRegex.test(node.nodeValue)) {
            textNodes.push(node);
        }
    }
    textNodes.forEach(textNode => {
        const parent = textNode.parentNode;
        if (parent && parent.tagName !== "SCRIPT" && parent.tagName !== "STYLE") {
            const span = document.createElement("span");
            span.className = "emoji-flag-span";
            span.innerHTML = textNode.nodeValue.replace(flagRegex, (match) => {
                const countryCode = Array.from(match)
                    .map(character => String.fromCharCode(
                        character.codePointAt(0) - 0x1F1E6 + 65
                    ))
                    .join("");
                return `<span class="flag-fallback" role="img" aria-label="${countryCode}">${countryCode}</span>`;
            });
            parent.replaceChild(span, textNode);
        }
    });
}

// RAG Document Upload Logic (Integrated into bottom "+" Button)
