/* Read-only fragments, using FABRO's existing non-overlapping visibility-aware poller. */
(function () {
    'use strict';
    function initialize() {
        const root = document.getElementById('fabroControlTower');
        if (!root || window.__fabroControlTower?.root === root) return;
        window.__fabroControlTower?.dispose();
        const controller = new AbortController(), pending = new Map();
        const source = new URL(root.dataset.source, location.origin);
        if (source.origin !== location.origin) return;
        let poll = null, force = false, received = root.dataset.updatedAt ? performance.now() : -Infinity;
        const error = root.querySelector('[data-ct-error]');
        const scrollHost = root.closest('.erp-dashboard-pane');
        function apply(host, html) {
            if (host.innerHTML === html) { pending.delete(host); return; }
            // A focused review link remains usable and keeps its DOM identity until the user leaves it.
            if (host.contains(document.activeElement)) { pending.set(host, html); return; }
            const top = scrollHost?.scrollTop || 0, left = scrollHost?.scrollLeft || 0;
            const list = host.querySelector('.ct-queue-list, .ct-activity-list'), listTop = list?.scrollTop || 0;
            host.innerHTML = html; pending.delete(host);
            const next = host.querySelector('.ct-queue-list, .ct-activity-list');
            if (next) next.scrollTop = listTop;
            if (scrollHost) { scrollHost.scrollTop = top; scrollHost.scrollLeft = left; }
        }
        async function check(signal) {
            if (!force && performance.now() - received < 25000) return;
            force = false;
            try {
                const response = await fetch(source.href, {signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
                if (response.redirected || [401, 403].includes(response.status)) {
                    error.textContent = root.dataset.accessError; error.hidden = false; return false;
                }
                if (!response.ok) throw new Error('Refresh unavailable');
                const data = await response.json();
                if (signal.aborted || !root.isConnected) return;
                if (!data.fragments || !data.generated_at) throw new Error('Invalid control tower data');
                for (const name of ['metrics', 'pipeline', 'attention', 'activity']) {
                    if (typeof data.fragments[name] !== 'string') throw new Error('Invalid control tower fragment');
                    apply(root.querySelector(`[data-ct-fragment="${name}"]`), data.fragments[name]);
                }
                received = performance.now(); error.hidden = true;
                const updated = root.querySelector('[data-ct-updated]');
                updated.dateTime = data.generated_at; updated.textContent = data.updated_label; updated.title = data.generated_at;
                root.dataset.updatedAt = data.generated_at;
            } catch (failure) {
                if (!signal.aborted) { error.textContent = root.dataset.updateError; error.hidden = false; }
                throw failure;
            }
        }
        const owner = {root, dispose: () => controller.abort()};
        window.__fabroControlTower = owner;
        controller.signal.addEventListener('abort', () => {
            poll?.dispose(); pending.clear();
            if (window.__fabroControlTower === owner) delete window.__fabroControlTower;
        }, {once: true});
        poll = window.fabroCreateGallerySync({root, signal: controller.signal, canCheck: () => true,
            check, interval: 30000, onDispose: () => controller.abort()});
        const refresh = () => { force = true; poll.refresh(); };
        root.querySelector('[data-ct-refresh]').addEventListener('click', refresh, {signal: controller.signal});
        root.addEventListener('focusout', () => queueMicrotask(() => {
            if (!controller.signal.aborted) for (const [host, html] of pending) apply(host, html);
        }), {signal: controller.signal});
        window.addEventListener('focus', refresh, {signal: controller.signal});
        window.addEventListener('pagehide', owner.dispose, {once: true, signal: controller.signal});
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true});
    else initialize();
})();
