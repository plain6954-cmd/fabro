/* Presentation only. All actions are independently enforced on the server. */
(function () {
    'use strict';
    if (window.fabroActivityAccess) return;
    let permissions = {}, running = null;
    try { permissions = JSON.parse(document.getElementById('fabro-activity-data')?.textContent || '{}'); } catch (_) {}
    const allowed = key => permissions[key] === true;
    function apply() {
        document.querySelectorAll('[data-activity], [data-activity-any]').forEach(node => {
            const denied = node.dataset.activityAny ? !node.dataset.activityAny.split(' ').some(allowed) : !allowed(node.dataset.activity);
            if (denied) { node.hidden = true; node.dataset.activityDenied = 'true'; }
            else if (node.dataset.activityDenied) { node.hidden = false; delete node.dataset.activityDenied; }
            if (denied && /^(BUTTON|INPUT|SELECT|TEXTAREA)$/.test(node.tagName)) { if (!node.disabled) node.dataset.activityDisabledByGate = 'true'; node.disabled = true; }
            else if (!denied && node.dataset.activityDisabledByGate) { node.disabled = false; node.removeAttribute?.('disabled'); delete node.dataset.activityDisabledByGate; }
        });
    }
    async function refresh() {
        if (running || document.hidden) return;
        running = fetch('/account/activity-access/', {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}})
            .then(response => { if (!response.ok || response.redirected) throw new Error('Access unavailable'); return response.json(); })
            .then(data => { permissions = data.permissions; apply(); }).catch(() => {}).finally(() => { running = null; });
        return running;
    }
    let queued = false;
    const observer = new MutationObserver(() => { if (!queued) { queued = true; queueMicrotask(() => { queued = false; apply(); }); } });
    observer.observe(document.documentElement, {childList: true, subtree: true});
    window.addEventListener('pagehide', () => observer.disconnect(), {once: true});
    window.fabroActivityAllowed = allowed;
    window.fabroActivityAccess = {apply, refresh};
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, {once: true}); else apply();
    document.addEventListener('htmx:afterSettle', refresh);
    window.addEventListener('focus', refresh);
})();
