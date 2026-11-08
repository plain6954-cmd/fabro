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
        previewImages: [],
        selectedFileId: null,
        viewMode: 'grid', // 'grid' | 'list'
        sortOption: 'newest',
        searchQuery: '',
        isLegacyView: false,
        currentUser: null,
        loadRequestId: 0,
        isSubmittingDecision: false,
        uploads: [],
        uploadBusy: false,
        uploadSequence: 0,
        renderedTiles: new Map(),
        galleryManifest: {},
        galleryRevision: null,
        galleryLoading: false,
        pendingDeleteFileId: null,
        isDeletingFile: false,
    };
    let gallerySync = null;
    let accessRefreshPending = false;
    function refreshAccess(force = false) {
        if (!state.vehicleId || state.galleryLoading && !force) return;
        load3DDesignWorkspace(state.vehicleId).then(success => { accessRefreshPending = !success; });
    }
    document.addEventListener('fabro:access-changed', () => {
        if (!state.vehicleId) return;
        // Reuse authorized manifests for own/all and protected-workflow state.
        // Existing loader retains open review drafts and guards stale responses.
        document.querySelectorAll('.tiny-pic-delete-btn, .tile-delete-x-btn, .btn-tile-delete, .tile-delete-btn').forEach(node => { node.hidden = true; });
        accessRefreshPending = true;
        refreshAccess(true);
    }, {signal: eventController.signal});
    document.addEventListener('fabro:access-revalidated', () => { if (accessRefreshPending) refreshAccess(); }, {signal: eventController.signal});

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
        return item?.can_delete === true;
    }

    function openDelete3DDesignModal(fileId) {
        if (!fileId) return;
        const file = [...state.referenceImages, ...state.designFiles].find(f => f.id === fileId);
        if (!file) return;

        state.pendingDeleteFileId = fileId;
        state.isDeletingFile = false;

        const modal = document.getElementById('delete3DDesignModal');
        if (!modal) return;

        // Populate Pattern Number
        const patternEl = document.getElementById('deleteModalPatternNumber');
        if (patternEl) {
            const patternNum = file.pattern_number
                || (state.vehicleData && (state.vehicleData.serial_number || state.vehicleData.heading))
                || (document.getElementById('patternHeadingSerial')?.textContent?.trim())
                || (state.vehicleId ? `Vehicle #${state.vehicleId}` : '—');
            patternEl.textContent = patternNum;
        }

        // Populate Filename
        const filenameEl = document.getElementById('deleteModalFilename');
        if (filenameEl) {
            filenameEl.textContent = file.title || 'Untitled';
        }

        // Populate Upload Date
        const uploadedEl = document.getElementById('deleteModalUploadedAt');
        if (uploadedEl) {
            uploadedEl.textContent = file.uploaded_at || '—';
        }

        // Populate Approval Status
        const statusEl = document.getElementById('deleteModalApprovalStatus');
        if (statusEl) {
            const status = (file.approval_status || 'pending').toLowerCase();
            if (status === 'approved') {
                statusEl.innerHTML = '<span style="color: #34d399; background: rgba(16, 185, 129, 0.15); padding: 0.2rem 0.55rem; border-radius: 4px; display: inline-flex; align-items: center; gap: 0.35rem;"><i class="fas fa-check-circle"></i> Approved</span>';
            } else if (status === 'rejected') {
                statusEl.innerHTML = '<span style="color: #f87171; background: rgba(239, 68, 68, 0.15); padding: 0.2rem 0.55rem; border-radius: 4px; display: inline-flex; align-items: center; gap: 0.35rem;"><i class="fas fa-times-circle"></i> Rejected</span>';
            } else {
                statusEl.innerHTML = '<span style="color: #fbbf24; background: rgba(245, 158, 11, 0.15); padding: 0.2rem 0.55rem; border-radius: 4px; display: inline-flex; align-items: center; gap: 0.35rem;"><i class="far fa-clock"></i> Pending</span>';
            }
        }

        // Toggle History Warning
        const warningEl = document.getElementById('deleteModalHistoryWarning');
        if (warningEl) {
            const hasHistory = file.has_approval_history === true
                || file.approval_status === 'approved'
                || file.approval_status === 'rejected'
                || (Array.isArray(file.history) && (file.history.length > 1 || file.history.some(h => (h.cad_status && h.cad_status !== 'pending') || (h.ed_status && h.ed_status !== 'pending') || (h.md_status && h.md_status !== 'pending') || h.cad_reviewer || h.ed_reviewer || h.md_reviewer)))
                || (file.cad && file.cad.status && file.cad.status !== 'pending')
                || (file.ed && file.ed.status && file.ed.status !== 'pending')
                || (file.md && file.md.status && file.md.status !== 'pending');
            warningEl.style.display = hasHistory ? 'block' : 'none';
        }

        // Reset Feedback
        const errEl = document.getElementById('deleteModalErrorFeedback');
        if (errEl) {
            errEl.textContent = '';
            errEl.style.display = 'none';
        }
        const succEl = document.getElementById('deleteModalSuccessFeedback');
        if (succEl) {
            succEl.textContent = '';
            succEl.style.display = 'none';
        }

        // Reset Actions
        const confirmBtn = document.getElementById('btnConfirmDelete3DDesign');
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = '<i class="fas fa-trash-alt"></i> <span>Confirm Delete</span>';
        }
        const cancelBtn = document.getElementById('btnCancelDelete3DDesign');
        if (cancelBtn) {
            cancelBtn.disabled = false;
        }

        modal.style.display = 'flex';
        cancelBtn?.focus();
    }

    function closeDelete3DDesignModal() {
        const modal = document.getElementById('delete3DDesignModal');
        if (modal) modal.style.display = 'none';
        state.pendingDeleteFileId = null;
        state.isDeletingFile = false;
    }

    async function confirmDelete3DDesignFile() {
        const fileId = state.pendingDeleteFileId;
        if (!fileId || state.isDeletingFile) return;

        state.isDeletingFile = true;
        const confirmBtn = document.getElementById('btnConfirmDelete3DDesign');
        const cancelBtn = document.getElementById('btnCancelDelete3DDesign');
        const errEl = document.getElementById('deleteModalErrorFeedback');
        const succEl = document.getElementById('deleteModalSuccessFeedback');

        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Deleting...</span>';
        }
        if (cancelBtn) cancelBtn.disabled = true;
        if (errEl) errEl.style.display = 'none';
        if (succEl) succEl.style.display = 'none';

        try {
            const formData = new FormData();
            if (state.vehicleId) {
                formData.append('vehicle_id', state.vehicleId);
            }

            const resp = await fetch(`/api/design-images/${fileId}/delete/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
                body: formData,
            });

            const data = await resp.json().catch(() => ({}));
            if (resp.ok && data.status === 'success') {
                if (succEl) {
                    succEl.textContent = data.message || 'File deleted successfully.';
                    succEl.style.display = 'block';
                }

                // Remove from state
                state.referenceImages = state.referenceImages.filter(f => f.id !== fileId);
                state.designFiles = state.designFiles.filter(f => f.id !== fileId);
                state.uploads = state.uploads.filter(entry => entry.serverFile?.id !== fileId);

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

                document.dispatchEvent(new CustomEvent('fabro:design-file-deleted', {
                    detail: { fileId, vehicleId: state.vehicleId }
                }));

                setTimeout(() => {
                    closeDelete3DDesignModal();
                }, 350);
            } else {
                state.isDeletingFile = false;
                if (confirmBtn) {
                    confirmBtn.disabled = false;
                    confirmBtn.innerHTML = '<i class="fas fa-trash-alt"></i> <span>Confirm Delete</span>';
                }
                if (cancelBtn) cancelBtn.disabled = false;
                if (errEl) {
                    errEl.textContent = data.message || `Error deleting file (Status ${resp.status}).`;
                    errEl.style.display = 'block';
                }
            }
        } catch (err) {
            console.error('[3D Design] Error deleting file:', err);
            state.isDeletingFile = false;
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = '<i class="fas fa-trash-alt"></i> <span>Confirm Delete</span>';
            }
            if (cancelBtn) cancelBtn.disabled = false;
            if (errEl) {
                errEl.textContent = 'A network error occurred while deleting the file. Please try again.';
                errEl.style.display = 'block';
            }
        }
    }

    function delete3DDesignFile(fileId, fileTitle) {
        openDelete3DDesignModal(fileId);
    }
    window.openDelete3DDesignModal = openDelete3DDesignModal;
    window.closeDelete3DDesignModal = closeDelete3DDesignModal;
    window.confirmDelete3DDesignFile = confirmDelete3DDesignFile;
    window.delete3DDesignFile = delete3DDesignFile;

    async function load3DDesignWorkspace(vehicleId) {
        if (!vehicleId) return;
        if (window.fabroActivityAllowed && !['folder.view','design.view_own','design.view_all','reference.view_own','reference.view_all'].some(window.fabroActivityAllowed)) return;
        const requestId = ++state.loadRequestId;
        state.vehicleId = vehicleId;
        state.galleryLoading = true;
        gallerySync?.wake();

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
                state.uploads = state.uploads.filter(entry => {
                    if (entry.vehicleId !== vehicleId || !entry.serverFile) return true;
                    const current = d3dFiles.find(file => file.id === entry.serverFile.id);
                    if (current) entry.serverFile = current;
                    return !!current;
                });
                state.currentUser = data.user_info || {};
                state.canApproveDesigns = data.can_approve_designs || false;
                state.canDelete = data.user_info?.can_delete === true;
                state.galleryManifest = data.gallery_manifest || {};
                state.galleryRevision = data.gallery_revision || null;
                document.dispatchEvent(new CustomEvent('fabro:design-data-refreshed',{detail:{vehicleId}}));

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
                    const drawer = document.getElementById('designApprovalDrawer');
                    const hasDraft = document.getElementById('designDrawerDecisionRemarks')?.value
                        || document.getElementById('radioChangeTypeMajor')?.checked
                        || window.fabroReviewVoice?.hasDraft?.(drawer);
                    // A delayed initial load or gallery refresh must not erase an open review draft.
                    if (hasDraft && state.designFiles.some(file => file.id === state.selectedFileId)) {
                        document.getElementById('drawerFileSelector').value = String(state.selectedFileId);
                        return true;
                    } else if (state.selectedFileId) {
                        selectDrawerFile(state.selectedFileId);
                    } else if (state.designFiles.length > 0) {
                        selectDrawerFile(state.designFiles[0].id);
                    }
                }
                return true;
            }
        } catch (err) {
            console.error('[3D Design] Failed to load workspace data:', err);
        } finally {
            if (requestId === state.loadRequestId) {
                state.galleryLoading = false;
                initializeGallerySync();
                gallerySync?.wake();
            }
        }
        return false;
    }

    async function checkGalleryUpdates(signal) {
        const vehicleId = state.vehicleId, requestId = state.loadRequestId;
        const url = `/api/design-folders/?vehicle_id=${encodeURIComponent(vehicleId)}&gallery_sync=1`;
        const headers = state.galleryRevision ? { 'If-None-Match': `"${state.galleryRevision}"` } : {};
        const response = await fetch(url, { headers, signal, cache: 'no-store' });
        if (response.redirected || [401, 403, 404].includes(response.status)) return false;
        if (response.status === 304) return;
        if (!response.ok) throw new Error('Gallery check unavailable');
        const update = await response.json();
        if (update.status !== 'success' || !update.gallery_manifest || !update.gallery_revision) throw new Error('Invalid gallery check');
        const manifest = update.gallery_manifest;
        const changed = Object.keys(manifest).filter(id => manifest[id] !== state.galleryManifest[id]);
        const files = [];
        for (let index = 0; index < changed.length; index += 100) {
            if (requestId !== state.loadRequestId || signal.aborted) return;
            const metadata = await fetch(`${url}&files=${encodeURIComponent(changed.slice(index, index + 100).join(','))}`, { signal, cache: 'no-store' });
            if (metadata.redirected || [401, 403, 404].includes(metadata.status)) return false;
            if (!metadata.ok) throw new Error('Gallery metadata unavailable');
            const data = await metadata.json();
            // A concurrent write needs a fresh check, rather than adopting mismatched revisions.
            if (data.gallery_revision !== update.gallery_revision) return;
            if (!Array.isArray(data.design_files)) throw new Error('Invalid gallery metadata');
            files.push(...data.design_files);
        }
        if (requestId !== state.loadRequestId || signal.aborted) return;
        const oldIds = new Set(state.designFiles.map(file => file.id));
        const updatedIds = new Set(changed);
        const next = state.designFiles.filter(file => Object.hasOwn(manifest, String(file.id)) && !updatedIds.has(String(file.id)));
        state.designFiles = next.concat(files).sort((a, b) => b.id - a.id);
        state.currentUser = update.user_info;
        state.canDelete = update.user_info?.can_delete === true;
        state.canApproveDesigns = update.user_info?.can_approve === true;
        state.galleryManifest = manifest;
        state.galleryRevision = update.gallery_revision;
        state.uploads = state.uploads.filter(entry => {
            if (entry.vehicleId !== vehicleId || !entry.serverFile) return true;
            const current = state.designFiles.find(file => file.id === entry.serverFile.id);
            if (current) entry.serverFile = current;
            return !!current;
        });
        const gallery = document.getElementById('design3DFilesGallery');
        if (!gallery) return;
        const scroll = { x: scrollX, y: scrollY, left: gallery.scrollLeft, top: gallery.scrollTop };
        render3DDesignFiles(new Set(files.filter(file => !oldIds.has(file.id)).map(file => file.id)));
        gallery.scrollLeft = scroll.left;
        gallery.scrollTop = scroll.top;
        window.scrollTo({ left: scroll.x, top: scroll.y, behavior: 'instant' });
        const badge = document.getElementById('design3DFilesCountBadge');
        if (badge) badge.textContent = state.designFiles.length;
        if (state.vehicleData) updateDesignerPanel();
        if (!document.getElementById('designApprovalDrawer')?.classList.contains('is-open')) populateDrawerFileSelector();
    }

    function initializeGallerySync() {
        const root = document.getElementById('pattern3DDesignWorkspace');
        if (!gallerySync && root && window.fabroCreateGallerySync) {
            gallerySync = window.fabroCreateGallerySync({ root, signal: eventController.signal,
                canCheck: () => !!state.vehicleId && !state.galleryLoading,
                check: checkGalleryUpdates });
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
        if (!fileList?.length || !state.vehicleId || state.uploadBusy || eventController.signal.aborted) return;
        if (fileList.length > 10) {
            alert('Upload at most 10 files at once.');
            const input = document.getElementById('design3DUploadInput');
            if (input) input.value = '';
            return;
        }
        const entries = Array.from(fileList, file => ({
            id: crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join(''),
            temporaryId: --state.uploadSequence,
            vehicleId: state.vehicleId, file, title: file.name, size: file.size,
            phase: 'queued', percent: 0, serverFile: null, error: '',
        }));
        state.uploads.push(...entries);
        render3DDesignFiles();
        await runDesignUploads(entries);
    }

    function uploadMessage(entry) {
        if (entry.phase === 'failed') return entry.error;
        if (entry.phase === 'queued') return 'Queued';
        if (entry.phase === 'processing') return 'Processing...';
        if (entry.phase === 'loading') return 'Loading image...';
        if (entry.phase === 'revealing' || entry.phase === 'done') return 'Uploaded';
        return 'Uploading...';
    }

    function updateDesignUploadProgress(entry) {
        const tile = document.querySelector(`[data-upload-id="${entry.id}"]`);
        if (!tile) return;
        tile.querySelector('.tile-upload-percent').textContent = `${entry.percent}%`;
        const progress = tile.querySelector('[role="progressbar"]');
        progress.setAttribute('aria-valuenow', entry.percent);
        progress.style.setProperty('--upload-progress', `${entry.percent}%`);
        tile.querySelector('.tile-upload-message').textContent = uploadMessage(entry);
    }

    function sendDesignUpload(entry) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const abort = () => xhr.abort();
            xhr.open('POST', `/api/vehicles/${entry.vehicleId}/design-images/upload/`);
            xhr.responseType = 'json';
            xhr.timeout = 120000;
            xhr.setRequestHeader('X-CSRFToken', getCsrfToken());
            // The existing backend reuses this file's saved record if a response was lost.
            xhr.setRequestHeader('X-Upload-Id', entry.id);
            xhr.upload.onprogress = event => {
                if (event.lengthComputable && event.total > 0) {
                    entry.percent = Math.min(100, Math.floor(event.loaded / event.total * 100));
                    updateDesignUploadProgress(entry);
                }
            };
            xhr.upload.onload = () => {
                entry.percent = 100;
                entry.phase = 'processing';
                updateDesignUploadProgress(entry);
            };
            xhr.onload = () => {
                const data = xhr.response;
                if (xhr.status >= 200 && xhr.status < 300 && data?.status === 'success' && data.images?.length === 1) {
                    resolve(data.images[0]);
                } else {
                    reject(new Error(data?.message || 'Upload could not be confirmed. Please retry.'));
                }
            };
            xhr.onerror = xhr.ontimeout = () => reject(new Error('Connection interrupted. Please retry.'));
            xhr.onabort = () => reject(new Error('Upload interrupted.'));
            xhr.onloadend = () => eventController.signal.removeEventListener('abort', abort);
            eventController.signal.addEventListener('abort', abort, { once: true });
            const body = new FormData();
            body.append('is_reference', '0');
            body.append('images', entry.file);
            xhr.send(body);
        });
    }

    async function loadUploadedImage(url) {
        const image = new Image();
        await new Promise((resolve, reject) => {
            const abort = () => { image.src = ''; reject(new Error('Image loading interrupted.')); };
            const cleanup = () => eventController.signal.removeEventListener('abort', abort);
            image.onload = () => { cleanup(); resolve(); };
            image.onerror = () => { cleanup(); reject(new Error('File saved, but its image could not load. Please retry.')); };
            eventController.signal.addEventListener('abort', abort, { once: true });
            image.src = url;
        });
        if (image.decode) await image.decode();
    }

    async function runDesignUploads(entries) {
        if (state.uploadBusy || eventController.signal.aborted) return;
        state.uploadBusy = true;
        const input = document.getElementById('design3DUploadInput');
        const button = document.getElementById('btnUpload3DDesigns');
        if (input) input.disabled = true;
        if (button) button.disabled = true;
        try {
            // One file per request exposes genuine, independent byte progress without parallel uploads.
            for (const entry of entries) {
                if (eventController.signal.aborted) break;
                try {
                    entry.error = '';
                    if (!entry.serverFile) {
                        entry.phase = 'uploading';
                        entry.percent = 0;
                        render3DDesignFiles();
                        entry.serverFile = await sendDesignUpload(entry);
                    }
                    if (eventController.signal.aborted) break;
                    entry.phase = 'loading';
                    if (state.vehicleId === entry.vehicleId) {
                        if (!await load3DDesignWorkspace(entry.vehicleId)) {
                            throw new Error('File saved, but the gallery could not refresh. Please retry.');
                        }
                        const current = state.designFiles.find(file => file.id === entry.serverFile.id);
                        if (!current) throw new Error('The saved file is no longer available in this gallery.');
                        entry.serverFile = current;
                    }
                    document.dispatchEvent(new CustomEvent('fabro:designer-uploaded', {detail:{vehicleId:entry.vehicleId,imageId:entry.serverFile.id}}));
                    if (isDesignImage(entry.serverFile)) {
                        await loadUploadedImage(entry.serverFile.url || entry.serverFile.original_url);
                    }
                    if (eventController.signal.aborted) break;
                    entry.phase = 'revealing';
                    entry.file = null;
                    render3DDesignFiles();
                    const tile = document.querySelector(`[data-upload-id="${entry.id}"]`);
                    if (tile) {
                        void tile.offsetWidth;
                        requestAnimationFrame(() => tile.classList.add('is-upload-revealed'));
                    }
                    setTimeout(() => {
                        entry.phase = 'done';
                        tile?.querySelector('.tile-upload-overlay')?.remove();
                        tile?.classList.remove('is-upload-revealing', 'is-upload-revealed');
                    }, 350);
                } catch (error) {
                    if (eventController.signal.aborted) break;
                    entry.phase = 'failed';
                    entry.error = error.message || 'Unable to upload this file. Please retry.';
                    render3DDesignFiles();
                }
            }
        } finally {
            state.uploadBusy = false;
            if (input) { input.value = ''; input.disabled = false; }
            if (button) button.disabled = false;
            document.querySelectorAll('.tile-upload-retry').forEach(retry => { retry.disabled = false; });
        }
    }

    function retry3DDesignUpload(id) {
        const entry = state.uploads.find(upload => upload.id === id && upload.phase === 'failed');
        if (entry) return runDesignUploads([entry]);
    }

    /**
     * SECTION 2: UPLOADED 3D DESIGN FILES
     */
    function isDesignImage(file) {
        return file.file_type === 'image';
    }

    function open3DDesignPreview(fileId, source) {
        const file = state.designFiles.find(entry => entry.id === fileId);
        if (!file) return;
        // Thumbnail clicks stop propagation, so invoke the shared comparison entry directly.
        window.openDesignComparison(file.id, source);
    }

    function render3DDesignFiles(animateNew = new Set()) {
        const gallery = document.getElementById('design3DFilesGallery');
        if (!gallery) return;

        let files = [...state.designFiles];
        const uploads = state.uploads.filter(entry => entry.vehicleId === state.vehicleId);
        const batchActive = uploads.some(entry => !['done', 'failed'].includes(entry.phase));
        const pinnedUploads = uploads.filter(entry => batchActive || entry.phase === 'failed');
        const uploadIds = new Set(pinnedUploads.map(entry => entry.serverFile?.id));
        files = files.filter(file => !uploadIds.has(file.id)).map(file => ({
            ...file, upload: uploads.find(entry => entry.serverFile?.id === file.id),
        }));

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

        // Reserve each selected file's slot; replace that same slot after confirmation.
        files.unshift(...pinnedUploads.filter(entry => entry.phase !== 'done' || !state.searchQuery || entry.title.toLowerCase().includes(state.searchQuery.toLowerCase())).map(entry => ({
            ...(entry.serverFile || { id: entry.temporaryId, title: entry.title, file_size: entry.size,
                file_size_display: entry.size < 1024 * 1024 ? `${Math.round(entry.size / 1024 * 10) / 10} KB` : `${Math.round(entry.size / (1024 * 1024) * 100) / 100} MB`,
                uploaded_by: state.currentUser?.username, file_ext: entry.title.split('.').pop() }),
            upload: entry,
        })));

        // Use only the visible, authorized image results in the current gallery order.
        state.previewImages = files.filter(file => isDesignImage(file) && (!file.upload || ['revealing', 'done'].includes(file.upload.phase))).map(file => ({
            id: file.id, title: file.title,
            url: file.original_url || `/design-images/${encodeURIComponent(file.id)}/download/`,
        }));

        if (files.length === 0) {
            state.renderedTiles.clear();
            gallery.innerHTML = `
                <div class="design-files-empty-state" style="padding: 2.5rem 1rem; text-align: center; color: var(--fabro-text-muted); font-size: 0.85rem; width: 100%;">
                    <i class="fas fa-cube" style="font-size: 2rem; opacity: 0.35; margin-bottom: 0.65rem; display: block; color: #a855f7;"></i>
                    <h4 style="color: #cbd5e1; font-weight: 600; font-size: 0.95rem; margin-bottom: 0.35rem;">No 3D Design Files Found</h4>
                    <p style="margin: 0; font-size: 0.8rem; color: var(--fabro-text-muted);">Try adjusting your search filter or upload a new 3D design file.</p>
                </div>
            `;
            return;
        }

        const tiles = [];
        files.forEach(file => {
            const upload = file.upload;
            const uploadPending = upload && !['revealing', 'done'].includes(upload.phase);
            const isRejected = file.approval_status === 'rejected';
            const isApproved = file.approval_status === 'approved';
            const isPending = !isApproved && !isRejected;

            const tileClass = `fabro-design-tile ${isRejected ? 'is-rejected' : ''} ${isApproved ? 'is-approved' : ''} ${uploadPending ? 'is-upload-pending' : ''} ${upload?.phase === 'revealing' ? 'is-upload-revealing' : ''}`;
            const thumbSrc = file.url || file.preview_url;
            const isImage = isDesignImage(file) && !uploadPending;
            const isPdf = file.file_type === 'pdf' && !uploadPending;
            const canPreview = isImage || isPdf;

            // Status Badge Overlay
            const universalApproved = file.cad?.status === 'approved'
                && (file.ed?.status === 'approved' || file.md?.status === 'approved');
            let statusPill = '';
            if (universalApproved) {
                statusPill = `<span id="design3DStatus${file.id}" class="stepper-badge tile-overall-status approved" onclick="event.stopPropagation()"><i class="fas fa-check-circle" aria-hidden="true"></i> Approved</span>`;
            } else {
                statusPill = `<span id="design3DStatus${file.id}" class="stepper-badge tile-overall-status pending" onclick="event.stopPropagation()"><i class="far fa-clock" aria-hidden="true"></i> Pending</span>`;
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
                mediaHtml = '<div class="' + (isPdf ? 'tile-pdf-placeholder' : '') + '" style="display:flex;flex-direction:column;align-items:center;gap:0.4rem;color:#c084fc;"><i class="fas ' + (isPdf ? 'fa-file-pdf' : 'fa-cube') + '" aria-hidden="true" style="font-size:2.2rem;"></i><span style="font-size:0.72rem;font-weight:700;">' + fileExtBadge + '</span></div>';
            }

            const fileSizeText = file.file_size_display || (Math.round((file.file_size || 0) / 1024) + ' KB');

            const html = `
                <div class="${tileClass}" data-file-id="${file.id}" ${upload ? `data-upload-id="${upload.id}"` : ''}>
                    <div class="tile-top-actions-overlay">
                        ${!uploadPending && canCurrentUserDelete(file) ? `
                            <button type="button" class="tile-delete-btn btn-danger" onclick="event.stopPropagation(); window.openDelete3DDesignModal(${file.id})" title="Delete uploaded 3D design file" aria-label="Delete ${escapeHtml(file.title)}">
                                <i class="fas fa-trash-alt"></i>
                            </button>
                        ` : ''}
                    </div>

                    ${canPreview ? `<button type="button" class="tile-media-container" data-design-${isPdf ? 'pdf' : 'image'}-id="${file.id}" aria-label="${isPdf ? 'Open PDF' : 'Enlarge'} ${escapeHtml(file.title)}" aria-describedby="design3DStatus${file.id}" onclick="event.stopPropagation(); window.open3DDesignPreview(${file.id}, this)">` : '<div class="tile-media-container">'}
                        ${mediaHtml}
                        ${statusPill}
                        ${upload && upload.phase !== 'done' ? `
                            <div class="tile-upload-overlay" onclick="event.stopPropagation()">
                                <span class="tile-upload-percent">${upload.percent}%</span>
                                <div class="tile-upload-progress" role="progressbar" aria-label="Uploading ${escapeHtml(file.title)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${upload.percent}" style="--upload-progress: ${upload.percent}%"></div>
                                <span class="tile-upload-message" role="status" title="${escapeHtml(uploadMessage(upload))}">${escapeHtml(uploadMessage(upload))}</span>
                                ${upload.phase === 'failed' ? `<button type="button" class="tile-upload-retry" ${state.uploadBusy ? 'disabled' : ''} title="${escapeHtml(upload.error)}" aria-label="Retry ${escapeHtml(file.title)}: ${escapeHtml(upload.error)}" onclick="event.stopPropagation(); window.retry3DDesignUpload('${upload.id}')">Retry</button>` : ''}
                            </div>
                        ` : ''}
                    ${canPreview ? '</button>' : '</div>'}

                    <div class="tile-body">
                        <div class="tile-header-row">
                            <h4 class="tile-title" title="${escapeHtml(file.title)}">${escapeHtml(file.title)}</h4>
                            <button type="button" class="btn-open-tile-drawer" ${uploadPending ? 'disabled' : ''} onclick="event.stopPropagation(); window.openApprovalDrawer(${file.id})" title="View Approval Workflow" aria-label="View Approval Workflow">
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
                            <span>Completed: ${upload && !upload.serverFile ? `<strong class="tile-upload-date-placeholder"><span>—</span><span aria-hidden="true">${escapeHtml(state.designFiles[0]?.completed_at || 'Sep 30, 2000 12:00 AM')}</span></strong>` : `<strong>${escapeHtml(file.completed_at || file.uploaded_at || '—')}</strong>`}</span>
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
                            <button type="button" class="approval-workflow-tile-btn" ${uploadPending ? 'disabled' : ''} onclick="event.stopPropagation(); window.openApprovalDrawer(${file.id})" title="Approval Workflow">
                                <i class="fas fa-clipboard-check"></i>
                                <span>Approval Workflow</span>
                            </button>
                            ${!uploadPending && canCurrentUserDelete(file) ? `<button type="button" class="btn-tile-delete" onclick="event.stopPropagation(); window.openDelete3DDesignModal(${file.id})" title="Delete uploaded 3D design file" aria-label="Delete ${escapeHtml(file.title)}"><i class="fas fa-trash-alt"></i></button>` : ''}
                        </div>
                    </div>
                </div>
            `;
            tiles.push({ key: upload?.id || String(file.id), html });
        });

        const focused = document.activeElement;
        const nextTiles = new Map();
        const nodes = tiles.map(({ key, html }) => {
            const previous = state.renderedTiles.get(key);
            let node = previous?.node;
            if (node && previous.html === html) node.querySelectorAll('.tile-delete-x-btn, .btn-tile-delete, .tile-delete-btn').forEach(button => { button.hidden = false; });
            if (!node || previous.html !== html) {
                const template = document.createElement('template');
                template.innerHTML = html.trim();
                node = template.content.firstElementChild;
                if (previous?.node) {
                    // Keep viewer opener buttons connected across approval-only changes.
                    const selector = '[data-design-image-id], [data-design-pdf-id]';
                    const media = previous.node.querySelector(selector), nextMedia = node.querySelector(selector);
                    if (media && nextMedia && media.getAttribute('data-design-image-id') === nextMedia.getAttribute('data-design-image-id') && media.getAttribute('data-design-pdf-id') === nextMedia.getAttribute('data-design-pdf-id')) {
                        const image = media.querySelector('img'), nextImage = nextMedia.querySelector('img');
                        if (image && nextImage && image.getAttribute('src') === nextImage.getAttribute('src')) nextImage.replaceWith(image);
                        media.replaceChildren(...nextMedia.childNodes);
                        media.setAttribute('aria-label', nextMedia.getAttribute('aria-label'));
                        nextMedia.replaceWith(media);
                    }
                    const previousTile = previous.node;
                    const revealed = node.classList.contains('is-upload-revealing') && previousTile.classList.contains('is-upload-revealed');
                    const appearing = previousTile.classList.contains('is-gallery-added');
                    previousTile.className = node.className;
                    previousTile.dataset.fileId = node.dataset.fileId;
                    if (node.dataset.uploadId) previousTile.dataset.uploadId = node.dataset.uploadId;
                    else delete previousTile.dataset.uploadId;
                    previousTile.replaceChildren(...node.childNodes);
                    if (revealed) previousTile.classList.add('is-upload-revealed');
                    if (appearing) previousTile.classList.add('is-gallery-added');
                    node = previousTile;
                } else if (animateNew.has(Number(node.dataset.fileId)) && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
                    node.classList.add('is-gallery-added');
                    node.addEventListener('animationend', () => node.classList.remove('is-gallery-added'), { once: true });
                }
            }
            nextTiles.set(key, { html, node });
            return node;
        });
        // Insert/move only changed positions; unchanged tiles stay mounted.
        const desired = new Set(nodes);
        for (const child of Array.from(gallery.children)) if (!desired.has(child)) child.remove();
        nodes.forEach((node, index) => {
            if (gallery.children[index] !== node) gallery.insertBefore(node, gallery.children[index] || null);
        });
        if (focused?.isConnected && document.activeElement !== focused) focused.focus({ preventScroll: true });
        state.renderedTiles = nextTiles;
        position3DDesignStatusBadges(gallery);
    }

    function position3DDesignStatusBadges(gallery) {
        // List thumbnails are 48px wide: keep the same readable pill beside them.
        const target = state.viewMode === 'list' ? '.tile-top-actions-overlay' : '.tile-media-container';
        gallery.querySelectorAll('.fabro-design-tile').forEach(tile => {
            const badge = tile.querySelector('.tile-overall-status');
            if (badge.parentElement !== tile.querySelector(target)) tile.querySelector(target).appendChild(badge);
        });
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
            position3DDesignStatusBadges(gallery);
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
        populateDrawerFileSelector();
        window.closeDesignPdfViewer?.();
        const drawer = document.getElementById('designApprovalDrawer');
        const backdrop = document.getElementById('designApprovalDrawerBackdrop');
        if (!drawer || !backdrop) return;
        window.closeDesignImageViewer?.(true);

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
        if (drawer) { window.fabroReviewVoice?.resetWithin(drawer); drawer.classList.remove('is-open'); }
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
        window.fabroReviewVoice?.resetWithin(document.getElementById('designApprovalDrawer'));
        state.selectedFileId = id;

        const selector = document.getElementById('drawerFileSelector');
        if (selector && selector.value != id) {
            selector.value = id;
        }

        const file = state.designFiles.find(f => f.id === id);
        if (!file) return;

        const compare = document.getElementById('drawerCompareDesign');
        if (compare) { compare.dataset.designComparison = String(file.id); compare.disabled = false; }

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
                ? `<button type="button" class="tile-delete-btn btn-danger" onclick="event.stopPropagation(); window.openDelete3DDesignModal(${file.id})" title="Delete uploaded 3D design file" aria-label="Delete ${escapeHtml(file.title)}" style="position:absolute;top:6px;right:6px;"><i class="fas fa-trash-alt"></i></button>`
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
                selector.className = 'drawer-review-role-selector';
                decisionBox.prepend(selector);
            }
            selector.replaceChildren();
            const drafts = new Map();
            let selectedStage = null;
            const remarks = document.getElementById('designDrawerDecisionRemarks');
            const selectStage = role => {
                if (state.isSubmittingDecision || selectedStage === role) return;
                if (selectedStage) drafts.set(selectedStage, {
                    comment: remarks?.value || '',
                    changeType: decisionBox.querySelector('input[name="drawerChangeType"]:checked')?.value || 'minor',
                });
                selectedStage = role;
                const draft = drafts.get(role);
                window.fabroReviewVoice?.resetWithin(decisionBox);
                decisionBox.dataset.activeStage = role;
                const label = document.getElementById('drawerActiveReviewStageLabel');
                if (label) label.textContent = role ? role.toUpperCase() : 'Select reviewer above';
                selector.querySelectorAll('button').forEach(button => {
                    button.setAttribute('aria-pressed', String(button.dataset.stage === role));
                });
                ['radioChangeTypeMinor', 'radioChangeTypeMajor'].forEach(id => {
                    const input = document.getElementById(id);
                    if (input) input.checked = input.value === (draft?.changeType || 'minor');
                });
                if (remarks) remarks.value = draft?.comment || '';
                hideDrawerErrors();
            };
            if (file.can_admin_review) {
                ['cad', 'ed', 'md'].forEach(role => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.dataset.stage = role;
                    button.className = 'drawer-review-stage';
                    button.dataset.reviewStatus = file[role]?.status || 'pending';
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
        window.fabroReviewVoice?.stopPlaybackWithin(timeline);

        if (!history || history.length === 0) {
            timeline.innerHTML = `<div style="font-size:0.75rem;color:var(--fabro-text-muted);text-align:center;padding:0.5rem;">No previous review cycles.</div>`;
            return;
        }

        let html = '';
        history.forEach(item => {
            html += `
                <div class="drawer-history-cycle">
                    <div class="drawer-history-cycle-heading">
                        <strong>Cycle #${item.cycle || 1}</strong>
                        <span>${item.submitted_at || ''}</span>
                    </div>
                    <div class="review-voice-history" data-drawer-voice-cycle="${Number(item.cycle) || 1}"></div>
                    <div class="drawer-history-statuses">
                        <span data-review-status="${item.cad_status}">CAD: <strong>${reviewStatusLabel(item.cad_status)}</strong></span>
                        <span data-review-status="${item.ed_status}">ED: <strong>${reviewStatusLabel(item.ed_status)}</strong></span>
                        <span data-review-status="${item.md_status}">MD: <strong>${reviewStatusLabel(item.md_status)}</strong></span>
                    </div>
                </div>
            `;
        });
        timeline.innerHTML = html;
        history.forEach(item => {
            const host = timeline.querySelector(`[data-drawer-voice-cycle="${Number(item.cycle) || 1}"]`);
            if (host) window.fabroReviewVoice?.appendBubbles(host, item.voice_notes || []);
        });
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
        const recorderRoot = decisionBox?.querySelector('[data-review-voice]');
        if (recorderRoot && !window.fabroReviewVoice?.ready(recorderRoot)) return;
        const voiceFile = recorderRoot && window.fabroReviewVoice?.file(recorderRoot);
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

            const headers = { 'X-CSRFToken': getCsrfToken() };
            let body;
            if (voiceFile) {
                body = new FormData();
                Object.entries(payload).forEach(([key, value]) => body.append(key, value));
                body.append('voice_note', voiceFile);
            } else {
                headers['Content-Type'] = 'application/json';
                body = JSON.stringify(payload);
            }
            const resp = await fetch(endpoint, { method: 'POST', headers, body });

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

    function openReferenceFile(image, source) {
        if (!image) return;

        const ext = String(image.file_ext || '').replace(/^\./, '').toLowerCase();
        const canCompare = ['image', 'pdf'].includes(image.file_type) || ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'pdf'].includes(ext);

        if (canCompare) {
            window.openDesignComparison(image.id, source);
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
    window.retry3DDesignUpload = retry3DDesignUpload;
    window.filter3DDesignFiles = filter3DDesignFiles;
    window.sort3DDesignFiles = sort3DDesignFiles;
    window.switch3DFilesView = switch3DFilesView;
    window.toggleApprovalDrawer = toggleApprovalDrawer;
    window.openApprovalDrawer = openApprovalDrawer;
    window.open3DDesignPreview = open3DDesignPreview;
    window.closeApprovalDrawer = closeApprovalDrawer;
    window.selectDrawerFile = selectDrawerFile;
    window.submitDrawerDecision = submitDrawerDecision;
    window.scrollRefImages = scrollRefImages;
    window.toggleLegacyFoldersView = toggleLegacyFoldersView;
    window.previewImageLightbox = previewImageLightbox;
    window.load3DDesignWorkspace = load3DDesignWorkspace;
    window.openDelete3DDesignModal = openDelete3DDesignModal;
    window.closeDelete3DDesignModal = closeDelete3DDesignModal;
    window.confirmDelete3DDesignFile = confirmDelete3DDesignFile;
    window.delete3DDesignFile = delete3DDesignFile;

    // Global listeners are replaced when this page asset is loaded again by HTMX.
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeApprovalDrawer();
            closeDelete3DDesignModal();
        }
    }, { signal: eventController.signal });

    function initialize3DWorkspace() {
        initializeGallerySync();
        const track = document.getElementById('refImagesScrollTrack');
        if (track && track !== referenceTrack) {
            referenceTrack = track;
            track.addEventListener('scroll', updateRefScrollArrows, { passive: true, signal: eventController.signal });
            track.addEventListener('click', (event) => {
                const card = event.target.closest('.ref-image-card');
                if (!card) return;
                const image = state.referenceImages[Number(card.dataset.refIndex)];
                if (image) openReferenceFile(image, card);
            }, { signal: eventController.signal });
            track.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                const card = event.target.closest('.ref-image-card');
                if (!card) return;
                if (event.target.closest('button, a, input')) return;
                event.preventDefault();
                const image = state.referenceImages[Number(card.dataset.refIndex)];
                if (image) openReferenceFile(image, card);
            }, { signal: eventController.signal });
        }
    }

    document.addEventListener('DOMContentLoaded', initialize3DWorkspace, { once: true, signal: eventController.signal });
    document.addEventListener('fabro:page-ready', initialize3DWorkspace, { signal: eventController.signal });
    document.addEventListener('fabro:before-page-swap', () => {
        eventController.abort();
        state.loadRequestId++;
        referenceTrack = null;
        closeApprovalDrawer();
        closeDelete3DDesignModal();
    }, { signal: eventController.signal });
    if (document.readyState !== 'loading') initialize3DWorkspace();
    window.__fabro3DDispose = () => eventController.abort();

})();
