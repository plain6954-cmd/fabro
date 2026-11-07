// FABRO — Pattern Master Measurements Workspace Controller
(function() {
    let currentVehicleId = null;
    let accessGeneration = 0;
    const accessScope = window.fabroCreatePageScope();
    accessScope.onCleanup(() => { accessGeneration++; currentVehicleId = null; });
    accessScope.listen(document, 'fabro:access-changed', event => {
        accessGeneration++;
        if (['measurement.view_own', 'measurement.view_all'].some(key => event.detail.previous[key] !== event.detail.permissions[key])) closeInteriorMediaPreview();
        if (editingPicked) editingPicked.can_edit = false;
        swatchGallery?.refreshAccess(editingPicked);
        updatePickerSaveState();
        loadPickedColors(currentVehicleId);
        // Never retain stale view/action grants while the server reauthorizes.
        lastScannedFiles = []; lastInteriorFiles = [];
        renderScannedFiles([]); renderInteriorMedia([]);
        if (currentVehicleId) loadMeasurementFiles(currentVehicleId);
    });
    let availableColors = [];
    let isSubmittingColor = false;

    // HSV to HEX and HEX to HSV helpers
    function hsvToRgb(h, s, v) {
        let r, g, b;
        let i = Math.floor(h * 6);
        let f = h * 6 - i;
        let p = v * (1 - s);
        let q = v * (1 - f * s);
        let t = v * (1 - (1 - f) * s);
        switch (i % 6) {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            case 5: r = v; g = p; b = q; break;
        }
        return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
    }

    function rgbToHex(r, g, b) {
        return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('').toUpperCase();
    }

    function hexToRgb(hex) {
        const h = (hex || '').replace('#', '');
        if (h.length !== 6) return null;
        return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }

    function rgbToHsv(r, g, b) {
        r /= 255; g /= 255; b /= 255;
        let max = Math.max(r, g, b), min = Math.min(r, g, b);
        let h, s, v = max;
        let d = max - min;
        s = max === 0 ? 0 : d / max;
        if (max === min) {
            h = 0;
        } else {
            switch (max) {
                case r: h = (g - b) / d + (g < b ? 6 : 0); break;
                case g: h = (b - r) / d + 2; break;
                case b: h = (r - g) / d + 4; break;
            }
            h /= 6;
        }
        return [h, s, v];
    }

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el && el.value) return el.value;
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    // --------------------------------------------------------------------------
    // Color Picker Controller Class
    // --------------------------------------------------------------------------
    class VisualColorPicker {
        constructor(canvasId, hueSliderId, hexInputId, swatchId, onChange) {
            this.canvas = document.getElementById(canvasId);
            this.hueSlider = document.getElementById(hueSliderId);
            this.hexInput = document.getElementById(hexInputId);
            this.swatch = document.getElementById(swatchId);
            this.onChange = onChange;

            this.h = 0;
            this.s = 1;
            this.v = 1;
            this.isDragging = false;

            this.init();
        }

        init() {
            if (!this.canvas || !this.hueSlider) return;

            // Handle slider input
            this.hueSlider.addEventListener('input', () => {
                this.h = parseFloat(this.hueSlider.value) / 360;
                this.updateCanvasBaseColor();
                this.updateColor();
            });

            // Handle canvas mouse/touch
            const handleMove = (e) => {
                if (!this.isDragging) return;
                const rect = this.canvas.getBoundingClientRect();
                const clientX = e.touches ? e.touches[0].clientX : e.clientX;
                const clientY = e.touches ? e.touches[0].clientY : e.clientY;
                let x = Math.max(0, Math.min(rect.width, clientX - rect.left));
                let y = Math.max(0, Math.min(rect.height, clientY - rect.top));

                this.s = x / rect.width;
                this.v = 1 - (y / rect.height);
                this.updateHandlePosition(x, y);
                this.updateColor();
            };

            this.canvas.addEventListener('mousedown', (e) => {
                this.isDragging = true;
                handleMove(e);
            });
            window.addEventListener('mousemove', handleMove);
            window.addEventListener('mouseup', () => { this.isDragging = false; });

            this.canvas.addEventListener('touchstart', (e) => {
                this.isDragging = true;
                handleMove(e);
            }, { passive: true });
            window.addEventListener('touchmove', handleMove, { passive: true });
            window.addEventListener('touchend', () => { this.isDragging = false; });

            // Handle manual HEX input
            if (this.hexInput) {
                this.hexInput.addEventListener('input', () => {
                    let val = this.hexInput.value.trim();
                    if (!val.startsWith('#')) val = '#' + val;
                    const rgb = hexToRgb(val);
                    if (rgb) {
                        const [h, s, v] = rgbToHsv(rgb[0], rgb[1], rgb[2]);
                        this.h = h; this.s = s; this.v = v;
                        this.hueSlider.value = Math.round(this.h * 360);
                        this.updateCanvasBaseColor();
                        const rect = this.canvas.getBoundingClientRect();
                        if (rect.width > 0) {
                            this.updateHandlePosition(this.s * rect.width, (1 - this.v) * rect.height);
                        }
                        if (this.swatch) this.swatch.style.backgroundColor = val;
                        if (this.onChange) this.onChange(val);
                    }
                });
            }

            this.setColor('#DC2626');
        }

        updateHandle() {
            if (!this.canvas) return;
            const rect = this.canvas.getBoundingClientRect();
            if (rect.width > 0) {
                this.updateHandlePosition(this.s * rect.width, (1 - this.v) * rect.height);
            }
        }

        updateCanvasBaseColor() {
            const [r, g, b] = hsvToRgb(this.h, 1, 1);
            this.canvas.style.backgroundColor = rgbToHex(r, g, b);
        }

        updateHandlePosition(x, y) {
            let handle = this.canvas.querySelector('.sat-val-handle');
            if (!handle) {
                handle = document.createElement('div');
                handle.className = 'sat-val-handle';
                this.canvas.appendChild(handle);
            }
            handle.style.left = `${x}px`;
            handle.style.top = `${y}px`;
        }

        updateColor() {
            const [r, g, b] = hsvToRgb(this.h, this.s, this.v);
            const hex = rgbToHex(r, g, b);
            if (this.hexInput) this.hexInput.value = hex;
            if (this.swatch) this.swatch.style.backgroundColor = hex;
            if (this.onChange) this.onChange(hex);
        }

        setColor(hex) {
            const rgb = hexToRgb(hex);
            if (!rgb) return;
            const [h, s, v] = rgbToHsv(rgb[0], rgb[1], rgb[2]);
            this.h = h; this.s = s; this.v = v;
            if (this.hueSlider) this.hueSlider.value = Math.round(this.h * 360);
            this.updateCanvasBaseColor();
            const rect = this.canvas.getBoundingClientRect();
            const w = rect.width || 200;
            const hgt = rect.height || 110;
            this.updateHandlePosition(this.s * w, (1 - this.v) * hgt);
            if (this.hexInput) this.hexInput.value = hex.toUpperCase();
            if (this.swatch) this.swatch.style.backgroundColor = hex;
            if (this.onChange) this.onChange(hex);
        }
    }

    // Picker instances
    let singleNewPicker = null;
    let dualInnerNewPicker = null;
    let dualOuterNewPicker = null;

    // --------------------------------------------------------------------------
    // File Upload Handlers (Scanned & Interior)
    // --------------------------------------------------------------------------
    function setupDropzones() {
        // Scanned dropzone
        const scannedZone = document.getElementById('scannedPatternDropzone');
        const scannedInput = document.getElementById('scannedPatternFileInput');
        if (scannedZone && scannedInput && !scannedZone.dataset.uploadBound) {
            scannedZone.dataset.uploadBound = 'true';
            scannedZone.addEventListener('click', () => scannedInput.click());
            scannedZone.addEventListener('dragover', (e) => { e.preventDefault(); scannedZone.classList.add('dragover'); });
            scannedZone.addEventListener('dragleave', () => scannedZone.classList.remove('dragover'));
            scannedZone.addEventListener('drop', (e) => {
                e.preventDefault();
                scannedZone.classList.remove('dragover');
                if (e.dataTransfer.files && e.dataTransfer.files.length) {
                    uploadFiles(e.dataTransfer.files, 'scanned_pattern');
                }
            });
            scannedInput.addEventListener('change', () => {
                if (scannedInput.files && scannedInput.files.length) {
                    uploadFiles(scannedInput.files, 'scanned_pattern');
                    scannedInput.value = '';
                }
            });
        }

        // Interior media dropzone
        const interiorZone = document.getElementById('interiorMediaDropzone');
        const interiorInput = document.getElementById('interiorMediaFileInput');
        if (interiorZone && interiorInput && !interiorZone.dataset.uploadBound) {
            interiorZone.dataset.uploadBound = 'true';
            interiorZone.addEventListener('click', () => interiorInput.click());
            interiorZone.addEventListener('dragover', (e) => { e.preventDefault(); interiorZone.classList.add('dragover'); });
            interiorZone.addEventListener('dragleave', () => interiorZone.classList.remove('dragover'));
            interiorZone.addEventListener('drop', (e) => {
                e.preventDefault();
                interiorZone.classList.remove('dragover');
                if (e.dataTransfer.files && e.dataTransfer.files.length) {
                    uploadFiles(e.dataTransfer.files, 'interior_media');
                }
            });
            interiorInput.addEventListener('change', () => {
                if (interiorInput.files && interiorInput.files.length) {
                    uploadFiles(interiorInput.files, 'interior_media');
                    interiorInput.value = '';
                }
            });
        }
    }

    function uploadFiles(fileList, category) {
        if (!currentVehicleId) {
            alert('No vehicle selected.');
            return;
        }

        const progressBar = document.getElementById(category === 'scanned_pattern' ? 'scannedUploadProgress' : 'interiorUploadProgress');
        if (progressBar) {
            progressBar.style.display = 'block';
            progressBar.style.width = '30%';
        }

        const formData = new FormData();
        formData.append('vehicle_id', currentVehicleId);
        formData.append('category', category);
        formData.append('client_upload_key', crypto.randomUUID());

        Array.from(fileList).forEach(f => formData.append('files', f));

        fetch('/api/measurement-files/upload/', {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: formData
        })
        .then(r => r.json())
        .then(res => {
            if (progressBar) {
                progressBar.style.width = '100%';
                setTimeout(() => { progressBar.style.display = 'none'; progressBar.style.width = '0%'; }, 400);
            }
            if (res.status === 'success') {
                loadMeasurementFiles(currentVehicleId);
            } else {
                alert(res.message || 'Error uploading files.');
            }
        })
        .catch(err => {
            if (progressBar) progressBar.style.display = 'none';
            alert('Upload failed due to network error.');
        });
    }

    let lastScannedFiles = [];
    let lastInteriorFiles = [];

    function loadMeasurementFiles(vehicleId) {
        if (!vehicleId) return;
        const generation = accessGeneration;
        fetch(`/api/measurement-files/?vehicle_id=${vehicleId}`)
            .then(r => r.json())
            .then(res => {
                if (generation !== accessGeneration || vehicleId !== currentVehicleId) return;
                if (res.status === 'success') {
                    lastScannedFiles = res.scanned_files || [];
                    lastInteriorFiles = res.interior_files || [];
                    renderScannedFiles(lastScannedFiles);
                    renderInteriorMedia(lastInteriorFiles);
                    if (previewFiles.length && ![...lastScannedFiles, ...lastInteriorFiles].some(file => file.id === previewFiles[previewIndex]?.id)) closeInteriorMediaPreview();
                }
            })
            .catch(err => console.error('Error loading measurement files:', err));
    }

    function sortScannedFiles(order) {
        let sorted = [...lastScannedFiles];
        if (order === 'oldest') {
            sorted.sort((a, b) => (a.id - b.id));
        } else if (order === 'name') {
            sorted.sort((a, b) => (a.filename || '').localeCompare(b.filename || ''));
        } else {
            sorted.sort((a, b) => (b.id - a.id));
        }
        renderScannedFiles(sorted);
    }

    function sortInteriorMedia(order) {
        let sorted = [...lastInteriorFiles];
        if (order === 'oldest') {
            sorted.sort((a, b) => (a.id - b.id));
        } else if (order === 'name') {
            sorted.sort((a, b) => (a.filename || '').localeCompare(b.filename || ''));
        } else {
            sorted.sort((a, b) => (b.id - a.id));
        }
        renderInteriorMedia(sorted);
    }

    function element(tag, className = '', text) {
        const node = document.createElement(tag); node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }
    function authorizedUrl(value) {
        const url = new URL(value, location.origin);
        if (url.origin !== location.origin || !/^\/(measurement-files\/\d+\/download\/|picked-colors\/\d+\/swatch\/)$/.test(url.pathname)) throw Error('Invalid file URL');
        return url.href;
    }
    const previewable = file => ['image', 'video'].includes(file.file_type);
    function renderMeasurementStrip(files, id, counter) {
        const host = document.getElementById(id), badge = document.getElementById(counter);
        if (badge) badge.textContent = files.length;
        if (!host) return;
        host.replaceChildren();
        if (!files.length) host.append(element('p', 'panel-empty-state', 'No files uploaded yet.'));
        for (const file of files) {
            const tile = element('div', 'measurement-thumb'); tile.dataset.fileId = file.id;
            const button = element('button', 'measurement-thumb-preview'); button.type = 'button';
            button.setAttribute('aria-label', 'Open ' + file.filename);
            if (file.file_type === 'image') {
                const image = element('img'); image.src = authorizedUrl(file.url); image.alt = file.filename; image.loading = 'lazy';
                image.onerror = () => image.replaceWith(element('i', 'far fa-file-image')); button.append(image);
            } else button.append(element('i', file.file_type === 'video' ? 'fas fa-video' : file.file_type === 'pdf' ? 'fas fa-file-pdf' : 'far fa-file'));
            button.addEventListener('click', () => {
                if (previewable(file)) openMeasurementFile(file, files);
                else window.open(authorizedUrl(file.download_url || file.url), '_blank', 'noopener');
            });
            const name = element('span', 'measurement-thumb-name', file.filename); name.title = file.filename;
            const actions = element('div', 'measurement-thumb-actions');
            actions.append(element('span', '', (file.file_ext || file.file_type || 'FILE').toUpperCase()));
            if (file.download_url) { const link = element('a'); link.href = authorizedUrl(file.download_url); link.title = 'Download '+file.filename; link.setAttribute('aria-label',link.title); link.append(element('i','fas fa-download')); actions.append(link); }
            if (file.can_delete) { const remove = element('button'); remove.title='Delete '+file.filename; remove.setAttribute('aria-label',remove.title); remove.append(element('i','fas fa-trash')); remove.type = 'button'; remove.onclick = () => deleteMeasurementFile(file.id); actions.append(remove); }
            tile.append(button, name, actions); host.append(tile);
        }
        host.onwheel = event => {
            if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
                const before = host.scrollLeft; host.scrollLeft += event.deltaY;
                if (host.scrollLeft !== before) event.preventDefault();
            }
        };
    }
    function renderScannedFiles(files) { renderMeasurementStrip(files, 'scannedFilesList', 'scannedFilesCountBadge'); }
    function renderInteriorMedia(files) { renderMeasurementStrip(files, 'interiorMediaGrid', 'interiorMediaCountBadge'); }

    function deleteMeasurementFile(fileId) {
        if (!confirm('Are you sure you want to delete this file?')) return;

        fetch(`/api/measurement-files/${fileId}/delete/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() }
        })
        .then(r => r.json())
        .then(res => {
            if (res.status === 'success') {
                loadMeasurementFiles(currentVehicleId);
            } else {
                alert(res.message || 'Error deleting file.');
            }
        })
        .catch(() => alert('Network error deleting file.'));
    }

    let previewFiles = [], previewIndex = 0, previewOverflow = null, previewOpener, previewRender = 0;
    function showMeasurementFile() {
        const generation = ++previewRender;
        const file = previewFiles[previewIndex], host = document.getElementById('interiorMediaPreviewContainer');
        if (!file || !host) return;
        host.querySelectorAll('video').forEach(video => { video.pause(); video.removeAttribute('src'); video.load(); });
        host.replaceChildren();
        const media = element(file.file_type === 'video' ? 'video' : 'img');
        media.src = authorizedUrl(file.url);
        if (file.file_type === 'video') { media.controls = true; media.playsInline = true; media.preload = 'metadata'; }
        else media.alt = file.filename;
        media.onerror = () => {
            if (generation !== previewRender) return;
            const link = element('a', 'btn btn-secondary', 'Open authorized file'); link.href = authorizedUrl(file.download_url || file.url); link.target = '_blank'; link.rel = 'noopener';
            host.replaceChildren(element('p', '', 'This browser cannot preview this format.'), link);
        };
        host.append(media);
        document.getElementById('measurementViewerTitle').textContent = file.filename;
        document.getElementById('measurementViewerMetadata').textContent = [file.uploaded_by, file.uploaded_at, Math.round((file.file_size || 0) / 1024) + ' KB'].filter(Boolean).join(' · ');
        document.getElementById('measurementViewerCounter').textContent = `${previewIndex + 1} / ${previewFiles.length}`;
        document.querySelectorAll('#interiorMediaPreviewModal footer button').forEach(button => { button.disabled = previewFiles.length < 2; });
    }
    function openMeasurementFile(file, files) {
        const modal = document.getElementById('interiorMediaPreviewModal');
        if (!modal) return;
        previewFiles = files.filter(previewable); previewIndex = previewFiles.findIndex(item => item.id === file.id);
        if (previewIndex < 0) return;
        if (!modal.dataset.measurementBound) {
            modal.dataset.measurementBound = 'true';
            accessScope.listen(modal, 'cancel', event => { event.preventDefault(); closeInteriorMediaPreview(); });
            accessScope.listen(modal, 'keydown', event => {
                if (['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); navigateMeasurementPreview(event.key === 'ArrowLeft' ? -1 : 1); }
            });
            accessScope.listen(modal, 'click', event => { if (event.target === modal) closeInteriorMediaPreview(); });
        }
        if (!modal.open) {
            previewOverflow = [document.body, document.documentElement].map(node => [node, node.style.getPropertyValue('overflow'), node.style.getPropertyPriority('overflow')]);
            previewOverflow.forEach(([node]) => node.style.setProperty('overflow', 'hidden', 'important'));
            previewOpener = document.activeElement; modal.showModal();
        }
        showMeasurementFile();
    }
    function navigateMeasurementPreview(delta) {
        if (!previewFiles.length) return;
        previewIndex = (previewIndex + delta + previewFiles.length) % previewFiles.length; showMeasurementFile();
    }
    function openInteriorMediaPreview(url) {
        const files = [...lastScannedFiles, ...lastInteriorFiles], file = files.find(item => item.url === url);
        if (file && previewable(file)) openMeasurementFile(file, files);
    }
    function closeInteriorMediaPreview() {
        previewRender++;
        const modal = document.getElementById('interiorMediaPreviewModal'), host = document.getElementById('interiorMediaPreviewContainer');
        host?.querySelectorAll('video').forEach(video => { video.pause(); video.removeAttribute('src'); video.load(); });
        host?.replaceChildren(); if (modal?.open) modal.close();
        if (previewOverflow !== null) { previewOverflow.forEach(([node, value, priority]) => { if (value) node.style.setProperty('overflow', value, priority); else node.style.removeProperty('overflow'); }); previewOverflow = null; }
        if (previewOpener?.isConnected) previewOpener.focus({preventScroll:true}); previewOpener = null; previewFiles = [];
    }
    accessScope.onCleanup(closeInteriorMediaPreview);

    // --------------------------------------------------------------------------
    // Color Picker UI Controller
    // --------------------------------------------------------------------------
    let editingPicked = null, pickedRows = [], pickedRequest = 0, colorSubmissionKey = null, colorDraftDirty = false, swatchGallery = null;
    let currentMode = 'existing'; // 'existing' or 'new'
    let currentTone = 'single';   // 'single' or 'dual'
    let dualInnerSource = 'new';  // 'new' or 'existing'
    let dualOuterSource = 'new';  // 'new' or 'existing'
    let currentCategory = 'interior_match';

    function setColorCategory(category, dirty = false) {
        currentCategory = category === 'fabro_color' ? 'fabro_color' : 'interior_match';
        const toggle = document.getElementById('pickedCategoryToggle');
        if (!toggle) return;
        toggle.dataset.category = currentCategory;
        toggle.querySelectorAll('[data-color-category]').forEach(button => {
            const selected = button.dataset.colorCategory === currentCategory;
            button.setAttribute('aria-checked', String(selected)); button.tabIndex = selected ? 0 : -1;
        });
        if (dirty) { colorSubmissionKey = null; colorDraftDirty = true; }
    }
    accessScope.listen(document, 'click', event => {
        const button = event.target.closest('#pickedCategoryToggle [data-color-category]');
        if (button && !isSubmittingColor) setColorCategory(button.dataset.colorCategory, true);
    });
    accessScope.listen(document, 'keydown', event => {
        const button = event.target.closest('#pickedCategoryToggle [data-color-category]');
        if (!button || isSubmittingColor || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
        event.preventDefault();
        const category = event.key === 'Home' ? 'interior_match' : event.key === 'End' ? 'fabro_color' : currentCategory === 'interior_match' ? 'fabro_color' : 'interior_match';
        setColorCategory(category, true);
        document.querySelector(`#pickedCategoryToggle [data-color-category="${category}"]`).focus();
    });

    function paintColorPreview(host, colors) {
        if (!host) return;
        const dual = colors.tone_type === 'dual';
        const valid = color => /^#[a-fA-F0-9]{6}$/.test(color?.hex);
        const outer = dual ? colors.outer : colors.inner;
        host.replaceChildren(); host.classList.toggle('is-dual', dual);
        host.classList.toggle('is-unavailable', !valid(outer));
        host.style.backgroundColor = valid(outer) ? outer.hex : 'transparent';
        const description = color => valid(color) ? (color.name || color.hex) : 'preview unavailable';
        host.setAttribute('role', 'img');
        host.setAttribute('aria-label', dual ? `Outer: ${description(outer)}; Inner: ${description(colors.inner)}` : `Single tone: ${description(colors.inner)}`);
        host.title = host.getAttribute('aria-label');
        if (!valid(outer)) host.append(element('span','color-preview-missing','?'));
        if (dual) {
            const inner = element('span','color-preview-inner');
            inner.classList.toggle('is-unavailable', !valid(colors.inner));
            inner.style.backgroundColor = valid(colors.inner) ? colors.inner.hex : 'transparent';
            if (!valid(colors.inner)) inner.textContent = '?';
            host.append(inner);
        }
    }
    function updatePickerPreview() {
        const existing = id => {
            const select = document.getElementById(id), option = select?.selectedOptions[0];
            return {hex: select?.value ? option?.dataset.hex : '', name:select?.value ? option?.textContent : ''};
        };
        const fresh = prefix => {
            const value = document.getElementById(prefix+'HexInput')?.value.trim() || '';
            // The existing backend also accepts six digits without a leading #.
            return {hex:/^[a-fA-F0-9]{6}$/.test(value) ? '#'+value : value, name:document.getElementById(prefix+'NameInput')?.value};
        };
        const inner = currentMode === 'existing' ? existing(currentTone === 'single' ? 'selectExistingSingleColor' : 'selectExistingDualInnerColor')
            : currentTone === 'single' ? fresh('newSingle') : dualInnerSource === 'new' ? fresh('dualInnerNew') : existing('selectDualInnerFromExisting');
        const outer = currentMode === 'existing' ? existing('selectExistingDualOuterColor') : dualOuterSource === 'new' ? fresh('dualOuterNew') : existing('selectDualOuterFromExisting');
        paintColorPreview(document.getElementById('pickedColorLivePreview'), {tone_type:currentTone, inner, outer});
    }
    for (const name of ['input','change']) accessScope.listen(document, name, event => {
        if (event.target.closest('#panelColorPicker')) updatePickerPreview();
    });

    function switchColorTopTab(mode) {
        currentMode = mode;
        document.querySelectorAll('.color-top-tab-btn').forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.mode === mode);
        });

        // Switch containers
        const existingView = document.getElementById('colorPickerExistingView');
        const newView = document.getElementById('colorPickerNewView');
        if (existingView) existingView.style.display = (mode === 'existing') ? 'block' : 'none';
        if (newView) newView.style.display = (mode === 'new') ? 'block' : 'none';

        if (mode === 'new' && currentTone === 'dual') {
            const newDual = document.getElementById('newDualToneContainer');
            if (newDual) newDual.style.display = 'grid';
            setTimeout(() => {
                if (dualInnerNewPicker) dualInnerNewPicker.updateHandle();
                if (dualOuterNewPicker) dualOuterNewPicker.updateHandle();
            }, 60);
        }
        updatePickerPreview();
    }

    function switchToneTab(tone) {
        currentTone = tone;
        const radio = document.querySelector(`input[name="tone_choice"][value="${tone}"]`);
        if (radio) radio.checked = true;
        document.querySelectorAll('.sub-tone-pill').forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.tone === tone);
        });

        // Existing view containers
        const exSingle = document.getElementById('existingSingleToneContainer');
        const exDual = document.getElementById('existingDualToneContainer');
        if (exSingle) exSingle.style.display = (tone === 'single') ? 'block' : 'none';
        if (exDual) exDual.style.display = (tone === 'dual') ? 'grid' : 'none';

        // New view containers
        const newSingle = document.getElementById('newSingleToneContainer');
        const newDual = document.getElementById('newDualToneContainer');
        if (newSingle) newSingle.style.display = (tone === 'single') ? 'block' : 'none';
        if (newDual) newDual.style.display = (tone === 'dual') ? 'grid' : 'none';

        if (tone === 'dual') {
            setTimeout(() => {
                if (dualInnerNewPicker) dualInnerNewPicker.updateHandle();
                if (dualOuterNewPicker) dualOuterNewPicker.updateHandle();
            }, 60);
        }
        updatePickerPreview();
    }

    function switchDualInnerSource(source) {
        dualInnerSource = source;
        document.querySelectorAll('.dual-inner-src-btn').forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.source === source);
        });
        const newBox = document.getElementById('dualInnerNewColorBox');
        const exBox = document.getElementById('dualInnerExistingColorBox');
        if (newBox) newBox.style.display = (source === 'new') ? 'block' : 'none';
        if (exBox) exBox.style.display = (source === 'existing') ? 'block' : 'none';
        updatePickerPreview();
    }

    function switchDualOuterSource(source) {
        dualOuterSource = source;
        document.querySelectorAll('.dual-outer-src-btn').forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.source === source);
        });
        const newBox = document.getElementById('dualOuterNewColorBox');
        const exBox = document.getElementById('dualOuterExistingColorBox');
        if (newBox) newBox.style.display = (source === 'new') ? 'block' : 'none';
        if (exBox) exBox.style.display = (source === 'existing') ? 'block' : 'none';
        updatePickerPreview();
    }

    function populateColorDropdowns() {
        const selects = [
            document.getElementById('selectExistingSingleColor'),
            document.getElementById('selectExistingDualInnerColor'),
            document.getElementById('selectExistingDualOuterColor'),
            document.getElementById('selectDualInnerFromExisting'),
            document.getElementById('selectDualOuterFromExisting'),
        ];

        selects.forEach(sel => {
            if (!sel) return;
            const currentVal = sel.value;
            sel.replaceChildren(new Option('-- Choose from Color Master --', ''));
            for (const color of availableColors) {
                const option = new Option(`${color.name} (${color.color_code})`, color.id);
                option.dataset.hex = color.hex_code; option.dataset.code = color.color_code; sel.append(option);
            }
            if (currentVal) sel.value = currentVal;

            sel.addEventListener('change', () => {
                const opt = sel.options[sel.selectedIndex];
                const hex = opt ? (opt.dataset.hex || '#000000') : '#000000';
                const swatchId = sel.dataset.swatchTarget;
                if (swatchId) {
                    const swatch = document.getElementById(swatchId);
                    if (swatch) swatch.style.backgroundColor = hex;
                }
            });
        });
    }

    function handleSwatchPhotoSelected(input) {
        swatchGallery?.enqueue(input.files);
    }

    function clearSwatchPhoto() {
        swatchGallery?.discard();
    }

    // Save Color Selection
    async function saveColorSelection() {
        if (!currentVehicleId) {
            alert('No vehicle selected.');
            return;
        }

        if (isSubmittingColor || swatchGallery?.busy) return;

        const formData = new FormData();
        formData.append('vehicle_id', currentVehicleId);
        formData.append('tone_type', currentTone);
        formData.append('category', currentCategory);
        formData.append('client_submission_key', colorSubmissionKey || (colorSubmissionKey = crypto.randomUUID()));
        formData.append('remarks', document.getElementById('pickedColorRemarks')?.value || '');

        if (currentMode === 'existing') {
            if (currentTone === 'single') {
                const sel = document.getElementById('selectExistingSingleColor');
                if (!sel || !sel.value) {
                    alert('Please select a color from Color Master.');
                    return;
                }
                formData.append('inner_source', 'existing');
                formData.append('inner_existing_color_id', sel.value);
            } else {
                const selInner = document.getElementById('selectExistingDualInnerColor');
                const selOuter = document.getElementById('selectExistingDualOuterColor');
                if (!selInner || !selInner.value || !selOuter || !selOuter.value) {
                    alert('Please select both Inner and Outer colors.');
                    return;
                }
                formData.append('inner_source', 'existing');
                formData.append('inner_existing_color_id', selInner.value);
                formData.append('outer_source', 'existing');
                formData.append('outer_existing_color_id', selOuter.value);
            }
        } else {
            // Pantone / New Color mode
            if (currentTone === 'single') {
                const hex = document.getElementById('newSingleHexInput')?.value || '';
                const pantone = document.getElementById('newSinglePantoneInput')?.value || '';
                if (!hex) {
                    alert('Please specify a valid HEX color code.');
                    return;
                }
                formData.append('inner_source', 'new');
                formData.append('inner_hex_code', hex);
                formData.append('inner_pantone_code', pantone);
            } else {
                // Dual Tone
                // Inner
                if (dualInnerSource === 'new') {
                    const hex = document.getElementById('dualInnerNewHexInput')?.value || '';
                    const pantone = document.getElementById('dualInnerNewPantoneInput')?.value || '';
                    if (!hex) { alert('Please specify a valid HEX code for Inner Color.'); return; }
                    formData.append('inner_source', 'new');
                    formData.append('inner_hex_code', hex);
                    formData.append('inner_pantone_code', pantone);
                } else {
                    const sel = document.getElementById('selectDualInnerFromExisting');
                    if (!sel || !sel.value) { alert('Please select an existing Inner Color.'); return; }
                    formData.append('inner_source', 'existing');
                    formData.append('inner_existing_color_id', sel.value);
                }

                // Outer
                if (dualOuterSource === 'new') {
                    const hex = document.getElementById('dualOuterNewHexInput')?.value || '';
                    const pantone = document.getElementById('dualOuterNewPantoneInput')?.value || '';
                    if (!hex) { alert('Please specify a valid HEX code for Outer Color.'); return; }
                    formData.append('outer_source', 'new');
                    formData.append('outer_hex_code', hex);
                    formData.append('outer_pantone_code', pantone);
                } else {
                    const sel = document.getElementById('selectDualOuterFromExisting');
                    if (!sel || !sel.value) { alert('Please select an existing Outer Color.'); return; }
                    formData.append('outer_source', 'existing');
                    formData.append('outer_existing_color_id', sel.value);
                }
            }
        }

        if (currentMode === 'new') {
            formData.append('inner_color_name', document.getElementById(currentTone === 'single' ? 'newSingleNameInput' : 'dualInnerNewNameInput')?.value || '');
            if (currentTone === 'dual') formData.append('outer_color_name', document.getElementById('dualOuterNewNameInput')?.value || '');
        }
        const vehicleId = currentVehicleId, editingId = editingPicked?.id;
        if (editingPicked && !editingPicked.can_edit) { pickerFeedback('Editing access changed. Your draft is preserved.'); return; }
        isSubmittingColor = true; updatePickerSaveState();
        const url = editingId ? `/api/picked-colors/${editingId}/edit/` : '/api/pattern-color-selection/save/';
        try {
            formData.set('swatch_photos', JSON.stringify(await swatchGallery.plans()));
            const response = await fetch(url, {method:'POST', headers:{'X-CSRFToken':getCsrfToken()}, body:formData, signal:accessScope.signal});
            const res = await response.json().catch(() => ({}));
            if (!response.ok || res.status !== 'success') throw Error(res.message || 'Saving is not permitted or unavailable.');
            if (vehicleId !== currentVehicleId) return;
            const savedItem = res.picked_selection || res.selection;
            setColorCategory(savedItem.category);
            colorDraftDirty = false;
            swatchGallery.adopt(savedItem);
            await swatchGallery.run();
            await loadPickedColors(vehicleId);
            loadPatternColorSelection(vehicleId);
            editingPicked = savedItem;
            pickerFeedback(swatchGallery.hasPending() ? 'Color selection saved. Retry or remove the failed photos.' : (editingId ? 'Color changes saved.' : 'Color selection saved.'));
        } catch (error) {
            if (!accessScope.signal.aborted && vehicleId === currentVehicleId) pickerFeedback(error.message);
        } finally { isSubmittingColor = false; if (!accessScope.signal.aborted) updatePickerSaveState(); }
    }

    function pickerFeedback(message) { const host = document.getElementById('pickedEditNotice'); if (host) host.textContent = message; }
    function updatePickerSaveState() {
        const button = document.getElementById('btnSaveColorSelection'); if (!button) return;
        const allowed = key => window.fabroActivityAllowed?.(key) === true;
        button.disabled = isSubmittingColor || swatchGallery?.busy || (editingPicked
            ? !editingPicked.can_edit || !(allowed('picked_colors.edit_own') || allowed('picked_colors.edit_all'))
            : !allowed('picked_colors.add'));
        button.textContent = isSubmittingColor ? 'Saving…' : editingPicked ? 'Save Changes' : 'Save Color Selection';
        document.querySelectorAll('#pickedCategoryToggle button').forEach(button => { button.disabled = isSubmittingColor; });
        const cancel = document.getElementById('btnCancelPickedEdit');
        if (cancel) { cancel.hidden = !editingPicked; cancel.disabled = isSubmittingColor || swatchGallery?.busy; cancel.textContent = 'New selection'; }
        if (editingPicked && !editingPicked.can_edit && !isSubmittingColor) pickerFeedback('Editing access changed. Your draft is preserved.');
    }
    async function loadPickedColors(vehicleId) {
        if (!vehicleId) return;
        const token = ++pickedRequest, generation = accessGeneration;
        const host = document.getElementById('pickedColorsList'); if (!host) return;
        try {
            const response = await fetch(`/api/picked-colors/?vehicle_id=${encodeURIComponent(vehicleId)}`, {cache:'no-store',credentials:'same-origin'});
            if (!response.ok) throw Error('Picked Colors is unavailable for your current access.');
            const data = await response.json();
            if (token !== pickedRequest || generation !== accessGeneration || vehicleId !== currentVehicleId) return;
            pickedRows = data.selections || []; renderPickedColors();
            swatchGallery?.setReadAccess(!editingPicked || pickedRows.some(row=>row.id===editingPicked.id));
            if (editingPicked) {
                const refreshed = pickedRows.find(row => row.id === editingPicked.id);
                editingPicked = refreshed || {...editingPicked, can_edit:false};
            }
            swatchGallery?.refreshAccess(editingPicked);
        } catch (error) {
            if (token !== pickedRequest || generation !== accessGeneration || vehicleId !== currentVehicleId) return;
            pickedRows = []; renderPickedColors();
            for (const id of ['pickedColorsList','fabroColorsList']) document.getElementById(id)?.replaceChildren(element('p','',error.message));
            if (editingPicked) editingPicked.can_edit = false;
            swatchGallery?.setReadAccess(false);
        }
        updatePickerSaveState();
    }
    function renderPickedColors() {
        const host = document.getElementById('pickedColorsList'); if (!host) return;
        const sections = {interior_match:host, fabro_color:document.getElementById('fabroColorsList')};
        for (const [category, list] of Object.entries(sections)) {
            if (!list) continue;
            const count = pickedRows.filter(row => (row.category || 'interior_match') === category).length;
            list.replaceChildren(); document.getElementById(category === 'interior_match' ? 'pickedColorsCount' : 'fabroColorsCount').textContent = count;
            if (!count) list.append(element('p','',category === 'interior_match' ? 'No Interior Match colors saved yet.' : 'No Fabro Color options saved yet.'));
        }
        for (const row of pickedRows) {
            const tile = element('article','picked-color-tile'); tile.dataset.pickedId = row.id;
            const swatch = element('div','picked-color-swatch'), colors = row.snapshot;
            paintColorPreview(swatch, colors);
            const details = element('div','picked-color-details');
            for (const side of colors.tone_type === 'dual' ? ['outer','inner'] : ['inner']) {
                const color = colors[side];
                details.append(element('strong','',(colors.tone_type === 'dual' ? side[0].toUpperCase()+side.slice(1)+': ' : '') + (color.name || 'New color')));
                details.append(element('small','',[color.code, color.pantone, color.hex].filter(Boolean).join(' · ')));
            }
            details.append(element('small','',new Date(row.created_at).toLocaleString() + ' · ' + row.creator_name));
            if (row.remarks) details.append(element('p','',row.remarks));
            if (row.swatch_photos?.length) {
                const photos = element('div','picked-color-photo-strip');
                for (const photo of row.swatch_photos) {
                    const open=element('button');open.type='button';open.title=photo.filename;open.setAttribute('aria-label','View matching photos for this selection');
                    const image=element('img');image.src=photo.url;image.alt=photo.filename;image.loading='lazy';image.onerror=()=>{image.hidden=true;open.textContent='Photo';};open.append(image);
                    open.onclick=()=>{ if(editPickedColor(row.id, true) === false)return; const entry=swatchGallery.entries.find(item=>item.photo?.id===photo.id);if(entry)swatchGallery.openPreview(entry,open); };
                    photos.append(open);
                }
                details.append(photos);
            }
            const actions = element('div','picked-color-actions');
            const action = (name, label, icon, handler) => {
                const button = element('button',name === 'delete' ? 'btn btn-danger' : 'btn btn-secondary');
                button.type='button'; button.dataset.pickedAction=name; button.title=label; button.setAttribute('aria-label',label);
                const glyph=element('i',`fas ${icon}`);glyph.setAttribute('aria-hidden','true');button.append(glyph);
                button.onclick=event=>{event.stopPropagation();handler();};actions.append(button);
            };
            if (row.can_edit) action('edit','Edit Color','fa-pen',()=>editPickedColor(row.id));
            if (row.can_delete) action('delete','Delete Color','fa-trash',()=>deletePickedColor(row.id));
            tile.append(swatch,details,actions); sections[row.category || 'interior_match']?.append(tile);
        }
    }
    function setPickerValue(id,value) { const input=document.getElementById(id); if(input){input.value=value || '';input.dispatchEvent(new Event('input',{bubbles:true}));} }
    function savedMaster(id,color) {
        const select=document.getElementById(id); if(!select)return;
        let option=[...select.options].find(item=>item.value===String(color.master_id));
        if(!option){option=new Option('',String(color.master_id));select.append(option);}
        option.textContent=`${color.name} (${color.code}) — saved`;option.dataset.hex=color.hex;
        select.value=String(color.master_id);select.dispatchEvent(new Event('change',{bubbles:true}));
    }
    function editPickedColor(id, viewOnly=false) {
        const row=pickedRows.find(item=>item.id===id); if(!row || !row.can_edit && !viewOnly)return false;
        if(swatchGallery?.busy){pickerFeedback('Wait for or cancel the current photo upload first.');return false;}
        if(colorDraftDirty && !confirm('Replace the current unsaved color draft?'))return false;
        editingPicked=row; setColorCategory(row.category); const colors=row.snapshot;
        switchToneTab(colors.tone_type);
        switchColorTopTab(colors.inner.source==='existing' && (!colors.outer || colors.outer.source==='existing') ? 'existing' : 'new');
        for(const side of colors.tone_type==='dual'?['inner','outer']:['inner']) {
            const color=colors[side];
            if(colors.tone_type==='single') {
                if(color.source==='existing')savedMaster('selectExistingSingleColor',color);
                else {setPickerValue('newSingleHexInput',color.hex);setPickerValue('newSinglePantoneInput',color.pantone);setPickerValue('newSingleNameInput',color.name);}
            } else if(currentMode==='existing') savedMaster(side==='inner'?'selectExistingDualInnerColor':'selectExistingDualOuterColor',color);
            else {
                (side==='inner'?switchDualInnerSource:switchDualOuterSource)(color.source);
                if(color.source==='existing')savedMaster(side==='inner'?'selectDualInnerFromExisting':'selectDualOuterFromExisting',color);
                else {const prefix=side==='inner'?'dualInnerNew':'dualOuterNew';setPickerValue(prefix+'HexInput',color.hex);setPickerValue(prefix+'PantoneInput',color.pantone);setPickerValue(prefix+'NameInput',color.name);}
            }
        }
        setPickerValue('pickedColorRemarks',row.remarks);swatchGallery?.setContext(currentVehicleId,row); colorSubmissionKey=null;colorDraftDirty=false;
        pickerFeedback('Editing saved selection. Original creator and date will be preserved.');updatePickerSaveState();
        document.getElementById('panelColorPicker').scrollIntoView({block:'nearest',behavior:'smooth'});
        return true;
    }
    function cancelPickedColorEdit() {
        if(isSubmittingColor || swatchGallery?.busy || (colorDraftDirty || swatchGallery?.hasPending()) && !confirm('Discard the unsaved color edit and local photos?'))return;
        editingPicked=null;setColorCategory('interior_match');colorSubmissionKey=null;colorDraftDirty=false;document.getElementById('pickedColorRemarks').value='';clearSwatchPhoto();pickerFeedback('');updatePickerSaveState();
    }
    async function deletePickedColor(id) {
        if(swatchGallery?.busy && editingPicked?.id===id){pickerFeedback('Wait for or cancel the photo upload before deleting this selection.');return;}
        if(!pickedRows.find(row=>row.id===id)?.can_delete || !confirm('Delete this saved color selection? Approval history and shared media will be retained.'))return;
        const vehicleId=currentVehicleId;
        try {
            const data=new FormData();data.set('vehicle_id',vehicleId);
            const response=await fetch(`/api/picked-colors/${id}/delete/`,{method:'POST',headers:{'X-CSRFToken':getCsrfToken()},body:data});
            if(!response.ok)throw Error('Deleting this selection is not permitted or unavailable.');
            if(vehicleId===currentVehicleId){if(editingPicked?.id===id){editingPicked=null;setColorCategory('interior_match');colorSubmissionKey=null;colorDraftDirty=false;clearSwatchPhoto();updatePickerSaveState();}loadPickedColors(vehicleId);loadPatternColorSelection(vehicleId);}
        }catch(error){pickerFeedback(error.message);}
    }
    accessScope.listen(document,'input',event=>{if(event.isTrusted && event.target.closest('#panelColorPicker') && !isSubmittingColor){colorSubmissionKey=null;colorDraftDirty=true;}});
    accessScope.listen(document,'fabro:access-changed',()=>{document.querySelectorAll('[data-picked-action]').forEach(button=>{button.hidden=true;button.disabled=true;});});
    accessScope.listen(document,'fabro:access-revalidated',updatePickerSaveState);

    // Load saved color selection and status card
    function loadPatternColorSelection(vehicleId) {
        const card = document.getElementById('patternColorStatusCard');
        if (!card || !vehicleId) return;

        fetch(`/api/pattern-color-selection/details/?vehicle_id=${vehicleId}`)
            .then(r => r.json())
            .then(res => {
                if (res.status === 'success' && res.selection) {
                    const data = res.selection;
                    card.style.display = 'flex';

                    const pill = document.getElementById('colorStatusCardPill');
                    if (pill) {
                        const st = (data.status || 'pending').toLowerCase();
                        pill.className = `color-approval-status-pill ${st}`;
                        pill.textContent = st === 'approved' ? 'Approved' : (st === 'rejected' ? 'Rejected' : 'Pending Approval');
                    }

                    // View details button
                    const btnDetails = document.getElementById('btnViewColorApprovalDetails');
                    if (btnDetails) {
                        btnDetails.onclick = () => window.openColorApprovalDrawer(data.id, btnDetails);
                    }
                } else {
                    card.style.display = 'none';
                }
            })
            .catch(() => { card.style.display = 'none'; });
    }

    function showSupportedFormatsModal(category) {
        // Replaced by hover popover tooltip — no modal needed
    }

    function closeSupportedFormatsModal() {
        // Replaced by hover popover tooltip — no modal needed
    }

    function setupSupportedFormatsPopovers() {
        document.querySelectorAll('.supported-formats-wrapper').forEach(wrapper => {
            const popover = wrapper.querySelector('.supported-formats-popover');
            if (!popover || wrapper.dataset.popoverBound) return;
            wrapper.dataset.popoverBound = '1';

            wrapper.addEventListener('mouseenter', () => {
                popover.style.opacity = '1';
                popover.style.visibility = 'visible';
                popover.style.transform = 'translateY(0)';
                popover.style.pointerEvents = 'auto';
            });
            wrapper.addEventListener('mouseleave', () => {
                popover.style.opacity = '0';
                popover.style.visibility = 'hidden';
                popover.style.transform = 'translateY(-4px)';
                popover.style.pointerEvents = 'none';
            });
        });
    }

    function switchSidebarSection(section) {
        const measWorkspace = document.getElementById('patternMeasurementsWorkspace');
        const design3DWorkspace = document.getElementById('pattern3DDesignWorkspace');
        const measNavBtn = document.getElementById('sidebarNavMeasurementsBtn');
        const design3DNavBtn = document.getElementById('sidebarNav3DDesignBtn');

        document.querySelectorAll('.sidebar-nav-card .sidebar-nav-item').forEach(el => el.classList.remove('is-active'));

        if (section === '3d-design') {
            if (measWorkspace) measWorkspace.style.display = 'none';
            if (design3DWorkspace) design3DWorkspace.style.display = 'block';
            if (design3DNavBtn) design3DNavBtn.classList.add('is-active');
            if (typeof window.load3DDesignWorkspace === 'function') {
                const urlParams = new URLSearchParams(window.location.search);
                const vId = urlParams.get('vehicle_id') || currentVehicleId;
                if (vId) window.load3DDesignWorkspace(parseInt(vId, 10));
            }
        } else {
            if (design3DWorkspace) design3DWorkspace.style.display = 'none';
            if (measWorkspace) measWorkspace.style.display = 'block';
            if (measNavBtn) measNavBtn.classList.add('is-active');
        }
    }

    function initWorkspace(vehicleId, vehicleData) {
        if (currentVehicleId !== vehicleId) { closeInteriorMediaPreview(); editingPicked=null;setColorCategory('interior_match');colorSubmissionKey=null;colorDraftDirty=false;const remarks=document.getElementById('pickedColorRemarks');if(remarks)remarks.value=''; }
        currentVehicleId = vehicleId;
        if (!swatchGallery && window.FabroMatchingSwatchGallery) {
            swatchGallery = new window.FabroMatchingSwatchGallery(document.getElementById('matchingSwatchGallery'), {
                scope:accessScope, csrf:getCsrfToken, feedback:pickerFeedback,
                dirty:()=>{colorSubmissionKey=null;colorDraftDirty=true;}, state:updatePickerSaveState,
                complete:()=>{if(currentVehicleId){loadPickedColors(currentVehicleId);loadPatternColorSelection(currentVehicleId);}}
            });
        }
        if(swatchGallery?.vehicleId !== vehicleId) swatchGallery?.setContext(vehicleId);

        // Parse available colors from template JSON script
        const colorsScript = document.getElementById('carDetailsColorsData');
        if (colorsScript) {
            try {
                availableColors = JSON.parse(colorsScript.textContent || '[]');
            } catch(e) { availableColors = []; }
        }

        populateColorDropdowns();
        setupDropzones();
        setupSupportedFormatsPopovers();

        // Initialize Visual Pickers
        singleNewPicker = new VisualColorPicker('newSingleCanvas', 'newSingleHueSlider', 'newSingleHexInput', 'newSingleSwatch', updatePickerPreview);
        dualInnerNewPicker = new VisualColorPicker('dualInnerNewCanvas', 'dualInnerNewHueSlider', 'dualInnerNewHexInput', 'dualInnerNewSwatch', updatePickerPreview);
        dualOuterNewPicker = new VisualColorPicker('dualOuterNewCanvas', 'dualOuterNewHueSlider', 'dualOuterNewHexInput', 'dualOuterNewSwatch', updatePickerPreview);

        // Update photo and heading
        if (vehicleData) {
            const photoImg = document.getElementById('designVehiclePhoto');
            const placeholder = document.getElementById('designVehiclePhotoPlaceholder');
            if (photoImg) {
                photoImg.onload = () => {
                    photoImg.style.display = 'block';
                    if (placeholder) placeholder.style.display = 'none';
                };
                photoImg.onerror = () => {
                    photoImg.style.display = 'none';
                    if (placeholder) placeholder.style.display = '';
                };
            }
            if (vehicleData.photo_url) {
                if (photoImg) { photoImg.style.display = 'none'; photoImg.src = vehicleData.photo_url; }
            } else {
                if (photoImg) photoImg.style.display = 'none';
                if (placeholder) placeholder.style.display = 'flex';
            }

            const serialBadge = document.getElementById('designVehicleSerialBadge');
            if (serialBadge) {
                const sn = vehicleData.serial_number || `${vehicleId}`;
                serialBadge.textContent = sn.startsWith('#') ? sn : `#${sn}`;
            }
        }

        loadMeasurementFiles(vehicleId);
        loadPatternColorSelection(vehicleId);
        loadPickedColors(vehicleId);
        updatePickerSaveState();
    }

    function uploadVehiclePhoto(file) {
        if (!file) return;
        if (!currentVehicleId) {
            alert('No vehicle selected.');
            return;
        }

        const label = document.getElementById('vehiclePhotoUploadLabel');
        const prevText = label ? label.textContent : '';
        if (label) label.textContent = 'Uploading...';

        const formData = new FormData();
        formData.append('photo', file);

        fetch(`/api/vehicles/${currentVehicleId}/upload-photo/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
            body: formData,
        })
        .then(r => r.json())
        .then(res => {
            if (label) label.textContent = prevText || 'Upload Photo';
            if (res.status === 'success') {
                const img = document.getElementById('designVehiclePhoto');
                const placeholder = document.getElementById('designVehiclePhotoPlaceholder');
                if (img && res.photo_url) {
                    img.src = res.photo_url;
                    img.style.display = 'block';
                }
                if (placeholder) {
                    placeholder.style.display = 'none';
                }
            } else {
                alert(res.message || 'Error uploading vehicle image.');
            }
        })
        .catch(err => {
            if (label) label.textContent = prevText || 'Upload Photo';
            alert('Error: ' + err.message);
        });
    }

    function escapeHtml(text) {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return String(text || '').replace(/[&<>"']/g, m => map[m]);
    }

    // Expose hooks to window
    window.initMeasurementsWorkspace = initWorkspace;
    window.uploadVehiclePhoto = uploadVehiclePhoto;
    window.loadMeasurementFiles = loadMeasurementFiles;
    window.loadPatternColorSelection = loadPatternColorSelection;
    window.deleteMeasurementFile = deleteMeasurementFile;
    window.openInteriorMediaPreview = openInteriorMediaPreview;
    window.closeInteriorMediaPreview = closeInteriorMediaPreview;
    window.navigateMeasurementPreview = navigateMeasurementPreview;
    window.switchColorTopTab = switchColorTopTab;
    window.switchToneTab = switchToneTab;
    window.switchDualInnerSource = switchDualInnerSource;
    window.switchDualOuterSource = switchDualOuterSource;
    window.handleSwatchPhotoSelected = handleSwatchPhotoSelected;
    window.clearSwatchPhoto = clearSwatchPhoto;
    window.saveColorSelection = saveColorSelection;
    window.cancelPickedColorEdit = cancelPickedColorEdit;
    window.switchSidebarSection = switchSidebarSection;
    window.sortScannedFiles = sortScannedFiles;
    window.sortInteriorMedia = sortInteriorMedia;
    window.showSupportedFormatsModal = showSupportedFormatsModal;
    window.closeSupportedFormatsModal = closeSupportedFormatsModal;

    // Refresh hook for decision drawer
    window.onColorDecisionSubmitted = function(selectionId, res) {
        if (currentVehicleId) {
            loadPatternColorSelection(currentVehicleId);
        }
    };
})();

