(function (global) {
    "use strict";

    const states = new WeakMap();
    const MIN_FRAME_MS = 42;

    function stateFor(container) {
        let state = states.get(container);
        if (!state) {
            state = {
                frameId: null,
                timeoutId: null,
                lastPaint: 0,
                text: "",
                render: null,
            };
            states.set(container, state);
        }
        return state;
    }

    function paint(container, state) {
        state.frameId = null;
        state.timeoutId = null;
        state.lastPaint = performance.now();
        if (typeof state.render === "function") {
            state.render(container, state.text);
        }
    }

    function schedule(container, text, render, options = {}) {
        if (!container || typeof render !== "function") return;
        const state = stateFor(container);
        state.text = text || "";
        state.render = render;

        if (options.final) {
            if (state.frameId !== null) {
                cancelAnimationFrame(state.frameId);
                state.frameId = null;
            }
            if (state.timeoutId !== null) {
                clearTimeout(state.timeoutId);
                state.timeoutId = null;
            }
            paint(container, state);
            return;
        }

        if (state.frameId !== null || state.timeoutId !== null) return;
        const elapsed = performance.now() - state.lastPaint;
        const delay = Math.max(0, MIN_FRAME_MS - elapsed);
        state.frameId = requestAnimationFrame(() => {
            if (delay <= 1) {
                paint(container, state);
                return;
            }
            state.timeoutId = setTimeout(() => paint(container, state), delay);
        });
    }

    function cancel(container) {
        const state = states.get(container);
        if (!state) return;
        if (state.frameId !== null) cancelAnimationFrame(state.frameId);
        if (state.timeoutId !== null) clearTimeout(state.timeoutId);
        states.delete(container);
    }

    global.LasmeProgressiveRenderer = { schedule, cancel };
})(window);
