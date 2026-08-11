(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.LasmeMath = api;
    }
})(typeof window !== "undefined" ? window : globalThis, function () {
    "use strict";

    const KATEX_MACROS = Object.freeze({
        "\\VC": "\\operatorname{VC}",
        "\\Var": "\\operatorname{Var}",
        "\\Cov": "\\operatorname{Cov}",
        "\\E": "\\mathbb{E}",
        "\\P": "\\mathbb{P}",
        "\\R": "\\mathbb{R}",
        "\\N": "\\mathbb{N}",
        "\\Z": "\\mathbb{Z}",
        "\\Q": "\\mathbb{Q}",
        "\\RR": "\\mathbb{R}",
        "\\NN": "\\mathbb{N}",
        "\\ZZ": "\\mathbb{Z}",
        "\\QQ": "\\mathbb{Q}",
    });

    const CODE_TOKEN_PREFIX = "LASMECODETOKEN";
    const CURRENCY_TOKEN_PREFIX = "LASMECURRENCYTOKEN";
    const EXISTING_MATH_PREFIX = "LASMEEXISTINGMATH";
    const BARE_MATH_PREFIX = "LASMEBAREMATH";
    const MARKDOWN_MATH_PREFIX = "LASMEMATHBLOCK";
    const TOKEN_SUFFIX = "ENDLASME";

    function token(prefix, index) {
        return `${prefix}${index}${TOKEN_SUFFIX}`;
    }

    function restoreTokens(text, prefix, values) {
        // Models frequently escape currency as "\$5". Consume that optional
        // slash as well, otherwise it can make an internal placeholder look
        // like a LaTeX command and leak it into the rendered response.
        const optionalEscape = prefix === CURRENCY_TOKEN_PREFIX ? "\\\\?" : "";
        const expression = new RegExp(
            `${optionalEscape}${prefix}(\\d+)${TOKEN_SUFFIX}`,
            "g"
        );
        return text.replace(expression, (_, rawIndex) => values[Number(rawIndex)] ?? "");
    }

    function protectCode(text) {
        const code = [];
        const protectedText = text.replace(
            /```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`/g,
            block => {
                const placeholder = token(CODE_TOKEN_PREFIX, code.length);
                code.push(block);
                return placeholder;
            }
        );
        return { text: protectedText, code };
    }

    function protectCurrency(text) {
        const currency = [];
        const protectedText = text.replace(
            /\\?\$(?=\d)/g,
            () => {
                const placeholder = token(
                    CURRENCY_TOKEN_PREFIX,
                    currency.length
                );
                currency.push("$");
                return placeholder;
            }
        );
        return { text: protectedText, currency };
    }

    function unwrapPlainNumericMath(text) {
        const unwrap = (match, source) => {
            const plain = String(source || "")
                .replace(/\\([%$])/g, "$1")
                .replace(/\\,/g, " ")
                .trim();
            const isPlainNumeric = /\d/.test(plain)
                && /^[\d\s.,:+\-/%$A-Za-z]+$/.test(plain);
            return isPlainNumeric ? plain : match;
        };
        return String(text || "")
            .replace(/\\\(([\s\S]*?)\\\)/g, unwrap)
            .replace(/\$(?!\$)([^$\n]+?)\$/g, unwrap);
    }

    function canonicalizeLatex(source) {
        return String(source || "")
            .trim()
            // Local models sometimes emit "\hat R}" instead of "\hat{R}".
            .replace(
                /\\(hat|bar|vec|tilde|dot|ddot|overline|underline)\s+([A-Za-z])\}?/g,
                "\\$1{$2}"
            );
    }

    function protectDelimitedMath(text) {
        const blocks = [];
        let output = text;
        const capture = (display, math) => {
            const placeholder = token(EXISTING_MATH_PREFIX, blocks.length);
            blocks.push({ display, source: canonicalizeLatex(math) });
            return placeholder;
        };

        output = output.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => capture(true, math));
        output = output.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => capture(true, math));
        output = output.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => capture(false, math));
        output = output.replace(/\$(?!\$)([^$\n]+?)\$/g, (_, math) => capture(false, math));
        return { text: output, blocks };
    }

    function normalizeBareLatex(text) {
        const protectedMath = protectDelimitedMath(text);
        let output = protectedMath.text;
        const bareBlocks = [];
        const captureBare = match => {
            const placeholder = token(BARE_MATH_PREFIX, bareBlocks.length);
            bareBlocks.push(`\\(${canonicalizeLatex(match)}\\)`);
            return placeholder;
        };

        // Capture full expressions before their inner commands are considered.
        output = output.replace(
            /\|[^|\n]{0,120}\\(?:hat|bar|vec|tilde|frac|sqrt|VC|Var|Cov|mathbb|mathrm|operatorname)[^|\n]{0,120}\|/g,
            captureBare
        );
        output = output.replace(
            /\\(?:dfrac|tfrac|frac)\s*\{[^{}\n]{1,200}\}\s*\{[^{}\n]{1,200}\}/g,
            captureBare
        );
        output = output.replace(
            /\\sqrt(?:\[[^\]\n]{1,40}\])?\s*\{[^{}\n]{1,200}\}/g,
            captureBare
        );
        output = output.replace(
            /\\(?:hat|bar|vec|tilde|dot|ddot|overline|underline)\s*(?:\{[^{}\n]{1,80}\}|[A-Za-z]\}?)(?:\s*\([^)\n]{0,80}\))?/g,
            captureBare
        );
        output = output.replace(
            /\b[A-Za-z0-9_{}^']+\s*\\(?:le|leq|ge|geq|ne|neq|approx|sim|in|notin)\s*[A-Za-z0-9_{}^']+(?:\s*\([^)\n]{0,80}\))?/g,
            captureBare
        );
        output = output.replace(
            /\\(?:ln|log|exp|sin|cos|tan|min|max|argmin|argmax)\s*(?:\{[^{}\n]{1,120}\}|\([^)\n]{1,120}\)|[A-Za-z])/g,
            captureBare
        );
        output = output.replace(
            /\\(?:VC|Var|Cov|RR|NN|ZZ|QQ|E|P|R|N|Z|Q)(?:\s*\([^)\n]{1,80}\))?/g,
            captureBare
        );
        output = output.replace(
            /\\(?:alpha|beta|gamma|delta|epsilon|varepsilon|theta|lambda|mu|pi|rho|sigma|tau|phi|varphi|chi|psi|omega)(?:[_^](?:\{[^{}\n]{1,80}\}|[A-Za-z0-9]))?/g,
            captureBare
        );

        output = restoreTokens(output, BARE_MATH_PREFIX, bareBlocks);
        output = restoreTokens(
            output,
            EXISTING_MATH_PREFIX,
            protectedMath.blocks.map(block =>
                block.display ? `\\[${block.source}\\]` : `\\(${block.source}\\)`
            )
        );
        return output;
    }

    function prepareForMarkdown(value) {
        const protectedCode = protectCode(
            unwrapPlainNumericMath(
                String(value || "").replace(/\r\n?/g, "\n")
            )
        );
        const protectedCurrency = protectCurrency(protectedCode.text);
        let output = normalizeBareLatex(protectedCurrency.text);
        const math = [];
        const capture = (display, source) => {
            const placeholder = token(MARKDOWN_MATH_PREFIX, math.length);
            math.push({ display, source: canonicalizeLatex(source) });
            return placeholder;
        };

        output = output.replace(/\$\$([\s\S]*?)\$\$/g, (_, source) => capture(true, source));
        output = output.replace(/\\\[([\s\S]*?)\\\]/g, (_, source) => capture(true, source));
        output = output.replace(/\\\(([\s\S]*?)\\\)/g, (_, source) => capture(false, source));
        output = output.replace(/\$(?!\$)([^$\n]+?)\$/g, (_, source) => capture(false, source));
        output = restoreTokens(
            output,
            CURRENCY_TOKEN_PREFIX,
            protectedCurrency.currency
        );
        output = restoreTokens(output, CODE_TOKEN_PREFIX, protectedCode.code);
        return { text: output, math };
    }

    function restoreAfterMarkdown(html, math, escapeHtml) {
        const escapedMath = math.map(block => {
            const source = escapeHtml(block.source);
            return block.display ? `\\[${source}\\]` : `\\(${source}\\)`;
        });
        return restoreTokens(html, MARKDOWN_MATH_PREFIX, escapedMath);
    }

    return {
        KATEX_MACROS,
        canonicalizeLatex,
        normalizeBareLatex,
        unwrapPlainNumericMath,
        prepareForMarkdown,
        restoreAfterMarkdown,
    };
});
