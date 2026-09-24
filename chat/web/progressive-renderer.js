(function (root, factory) {
    const api = factory(root);
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.LasmeProgressiveRenderer = api;
    }
})(
    typeof window !== "undefined" ? window : globalThis,
    function (global) {
        "use strict";

        const states = new WeakMap();
        const MIN_FRAME_MS = 16;
        const MIN_CHARS_PER_FRAME = 6;
        const MAX_CHARS_PER_FRAME = 280;
        const TARGET_CATCH_UP_FRAMES = 10;

        function nextVisibleLength(currentLength, targetLength) {
            const remaining = Math.max(0, targetLength - currentLength);
            if (!remaining) return targetLength;
            const adaptiveStep = Math.ceil(
                remaining / TARGET_CATCH_UP_FRAMES
            );
            const step = Math.max(
                MIN_CHARS_PER_FRAME,
                Math.min(MAX_CHARS_PER_FRAME, adaptiveStep)
            );
            return Math.min(targetLength, currentLength + step);
        }

        function stripNumericCitations(value) {
            const text = String(value || "");
            if (!text) return "";
            const protectedParts = text.split(
                /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\r\n]*`)/g
            );
            for (let index = 0; index < protectedParts.length; index += 2) {
                protectedParts[index] = protectedParts[index]
                    .replace(
                        /[ \t]*\[(?:\d+)(?:\s*[,–-]\s*\d+)*\]/g,
                        ""
                    )
                    .replace(
                        /[ \t]*\[(?:\d+)(?:\s*[,–-]\s*\d+)*\s*$/g,
                        ""
                    )
                    .replace(/[ \t]+([,.;:!?])/g, "$1");
            }
            return protectedParts.join("");
        }

        function now() {
            return global.performance?.now?.() ?? Date.now();
        }

        function requestFrame(callback) {
            // PIÈGE : requestAnimationFrame EXISTE dans un onglet masqué
            // mais ne s'y DÉCLENCHE JAMAIS (document.hidden) — la
            // révélation serait gelée et la réponse jamais rendue. Le
            // timer de 16 ms est le relais de visibilité : il garde le
            // flux vivant quelle que soit la visibilité de la page.
            const hidden = Boolean(global.document && global.document.hidden);
            if (
                typeof global.requestAnimationFrame === "function"
                && !hidden
            ) {
                return global.requestAnimationFrame(callback);
            }
            return global.setTimeout(callback, MIN_FRAME_MS);
        }

        function cancelFrame(frameId) {
            // frameId peut provenir d'un rAF OU d'un setTimeout selon la
            // visibilité au moment de la planification : les deux annulations
            // sont sans danger et couvrent les deux cas.
            if (typeof global.cancelAnimationFrame === "function") {
                global.cancelAnimationFrame(frameId);
            }
            if (typeof global.clearTimeout === "function") {
                global.clearTimeout(frameId);
            }
        }

        function stateFor(container) {
            let state = states.get(container);
            if (!state) {
                state = {
                    frameId: null,
                    timeoutId: null,
                    lastPaint: 0,
                    targetText: "",
                    renderedText: "",
                    render: null,
                    onPaint: null,
                    onComplete: null,
                    final: false,
                    completionNotified: false,
                };
                states.set(container, state);
            }
            return state;
        }

        function notifyComplete(container, state) {
            if (
                !state.final
                || state.completionNotified
                || state.renderedText !== state.targetText
            ) {
                return;
            }
            state.completionNotified = true;
            if (typeof state.onComplete === "function") {
                state.onComplete(container);
            }
        }

        function queuePaint(container, state) {
            if (state.frameId !== null || state.timeoutId !== null) return;
            const elapsed = now() - state.lastPaint;
            const delay = Math.max(0, MIN_FRAME_MS - elapsed);
            state.frameId = requestFrame(() => {
                state.frameId = null;
                if (delay <= 1) {
                    paint(container, state);
                    return;
                }
                state.timeoutId = global.setTimeout(() => {
                    state.timeoutId = null;
                    paint(container, state);
                }, delay);
            });
        }

        function paint(container, state) {
            state.lastPaint = now();
            const nextLength = nextVisibleLength(
                state.renderedText.length,
                state.targetText.length
            );
            state.renderedText = state.targetText.slice(0, nextLength);
            if (typeof state.render === "function") {
                state.render(container, state.renderedText);
            }
            if (typeof state.onPaint === "function") {
                state.onPaint(container, state.renderedText);
            }
            if (state.renderedText.length < state.targetText.length) {
                queuePaint(container, state);
                return;
            }
            notifyComplete(container, state);
        }

        function schedule(container, text, render, options = {}) {
            if (!container || typeof render !== "function") return;
            const state = stateFor(container);
            const targetText = String(text || "");

            if (!targetText.startsWith(state.renderedText)) {
                state.renderedText = "";
            }
            state.targetText = targetText;
            state.render = render;
            state.onPaint = options.onPaint || state.onPaint;
            if (options.onComplete) {
                state.onComplete = options.onComplete;
            }
            if (options.final) {
                state.final = true;
            }
            state.completionNotified = false;

            if (state.renderedText === state.targetText) {
                notifyComplete(container, state);
                return;
            }
            queuePaint(container, state);
        }

        function cancel(container) {
            const state = states.get(container);
            if (!state) return;
            if (state.frameId !== null) cancelFrame(state.frameId);
            if (state.timeoutId !== null) {
                global.clearTimeout(state.timeoutId);
            }
            states.delete(container);
        }

        return {
            schedule,
            cancel,
            nextVisibleLength,
            stripNumericCitations,
        };
    }
);
