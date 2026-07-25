const test = require("node:test");
const assert = require("node:assert/strict");
const math = require("../../chat/web/math-renderer.js");

test("preserves delimited inline and display formulas", () => {
    const prepared = math.prepareForMarkdown(
        "Inline \\(R(h)\\) puis $$n \\geq 1$$."
    );

    assert.equal(prepared.math.length, 2);
    assert.deepEqual(prepared.math[0], { display: true, source: "n \\geq 1" });
    assert.deepEqual(prepared.math[1], { display: false, source: "R(h)" });
    assert.doesNotMatch(prepared.text, /R\(h\)|\\geq/);
});

test("repairs and wraps a bare hat command emitted by a local model", () => {
    const prepared = math.prepareForMarkdown(
        "L'erreur empirique \\hat R}(h) doit rester lisible."
    );

    assert.equal(prepared.math.length, 1);
    assert.equal(prepared.math[0].source, "\\hat{R}(h)");
    assert.equal(prepared.math[0].display, false);
});

test("wraps a complete bare absolute-value expression", () => {
    const prepared = math.prepareForMarkdown(
        "On contrôle | \\hat R - R | uniformément."
    );

    assert.equal(prepared.math.length, 1);
    assert.equal(prepared.math[0].source, "| \\hat{R} - R |");
});

test("supports the non-standard macros commonly produced by models", () => {
    assert.equal(math.KATEX_MACROS["\\VC"], "\\operatorname{VC}");
    assert.equal(math.KATEX_MACROS["\\R"], "\\mathbb{R}");
    assert.equal(math.KATEX_MACROS["\\E"], "\\mathbb{E}");
});

test("never interprets LaTeX-looking content inside code spans or fences", () => {
    const source = "Utilise `\\hat R` ici.\n\n```tex\n\\VC(H)\n```";
    const prepared = math.prepareForMarkdown(source);

    assert.equal(prepared.math.length, 0);
    assert.equal(prepared.text, source);
});

test("escapes restored formulas before inserting them into HTML", () => {
    const prepared = math.prepareForMarkdown("\\(x < y\\)");
    const html = math.restoreAfterMarkdown(
        `<p>${prepared.text}</p>`,
        prepared.math,
        value => value.replaceAll("<", "&lt;")
    );

    assert.equal(html, "<p>\\(x &lt; y\\)</p>");
});
