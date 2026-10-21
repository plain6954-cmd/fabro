/**
 * FABRO Leather Portal — 3D Design Workspace & Approval Workflow Controller
 * Pixel-Fidelity Interactive Controller for Reference Images, 3D Design Files Gallery,
 * Role-Based Designer Panel, and Right-Side Slide-in Approval Workflow Drawer.
 */

(function () {
    'use strict';

    function reviewStatusLabel(status) {
        if (status === 'skipped_uploader') return 'Skipped — Uploader';
        if (status === 'not_required') return 'Not required (historical)';
        return status || '—';
    }

    if (typeof window.__fabro3DDispose === 'function') window.__fabro3DDispose();
    const eventController = new AbortController();
    let referenceTrack = null;

    // State management
    const state = {
        vehicleId: null,
        vehicleData: null,
        canDelete: false,
        referenceImages: [],
        designFiles: [],
        selectedFileId: null,
        viewMode: 'grid', // 'grid' | 'list'
        sortOption: 'newest',
        searchQuery: '',
        isLegacyView: false,
        currentUser: null,
        loadRequestId: 0,
        isSubmittingDecision: false,
    };

    function getCsrfToken() {
        const el = document.querySelector('#designOptionsGlobalCsrf [name=csrfmiddlewaretoken]')
            || document.querySelector('[name=csrfmiddlewaretoken]');
        if (el && el.value) return el.value;
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        if (match) return decodeURIComponent(match[1]);
        return '';
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Load the 3D Design Workspace data for a given vehicle
     */
    function canCurrentUserDelete(item) {
        if (state.canDelete === true) return true;
        if (item && item.can_delete === true) return true;
        if (item && state.currentUser && state.currentUser.is_designer) {
            if (!item.is_reference && (!item.uploaded_by || item.uploaded_by === state.currentUser.username)) {
                return true;
            }
        }
        return false;
    }

    async function delete3DDesignFile(fileId, fileTitle) {
        if (!fileId) return;
        const entry = [...state.referenceImages, ...state.designFiles].find(f => f.id === fileId);
        const displayName = fileTitle || (entry && entry.title) || 'this file';
        if (!confirm(`Are you sure you want to delete "${displayName}"? This action cannot be undone.`)) {
            return;
        }

        try {
            const resp = await fetch(`/api/design-images/${fileId}/delete/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
            });
            const data = await resp.json();
            if (data.status === 'success') {
                // Remove from state
                state.referenceImages = state.referenceImages.filter(f => f.id !== fileId);
                state.designFiles = state.designFiles.filter(f => f.id !== fileId);

                // Update count badges
                const refBadge = document.getElementById('refImagesCountBadge');
                if (refBadge) refBadge.textContent = state.referenceImages.length;

                const filesBadge = document.getElementById('design3DFilesCountBadge');
                if (filesBadge) filesBadge.textContent = state.designFiles.length;

                // Re-render
                renderReferenceImages(state.referenceImages);
                render3DDesignFiles();

                // If currently open in drawer
                if (state.selectedFileId === fileId) {
                    if (state.designFiles.length > 0) {
                        selectDrawerFile(state.designFiles[0].id);
                    } else {
                        closeApprovalDrawer();
                    }
                }
            } else {
                alert(data.message || 'Error deleting file.');
            }
        } catch (err) {
            console.error('[3D Design] Error deleting file:', err);
            alert('An error occurred while deleting the file.');
        }
    }
    window.delete3DDesignFile = delete3DDesignFile;

    async function load3DDesignWorkspace(vehicleId) {
        if (!vehicleId) return;
        const requestId = ++state.loadRequestId;
        state.vehicleId = vehicleId;

        try {
            const resp = await fetch(`/api/design-folders/?vehicle_id=${vehicleId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            if (requestId !== state.loadRequestId || !document.getElementById('pattern3DDesignWorkspace')) return;

            if (data.status === 'success') {
                state.vehicleData = data.vehicle || {};
                const allDirect = data.reference_images || data.direct_images || [];
                const allFiles = data.design_files || [];

                // Reference images: only reference photos & swatch media
                const refImgs = allDirect.filter(img =>
                    img.is_reference === true
                );
                state.referenceImages = refImgs;
                const refImageIds = new Set(refImgs.map(img => img.id));

                // 3D Design files: strictly 3D model files (never reference images)
                const d3dFiles = allFiles.filter(f => !f.is_reference && !refImageIds.has(f.id));
                state.designFiles = d3dFiles;
                state.currentUser = data.user_info || {};
                state.canApproveDesigns = data.can_approve_designs || false;
                state.canDelete = data.user_info?.can_delete === true;

                // Update Badges
                const refBadge = document.getElementById('refImagesCountBadge');
                if (refBadge) refBadge.textContent = state.referenceImages.length;

                const filesBadge = document.getElementById('design3DFilesCountBadge');
                if (filesBadge) filesBadge.textContent = state.designFiles.length;

                // Update Designer Panel (if present)
                updateDesignerPanel();

                // Render Section 1 & Section 2
                renderReferenceImages(state.referenceImages);
                render3DDesignFiles();

                // Populate Drawer Dropdown
                populateDrawerFileSelector();

                // If drawer is open, refresh selected file
                if (document.getElementById('designApprovalDrawer')?.classList.contains('is-open')) {
                    if (state.selectedFileId) {
                        selectDrawerFile(state.selectedFileId);
                    } else if (state.designFiles.length > 0) {
                        selectDrawerFile(state.designFiles[0].id);
                    }
                }
            }
        } catch (err) {
            console.error('[3D Design] Failed to load workspace data:', err);
        }
    }

    /**
     * Update Designer Workflow Panel Metadata
     */
    function updateDesignerPanel() {
        const patternPill = document.getElementById('designerPatternNumberPill');
        if (patternPill) {
            patternPill.textContent = state.vehicleData.serial_number || `PAT-${state.vehicleId}`;
        }

        const designerName = document.getElementById('designerNameDisplay');
        if (designerName && state.currentUser) {
            designerName.textContent = state.currentUser.username || 'Designer';
        }

        // Check if there is a latest file with completed/approved timestamps
        if (state.designFiles.length > 0) {
            const latest = state.designFiles[0];
            const compEl = document.getElementById('designerCompletedTimeDisplay');
            if (compEl) compEl.textContent = latest.completed_at || latest.uploaded_at || '—';

            const appEl = document.getElementById('designerApprovalTimeDisplay');
            if (appEl) appEl.textContent = latest.approved_at || (latest.approval_status === 'approved' ? 'Approved' : 'Pending');

            const remInput = document.getElementById('designerRemarksInput');
            if (remInput && latest.designer_remarks && !remInput.value) {
                remInput.value = latest.designer_remarks;
            }
        }
    }

    /**
     * SECTION 1: REFERENCE IMAGES (Match Swatch Photo)
     */
    function renderReferenceImages(images) {
        const track = document.getElementById('refImagesScrollTrack');
        const emptyState = document.getElementById('refImagesEmptyState');
        const prevBtn = document.getElementById('refScrollPrev');
        const nextBtn = document.getElementById('refScrollNext');
        if (!track) return;

        if (!images || images.length === 0) {
            track.innerHTML = '';
            if (emptyState) {
                track.appendChild(emptyState);
                emptyState.style.display = 'block';
            }
            if (prevBtn) prevBtn.style.display = 'none';
            if (nextBtn) nextBtn.style.display = 'none';
            return;
        }

        let html = '';
        images.forEach((img, index) => {
            const ext = (img.file_ext || '').toLowerCase();
            const is3D = ['3ds', 'step', 'stp', 'fbx', 'obj', 'blend', 'iges', 'igs', 'stl', 'dxf', 'dwg', 'cad', 'nc', 'cut'].includes(ext) || img.file_type === 'cad';
            const isImg = !is3D && (img.file_type === 'image' || /\.(jpe?g|png|webp|gif|bmp)$/i.test(img.title || ''));
            const thumbSrc = img.url || img.preview_url;
            let refThumbHtml = '';
            if (isImg) {
                refThumbHtml = '<img src="' + escapeHtml(thumbSrc) + '" alt="' + escapeHtml(img.title) + '" loading="lazy" onerror="this.style.display=\'none\'; if(this.nextElementSibling) this.nextElementSibling.style.display=\'flex\';">' +
                    '<div class="ref-fallback-box" style="display:none;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:1.6rem;background:rgba(255,255,255,0.03);"><i class="fas fa-image"></i></div>';
            } else {
                refThumbHtml = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#a5b4fc;font-size:1.8rem;"><i class="far fa-file"></i></div>';
            }
            const refSizeText = img.file_size ? (Math.round(img.file_size / 1024) + ' KB') : '';

            const delBtnRef = canCurrentUserDelete(img)
                ? `<button type="button" class="tiny-pic-delete-btn" onclick="event.stopPropagation(); window.delete3DDesignFile(${img.id})" title="Delete this image"><i class="fas fa-trash-alt"></i></button>`
                : '';

            html += `
                <div class="ref-image-card" data-ref-index="${index}" role="button" tabindex="0" aria-label="Preview ${escapeHtml(img.title)}">
                    <div class="ref-image-thumb-box">
                        ${refThumbHtml}
                        ${delBtnRef}
                    </div>
                    <div class="ref-image-meta">
                        <div class="ref-image-name" title="${escapeHtml(img.title)}">${escapeHtml(img.title)}</div>
                        <div class="ref-image-details">
                            <span>${escapeHtml(img.uploaded_at || '')}</span>
                            <span>${refSizeText}</span>
                        </div>
                    </div>
                </div>
            `;
        });

        track.innerHTML = html;

        // Check scroll overflow for navigation arrows
        setTimeout(updateRefScrollArrows, 100);
    }

    function scrollRefImages(direction) {
        const track = document.getElementById('refImagesScrollTrack');
        if (!track) return;
        const dir = (direction === 'left' || direction === -1) ? -1 : 1;
        const scrollAmount = 320 * dir;
        track.scrollBy({ left: scrollAmount, behavior: 'smooth' });
        setTimeout(updateRefScrollArrows, 350);
    }

    function updateRefScrollArrows() {
        const track = document.getElementById('refImagesScrollTrack');
        const prevBtn = document.getElementById('refScrollPrev');
        const nextBtn = document.getElementById('refScrollNext');
        if (!track || !prevBtn || !nextBtn) return;

        const maxScroll = track.scrollWidth - track.clientWidth;
        if (maxScroll <= 5) {
            prevBtn.style.display = 'none';
            nextBtn.style.display = 'none';
        } else {
            prevBtn.style.display = track.scrollLeft > 10 ? 'flex' : 'none';
            nextBtn.style.display = track.scrollLeft < maxScroll - 10 ? 'flex' : 'none';
        }
    }

    /**
     * Upload Reference Images Handler
     */
    async function handleRefImageSelected(fileList) {
        if (!fileList || fileList.length === 0 || !state.vehicleId) return;

        const formData = new FormData();
        formData.append('is_reference', '1');
        Array.from(fileList).forEach(file => {
            formData.append('images', file);
        });

        try {
            const resp = await fetch(`/api/vehicles/${state.vehicleId}/design-images/upload/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
                body: formData,
            });
            const data = await resp.json();
            if (data.status === 'success') {
                load3DDesignWorkspace(state.vehicleId);
            } else {
                alert(data.message || 'Error uploading reference images.');
            }
        } catch (err) {
            console.error('[3D Design] Reference image upload error:', err);
        }
    }

    async function handle3DDesignSelected(fileList) {
        const input = document.getElementById('design3DUploadInput');
        if (!fileList || !fileList.length || !state.vehicleId) return;

        const vehicleId = state.vehicleId;
        const formData = new FormData();
        formData.append('is_reference', '0');
        Array.from(fileList).forEach(file => formData.append('images', file));

        if (input) input.disabled = true;
        try {
            const resp = await fetch(`/api/vehicles/${vehicleId}/design-images/upload/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() },
                body: formData,
            });
            const data = await resp.json();

            if (!resp.ok || data.status !== 'success') {
                throw new Error(data.message || 'Design upload failed.');
            }

            if (state.vehicleId === vehicleId) {
                await load3DDesignWorkspace(vehicleId);
            }
        } catch (error) {
            console.error('[3D Design] Upload failed:', error);
            alert(error.message || 'Unable to upload designs.');
        } finally {
            if (input) {
                input.value = '';
                input.disabled = false;
            }
        }
    }

    /**
     * SECTION 2: UPLOADED 3D DESIGN FILES
     */
    function render3DDesignFiles() {
        const gallery = document.getElementById('design3DFilesGallery');
        if (!gallery) return;

        let files = [...state.designFiles];

        // Search Filter
        if (state.searchQuery) {
            const q = state.searchQuery.toLowerCase();
            files = files.filter(f => (f.title || '').toLowerCase().includes(q));
        }

        // Sort
        if (state.sortOption === 'newest') {
            files.sort((a, b) => (b.id || 0) - (a.id || 0));
        } else if (state.sortOption === 'oldest') {
            files.sort((a, b) => (a.id || 0) - (b.id || 0));
        } else if (state.sortOption === 'name') {
            files.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
        } else if (state.sortOption === 'status') {
            files.sort((a, b) => (a.approval_status || '').localeCompare(b.approval_status || ''));
        }

        if (files.length === 0) {
            gallery.innerHTML = `
                <div class="design-files-empty-state" style="padding: 2.5rem 1rem; text-align: center; color: var(--fabro-text-muted); font-size: 0.85rem; width: 100%;">
                    <i class="fas fa-cube" style="font-size: 2rem; opacity: 0.35; margin-bottom: 0.65rem; display: block; color: #a855f7;"></i>
                    <h4 style="color: #cbd5e1; font-weight: 600; font-size: 0.95rem; margin-bottom: 0.35rem;">No 3D Design Files Found</h4>
                    <p style="margin: 0; font-size: 0.8rem; color: var(--fabro-text-muted);">Try adjusting your search filter or upload a new 3D design file.</p>
                </div>
            `;
            return;
        }

        let html = '';
        files.forEach(file => {
            const isRejected = file.approval_status === 'rejected';
            const isApproved = file.approval_status === 'approved';
            const isPending = !isApproved && !isRejected;

            const tileClass = `fabro-design-tile ${isRejected ? 'is-rejected' : ''} ${isApproved ? 'is-approved' : ''}`;
            const thumbSrc = file.url || file.preview_url;
            const ext = (file.file_ext || '').toLowerCase();
            const is3DModel = ['3ds', 'step', 'stp', 'fbx', 'obj', 'blend', 'iges', 'igs', 'stl', 'dxf', 'dwg', 'cad', 'nc', 'cut'].includes(ext) || file.file_type === 'cad';
            const isImage = !is3DModel && (file.file_type === 'image' || /\.(jpe?g|png|webp|gif|bmp)$/i.test(file.title || ''));

            // Status Badge Overlay
            let statusPill = '';
            if (isApproved) {
                statusPill = `<span class="stepper-badge approved" style="font-size: 0.68rem;"><i class="fas fa-check"></i> Approved</span>`;
            } else if (isRejected) {
                statusPill = `<span class="stepper-badge rejected" style="font-size: 0.68rem;"><i class="fas fa-times"></i> Rejected</span>`;
            } else {
                statusPill = `<span class="stepper-badge pending" style="font-size: 0.68rem;"><i class="far fa-clock"></i> Pending</span>`;
            }

            // Individual Approver Dots
            const mdStatus = file.md?.status || 'pending';
            const edStatus = file.ed?.status || 'pending';
            const cadStatus = file.cad?.status || 'pending';

            let mediaHtml = '';
            if (isImage) {
                const escapedThumb = escapeHtml(thumbSrc);
                const escapedTitle = escapeHtml(file.title);
                const fileExtBadge = escapeHtml(file.file_ext || '3D').toUpperCase();
                mediaHtml = '<img src="' + escapedThumb + '" alt="' + escapedTitle + '" loading="lazy" onerror="this.style.display=\'none\'; if(this.nextElementSibling) this.nextElementSibling.style.display=\'flex\';">' +
                    '<div class="tile-fallback-box" style="display:none;flex-direction:column;align-items:center;gap:0.4rem;color:#c084fc;"><i class="fas fa-cube" style="font-size:2.2rem;"></i><span style="font-size:0.72rem;font-weight:700;">' + fileExtBadge + '</span></div>';
            } else {
                const fileExtBadge = escapeHtml(file.file_ext || 'CAD').toUpperCase();
                mediaHtml = '<div style="display:flex;flex-direction:column;align-items:center;gap:0.4rem;color:#c084fc;"><i class="fas fa-cube" style="font-size:2.2rem;"></i><span style="font-size:0.72rem;font-weight:700;">' + fileExtBadge + '</span></div>';
            }

            const fileSizeText = file.file_size_display || (Math.round((file.file_size || 0) / 1024) + ' KB');

            html += `
                <div class="${tileClass}" data-file-id="${file.id}">
                    <div class="tile-checkbox-wrapper">
                        <input type="checkbox" class="file-tile-select" data-id="${file.id}" style="accent-color: var(--fabro-red); cursor: pointer;">
                    </div>

                    <div class="tile-top-actions-overlay">
                        ${statusPill}
                        ${canCurrentUserDelete(file) ? `
                            <button type="button" class="tile-delete-x-btn" onclick="event.stopPropagation(); window.delete3DDesignFile(${file.id}, '${escapeHtml(file.title)}')" title="Delete this file" aria-label="Delete this file">
                                <i class="fas fa-times"></i>
                            </button>
                        ` : ''}
                    </div>

                    <div class="tile-media-container" onclick="window.openApprovalDrawer(${file.id})">
                        ${mediaHtml}
                    </div>

                    <div class="tile-body">
                        <div class="tile-header-row">
                            <h4 class="tile-title" title="${escapeHtml(file.title)}">${escapeHtml(file.title)}</h4>
                            <button type="button" class="btn-open-tile-drawer" onclick="window.openApprovalDrawer(${file.id})" title="View Approval Workflow">
                                <i class="fas fa-clipboard-check"></i>
                            </button>
                        </div>

                        <div class="tile-meta-row">
                            <i class="far fa-file"></i>
                            <span>${fileSizeText}</span>
                            <span style="opacity:0.4;">•</span>
                            <i class="far fa-user"></i>
                            <span>${escapeHtml(file.uploaded_by || 'Designer')}</span>
                        </div>

                        <div class="tile-meta-row">
                            <i class="far fa-clock"></i>
                            <span>Completed: <strong>${escapeHtml(file.completed_at || file.uploaded_at || '—')}</strong></span>
                        </div>

                        <div class="tile-meta-row">
                            <i class="fas fa-check-double"></i>
                            <span>Approved: <strong>${escapeHtml(file.approved_at || (isApproved ? 'Approved' : 'Pending'))}</strong></span>
                        </div>

                        <!-- Approver Reviewer Dots: MD, ED, CAD -->
                        <div class="approver-indicators-row">
                            <div class="approver-dots-group">
                                <span class="approver-dot-badge is-${mdStatus}" title="MD: ${reviewStatusLabel(mdStatus).toUpperCase()}">MD</span>
                                <span class="approver-dot-badge is-${edStatus}" title="ED: ${reviewStatusLabel(edStatus).toUpperCase()}">ED</span>
                                <span class="approver-dot-badge is-${cadStatus}" title="CAD: ${reviewStatusLabel(cadStatus).toUpperCase()}">CAD</span>
                            </div>
                            <button type="button" class="approval-workflow-tile-btn" onclick="window.openApprovalDrawer(${file.id})" title="Approval Workflow">
                                <i class="fas fa-clipboard-check"></i>
                                <span>Approval Workflow</span>
                            </button>
                            ${canCurrentUserDelete(file) ? `<button type="button" class="btn-tile-delete" onclick="event.stopPropagation(); window.delete3DDesignFile(${file.id}, '${escapeHtml(file.title)}')" title="Delete this file"><i class="fas fa-times"></i></button>` : ''}
                        </div>
                    </div>
                </div>
            `;
        });

        gallery.innerHTML = html;
    }

    function filter3DDesignFiles() {
        const searchInput = document.getElementById('design3DFilesSearch');
        if (searchInput) {
            state.searchQuery = searchInput.value.trim();
            render3DDesignFiles();
        }
    }

    function sort3DDesignFiles(sortBy) {
        state.sortOption = sortBy;
        render3DDesignFiles();
    }

    function switch3DFilesView(mode) {
        state.viewMode = mode;
        const gallery = document.getElementById('design3DFilesGallery');
        const gridBtn = document.getElementById('design3DGridBtn');
        const listBtn = document.getElementById('design3DListBtn');

        if (gallery) {
            gallery.classList.toggle('view-grid', mode === 'grid');
            gallery.classList.toggle('view-list', mode === 'list');
        }
        if (gridBtn && listBtn) {
            gridBtn.classList.toggle('is-active', mode === 'grid');
            gridBtn.style.background = mode === 'grid' ? '#282c35' : '#111317';
            gridBtn.style.color = mode === 'grid' ? '#fff' : 'var(--fabro-text-secondary)';

            listBtn.classList.toggle('is-active', mode === 'list');
            listBtn.style.background = mode === 'list' ? '#282c35' : '#111317';
            listBtn.style.color = mode === 'list' ? '#fff' : 'var(--fabro-text-secondary)';
        }
    }

    /**
     * SECTION 4: RIGHT-SIDE APPROVAL WORKFLOW DRAWER
     */
    function toggleApprovalDrawer(fileId) {
        const drawer = document.getElementById('designApprovalDrawer');
        if (drawer?.classList.contains('is-open') && !fileId) {
            closeApprovalDrawer();
        } else {
            openApprovalDrawer(fileId);
        }
    }

    async function openApprovalDrawer(fileId) {
        const drawer = document.getElementById('designApprovalDrawer');
        const backdrop = document.getElementById('designApprovalDrawerBackdrop');
        if (!drawer || !backdrop) return;

        // Position dynamically directly under the top navbar and profile button
        const navbar = document.querySelector('.navbar');
        if (navbar) {
            const navRect = navbar.getBoundingClientRect();
            const navBottom = Math.max(0, Math.round(navRect.bottom));
            drawer.style.top = (navBottom + 6) + 'px';
            drawer.style.bottom = 'auto';
            drawer.style.height = 'auto';
            drawer.style.maxHeight = `calc(100vh - ${navBottom + 24}px)`;
        }

        drawer.classList.add('is-open');
        backdrop.classList.add('is-open');

        if (state.designFiles.length === 0) {
            const urlParams = new URLSearchParams(window.location.search);
            const vId = urlParams.get('vehicle_id') || window.currentVehicleId;
            if (vId) {
                await load3DDesignWorkspace(parseInt(vId, 10));
            }
        }

        // Target file ID
        let targetId = fileId;
        if (!targetId && state.designFiles.length > 0) {
            // Pick first pending file, or first file
            const pending = state.designFiles.find(f => f.approval_status === 'pending');
            targetId = pending ? pending.id : state.designFiles[0].id;
        }

        if (targetId) {
            selectDrawerFile(targetId);
        }
    }

    function closeApprovalDrawer() {
        const drawer = document.getElementById('designApprovalDrawer');
        const backdrop = document.getElementById('designApprovalDrawerBackdrop');
        if (drawer) drawer.classList.remove('is-open');
        if (backdrop) backdrop.classList.remove('is-open');
    }

    function toggleApprovalDrawer(fileId) {
        const drawer = document.getElementById('designApprovalDrawer');
        if (drawer && drawer.classList.contains('is-open')) {
            closeApprovalDrawer();
        } else {
            openApprovalDrawer(fileId);
        }
    }

    window.addEventListener('resize', () => {
        const drawer = document.getElementById('designApprovalDrawer');
        if (drawer && drawer.classList.contains('is-open')) {
            const navbar = document.querySelector('.navbar');
            if (navbar) {
                const navRect = navbar.getBoundingClientRect();
                const navBottom = Math.max(0, Math.round(navRect.bottom));
                drawer.style.top = (navBottom + 6) + 'px';
                drawer.style.bottom = 'auto';
                drawer.style.height = 'auto';
                drawer.style.maxHeight = `calc(100vh - ${navBottom + 24}px)`;
            }
        }
    }, { signal: eventController.signal });

    function populateDrawerFileSelector() {
        const selector = document.getElementById('drawerFileSelector');
        if (!selector) return;

        let optionsHtml = '';
        state.designFiles.forEach(file => {
            const statusLabel = (file.approval_status || 'pending').toUpperCase();
            optionsHtml += `<option value="${file.id}">${escapeHtml(file.title)} (${statusLabel})</option>`;
        });
        selector.innerHTML = optionsHtml;
    }

    function selectDrawerFile(fileId) {
        const id = parseInt(fileId, 10);
        state.selectedFileId = id;

        const selector = document.getElementById('drawerFileSelector');
        if (selector && selector.value != id) {
            selector.value = id;
        }

        const file = state.designFiles.find(f => f.id === id);
        if (!file) return;

        // 1. Update Preview Card
        const nameEl = document.getElementById('drawerFileName');
        if (nameEl) nameEl.textContent = file.title || 'Untitled';

        const sizeEl = document.getElementById('drawerFileSize');
        if (sizeEl) sizeEl.textContent = file.file_size_display || `${Math.round((file.file_size || 0)/1024)} KB`;

        const uploaderEl = document.getElementById('drawerFileUploadedBy');
        if (uploaderEl) uploaderEl.textContent = file.uploaded_by || 'Designer';

        const compEl = document.getElementById('drawerCompletedTime');
        if (compEl) compEl.textContent = file.completed_at || file.uploaded_at || '—';

        const appEl = document.getElementById('drawerApprovedTime');
        if (appEl) appEl.textContent = file.approved_at || (file.approval_status === 'approved' ? 'Approved' : 'Pending');

        const statusPill = document.getElementById('drawerFileOverallStatusPill');
        if (statusPill) {
            statusPill.className = `stepper-badge ${file.approval_status || 'pending'}`;
            statusPill.textContent = (file.approval_status || 'Pending').toUpperCase();
        }

        const thumbBox = document.getElementById('drawerFileThumb');
        if (thumbBox) {
            const ext = (file.file_ext || '').toLowerCase();
            const is3DModel = ['3ds', 'step', 'stp', 'fbx', 'obj', 'blend', 'iges', 'igs', 'stl', 'dxf', 'dwg', 'cad', 'nc', 'cut'].includes(ext) || file.file_type === 'cad';
            const isImg = !is3DModel && (file.file_type === 'image' || /\.(jpe?g|png|webp|gif|bmp)$/i.test(file.title || ''));
            const thumbSrc = file.url || file.preview_url;
            const drawerDelBtn = canCurrentUserDelete(file)
                ? `<button type="button" class="tile-delete-x-btn" onclick="event.stopPropagation(); window.delete3DDesignFile(${file.id}, '${escapeHtml(file.title)}')" title="Delete this file" style="position:absolute;top:6px;right:6px;"><i class="fas fa-times"></i></button>`
                : '';
            thumbBox.innerHTML = (isImg
                ? `<img src="${escapeHtml(thumbSrc)}" alt="${escapeHtml(file.title)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.onerror=null; this.parentElement.innerHTML='<i class=\'fas fa-cube\' style=\'font-size:1.8rem;color:#c084fc;\'></i>';">`
                : `<i class="fas fa-cube" style="font-size:1.8rem;color:#c084fc;"></i>`) + drawerDelBtn;
        }

        // 2. Update MD Reviewer Card
        updateReviewerCard('Md', file.md);

        // 3. Update ED Reviewer Card
        updateReviewerCard('Ed', file.ed);

        // 4. Update CAD Reviewer Card
        updateReviewerCard('Cad', file.cad);

        // 5. Update Decision Controls Box
        const decisionBox = document.getElementById('drawerDecisionBox');
        if (decisionBox) {
            const stages = ['cad', 'ed', 'md'].filter(role => file['can_review_' + role]);
            decisionBox.style.display = stages.length ? 'block' : 'none';
            decisionBox.dataset.activeStage = '';
            let selector = document.getElementById('drawerReviewRoleSelector');
            if (!selector) {
                selector = document.createElement('div');
                selector.id = 'drawerReviewRoleSelector';
                selector.setAttribute('aria-label', 'Review as');
                selector.style.cssText = 'display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory;padding:8px 0;';
                decisionBox.prepend(selector);
            }
            selector.replaceChildren();
            const selectStage = role => {
                if (state.isSubmittingDecision) return;
                decisionBox.dataset.activeStage = role;
                const label = document.getElementById('drawerActiveReviewStageLabel');
                if (label) label.textContent = role ? role.toUpperCase() : 'Select reviewer above';
                selector.querySelectorAll('button').forEach(button => {
                    button.setAttribute('aria-pressed', String(button.dataset.stage === role));
                    button.style.outline = button.dataset.stage === role ? '2px solid #a78bfa' : '';
                });
                ['radioChangeTypeMinor', 'radioChangeTypeMajor'].forEach(id => {
                    const input = document.getElementById(id);
                    if (input) input.checked = input.value === 'minor';
                });
                const remarks = document.getElementById('designDrawerDecisionRemarks');
                if (remarks) remarks.value = '';
                hideDrawerErrors();
            };
            if (file.can_admin_review) {
                ['cad', 'ed', 'md'].forEach(role => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.dataset.stage = role;
                    button.className = 'workflow-btn';
                    button.style.cssText = 'flex:0 0 auto;scroll-snap-align:start;min-height:44px;';
                    button.textContent = role.toUpperCase() + (stages.includes(role) ? '' : file[role]?.status === 'skipped_uploader' ? ' — Skipped — Uploader' : ' — completed');
                    button.disabled = !stages.includes(role);
                    button.addEventListener('click', () => selectStage(role));
                    selector.append(button);
                });
                selectStage(''); // Admin deliberately chooses; never advances to another role.
            } else {
                selectStage(stages[0] || '');
            }
        }

        // 6. Update Approval History Timeline
        renderDrawerHistory(file.history || []);
    }

    function updateReviewerCard(prefix, data) {
        const statusBadge = document.getElementById(`drawer${prefix}StatusBadge`);
        const nameEl = document.getElementById(`drawer${prefix}ReviewerName`);
        const timeEl = document.getElementById(`drawer${prefix}DecidedTime`);
        const changeBadgeBox = document.getElementById(`drawer${prefix}ChangeTypeBadge`);
        const remarksBox = document.getElementById(`drawer${prefix}Remarks`);

        const status = data?.status || 'pending';
        if (statusBadge) {
            statusBadge.className = `stepper-badge ${status}`;
            statusBadge.textContent = status === 'skipped_uploader' ? reviewStatusLabel(status) : status.toUpperCase();
        }

        if (nameEl) nameEl.textContent = status === 'skipped_uploader' ? '—' : data?.reviewer || 'Awaiting Review';
        if (timeEl) timeEl.textContent = data?.decided_at || '—';

        if (changeBadgeBox) {
            if (data?.change_type) {
                changeBadgeBox.style.display = 'block';
                const badge = changeBadgeBox.querySelector('.badge');
                if (badge) {
                    badge.textContent = data.change_type === 'major' ? 'Major Change' : 'Minor Change';
                    badge.style.background = data.change_type === 'major' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(99, 102, 241, 0.15)';
                    badge.style.color = data.change_type === 'major' ? '#fca5a5' : '#a5b4fc';
                }
            } else {
                changeBadgeBox.style.display = 'none';
            }
        }

        if (remarksBox) {
            if (data?.comment) {
                remarksBox.style.display = 'block';
                remarksBox.textContent = `"${data.comment}"`;
            } else {
                remarksBox.style.display = 'none';
            }
        }
    }

    function renderDrawerHistory(history) {
        const timeline = document.getElementById('drawerHistoryTimeline');
        if (!timeline) return;

        if (!history || history.length === 0) {
            timeline.innerHTML = `<div style="font-size:0.75rem;color:var(--fabro-text-muted);text-align:center;padding:0.5rem;">No previous review cycles.</div>`;
            return;
        }

        let html = '';
        history.forEach(item => {
            html += `
                <div style="background:#14161a;border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:0.6rem;font-size:0.75rem;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                        <span style="font-weight:700;color:#cbd5e1;">Cycle #${item.cycle || 1}</span>
                        <span style="font-size:0.7rem;color:var(--fabro-text-muted);">${item.submitted_at || ''}</span>
                    </div>
                    <div style="font-size:0.72rem;color:var(--fabro-text-secondary);display:flex;gap:0.5rem;">
                        <span>CAD: <strong>${reviewStatusLabel(item.cad_status)}</strong></span>
                        <span>ED: <strong>${reviewStatusLabel(item.ed_status)}</strong></span>
                        <span>MD: <strong>${reviewStatusLabel(item.md_status)}</strong></span>
                    </div>
                </div>
            `;
        });
        timeline.innerHTML = html;
    }

    function hideDrawerErrors() {
        const errType = document.getElementById('drawerChangeTypeError');
        if (errType) errType.style.display = 'none';
    }

    /**
     * Submit Review Decision (Approved or Rejected)
     */
    async function submitDrawerDecision(decision) {
        if (state.isSubmittingDecision) return;
        hideDrawerErrors();

        const decisionBox = document.getElementById('drawerDecisionBox');
        const stage = decisionBox?.dataset.activeStage || '';
        if (!stage) { alert('Select CAD, ED, or MD before submitting a review.'); return; }
        const fileId = state.selectedFileId;

        if (!fileId) return;

        // Change Type Validation (Mandatory for both Approve and Reject)
        const selectedRadio = document.querySelector('input[name="drawerChangeType"]:checked');
        if (!selectedRadio) {
            const errType = document.getElementById('drawerChangeTypeError');
            if (errType) errType.style.display = 'block';
            return;
        }
        const changeType = selectedRadio.value;

        // Remarks are optional; preserve the reviewer's text exactly.
        const remarksInput = document.getElementById('designDrawerDecisionRemarks');
        const remarks = remarksInput ? remarksInput.value : '';

        const endpoint = decision === 'approved'
            ? `/api/design-images/${fileId}/approve/`
            : `/api/design-images/${fileId}/reject/`;

        const approveButton = document.getElementById('drawerBtnApprove');
        const rejectButton = document.getElementById('drawerBtnReject');
        state.isSubmittingDecision = true;
        if (approveButton) approveButton.disabled = true;
        if (rejectButton) rejectButton.disabled = true;
        try {
            const payload = {
                stage: stage,
                change_type: changeType,
                comment: remarks,
                reason: remarks,
            };

            const resp = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify(payload),
            });

            const data = await resp.json();
            if (data.status === 'success') {
                // Refresh workspace and reload drawer details
                await load3DDesignWorkspace(state.vehicleId);
                selectDrawerFile(fileId);
            } else {
                alert(data.message || 'Error recording review decision.');
            }
        } catch (err) {
            console.error('[3D Design] Review submission failed:', err);
            alert('Failed to submit review decision. Please try again.');
        } finally {
            state.isSubmittingDecision = false;
            if (approveButton) approveButton.disabled = false;
            if (rejectButton) rejectButton.disabled = false;
        }
    }

    /**
     * Toggle Legacy Folders View
     */
    function toggleLegacyFoldersView() {
        state.isLegacyView = !state.isLegacyView;
        const primary = document.getElementById('primary3DDesignView');
        const legacy = document.getElementById('legacyFoldersWrapper');
        const btnText = document.getElementById('toggleLegacyFoldersText');

        if (primary && legacy) {
            primary.style.display = state.isLegacyView ? 'none' : 'flex';
            legacy.style.display = state.isLegacyView ? 'block' : 'none';
        }
        if (btnText) {
            btnText.textContent = state.isLegacyView ? 'Back to 3D Design' : 'Folders View';
        }
    }

    /**
     * Preview Image Lightbox Modal
     */

    function openReferenceFile(image) {
        if (!image) return;

        const ext = String(image.file_ext || '').replace(/^\./, '').toLowerCase();
        const isImage = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext);

        if (isImage) {
            previewImageLightbox(image.url || image.preview_url, image.title);
            return;
        }

        // Use FABRO's authenticated file-download endpoint.
        const downloadUrl = image.original_url ||
            `/design-images/${encodeURIComponent(image.id)}/download/`;

        const link = document.createElement('a');
        link.href = downloadUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        document.body.appendChild(link);
        link.click();
        link.remove();
    }

    function previewImageLightbox(src, title) {
        const modal = document.getElementById('interiorMediaPreviewModal');
        const container = document.getElementById('interiorMediaPreviewContainer');
        if (modal && container) {
            container.innerHTML = `
                <img src="${escapeHtml(src)}" alt="${escapeHtml(title)}" style="max-width:90vw;max-height:85vh;border-radius:8px;box-shadow:0 12px 40px rgba(0,0,0,0.8);">
                <div style="color:#fff;margin-top:0.75rem;font-size:0.9rem;font-weight:600;">${escapeHtml(title)}</div>
            `;
            modal.style.display = 'flex';
        }
    }

    // Attach to window for global template/UI access
    window.load3DDesignWorkspace = load3DDesignWorkspace;
    window.scrollRefImages = scrollRefImages;
    window.handleRefImageSelected = handleRefImageSelected;
    window.handle3DDesignSelected = handle3DDesignSelected;
    window.filter3DDesignFiles = filter3DDesignFiles;
    window.sort3DDesignFiles = sort3DDesignFiles;
    window.switch3DFilesView = switch3DFilesView;
    window.toggleApprovalDrawer = toggleApprovalDrawer;
    window.openApprovalDrawer = openApprovalDrawer;
    window.closeApprovalDrawer = closeApprovalDrawer;
    window.selectDrawerFile = selectDrawerFile;
    window.submitDrawerDecision = submitDrawerDecision;
    window.scrollRefImages = scrollRefImages;
    window.toggleLegacyFoldersView = toggleLegacyFoldersView;
    window.previewImageLightbox = previewImageLightbox;
    window.load3DDesignWorkspace = load3DDesignWorkspace;

    // Global listeners are replaced when this page asset is loaded again by HTMX.
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeApprovalDrawer();
        }
    }, { signal: eventController.signal });

    function initialize3DWorkspace() {
        const track = document.getElementById('refImagesScrollTrack');
        if (track && track !== referenceTrack) {
            referenceTrack = track;
            track.addEventListener('scroll', updateRefScrollArrows, { passive: true, signal: eventController.signal });
            track.addEventListener('click', (event) => {
                const card = event.target.closest('.ref-image-card');
                if (!card) return;
                const image = state.referenceImages[Number(card.dataset.refIndex)];
                if (image) openReferenceFile(image);
            }, { signal: eventController.signal });
            track.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                const card = event.target.closest('.ref-image-card');
                if (!card) return;
                event.preventDefault();
                const image = state.referenceImages[Number(card.dataset.refIndex)];
                if (image) openReferenceFile(image);
            }, { signal: eventController.signal });
        }
    }

    document.addEventListener('DOMContentLoaded', initialize3DWorkspace, { once: true, signal: eventController.signal });
    document.addEventListener('fabro:page-ready', initialize3DWorkspace, { signal: eventController.signal });
    document.addEventListener('fabro:before-page-swap', () => {
        state.loadRequestId++;
        referenceTrack = null;
        closeApprovalDrawer();
    }, { signal: eventController.signal });
    if (document.readyState !== 'loading') initialize3DWorkspace();
    window.__fabro3DDispose = () => eventController.abort();

})();
