/* Presentation only: existing Django forms own authorization and review decisions. */
window.fabroOnPageLoad(() => {
    'use strict';
    const root = document.querySelector('.design-review-page');
    if (!root) return;
    const scope = window.fabroCreatePageScope();
    const tabs = Array.from(root.querySelectorAll('[data-review-stage]'));
    const panels = Array.from(root.querySelectorAll('[data-review-panel]'));
    function selectStage(role, focus = false) {
        tabs.forEach(tab => {
            const selected = tab.dataset.reviewStage === role;
            tab.setAttribute('aria-selected', String(selected));
            tab.tabIndex = selected || (!role && tab === tabs[0]) ? 0 : -1;
            if (selected && focus) tab.focus();
        });
        panels.forEach(panel => {
            const hidden = panel.dataset.reviewPanel !== role;
            if (hidden && !panel.hidden) window.fabroReviewVoice?.suspendWithin(panel);
            panel.hidden = hidden;
        });
        root.querySelector('[data-review-select-prompt]').hidden = Boolean(role);
    }
    selectStage(root.dataset.initialStage);
    const imageItems = JSON.parse(document.getElementById('design-preview-images')?.textContent || '[]');
    if (imageItems.length < 2) document.querySelectorAll('#designImageViewer [data-viewer-action="previous"], #designImageViewer [data-viewer-action="next"]').forEach(button => { button.hidden = true; });
    tabs.forEach((tab, index) => {
        scope.listen(tab, 'click', () => selectStage(tab.dataset.reviewStage));
        scope.listen(tab, 'keydown', event => {
            if (event.altKey || event.ctrlKey || event.metaKey) return;
            const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
                : event.key === 'ArrowRight' ? (index + 1) % tabs.length
                : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1;
            if (target < 0) return;
            event.preventDefault(); selectStage(tabs[target].dataset.reviewStage, true);
        });
    });
    scope.listen(root, 'click', event => {
        if (event.target.closest('[data-confirm-decline]') && !window.confirm('Are you sure you want to decline this design and request changes?')) event.preventDefault();
    });

    const media = root.querySelector('[data-review-media]');
    const image = media.querySelector('[data-review-image]');
    const loading = media.querySelector('[data-review-loading]');
    const error = media.querySelector('[data-review-error]');
    function imageState() {
        loading.hidden = image.complete;
        error.hidden = !image.complete || Boolean(image.naturalWidth);
        image.hidden = image.complete && !image.naturalWidth;
        image.closest('button').hidden = image.hidden;
    }
    if (image) {
        scope.listen(image, 'load', imageState); scope.listen(image, 'error', imageState); imageState();
    }
    const canvas = media.querySelector('[data-review-pdf-canvas]');
    let task = null, pdf = null, rendering = null, generation = 0, renderNumber = 0, resizeFrame = null;
    async function renderPdf() {
        if (!pdf || scope.signal.aborted) return;
        const token = ++renderNumber;
        rendering?.cancel();
        const page = await pdf.getPage(1);
        if (token !== renderNumber || scope.signal.aborted) return;
        const base = page.getViewport({ scale: 1 });
        const width = Math.max(100, media.clientWidth - 32);
        const viewport = page.getViewport({ scale: Math.min(width / base.width, 510 / base.height) });
        const ratio = Math.min(devicePixelRatio || 1, 2);
        canvas.width = Math.ceil(viewport.width * ratio); canvas.height = Math.ceil(viewport.height * ratio);
        rendering = page.render({ canvasContext: canvas.getContext('2d'), viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] });
        try { await rendering.promise; }
        catch (failure) { if (failure.name !== 'RenderingCancelledException') throw failure; }
        if (token === renderNumber && !scope.signal.aborted) { canvas.hidden = false; loading.hidden = true; error.hidden = true; }
    }
    async function loadPdf() {
        const token = ++generation;
        renderNumber++; rendering?.cancel();
        const previous = task; task = pdf = null;
        previous?.destroy().catch(() => {});
        loading.hidden = false; error.hidden = true; canvas.hidden = true;
        try {
            const next = await window.fabroCreateDesignPdfTask({ id: JSON.parse(document.getElementById('review-design-id').textContent) });
            if (token !== generation || scope.signal.aborted) { next.destroy().catch(() => {}); return; }
            task = next;
            const documentPdf = await next.promise;
            if (token !== generation || scope.signal.aborted) return;
            pdf = documentPdf;
            await renderPdf();
        } catch (_failure) {
            if (token === generation && !scope.signal.aborted) { loading.hidden = true; error.hidden = false; canvas.hidden = true; }
        }
    }
    if (canvas) {
        loadPdf();
        let width = media.clientWidth;
        const observer = new ResizeObserver(() => {
            if (Math.abs(width - media.clientWidth) < 1) return;
            width = media.clientWidth;
            cancelAnimationFrame(resizeFrame);
            resizeFrame = requestAnimationFrame(() => renderPdf().catch(() => { loading.hidden = true; error.hidden = false; }));
        });
        observer.observe(media); scope.onCleanup(() => observer.disconnect());
        root.querySelectorAll('[data-review-pdf]').forEach(button => scope.listen(button, 'click', () => {
            window.openDesignPdfViewer({ id: JSON.parse(document.getElementById('review-design-id').textContent), title: root.querySelector('.review-file-metadata h2').textContent }, button);
        }));
    }
    const retry = root.querySelector('[data-review-retry]');
    if (retry) scope.listen(retry, 'click', () => {
        if (canvas) loadPdf();
        else { loading.hidden = false; error.hidden = true; image.hidden = false; image.src = image.src; }
    });
    scope.onCleanup(() => { generation++; renderNumber++; rendering?.cancel(); task?.destroy().catch(() => {}); cancelAnimationFrame(resizeFrame); });
});
