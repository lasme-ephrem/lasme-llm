/**
 * Test de chargement combiné des scripts du front (C1).
 *
 * Le navigateur exécute tous les scripts classiques dans le MÊME espace
 * global, dans l'ordre de chargement. Ce test concatène donc les fichiers
 * dans l'ordre réel d'index.html et les évalue dans une portée unique avec
 * un DOM factice — il attrape : syntaxe, déclarations dupliquées
 * (SyntaxError: Identifier already declared), accès anticipés (TDZ) et
 * appels de chargement vers des fonctions déclarées plus tard.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "chat", "web");

// ORDRE DE CHARGEMENT RÉEL — doit rester aligné sur index.html.
const LOAD_ORDER = [
    "vendor/dompurify/purify.min.js", // stubs : non évalués (vendored)
    "math-renderer.js",
    "progressive-renderer.js",
    "answer-stream.js",
    "app.js",
    "src/ui/helpers.js",
    "src/ui/inputs.js",
    "src/ui/model-picker.js",
    "src/ui/sidebar.js",
    "src/ui/theme.js",
    "src/chat/composer.js",
    "src/chat/sessions.js",
    "src/chat/memory.js",
    "src/chat/stream.js",
    "src/renderers/image-cards.js",
    "src/renderers/thinking.js",
    "src/renderers/tools.js",
    "src/renderers/agent-replay.js",
    "src/renderers/performance.js",
    "src/renderers/tables.js",
    "src/renderers/sources.js",
    "src/renderers/message.js",
    "src/studio/ide.js",
    "workspace.js",
];

// Modules VRAIMENT évalués (les libs vendorées sont remplacées par des
// stubs — leur comportement n'est pas celui qu'on teste ici).
const EVALUATED = LOAD_ORDER.filter(
    (file) => !file.startsWith("vendor/")
);

function makeStub() {
    return new Proxy(function () {}, {
        get(_target, prop) {
            if (prop === Symbol.iterator) return function* () {};
            if (prop === Symbol.toPrimitive || prop === "toString" || prop === "valueOf") {
                return () => "";
            }
            if (prop === "then" || prop === Symbol.toStringTag) return undefined;
            if (prop === "length" || prop === "size") return 0;
            return makeStub();
        },
        set() {
            return true;
        },
        apply() {
            return makeStub();
        },
        construct() {
            return makeStub();
        },
        has() {
            return true;
        },
    });
}

function installDomGlobals() {
    const element = makeStub();
    global.document = makeStub();
    global.document.getElementById = () => element;
    global.document.querySelector = () => element;
    global.document.querySelectorAll = () => [];
    global.document.addEventListener = () => {};
    global.document.createElement = () => element;
    global.document.body = element;
    global.document.documentElement = element;
    global.document.head = element;
    global.document.visibilityState = "visible";
    global.window = global;
    global.window.addEventListener = () => {};
    global.window.removeEventListener = () => {};
    global.window.matchMedia = () => ({
        matches: false,
        addEventListener: () => {},
        removeEventListener: () => {},
    });
    global.localStorage = {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {},
    };
    global.sessionStorage = {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {},
    };
    global.location = {
        href: "http://127.0.0.1:8000/",
        search: "",
        hash: "",
        pathname: "/",
        origin: "http://127.0.0.1:8000",
    };
    global.navigator = { userAgent: "node", clipboard: element };
    global.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    global.cancelAnimationFrame = (id) => clearTimeout(id);
    global.fetch = async () => ({
        ok: true,
        status: 200,
        json: async () => ({}),
        body: null,
    });
    global.alert = () => {};
    global.confirm = () => true;
    global.prompt = () => "";
    global.getComputedStyle = () => ({ getPropertyValue: () => "" });
    // Libs vendorées : stubs permissifs (n'importe quelle méthode existe).
    global.marked = makeStub();
    global.DOMPurify = makeStub();
    global.KaTeX = makeStub();
    global.hljs = makeStub();
    global.mermaid = makeStub();
}

test("tous les scripts du front se chargent dans l'ordre sans erreur", () => {
    installDomGlobals();
    const parts = [];
    for (const file of EVALUATED) {
        const full = path.join(WEB, file);
        assert.ok(fs.existsSync(full), `fichier manquant : ${file}`);
        parts.push(`//# ${file}\n${fs.readFileSync(full, "utf-8")}`);
    }
    // Une portée unique = la portée globale partagée des scripts classiques.
    const combined = parts.join("\n;\n");
    assert.doesNotThrow(() => {
        // eslint-disable-next-line no-new-func
        new Function(
            `${combined}\n;`
            + "if (typeof extractRunnerFiles !== 'function') throw new Error('extractRunnerFiles missing');\n"
            + "if (typeof renderRunnerOutputs !== 'function') throw new Error('renderRunnerOutputs missing');\n"
            + "if (typeof openRunnerFileInCanvas !== 'function') throw new Error('openRunnerFileInCanvas missing');\n"
            + "if (typeof togglePinSession !== 'function') throw new Error('togglePinSession missing');\n"
            + "if (typeof openSearchModal !== 'function') throw new Error('openSearchModal missing');\n"
            + "if (typeof openExportSessionModal !== 'function') throw new Error('openExportSessionModal missing');\n"
            + "if (typeof openDuelModal !== 'function') throw new Error('openDuelModal missing');\n"
            + "if (typeof openMissionsModal !== 'function') throw new Error('openMissionsModal missing');\n"
            + "const speechClean = stripMarkdownForSpeech('**Bonjour** `code`');\n"
            + "if (!speechClean.includes('Bonjour')) throw new Error('stripMarkdownForSpeech broken');\n"
            + "const md = csvToMarkdownTable('a,b\\n1,2');\n"
            + "if (!md.includes('| a | b |')) throw new Error('csvToMarkdownTable broken');\n"
        )();
    });
});

test("l'ordre de chargement du test est complet (app.js puis src/ puis workspace)", () => {
    assert.ok(EVALUATED.includes("app.js"));
    assert.ok(EVALUATED.includes("src/studio/ide.js"));
    assert.equal(EVALUATED[EVALUATED.length - 1], "workspace.js");
    // Les modules ne précèdent jamais le noyau d'état.
    assert.ok(EVALUATED.indexOf("app.js") < EVALUATED.indexOf("src/ui/helpers.js"));
});
