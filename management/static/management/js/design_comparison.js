/* Independent view state; no approval mutations. Exported for terminal unit tests. */
(function () {
    'use strict';
    class ComparisonPanelState {
        constructor(files = []) { this.files = files; this.index = -1; this.page = 1; this.fit(); }
        current() { return this.files[this.index] || null; }
        select(index) {
            this.index = this.files.length ? (index % this.files.length + this.files.length) % this.files.length : -1;
            this.page = 1; this.fit(); return this.current();
        }
        move(delta) { return this.select(this.index + delta); }
        changePage(delta, count) { this.page = Math.max(1, Math.min(count, this.page + delta)); return this.page; }
        fit() { this.scale = 1; this.x = this.y = 0; }
        zoom(factor, pdf = false) { this.scale = Math.max(pdf ? 0.25 : 1, Math.min(pdf ? 4 : 8, this.scale * factor)); }
    }
    function clampPan(value, content, container) { const bound = Math.max(0, (content - container) / 2); return Math.max(-bound, Math.min(bound, value)); }
    function comparisonSelection(data, id) {
        if (!Array.isArray(data.references) || !Array.isArray(data.uploads)) throw new Error('Invalid comparison');
        const reference = data.references.findIndex(file => file.id === Number(id));
        const upload = data.uploads.findIndex(file => file.id === Number(id));
        if (reference < 0 && upload < 0) throw new Error('Invalid comparison');
        // The manifest orders files by upload time, then ID; the final upload is the latest revision.
        return { reference: reference < 0 ? 0 : reference, upload: upload < 0 ? data.uploads.length - 1 : upload,
            side: reference < 0 ? 'upload' : 'reference' };
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = { ComparisonPanelState, clampPan, comparisonSelection };
    if (typeof window === 'undefined') return;
    window.fabroOnPageLoad(() => {
        const dialog = document.getElementById('designComparisonViewer');
        if (!dialog || dialog.dataset.initialized) return;
        dialog.dataset.initialized = 'true';
        const scope = window.fabroCreatePageScope();
        const home = document.createComment('comparison-viewer-home'); dialog.before(home);
        const notice = dialog.querySelector('[data-comparison-notice]');
        const information = dialog.querySelector('[data-comparison-information]');
        const reviewHost = dialog.querySelector('[data-comparison-reviewers]');
        const cycleSelect = dialog.querySelector('[data-comparison-cycle]');
        let manifest = null, request = null, openToken = 0, restore = null, opener = null, activeSide = 'upload';
        function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
        function privateUrl(file, key = 'url') {
            const url = new URL(file[key], location.origin);
            if (url.origin !== location.origin || url.pathname !== `/design-images/${file.id}/comparison-file/`) throw new Error('Invalid file destination');
            return url.href;
        }
        function size(value) { return value ? value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB` : ''; }
        const panels = Object.fromEntries(['reference', 'upload'].map(side => {
            const root = dialog.querySelector(`[data-comparison-panel="${side}"]`);
            const carousel = dialog.querySelector(`[data-comparison-carousel="${side}"]`);
            return [side, { side, root, carousel, model: new ComparisonPanelState(), stage: root.querySelector('[data-panel-stage]'), image: root.querySelector('[data-panel-image]'), canvas: root.querySelector('[data-panel-canvas]'), message: root.querySelector('[data-panel-message]'), fallback: root.querySelector('[data-panel-fallback]'), pointers: new Map(), task: null, pdf: null, renderTask: null, token: 0, renderToken: 0, frame: null }];
        }));
        function active(side) {
            activeSide = side;
            for (const p of Object.values(panels)) p.root.dataset.active = String(p.side === side);
            const file = panels[side].model.current(), link = dialog.querySelector('[data-comparison-download]');
            link.hidden = !file; if (file) link.href = privateUrl(file, 'download'); else link.removeAttribute('href');
        }
        function updateControls(p) {
            const file = p.model.current(), pdf = file?.type === 'pdf';
            p.root.querySelector('[data-panel-counter]').textContent = `${file ? p.model.index + 1 : 0} / ${p.model.files.length}`;
            p.root.querySelector('[data-panel-zoom]').textContent = `${Math.round(p.model.scale * 100)}%`;
            const media = file && ['pdf', 'image'].includes(file.type);
            for (const action of ['in', 'out', 'fit']) p.root.querySelector(`[data-panel-action="${action}"]`).disabled = !media;
            for (const action of ['previous', 'next']) p.root.querySelector(`[data-panel-action="${action}"]`).disabled = p.model.files.length < 2;
            for (const button of p.carousel.querySelectorAll('[data-carousel-step]')) button.disabled = p.model.files.length < 2;
            p.root.querySelector('[data-pdf-controls]').hidden = !pdf;
            p.root.querySelector('[data-pdf-counter]').textContent = `${p.pdf ? p.model.page : 0} / ${p.pdf?.numPages || 0}`;
            p.root.querySelector('[data-panel-action="pdf-previous"]').disabled = !p.pdf || p.model.page <= 1;
            p.root.querySelector('[data-panel-action="pdf-next"]').disabled = !p.pdf || p.model.page >= p.pdf.numPages;
            p.carousel.querySelectorAll('[data-file-index]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.fileIndex) === p.model.index)));
        }
        function clearPanel(p) {
            p.token++; p.renderToken++;
            for (const id of p.pointers.keys()) if (p.stage.hasPointerCapture(id)) p.stage.releasePointerCapture(id);
            p.pointers.clear(); p.gesture = null;
            p.renderTask?.cancel(); p.renderTask = null;
            const task = p.task; p.task = p.pdf = null;
            task?.destroy().catch(() => {});
            cancelAnimationFrame(p.frame);
            p.image.onload = p.image.onerror = null; p.image.removeAttribute('src'); p.image.style.transform = ''; p.image.hidden = true;
            p.canvas.width = p.canvas.height = 0; p.canvas.style.width = p.canvas.style.height = ''; p.canvas.hidden = true;
            p.stage.scrollTop = p.stage.scrollLeft = 0;
            p.fallback.hidden = true; p.message.hidden = true;
            p.root.querySelector('[data-panel-action="retry"]').hidden = true;
        }
        function fail(p) {
            p.image.hidden = p.canvas.hidden = true;
            p.message.textContent = 'File unavailable. Check your access or try again.'; p.message.hidden = false;
            p.root.querySelector('[data-panel-action="retry"]').hidden = false;
        }
        function paintImage(p) {
            if (!p.image.naturalWidth || p.image.hidden || !p.stage.getClientRects().length) return;
            const fit = Math.min(p.stage.clientWidth / p.image.naturalWidth, p.stage.clientHeight / p.image.naturalHeight);
            p.model.x = clampPan(p.model.x, p.image.naturalWidth * fit * p.model.scale, p.stage.clientWidth);
            p.model.y = clampPan(p.model.y, p.image.naturalHeight * fit * p.model.scale, p.stage.clientHeight);
            p.image.style.transform = `translate3d(${p.model.x}px, ${p.model.y}px, 0) scale(${p.model.scale})`;
        }
        async function renderPdf(p) {
            if (!p.pdf || !dialog.open || !p.stage.getClientRects().length) return;
            const token = ++p.renderToken, documentPdf = p.pdf;
            p.renderTask?.cancel();
            try {
                const page = await documentPdf.getPage(p.model.page);
                if (token !== p.renderToken || documentPdf !== p.pdf || !dialog.open) return;
                const original = page.getViewport({ scale: 1 });
                const fit = Math.max(100, p.stage.clientWidth - 24) / original.width;
                const viewport = page.getViewport({ scale: fit * p.model.scale });
                const ratio = Math.min(devicePixelRatio || 1, 2, Math.sqrt(16000000 / (viewport.width * viewport.height)));
                p.canvas.width = Math.ceil(viewport.width * ratio); p.canvas.height = Math.ceil(viewport.height * ratio);
                p.canvas.style.width = `${viewport.width}px`; p.canvas.style.height = `${viewport.height}px`;
                const render = page.render({ canvasContext: p.canvas.getContext('2d'), viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
                p.renderTask = render; await render.promise;
                if (token !== p.renderToken || !dialog.open) return;
                p.canvas.hidden = false; p.message.hidden = true; updateControls(p);
            } catch (failure) {
                if (token === p.renderToken && dialog.open && failure.name !== 'RenderingCancelledException') fail(p);
            }
        }
        async function loadPanel(p) {
            clearPanel(p);
            const file = p.model.current(), token = p.token;
            p.root.querySelector('[data-panel-title]').textContent = p.side === 'upload' ? `Designer Upload${file?.cycle ? ' · Rev ' + file.cycle : ''}` : file?.type === 'pdf' ? 'Reference PDF' : file?.type === 'image' ? 'Reference Image' : 'Reference Viewer';
            p.root.querySelector('[data-panel-file]').textContent = file?.title || '';
            p.stage.dataset.type = file?.type || 'empty';
            updateControls(p);
            if (!file) { p.message.textContent = p.side === 'reference' ? 'No authorized reference files in this context.' : 'No designer uploads available'; p.message.hidden = false; return; }
            try {
                if (file.type === 'image') {
                    p.message.textContent = 'Loading image…'; p.message.hidden = false;
                    p.image.alt = file.title;
                    p.image.onload = () => { if (token === p.token && dialog.open) { p.message.hidden = true; p.image.hidden = false; paintImage(p); } };
                    p.image.onerror = () => { if (token === p.token && dialog.open) fail(p); };
                    p.image.src = privateUrl(file);
                } else if (file.type === 'pdf') {
                    p.message.textContent = 'Loading PDF…'; p.message.hidden = false;
                    const task = await window.fabroCreateDesignPdfTask({ original_url: privateUrl(file) });
                    if (token !== p.token || !dialog.open) { task.destroy().catch(() => {}); return; }
                    p.task = task; const pdf = await task.promise;
                    if (token !== p.token || !dialog.open) return;
                    p.pdf = pdf; await renderPdf(p);
                } else {
                    p.fallback.querySelector('[data-fallback-title]').textContent = file.title;
                    p.fallback.querySelector('[data-fallback-meta]').textContent = [file.extension, size(file.size), 'Preview is not available for this format.'].filter(Boolean).join(' · ');
                    p.fallback.querySelector('[data-fallback-download]').href = privateUrl(file, 'download'); p.fallback.hidden = false;
                }
            } catch (_failure) { if (token === p.token && dialog.open) fail(p); }
        }
        function metadata() {
            if (!manifest) return;
            const reference = panels.reference.model.current(), upload = panels.upload.model.current();
            information.replaceChildren();
            const fields = [['Vehicle', manifest.vehicle || 'Unassigned'], ['Pattern', manifest.pattern], ['Revision', upload?.cycle],
                ['Reference set', manifest.references.length], ['Designer uploads', manifest.uploads.length],
                ['Reference', reference?.title], ['Reference size', size(reference?.size)], ['Designer file', upload?.title],
                ['File size', size(upload?.size)], ['Uploader', upload?.uploader], ['Uploaded', upload?.date]];
            for (const [label, value] of fields) if (value !== undefined && value !== null && value !== '') {
                const field = node('span', '', label + ': '); field.append(node('strong', '', String(value))); information.append(field);
            }
        }
        function remarks() {
            window.fabroReviewVoice?.stopPlaybackWithin(reviewHost); reviewHost.replaceChildren();
            const file = panels.upload.model.current(), history = file?.history || [];
            const cycle = history.find(item => String(item.cycle) === cycleSelect.value) || history[0];
            dialog.querySelector('[data-comparison-history-note]').hidden = !cycle || cycle === history[0];
            if (!cycle) { reviewHost.append(node('p', '', file?.remarks_allowed ? 'No review has been submitted for this upload.' : 'Review details are not available for this account.')); return; }
            for (const stage of cycle.stages) {
                const card = node('section', 'comparison-review-card'); card.dataset.reviewerStage = stage.role;
                const header = node('header'); header.append(node('strong', '', stage.role), node('span', `comparison-status ${stage.status}`, stage.label)); card.append(header);
                const meta = [stage.reviewer, stage.timestamp, stage.classification ? stage.classification[0].toUpperCase() + stage.classification.slice(1) + ' Change' : ''].filter(Boolean).join(' · ');
                if (meta) card.append(node('div', 'comparison-review-meta', meta));
                if (stage.comment) card.append(node('p', '', stage.comment));
                if (stage.voice_notes?.length) window.fabroReviewVoice?.appendBubbles(card, stage.voice_notes);
                reviewHost.append(card);
            }
        }
        function updateRemarks() {
            cycleSelect.replaceChildren();
            const file = panels.upload.model.current();
            for (const cycle of file?.history || []) { const option = node('option', '', `Cycle ${cycle.cycle}${cycle.cycle === file.cycle ? ' · current' : ' · earlier remarks'}`); option.value = cycle.cycle; cycleSelect.append(option); }
            cycleSelect.hidden = !file?.history?.length; remarks();
        }
        function selectFile(p, index) {
            p.model.select(index); loadPanel(p);
            if (innerWidth <= 650) setMobile(p.side); else active(p.side);
            metadata();
            const thumb = p.carousel.querySelector(`[data-file-index="${p.model.index}"]`);
            thumb?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'instant' });
            if (p.side === 'upload') updateRemarks();
        }
        function carousel(p) {
            const strip = p.carousel.querySelector('[data-carousel-strip]'); strip.replaceChildren();
            p.carousel.querySelector('[data-carousel-count]').textContent = `(${p.model.files.length})`;
            p.model.files.forEach((file, index) => {
                const button = node('button'); button.type = 'button'; button.dataset.fileIndex = index;
                button.setAttribute('aria-label', file.title); button.title = file.title; button.setAttribute('aria-pressed', 'false');
                if (file.thumbnail) {
                    const img = node('img'); img.src = privateUrl(file, 'thumbnail'); img.alt = file.title; img.loading = 'lazy';
                    img.onerror = () => { img.remove(); button.append(node('span', '', file.extension || 'Image')); }; button.append(img);
                } else button.append(node('span', '', file.type === 'pdf' ? '▤ PDF' : file.type === 'image' ? '▧ Image' : '▤ ' + file.extension));
                strip.append(button);
            });
            if (!p.model.files.length) strip.append(node('span', '', 'No files'));
        }
        function redraw(p) { if (p.model.current()?.type === 'pdf') renderPdf(p); else paintImage(p); }
        function fit(p) { p.model.fit(); p.stage.scrollTop = p.stage.scrollLeft = 0; redraw(p); updateControls(p); }
        function zoom(p, factor) { p.model.zoom(factor, p.model.current()?.type === 'pdf'); redraw(p); updateControls(p); }
        function resize() {
            for (const p of Object.values(panels)) { cancelAnimationFrame(p.frame); p.frame = requestAnimationFrame(() => { if (dialog.open) redraw(p); }); }
        }
        function split() { dialog.dataset.panelFocus = ''; resize(); }
        function setMobile(side) {
            if (dialog.dataset.panelFocus && dialog.dataset.panelFocus !== side) dialog.dataset.panelFocus = '';
            dialog.dataset.mobileSide = side;
            dialog.querySelectorAll('[data-mobile-side]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mobileSide === side)));
            active(side); resize();
        }
        function collapseRemarks(collapsed) {
            dialog.dataset.remarksCollapsed = String(collapsed);
            const button = dialog.querySelector('[data-comparison-action="remarks"]'); button.setAttribute('aria-expanded', String(!collapsed)); button.textContent = collapsed ? '☰' : '−'; resize();
        }
        async function open(id, source) {
            if (!/^\d+$/.test(String(id))) return;
            if (dialog.open) close();
            opener = source || document.activeElement;
            restore = { x: scrollX, y: scrollY, style: { position: document.body.style.position, top: document.body.style.top, left: document.body.style.left, width: document.body.style.width, overflow: document.body.style.overflow } };
            document.body.append(dialog); Object.assign(document.body.style, { position: 'fixed', top: `-${scrollY}px`, left: '0', width: '100%', overflow: 'hidden' });
            document.querySelectorAll('audio[data-review-voice-audio]').forEach(audio => audio.pause());
            dialog.showModal(); dialog.dataset.panelFocus = ''; manifest = null; information.replaceChildren();
            notice.textContent = 'Loading comparison…'; notice.hidden = false;
            collapseRemarks(innerWidth < 1300); setMobile('upload');
            for (const p of Object.values(panels)) { clearPanel(p); p.model = new ComparisonPanelState(); carousel(p); loadPanel(p); }
            cycleSelect.replaceChildren(); updateRemarks(); dialog.querySelector('[data-comparison-action="close"]').focus();
            const token = ++openToken; request = new AbortController();
            try {
                const response = await fetch(`/api/design-images/${id}/comparison/`, { signal: request.signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'} });
                if (response.redirected || !response.ok) throw new Error('Comparison unavailable');
                const data = await response.json();
                if (token !== openToken || !dialog.open) return;
                const selection = comparisonSelection(data, id);
                manifest = data; notice.hidden = true;
                panels.reference.model = new ComparisonPanelState(data.references); panels.upload.model = new ComparisonPanelState(data.uploads);
                carousel(panels.reference); carousel(panels.upload);
                selectFile(panels.reference, selection.reference); selectFile(panels.upload, selection.upload);
                setMobile(selection.side);
            } catch (failure) {
                if (token === openToken && dialog.open && failure.name !== 'AbortError') { notice.textContent = 'Comparison unavailable. The file may be missing or your access may have changed.'; notice.hidden = false; }
            }
        }
        function close() {
            openToken++; request?.abort(); request = null;
            window.fabroReviewVoice?.stopPlaybackWithin(reviewHost); reviewHost.replaceChildren();
            for (const p of Object.values(panels)) { clearPanel(p); p.model = new ComparisonPanelState(); p.carousel.querySelector('[data-carousel-strip]').replaceChildren(); }
            if (document.fullscreenElement === dialog) document.exitFullscreen().catch(() => {});
            if (dialog.open) dialog.close();
            if (restore) { Object.assign(document.body.style, restore.style); window.scrollTo({ left: restore.x, top: restore.y, behavior: 'instant' }); restore = null; }
            if (home.isConnected) home.after(dialog); else dialog.remove();
            if (opener?.isConnected) opener.focus({preventScroll: true}); manifest = null;
        }
        function escape() { if (document.fullscreenElement === dialog) document.exitFullscreen().catch(() => {}); else if (dialog.dataset.panelFocus) split(); else close(); }
        scope.listen(dialog, 'cancel', event => { event.preventDefault(); escape(); });
        scope.listen(document, 'click', event => { const source = event.target.closest('[data-design-comparison]'); if (source && !source.disabled) { event.preventDefault(); open(source.dataset.designComparison, source); } });
        scope.listen(cycleSelect, 'change', remarks);
        scope.listen(dialog, 'click', event => {
            const action = event.target.closest('[data-comparison-action]')?.dataset.comparisonAction;
            if (action === 'close') close();
            if (action === 'fit') Object.values(panels).forEach(fit);
            if (action === 'split') split();
            if (action === 'remarks') collapseRemarks(dialog.dataset.remarksCollapsed !== 'true');
            if (action === 'fullscreen') {
                const token = openToken;
                const operation = document.fullscreenElement === dialog ? document.exitFullscreen() : dialog.requestFullscreen?.();
                operation?.then(() => { if ((!dialog.open || token !== openToken) && document.fullscreenElement === dialog) return document.exitFullscreen(); })
                    .catch(() => { if (dialog.open && token === openToken) { notice.textContent = 'Browser fullscreen is unavailable. The full-viewport viewer is still available.'; notice.hidden = false; } });
            }
            const mobile = event.target.closest('[data-mobile-side]'); if (mobile) setMobile(mobile.dataset.mobileSide);
        });
        scope.listen(dialog, 'focusin', event => {
            const container = event.target.closest('[data-comparison-panel], [data-comparison-carousel]');
            if (container) active(container.dataset.comparisonPanel || container.dataset.comparisonCarousel);
        });
        scope.listen(dialog, 'keydown', event => {
            event.stopPropagation();
            if (event.key === 'Escape') { event.preventDefault(); escape(); return; }
            if (event.altKey || event.ctrlKey || event.metaKey || event.target.matches('select, input, textarea, audio')) return;
            const carouselRoot = event.target.closest('[data-comparison-carousel]');
            const panelRoot = event.target.closest('[data-comparison-panel]');
            const p = carouselRoot ? panels[carouselRoot.dataset.comparisonCarousel] : panelRoot ? panels[panelRoot.dataset.comparisonPanel] : null;
            if (!p) return;
            if (carouselRoot && ['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); selectFile(p, p.model.index + (event.key === 'ArrowRight' ? 1 : -1)); }
            else if (panelRoot && p.pdf && ['PageDown', 'PageUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) { event.preventDefault(); p.model.changePage(['PageDown', 'ArrowRight'].includes(event.key) ? 1 : -1, p.pdf.numPages); renderPdf(p); }
            else if (panelRoot && ['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoom(p, event.key === '-' ? 0.8 : 1.25); }
        });
        for (const p of Object.values(panels)) {
            scope.listen(p.carousel, 'click', event => {
                active(p.side); const thumb = event.target.closest('[data-file-index]'); const step = event.target.closest('[data-carousel-step]');
                if (thumb) selectFile(p, Number(thumb.dataset.fileIndex));
                if (step) selectFile(p, p.model.index + Number(step.dataset.carouselStep));
            });
            scope.listen(p.root, 'pointerdown', () => active(p.side));
            scope.listen(p.root, 'click', event => {
                const action = event.target.closest('[data-panel-action]')?.dataset.panelAction;
                if (action === 'previous' || action === 'next') selectFile(p, p.model.index + (action === 'next' ? 1 : -1));
                if (action === 'in') zoom(p, 1.25); if (action === 'out') zoom(p, 0.8); if (action === 'fit') fit(p);
                if (action === 'focus') { dialog.dataset.panelFocus = dialog.dataset.panelFocus === p.side ? '' : p.side; setMobile(p.side); resize(); }
                if (action === 'retry') loadPanel(p);
                if ((action === 'pdf-next' || action === 'pdf-previous') && p.pdf) { p.model.changePage(action === 'pdf-next' ? 1 : -1, p.pdf.numPages); renderPdf(p); }
            });
            scope.listen(p.stage, 'wheel', event => {
                if (p.model.current()?.type === 'image' || event.ctrlKey) { event.preventDefault(); zoom(p, event.deltaY < 0 ? 1.1 : 1 / 1.1); }
            }, {passive: false});
            scope.listen(p.stage, 'dblclick', () => { if (p.model.current()?.type === 'image') zoom(p, p.model.scale > 1 ? 1 / p.model.scale : 2); });
            function baseline() {
                const points = Array.from(p.pointers.values());
                if (!points.length) { p.gesture = null; return; }
                p.gesture = { cx: points.reduce((n, point) => n + point.x, 0) / points.length, cy: points.reduce((n, point) => n + point.y, 0) / points.length,
                    distance: points.length > 1 ? Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) : 0,
                    x: p.model.x, y: p.model.y, scale: p.model.scale, left: p.stage.scrollLeft, top: p.stage.scrollTop };
            }
            scope.listen(p.stage, 'pointerdown', event => {
                if (event.button !== 0 || event.target.closest('button, a') || !['image', 'pdf'].includes(p.model.current()?.type)) return;
                event.preventDefault(); p.stage.setPointerCapture(event.pointerId); p.pointers.set(event.pointerId, {x: event.clientX, y: event.clientY}); baseline();
            });
            scope.listen(p.stage, 'pointermove', event => {
                if (!p.pointers.has(event.pointerId) || !p.gesture) return;
                p.pointers.set(event.pointerId, {x: event.clientX, y: event.clientY}); const points = Array.from(p.pointers.values()), gesture = p.gesture;
                const cx = points.reduce((n, point) => n + point.x, 0) / points.length, cy = points.reduce((n, point) => n + point.y, 0) / points.length;
                if (points.length > 1 && gesture.distance) {
                    const ratio = Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) / gesture.distance;
                    p.model.scale = gesture.scale; p.model.zoom(ratio, p.model.current()?.type === 'pdf'); updateControls(p);
                    cancelAnimationFrame(p.frame); p.frame = requestAnimationFrame(() => redraw(p));
                }
                if (p.model.current()?.type === 'image') { p.model.x = gesture.x + cx - gesture.cx; p.model.y = gesture.y + cy - gesture.cy; paintImage(p); }
                else if (points.length === 1) { p.stage.scrollLeft = gesture.left - cx + gesture.cx; p.stage.scrollTop = gesture.top - cy + gesture.cy; }
            });
            for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) scope.listen(p.stage, type, event => { p.pointers.delete(event.pointerId); baseline(); });
            let width = 0, height = 0;
            const observer = new ResizeObserver(() => {
                if (width === p.stage.clientWidth && height === p.stage.clientHeight) return;
                width = p.stage.clientWidth; height = p.stage.clientHeight;
                cancelAnimationFrame(p.frame); p.frame = requestAnimationFrame(() => { if (dialog.open) redraw(p); });
            });
            observer.observe(p.stage); scope.onCleanup(() => observer.disconnect());
        }
        if (!document.fullscreenEnabled || !dialog.requestFullscreen) dialog.querySelector('[data-comparison-action="fullscreen"]').disabled = true;
        window.openDesignComparison = open; window.closeDesignComparison = close;
        scope.listen(window, 'pagehide', close);
        scope.onCleanup(() => { close(); delete dialog.dataset.initialized; if (window.openDesignComparison === open) { delete window.openDesignComparison; delete window.closeDesignComparison; } });
    });
})();
