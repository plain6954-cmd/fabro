/* Presentation only. All actions are independently enforced on the server. */
(function () {
    'use strict';
    if (window.fabroActivityAccess) return;
    let permissions = {}, running = null, version = '', contextVersion, userId, timer, channel, request;
    let stopped = false, failures = 0, peerAt = 0, notice = null;
    let fragmentBaseline = null, fragmentRunning = false;
    const interval = 2000;
    try { permissions = JSON.parse(document.getElementById('fabro-activity-data')?.textContent || '{}'); } catch (_) {}
    try { const data = JSON.parse(document.getElementById('fabro-activity-sync')?.textContent || '{}'); version = data.version || ''; contextVersion = data.context_version; userId = data.user_id; } catch (_) {}
    const allowed = key => permissions[key] === true;
    const blocked = node => Boolean((node.dataset.activity && !allowed(node.dataset.activity))
        || (node.dataset.activityAll && !node.dataset.activityAll.split(' ').every(allowed))
        || (node.dataset.activityAny && !node.dataset.activityAny.split(' ').some(allowed)));
    async function fragments(previous, expected) {
        if (fragmentRunning) return;
        const hosts = Array.from(document.querySelectorAll('[data-access-fragment]')).filter(host =>
            host.dataset.accessKeys?.split(' ').some(key => permissions[key] !== previous[key]));
        if (!hosts.length) { fragmentBaseline = null; return; }
        fragmentRunning = true;
        // Hydrate only authorized read-only fragments, never forms or drafts.
        try {
            const response = await fetch(window.location.href, {credentials: 'same-origin', cache: 'no-store'});
            if (!response.ok || response.redirected || version !== expected) return;
            const fresh = new DOMParser().parseFromString(await response.text(), 'text/html');
            if (version !== expected) return;
            hosts.forEach(host => {
                const next = fresh.querySelector(`[data-access-fragment="${host.dataset.accessFragment}"]`);
                if (next) host.replaceChildren(...Array.from(next.childNodes));
            });
            apply();
            fragmentBaseline = null;
        } catch (_) { /* Next successful version check retries pending hydration. */ }
        finally { fragmentRunning = false; }
    }
    function apply(root = document) {
        root.querySelectorAll('[data-activity], [data-activity-any], [data-activity-all]').forEach(node => {
            const denied = blocked(node);
            if (denied) { node.hidden = true; node.dataset.activityDenied = 'true'; node.setAttribute?.('aria-hidden', 'true'); node.querySelectorAll?.('audio').forEach(audio => audio.pause()); }
            else if (node.dataset.activityDenied) { node.hidden = false; delete node.dataset.activityDenied; node.removeAttribute?.('aria-hidden'); }
            if (denied && /^(BUTTON|INPUT|SELECT|TEXTAREA)$/.test(node.tagName)) { if (!node.disabled) node.dataset.activityDisabledByGate = 'true'; node.disabled = true; }
            else if (!denied && node.dataset.activityDisabledByGate) { node.disabled = false; node.removeAttribute?.('disabled'); delete node.dataset.activityDisabledByGate; }
        });
        root.querySelectorAll('[data-approval-file]').forEach(host => { if (host.shadowRoot) apply(host.shadowRoot); });
    }
    function accessChanged(blocked, signedOut = false) {
        if (!blocked) { notice?.remove(); notice = null; return; }
        if (notice || !document.body) return;
        notice = document.createElement('dialog'); notice.id = 'fabro-access-changed';
        notice.setAttribute('aria-label', 'Access changed');
        notice.style.cssText = 'margin:auto;padding:2rem;max-width:min(90vw,32rem);color:var(--text-primary,#eee);background:var(--bg-secondary,#19151b);border:1px solid var(--border-color,#555);border-radius:12px';
        const text = document.createElement('p'), link = document.createElement('a');
        text.textContent = signedOut ? 'Your session is no longer available. Sign in to continue.' : 'Your access to this section changed. Your unsaved work has been retained on this page.';
        link.className = 'btn btn-primary'; link.href = signedOut ? '/login/' : '/profile/';
        link.textContent = signedOut ? 'Sign in' : 'Open my profile'; notice.append(text, link); document.body.append(notice);
        notice.addEventListener('cancel', event => event.preventDefault()); notice.showModal(); link.focus();
    }
    async function refresh() {
        if (stopped || document.hidden) return;
        if (running) return running;
        request = new AbortController();
        const timeout = setTimeout(() => request?.abort(), 8000);
        const params = new URLSearchParams({version, page: window.location ? window.location.pathname + (window.location.search || '') : '/profile/'});
        running = fetch('/account/activity-access/?' + params, {credentials: 'same-origin', cache: 'no-store', signal: request.signal, headers: {Accept: 'application/json'}})
            .then(async response => {
                if (response.redirected || [401, 403].includes(response.status)) { permissions = {}; apply(); accessChanged(true, true); return; }
                if (!response.ok) throw new Error('Access unavailable');
                const data = await response.json();
                if (userId && data.user_id !== userId) { permissions = {}; apply(); accessChanged(true, true); return; }
                if (data.permissions) {
                    const changed = data.version !== version, previous = permissions;
                    permissions = data.permissions; version = data.version || ''; apply();
                    if (changed) { fragmentBaseline = fragmentBaseline || previous; document.dispatchEvent(new CustomEvent('fabro:access-changed', {detail: {permissions, previous, version}})); }
                }
                if (fragmentBaseline) fragments(fragmentBaseline, version);
                document.dispatchEvent(new CustomEvent('fabro:access-revalidated', {detail: {version}}));
                // A different role/country/staff identity may invalidate server-
                // rendered record scope. Stop interaction and retain drafts;
                // ordinary activity grants/denials never require navigation.
                accessChanged(data.page_allowed === false || Boolean(contextVersion && data.context_version !== contextVersion)); failures = 0;
                channel?.postMessage({type: 'activity_access', user_id: userId, version});
            }).catch(() => { failures++; }).finally(() => { clearTimeout(timeout); running = null; request = null; });
        return running;
    }
    function schedule() {
        clearTimeout(timer);
        if (stopped || document.hidden) return;
        timer = setTimeout(async () => {
            if (Date.now() - peerAt >= interval - 100) {
                if (userId && navigator.locks && channel) {
                    await navigator.locks.request('fabro-access-' + userId, {ifAvailable: true}, async lock => { if (lock) await refresh(); });
                } else await refresh();
            }
            schedule();
        }, Math.min(30000, interval * 2 ** Math.min(failures, 4)));
    }
    function wake() { if (!document.hidden && !stopped) refresh().finally(schedule); }
    try {
        if (userId && typeof BroadcastChannel !== 'undefined') {
            channel = new BroadcastChannel('fabro-activity-' + userId);
            channel.onmessage = event => {
                const data = event.data;
                if (data?.type !== 'activity_access' || data.user_id !== userId) return;
                peerAt = Date.now(); if (data.version !== version) wake();
            };
        }
    } catch (_) { channel = null; }
    let queued = false;
    const observer = new MutationObserver(() => { if (!queued) { queued = true; queueMicrotask(() => { queued = false; apply(); }); } });
    observer.observe(document.documentElement, {childList: true, subtree: true});
    function suspend() { clearTimeout(timer); request?.abort(); }
    window.addEventListener('pagehide', () => { stopped = true; suspend(); observer.disconnect(); channel?.close(); });
    window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false; channel = null; observer.observe(document.documentElement, {childList: true, subtree: true}); wake(); } });
    document.addEventListener('visibilitychange', () => { if (document.hidden) suspend(); else wake(); });
    window.addEventListener('online', wake);
    function stopStale(event) {
        const node = event.target.closest?.('[data-activity], [data-activity-any], [data-activity-all]');
        if (node && blocked(node)) { event.preventDefault(); event.stopImmediatePropagation(); }
    }
    document.addEventListener('click', stopStale, true); document.addEventListener('submit', stopStale, true);
    window.fabroActivityAllowed = allowed;
    window.fabroActivityAccess = {apply, refresh, get version() { return version; }};
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { apply(); wake(); }, {once: true}); else { apply(); wake(); }
    document.addEventListener('htmx:afterSettle', wake);
    document.addEventListener('fabro:page-ready', wake);
    window.addEventListener('focus', wake);
})();
