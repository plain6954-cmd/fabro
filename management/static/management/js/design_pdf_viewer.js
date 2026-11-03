/* A single-page PDF.js canvas; image inspection and review decisions stay separate. */
window.fabroOnPageLoad(() => {
    'use strict';
    const dialog = document.getElementById('designPdfViewer');
    if (!dialog || dialog.__fabroPdfInitialized) return;
    dialog.__fabroPdfInitialized = true;
    const scope = window.fabroCreatePageScope();
    const stage = document.getElementById('designPdfStage');
    const canvas = document.getElementById('designPdfCanvas');
    const loading = document.getElementById('designPdfLoading');
    const error = document.getElementById('designPdfError');
    const download = document.getElementById('designPdfDownload');
    let library = null, loadingTask = null, documentPdf = null, renderTask = null;
    let session = 0, rendering = 0, pageNumber = 1, scale = 1, fit = true;
    let restore = null, opener = null, currentFile = null, resizeFrame = null;

    function controls() {
        const focused = document.activeElement;
        const ready = !!documentPdf;
        for (const action of ['previous', 'next', 'out', 'in', 'fit']) {
            dialog.querySelector(`[data-pdf-action="${action}"]`).disabled = !ready;
        }
        if (ready) {
            dialog.querySelector('[data-pdf-action="previous"]').disabled = pageNumber <= 1;
            dialog.querySelector('[data-pdf-action="next"]').disabled = pageNumber >= documentPdf.numPages;
            dialog.querySelector('[data-pdf-action="out"]').disabled = scale <= 0.1;
            dialog.querySelector('[data-pdf-action="in"]').disabled = scale >= 4;
        }
        document.getElementById('designPdfCounter').textContent = ready ? `${pageNumber} / ${documentPdf.numPages}` : '0 / 0';
        document.getElementById('designPdfZoom').textContent = `${Math.round(scale * 100)}%`;
        download.hidden = !ready;
        if (dialog.open && dialog.contains(focused) && focused.disabled) dialog.focus({ preventScroll: true });
    }

    function fail() {
        loading.hidden = true;
        canvas.hidden = true;
        error.hidden = false;
    }

    async function render() {
        if (!documentPdf || !dialog.open) return;
        const token = ++rendering;
        const pdf = documentPdf;
        const previous = renderTask;
        previous?.cancel();
        renderTask = null;
        loading.hidden = false;
        error.hidden = true;
        canvas.hidden = true;
        try {
            if (previous) await previous.promise.catch(() => {});
            const page = await pdf.getPage(pageNumber);
            if (token !== rendering || pdf !== documentPdf || !dialog.open) return;
            const base = page.getViewport({ scale: 1 });
            if (fit) scale = 1;
            const viewport = page.getViewport({ scale: Math.max(1, stage.clientWidth - 32) / base.width * scale });
            // Bound the one live canvas while retaining HiDPI detail where memory permits.
            const density = Math.min(devicePixelRatio || 1, Math.sqrt(16 * 1024 * 1024 / (viewport.width * viewport.height)));
            canvas.width = Math.max(1, Math.floor(viewport.width * density));
            canvas.height = Math.max(1, Math.floor(viewport.height * density));
            canvas.style.width = `${viewport.width}px`;
            canvas.style.height = `${viewport.height}px`;
            canvas.setAttribute('aria-label', `${currentFile.title}, ${pageNumber} / ${pdf.numPages}`);
            const task = page.render({
                canvasContext: canvas.getContext('2d'), viewport,
                transform: density !== 1 ? [density, 0, 0, density, 0, 0] : null,
            });
            renderTask = task;
            controls();
            await task.promise;
            if (token !== rendering || pdf !== documentPdf || !dialog.open) return;
            renderTask = null;
            page.cleanup();
            loading.hidden = true;
            canvas.hidden = false;
            stage.scrollTo(0, 0);
        } catch (failure) {
            if (token === rendering && dialog.open && failure.name !== 'RenderingCancelledException') fail();
        }
    }

    function close() {
        session++;
        rendering++;
        renderTask?.cancel();
        renderTask = null;
        const task = loadingTask;
        loadingTask = documentPdf = null;
        if (task) task.destroy().catch(() => {});
        cancelAnimationFrame(resizeFrame);
        canvas.width = canvas.height = 0;
        canvas.hidden = true;
        download.removeAttribute('href');
        dialog.classList.remove('is-visible');
        if (dialog.open) dialog.close();
        if (restore) {
            Object.assign(document.body.style, restore.style);
            window.scrollTo({ left: restore.x, top: restore.y, behavior: 'instant' });
            restore = null;
        }
        if (opener?.isConnected) opener.focus({ preventScroll: true });
        controls();
    }

    // Both the inline review preview and full-screen viewer use this private loader.
    async function createPdfTask(file) {
        const url = new URL(file.original_url || `/design-images/${encodeURIComponent(file.id)}/download/`, location.origin);
        if (url.origin !== location.origin || !/^\/design-images\/\d+\/(?:download|comparison-file)\/$/.test(url.pathname)) throw new Error('Invalid PDF destination');
        if (!library) library = import(dialog.dataset.pdfjsUrl).catch(failure => { library = null; throw failure; });
        const pdfjs = await library;
        if (scope.signal.aborted) throw new DOMException('Page closed', 'AbortError');
        pdfjs.GlobalWorkerOptions.workerSrc = dialog.dataset.workerUrl;
        const assetBase = dialog.dataset.assetBase;
        return pdfjs.getDocument({
            url: url.href, withCredentials: true,
            cMapUrl: `${assetBase}cmaps/`, cMapPacked: true,
            standardFontDataUrl: `${assetBase}standard_fonts/`, wasmUrl: `${assetBase}wasm/`,
            useWasm: false,
        });
    }

    async function open(file, source) {
        close();
        window.closeDesignImageViewer?.(true);
        window.closeApprovalDrawer?.();
        currentFile = file;
        opener = source;
        const token = ++session;
        pageNumber = scale = 1;
        fit = true;
        restore = { x: scrollX, y: scrollY, style: {
            position: document.body.style.position, top: document.body.style.top,
            left: document.body.style.left, width: document.body.style.width,
            overflow: document.body.style.overflow,
        } };
        Object.assign(document.body.style, { position: 'fixed', top: `-${scrollY}px`, left: '0', width: '100%', overflow: 'hidden' });
        document.getElementById('designPdfTitle').textContent = file.title;
        loading.hidden = false;
        error.hidden = true;
        dialog.showModal();
        controls();
        requestAnimationFrame(() => { if (dialog.open) dialog.classList.add('is-visible'); });
        try {
            // Always retrieve bytes through the existing same-origin permission check.
            const url = new URL(file.original_url || `/design-images/${encodeURIComponent(file.id)}/download/`, location.origin);
            if (url.origin !== location.origin || !/^\/design-images\/\d+\/(?:download|comparison-file)\/$/.test(url.pathname)) throw new Error('Invalid PDF destination');
            const task = await createPdfTask(file);
            if (token !== session || !dialog.open) { task.destroy().catch(() => {}); return; }
            loadingTask = task;
            const pdf = await task.promise;
            if (token !== session || !dialog.open) return;
            documentPdf = pdf;
            url.searchParams.set('download', '1');
            download.href = url.href;
            controls();
            await render();
        } catch (_failure) {
            if (token === session && dialog.open) fail();
        }
    }

    function navigate(number) {
        if (!documentPdf) return;
        pageNumber = Math.max(1, Math.min(documentPdf.numPages, number));
        render();
    }
    function zoom(value) {
        if (!documentPdf) return;
        fit = false;
        scale = Math.max(0.1, Math.min(4, value));
        render();
    }
    function fitWidth() { if (documentPdf) { fit = true; render(); } }
    scope.listen(dialog, 'cancel', event => { event.preventDefault(); close(); });
    scope.listen(dialog, 'click', event => {
        const action = event.target.closest('[data-pdf-action]')?.dataset.pdfAction;
        if (action === 'close') close();
        if (action === 'previous') navigate(pageNumber - 1);
        if (action === 'next') navigate(pageNumber + 1);
        if (action === 'out') zoom(scale / 1.25);
        if (action === 'in') zoom(scale * 1.25);
        if (action === 'fit') fitWidth();
        if (action === 'retry') open(currentFile, opener);
    });
    scope.listen(dialog, 'keydown', event => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (['ArrowRight', 'PageDown', 'ArrowLeft', 'PageUp', 'Home', 'End', '+', '=', '-', 'f', 'F'].includes(event.key)) event.preventDefault();
        if (event.key === 'ArrowRight' || event.key === 'PageDown') navigate(pageNumber + 1);
        if (event.key === 'ArrowLeft' || event.key === 'PageUp') navigate(pageNumber - 1);
        if (event.key === 'Home') navigate(1);
        if (event.key === 'End') navigate(documentPdf?.numPages || 1);
        if (event.key === '+' || event.key === '=') zoom(scale * 1.25);
        if (event.key === '-') zoom(scale / 1.25);
        if (event.key.toLowerCase() === 'f') fitWidth();
    });
    scope.listen(window, 'resize', () => {
        cancelAnimationFrame(resizeFrame);
        if (dialog.open && fit && documentPdf) resizeFrame = requestAnimationFrame(render);
    });
    window.fabroCreateDesignPdfTask = createPdfTask;
    window.openDesignPdfViewer = open;
    window.closeDesignPdfViewer = close;
    scope.onCleanup(() => {
        close();
        delete dialog.__fabroPdfInitialized;
        if (window.openDesignPdfViewer === open) {
            delete window.fabroCreateDesignPdfTask;
            delete window.openDesignPdfViewer;
            delete window.closeDesignPdfViewer;
        }
    });
});
