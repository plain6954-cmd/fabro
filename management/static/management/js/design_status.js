/* Refresh only the read-only status fragment; preserve viewer and form drafts. */
(function () {
    window.fabroOnPageLoad(() => {
        const root = document.getElementById('tab-pane-3d-status');
        if (!root) return;
        const scope = window.fabroCreatePageScope();
        let sequence = 0, readAt = Date.now();

        function initSearchPicker(container = root) {
            const picker = container.querySelector('#status-search-picker');
            const label = container.querySelector('#status-search-field-label');
            const input = container.querySelector('#status-search-input');
            const options = container.querySelector('#status-search-options');
            const hiddenBy = container.querySelector('#status-search-by');
            if (!picker || !label || !options || !hiddenBy) return;

            function togglePicker(open) {
                const show = open ?? !picker.classList.contains('is-suggesting');
                picker.classList.toggle('is-suggesting', show);
                if (input) input.setAttribute('aria-expanded', String(show));
            }

            scope.listen(label, 'click', (e) => {
                e.stopPropagation();
                togglePicker();
            });

            options.querySelectorAll('.search-option').forEach(option => {
                scope.listen(option, 'click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const key = option.dataset.searchBy || 'all';
                    hiddenBy.value = key;
                    const text = option.textContent.trim();
                    label.textContent = text;
                    options.querySelectorAll('.search-option').forEach(btn => btn.classList.toggle('is-active', btn === option));
                    togglePicker(false);
                    if (input) input.focus();
                });
            });

            scope.listen(document, 'click', (e) => {
                if (!picker.contains(e.target)) togglePicker(false);
            });

            scope.listen(picker, 'keydown', (e) => {
                if (e.key === 'Escape') togglePicker(false);
            });
        }

        async function refresh(signal = scope.signal, force = false) {
            if (!root.getClientRects().length || (!force && root.contains(document.activeElement))) return;
            const token = ++sequence, url = new URL(location.href);
            url.searchParams.set('subwindow', '3d-status');
            url.searchParams.set('status_fragment', '1');
            const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal });
            if (token !== sequence || scope.signal.aborted) return;
            if (!response.ok || response.redirected) {
                root.textContent = '3D Status is unavailable for your current access.';
                return;
            }
            const source = new DOMParser().parseFromString(await response.text(), 'text/html');
            if (token !== sequence || scope.signal.aborted || !root.getClientRects().length) return;
            const old = root.querySelector('.design-status-scroll'), scroll = [old?.scrollLeft || 0, old?.scrollTop || 0];
            root.replaceChildren(...Array.from(source.body.childNodes));
            readAt = Date.now();
            initSearchPicker(root);
            const next = root.querySelector('.design-status-scroll');
            if (next) { next.scrollLeft = scroll[0]; next.scrollTop = scroll[1]; }
        }

        initSearchPicker(root);
        scope.listen(document, 'fabro:design-review-saved', () => refresh().catch(() => {}));
        scope.listen(document, 'fabro:access-changed', () => refresh(scope.signal, true).catch(() => {}));
        window.fabroCreateGallerySync({
            root,
            signal: scope.signal,
            canCheck: () => !document.getElementById('designComparisonViewer')?.open,
            check: signal => Date.now() - readAt < 1000 ? true : refresh(signal)
        });
    });
})();
