/* One page-owned polling loop. No polling while the gallery or browser tab is hidden. */
(function () {
    'use strict';
    window.fabroCreateGallerySync = function ({ root, signal, canCheck, check }) {
        const controller = new AbortController();
        let timer = null, running = false, disposed = false, wasVisible = false, failures = 0;
        function visible() {
            return !disposed && !document.hidden && root.isConnected && root.getClientRects().length > 0 && canCheck();
        }
        function schedule(delay) {
            clearTimeout(timer);
            timer = null;
            if (visible() && !running) timer = setTimeout(run, delay);
        }
        async function run() {
            timer = null;
            if (running || !visible()) return;
            running = true;
            try {
                if (await check(controller.signal) === false) { dispose(); return; }
                failures = 0;
            } catch (_error) {
                if (!disposed) failures = Math.min(3, failures + 1);
            } finally {
                running = false;
                schedule(Math.min(60000, 10000 * 2 ** failures));
            }
        }
        function wake() {
            if (!root.isConnected) { dispose(); return; }
            const current = visible();
            if (!current) { clearTimeout(timer); timer = null; }
            else if (!wasVisible) schedule(0);
            wasVisible = current;
        }
        const observer = new MutationObserver(wake);
        // Watch only this workspace and its ancestor visibility/mount changes.
        for (let element = root; element; element = element.parentElement) {
            observer.observe(element, { childList: true, attributes: true, attributeFilter: ['style', 'class', 'hidden'] });
        }
        function dispose() {
            if (disposed) return;
            disposed = true;
            clearTimeout(timer);
            controller.abort();
            observer.disconnect();
            document.removeEventListener('visibilitychange', wake);
            signal.removeEventListener('abort', dispose);
        }
        signal.addEventListener('abort', dispose, { once: true });
        document.addEventListener('visibilitychange', wake);
        if (signal.aborted) dispose();
        else wake();
        return { wake, dispose };
    };
})();
