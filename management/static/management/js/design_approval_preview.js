/* Approval-details image inspection. Review decisions remain outside this dialog. */
window.fabroOnPageLoad(() => {
    'use strict';
    const dialog = document.getElementById('designImageViewer');
    if (!dialog || dialog.__fabroPreviewInitialized) return;
    dialog.__fabroPreviewInitialized = true;
    const scope = window.fabroCreatePageScope();
    scope.onCleanup(() => { delete dialog.__fabroPreviewInitialized; });
    const items = JSON.parse(document.getElementById('design-preview-images').textContent);
    const image = document.getElementById('designViewerImage');
    const stage = document.getElementById('designViewerStage');
    const loading = document.getElementById('designViewerLoading');
    const error = document.getElementById('designViewerError');
    const pointers = new Map();
    let index = 0, scale = 1, x = 0, y = 0, gesture = null;
    let restore = null, opener = null, closeTimer = null, closing = false;

    function navbarOffset() {
        const navbar = document.querySelector('.navbar');
        document.querySelector('.design-identity')?.style.setProperty('--design-navbar-height',
            `${Math.ceil(navbar?.getBoundingClientRect().height || 76) + 8}px`);
    }
    navbarOffset();
    const observer = new ResizeObserver(navbarOffset);
    const navbar = document.querySelector('.navbar');
    if (navbar) observer.observe(navbar);
    scope.onCleanup(() => observer.disconnect());

    function paint() {
        const maxX = Math.max(0, (image.clientWidth * scale - stage.clientWidth) / 2);
        const maxY = Math.max(0, (image.clientHeight * scale - stage.clientHeight) / 2);
        x = Math.max(-maxX, Math.min(maxX, x));
        y = Math.max(-maxY, Math.min(maxY, y));
        image.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
        document.getElementById('designViewerZoom').textContent = `${Math.round(scale * 100)}%`;
        dialog.querySelector('[data-viewer-action="out"]').disabled = scale <= 1;
        dialog.querySelector('[data-viewer-action="in"]').disabled = scale >= 8;
    }
    function zoom(value) { scale = Math.max(1, Math.min(8, value)); paint(); }
    function show(next) {
        index = (next + items.length) % items.length;
        const item = items[index];
        scale = 1; x = y = 0; pointers.clear(); gesture = null;
        document.getElementById('designViewerTitle').textContent = item.title;
        document.getElementById('designViewerCounter').textContent = `${index + 1} / ${items.length}`;
        dialog.querySelectorAll('[data-viewer-action="previous"], [data-viewer-action="next"]').forEach(button => {
            button.disabled = items.length < 2;
        });
        error.hidden = true;
        image.alt = item.title;
        if (image.dataset.url !== item.url) {
            image.hidden = true;
            loading.hidden = false;
            image.dataset.url = item.url;
            image.src = item.url;
        } else {
            image.hidden = !image.naturalWidth;
            loading.hidden = image.complete;
            error.hidden = !image.complete || !!image.naturalWidth;
        }
        paint();
    }
    function finishClose() {
        clearTimeout(closeTimer);
        if (dialog.open) dialog.close();
        if (restore) {
            Object.assign(document.body.style, restore.style);
            window.scrollTo({ left: restore.x, top: restore.y, behavior: 'instant' });
            restore = null;
        }
        opener?.focus({ preventScroll: true });
        pointers.clear(); closing = false;
    }
    function close() {
        if (!dialog.open || closing) return;
        closing = true;
        dialog.classList.remove('is-visible');
        closeTimer = setTimeout(finishClose, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180);
    }
    document.querySelectorAll('[data-design-preview]').forEach(button => {
        scope.listen(button, 'click', () => {
            const selected = items.findIndex(item => String(item.id) === button.dataset.designPreview);
            if (selected < 0) return;
            opener = button;
            restore = { x: scrollX, y: scrollY, style: {
                position: document.body.style.position, top: document.body.style.top,
                left: document.body.style.left, width: document.body.style.width,
                overflow: document.body.style.overflow,
            } };
            Object.assign(document.body.style, { position: 'fixed', top: `-${scrollY}px`, left: '0', width: '100%', overflow: 'hidden' });
            dialog.showModal();
            show(selected);
            requestAnimationFrame(() => { if (dialog.open && !closing) dialog.classList.add('is-visible'); });
        });
    });
    scope.listen(image, 'load', () => { image.hidden = false; loading.hidden = true; error.hidden = true; paint(); });
    scope.listen(image, 'error', () => { image.hidden = true; loading.hidden = true; error.hidden = false; });
    scope.listen(dialog, 'cancel', event => { event.preventDefault(); close(); });
    scope.listen(dialog, 'click', event => {
        const action = event.target.closest('[data-viewer-action]')?.dataset.viewerAction;
        if (action === 'close' || event.target === dialog) close();
        if (action === 'next') show(index + 1);
        if (action === 'previous') show(index - 1);
        if (action === 'in') zoom(scale * 1.25);
        if (action === 'out') zoom(scale / 1.25);
        if (action === 'reset') { x = y = 0; zoom(1); }
        if (action === 'retry') { image.dataset.url = ''; show(index); }
    });
    scope.listen(dialog, 'keydown', event => {
        if (event.key === 'ArrowRight') { event.preventDefault(); show(index + 1); }
        if (event.key === 'ArrowLeft') { event.preventDefault(); show(index - 1); }
        if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(scale * 1.25); }
        if (event.key === '-') { event.preventDefault(); zoom(scale / 1.25); }
    });
    scope.listen(stage, 'wheel', event => { event.preventDefault(); zoom(scale * (event.deltaY < 0 ? 1.1 : 1 / 1.1)); }, { passive: false });
    scope.listen(stage, 'dblclick', () => zoom(scale > 1 ? 1 : 2));
    function baseline() {
        const points = Array.from(pointers.values());
        gesture = { scale, x, y, cx: points.reduce((sum, p) => sum + p.x, 0) / points.length,
            cy: points.reduce((sum, p) => sum + p.y, 0) / points.length,
            distance: points.length === 2 ? Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) : 0 };
    }
    scope.listen(stage, 'pointerdown', event => {
        if (event.button !== 0 || event.target.closest('button')) return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        stage.setPointerCapture(event.pointerId); baseline();
    });
    scope.listen(stage, 'pointermove', event => {
        if (!pointers.has(event.pointerId)) return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        const points = Array.from(pointers.values());
        const cx = points.reduce((sum, p) => sum + p.x, 0) / points.length;
        const cy = points.reduce((sum, p) => sum + p.y, 0) / points.length;
        x = gesture.x + cx - gesture.cx; y = gesture.y + cy - gesture.cy;
        if (points.length === 2 && gesture.distance) {
            scale = Math.max(1, Math.min(8, gesture.scale * Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) / gesture.distance));
        }
        paint();
    });
    function endPointer(event) {
        if (!pointers.has(event.pointerId)) return;
        const start = gesture;
        pointers.delete(event.pointerId);
        if (pointers.size) baseline();
        else if (event.type === 'pointerup' && scale === 1 && start && Math.abs(event.clientX - start.cx) > 60 && Math.abs(event.clientY - start.cy) < 60) {
            show(index + (event.clientX < start.cx ? 1 : -1));
        }
    }
    scope.listen(stage, 'pointerup', endPointer);
    scope.listen(stage, 'pointercancel', endPointer);
    scope.listen(stage, 'lostpointercapture', endPointer);
    scope.listen(window, 'resize', paint);
    scope.onCleanup(finishClose);
});
