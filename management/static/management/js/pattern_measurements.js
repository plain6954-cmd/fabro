// FABRO — Pattern Master Measurements Workspace Controller
(function() {
    let currentVehicleId = null;
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
        if (scannedZone && scannedInput) {
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
        if (interiorZone && interiorInput) {
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

        fetch(`/api/measurement-files/?vehicle_id=${vehicleId}`)
            .then(r => r.json())
            .then(res => {
                if (res.status === 'success') {
                    lastScannedFiles = res.scanned_patterns || [];
                    lastInteriorFiles = res.interior_media || [];
                    renderScannedFiles(lastScannedFiles);
                    renderInteriorMedia(lastInteriorFiles);
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

    function renderScannedFiles(files) {
        const list = document.getElementById('scannedFilesList');
        const countBadge = document.getElementById('scannedFilesCountBadge');
        if (countBadge) countBadge.textContent = files.length;
        if (!list) return;

        if (files.length === 0) {
            list.innerHTML = `
                <div class="panel-empty-state">
                    <svg class="empty-folder-svg" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path>
                    </svg>
                    <strong class="empty-state-title">No files uploaded yet</strong>
                    <p class="empty-state-desc">Upload scanned patterns, DXF files, PDFs or reference images.</p>
                </div>
            `;
            return;
        }

        list.innerHTML = files.map(f => {
            let iconClass = 'file-type-icon';
            let iconMarkup = '<i class="fas fa-file"></i>';
            const ext = (f.file_ext || '').toLowerCase();
            if (ext === '.dxf') {
                iconClass += ' dxf';
                iconMarkup = '<i class="fas fa-drafting-compass"></i>';
            } else if (ext === '.pdf') {
                iconClass += ' pdf';
                iconMarkup = '<i class="fas fa-file-pdf"></i>';
            } else {
                iconClass += ' image';
                iconMarkup = '<i class="fas fa-file-image"></i>';
            }

            return `
                <div class="measurement-file-item" id="meas-file-${f.id}">
                    <div class="measurement-file-info">
                        <div class="${iconClass}">${iconMarkup}</div>
                        <div class="measurement-file-meta">
                            <span class="measurement-file-name" title="${escapeHtml(f.filename)}">${escapeHtml(f.filename)}</span>
                            <span class="measurement-file-size">${f.file_size_formatted}</span>
                        </div>
                    </div>
                    <div class="measurement-file-actions">
                        <a href="/measurement-files/${f.id}/download/" class="btn btn-secondary btn-sm" title="Download" style="padding:0.25rem 0.5rem; font-size:0.75rem;">
                            <i class="fas fa-download"></i>
                        </a>
                        <button type="button" class="btn btn-danger btn-sm" onclick="window.deleteMeasurementFile(${f.id})" title="Delete" style="padding:0.25rem 0.5rem; font-size:0.75rem;">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderInteriorMedia(files) {
        const grid = document.getElementById('interiorMediaGrid');
        const countBadge = document.getElementById('interiorMediaCountBadge');
        if (countBadge) countBadge.textContent = files.length;
        if (!grid) return;

        if (files.length === 0) {
            grid.innerHTML = `
                <div class="panel-empty-state" style="grid-column: 1 / -1;">
                    <svg class="empty-folder-svg" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path>
                    </svg>
                    <strong class="empty-state-title">No files uploaded yet</strong>
                    <p class="empty-state-desc">Upload interior photos or videos for reference.</p>
                </div>
            `;
            return;
        }

        grid.innerHTML = files.map(f => {
            const isVideo = f.is_video;
            const badgeIcon = isVideo ? '<i class="fas fa-video"></i> VIDEO' : '<i class="fas fa-image"></i> IMG';
            return `
                <div class="interior-media-card" id="meas-file-${f.id}" onclick="window.openInteriorMediaPreview('${f.url}', ${isVideo})">
                    <img src="${f.thumbnail_url || f.url}" alt="${escapeHtml(f.filename)}" class="interior-media-thumb">
                    <span class="interior-media-overlay-badge">${badgeIcon}</span>
                    <button type="button" class="interior-media-delete-btn" onclick="event.stopPropagation(); window.deleteMeasurementFile(${f.id});" title="Delete">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `;
        }).join('');
    }

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

    function openInteriorMediaPreview(url, isVideo) {
        const modal = document.getElementById('interiorMediaPreviewModal');
        const container = document.getElementById('interiorMediaPreviewContainer');
        if (!modal || !container) return;

        if (isVideo) {
            container.innerHTML = `<video controls autoplay style="max-width:100%; max-height:80vh; border-radius:8px;"><source src="${url}">Your browser does not support video playback.</video>`;
        } else {
            container.innerHTML = `<img src="${url}" alt="Preview" style="max-width:100%; max-height:80vh; object-fit:contain; border-radius:8px;">`;
        }
        modal.style.display = 'flex';
    }

    function closeInteriorMediaPreview() {
        const modal = document.getElementById('interiorMediaPreviewModal');
        const container = document.getElementById('interiorMediaPreviewContainer');
        if (modal) modal.style.display = 'none';
        if (container) container.innerHTML = '';
    }

    // --------------------------------------------------------------------------
    // Color Picker UI Controller
    // --------------------------------------------------------------------------
    let currentMode = 'existing'; // 'existing' or 'new'
    let currentTone = 'single';   // 'single' or 'dual'
    let dualInnerSource = 'new';  // 'new' or 'existing'
    let dualOuterSource = 'new';  // 'new' or 'existing'

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
            sel.innerHTML = '<option value="">-- Choose from Color Master --</option>' +
                availableColors.map(c => `<option value="${c.id}" data-hex="${c.hex_code}" data-code="${c.color_code}">${escapeHtml(c.name)} (${c.color_code})</option>`).join('');
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
        const preview = document.getElementById('matchingSwatchPreview');
        const img = document.getElementById('matchingSwatchImg');
        if (input.files && input.files[0]) {
            const reader = new FileReader();
            reader.onload = (e) => {
                if (img) img.src = e.target.result;
                if (preview) preview.style.display = 'block';
            };
            reader.readAsDataURL(input.files[0]);
        } else {
            if (preview) preview.style.display = 'none';
        }
    }

    function clearSwatchPhoto() {
        const input = document.getElementById('matchingSwatchPhotoInput');
        const preview = document.getElementById('matchingSwatchPreview');
        if (input) input.value = '';
        if (preview) preview.style.display = 'none';
    }

    // Save Color Selection
    function saveColorSelection() {
        if (!currentVehicleId) {
            alert('No vehicle selected.');
            return;
        }

        if (isSubmittingColor) return;

        const formData = new FormData();
        formData.append('vehicle_id', currentVehicleId);
        formData.append('tone_type', currentTone);
        formData.append('client_submission_key', crypto.randomUUID());

        const swatchInput = document.getElementById('matchingSwatchPhotoInput');
        if (swatchInput && swatchInput.files && swatchInput.files[0]) {
            formData.append('swatch_image', swatchInput.files[0]);
        }

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

        const btnSave = document.getElementById('btnSaveColorSelection');
        isSubmittingColor = true;
        if (btnSave) {
            btnSave.disabled = true;
            btnSave.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Saving...';
        }

        fetch('/api/pattern-color-selection/save/', {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: formData
        })
        .then(r => r.json())
        .then(res => {
            isSubmittingColor = false;
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.innerHTML = '<i class="fas fa-save"></i> Save Color Selection';
            }

            if (res.status === 'success') {
                if (res.is_new_color) {
                    alert('Color selection saved! Submitted for MD, ED, and CAD approval.');
                } else {
                    alert('Color selection saved successfully.');
                }
                loadPatternColorSelection(currentVehicleId);
            } else {
                alert(res.message || 'Error saving color selection.');
            }
        })
        .catch(() => {
            isSubmittingColor = false;
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.innerHTML = '<i class="fas fa-save"></i> Save Color Selection';
            }
            alert('Network error saving color selection.');
        });
    }

    // Load saved color selection and status card
    function loadPatternColorSelection(vehicleId) {
        const card = document.getElementById('patternColorStatusCard');
        if (!card || !vehicleId) return;

        fetch(`/api/pattern-color-selection/details/?vehicle_id=${vehicleId}`)
            .then(r => r.json())
            .then(res => {
                if (res.status === 'success' && res.data) {
                    const data = res.data;
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
        const measSection = document.getElementById('sidebarNavSectionMeasurements');
        const design3DSection = document.getElementById('sidebarNavSection3DDesign');
        const measWorkspace = document.getElementById('patternMeasurementsWorkspace');
        const design3DWorkspace = document.getElementById('pattern3DDesignWorkspace');

        document.querySelectorAll('.sidebar-nav-item').forEach(el => el.classList.remove('is-active'));

        if (section === '3d-design') {
            if (measWorkspace) measWorkspace.style.display = 'none';
            if (design3DWorkspace) design3DWorkspace.style.display = 'block';
            const navBtn = document.getElementById('sidebarNav3DFolders');
            if (navBtn) navBtn.classList.add('is-active');
        } else {
            if (design3DWorkspace) design3DWorkspace.style.display = 'none';
            if (measWorkspace) measWorkspace.style.display = 'block';
        }
    }

    function initWorkspace(vehicleId, vehicleData) {
        currentVehicleId = vehicleId;

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
        singleNewPicker = new VisualColorPicker('newSingleCanvas', 'newSingleHueSlider', 'newSingleHexInput', 'newSingleSwatch');
        dualInnerNewPicker = new VisualColorPicker('dualInnerNewCanvas', 'dualInnerNewHueSlider', 'dualInnerNewHexInput', 'dualInnerNewSwatch');
        dualOuterNewPicker = new VisualColorPicker('dualOuterNewCanvas', 'dualOuterNewHueSlider', 'dualOuterNewHexInput', 'dualOuterNewSwatch');

        // Update photo and heading
        if (vehicleData) {
            const photoImg = document.getElementById('designVehiclePhoto');
            const placeholder = document.getElementById('designVehiclePhotoPlaceholder');
            if (vehicleData.photo_url) {
                if (photoImg) { photoImg.src = vehicleData.photo_url; photoImg.style.display = 'block'; }
                if (placeholder) placeholder.style.display = 'none';
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
    window.switchColorTopTab = switchColorTopTab;
    window.switchToneTab = switchToneTab;
    window.switchDualInnerSource = switchDualInnerSource;
    window.switchDualOuterSource = switchDualOuterSource;
    window.handleSwatchPhotoSelected = handleSwatchPhotoSelected;
    window.clearSwatchPhoto = clearSwatchPhoto;
    window.saveColorSelection = saveColorSelection;
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

