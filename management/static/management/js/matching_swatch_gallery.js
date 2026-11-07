// Private matching-photo drafts, real per-request progress and retained retries.
(function () {
    const extensions = /\.(jpe?g|png|webp|heic|heif)$/i;
    const limit = 10 * 1024 * 1024;
    const node = (tag, cls, text) => {
        const result = document.createElement(tag); result.className = cls || '';
        if (text !== undefined) result.textContent = text;
        return result;
    };
    const key = () => crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(24)), n => n.toString(16).padStart(2, '0')).join('');
    function privateUrl(value) {
        const url = new URL(value, location.origin);
        if (url.origin !== location.origin || !/^\/(?:picked-colors\/\d+\/(?:photos\/\d+\/file\/|swatch\/)|color-selections\/\d+\/photos\/\d+\/file\/)$/.test(url.pathname)) throw Error('Invalid private photo URL.');
        return url.href;
    }

    class MatchingSwatchGallery {
        constructor(root, options) {
            this.root = root; this.options = options; this.scope = options.scope;
            this.grid = root.querySelector('[data-swatch-grid]'); this.input = root.querySelector('input[type=file]');
            this.add = root.querySelector('[data-swatch-add]'); this.status = root.querySelector('[data-swatch-status]');
            this.entries = []; this.owner = null; this.vehicleId = null; this.version = 0; this.busy = false; this.readAllowed = true;
            this.drafts = new Map(); this.dragDepth = 0; this.viewerIndex = 0;
            this.viewer = document.getElementById('matchingSwatchViewer');
            this.scope.listen(this.add, 'click', () => this.input.click());
            this.scope.listen(this.input, 'change', () => { this.enqueue(this.input.files); this.input.value = ''; });
            this.scope.listen(root, 'dragenter', event => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); this.dragDepth++; root.classList.add('is-dragging'); } });
            this.scope.listen(root, 'dragover', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
            this.scope.listen(root, 'dragleave', () => { if (--this.dragDepth <= 0) root.classList.remove('is-dragging'); });
            this.scope.listen(root, 'drop', event => { event.preventDefault(); this.dragDepth = 0; root.classList.remove('is-dragging'); this.enqueue(event.dataTransfer.files); });
            for (const name of ['dragover', 'drop']) this.scope.listen(document, name, event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
            this.scope.listen(window, 'beforeunload', event => { if (this.hasPendingAnywhere()) { event.preventDefault(); event.returnValue = ''; } });
            const beforeSwap = event => {
                if (event.detail?.target?.contains(root) && this.hasPendingAnywhere() && !this.leaveApproved) {
                    this.leaveApproved = confirm('Leave this page? Photos not yet uploaded are only stored on this device.');
                    if (!this.leaveApproved) event.preventDefault();
                }
            };
            this.scope.listen(document, 'htmx:beforeRequest', beforeSwap);
            this.scope.listen(document, 'htmx:beforeSwap', beforeSwap);
            this.scope.listen(document, 'htmx:afterRequest', () => { if (root.isConnected) this.leaveApproved = false; });
            this.scope.listen(this.viewer, 'cancel', event => { event.preventDefault(); this.closePreview(); });
            this.scope.listen(this.viewer.querySelector('[data-swatch-close]'), 'click', () => this.closePreview());
            this.scope.listen(this.viewer.querySelector('[data-swatch-prev]'), 'click', () => this.navigate(-1));
            this.scope.listen(this.viewer.querySelector('[data-swatch-next]'), 'click', () => this.navigate(1));
            this.scope.listen(this.viewer, 'keydown', event => { if (['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); this.navigate(event.key === 'ArrowLeft' ? -1 : 1); } });
            this.scope.onCleanup(() => {
                this.version++; this.closePreview();
                const all = new Set([...this.entries, ...[...this.drafts.values()].flatMap(draft => draft.entries)]);
                all.forEach(entry => { entry.cancelled=true; entry.xhr?.abort(); this.release(entry); }); this.drafts.clear();
            });
        }
        allowed() {
            return this.owner ? this.owner.can_edit && (window.fabroActivityAllowed?.('picked_colors.edit_own') || window.fabroActivityAllowed?.('picked_colors.edit_all'))
                : window.fabroActivityAllowed?.('picked_colors.add') === true;
        }
        canSend(entry) { return this.allowed() || entry.reserved && window.fabroActivityAllowed?.('picked_colors.add') === true; }
        hasPending() { return this.entries.some(entry => entry.file && entry.state !== 'saved'); }
        hasPendingAnywhere() { return this.hasPending() || [...this.drafts.values()].some(draft => draft.entries.some(entry => entry.file && entry.state !== 'saved')); }
        contextKey(vehicle = this.vehicleId, owner = this.owner) { return `${vehicle}:${owner?.id || 'new'}`; }
        release(entry) { if (entry.blob) { URL.revokeObjectURL(entry.blob); entry.blob = null; } }
        setContext(vehicleId, owner = null) {
            this.closePreview();
            if (this.vehicleId) this.drafts.set(this.contextKey(), {entries: this.entries, owner: this.owner});
            this.version++; this.entries.forEach(entry => { if (entry.xhr) { entry.state = 'failed'; entry.error = 'Upload interrupted. Retry this photo.'; entry.xhr.abort(); } });
            this.vehicleId = vehicleId; this.owner = owner; this.busy = false; this.readAllowed = true;
            this.entries = this.drafts.get(this.contextKey())?.entries || [];
            if (owner) this.merge(owner.swatch_photos || []);
            this.render();
            if (owner) this.run();
        }
        adopt(owner) {
            const previous = this.contextKey();
            this.owner = owner;
            this.drafts.delete(previous);
            this.drafts.set(this.contextKey(), {entries:this.entries, owner});
            this.merge(owner.swatch_photos || []); this.render();
        }
        discard() {
            this.closePreview(); this.entries.forEach(entry => { entry.cancelled=true; entry.xhr?.abort(); this.release(entry); });
            this.drafts.delete(this.contextKey()); this.version++; this.entries = []; this.owner = null; this.busy = false; this.readAllowed = true; this.render();
        }
        merge(photos) {
            const ids = new Set(photos.map(photo => photo.id));
            this.entries = this.entries.filter(entry => !entry.photo || ids.has(entry.photo.id) || entry.xhr);
            for (const photo of photos) {
                const existing = this.entries.find(entry => entry.photo?.id === photo.id);
                if (existing) existing.photo = photo;
                else this.entries.push({id:key(), photo, state:'saved', name:photo.filename});
            }
            this.drafts.set(this.contextKey(), {entries:this.entries, owner:this.owner});
        }
        refreshAccess(owner) { if (owner && this.owner?.id === owner.id) { this.owner = owner; if (!this.busy && !this.hasPending()) this.merge(owner.swatch_photos || []); } this.render(); }
        setReadAccess(value) { this.readAllowed = value; if (!value) this.closePreview(); this.render(); }
        async enqueue(files) {
            if (!this.vehicleId || !this.allowed()) { this.options.feedback('Adding matching photos is not permitted.'); return; }
            const version = this.version, draftEntries = this.entries;
            for (const file of Array.from(files || [])) {
                const fingerprint = `${file.name}:${file.size}:${file.lastModified}`;
                if (this.entries.some(entry => entry.fingerprint === fingerprint)) continue;
                const entry = {id:key(), file, fingerprint, name:file.name, state:'preparing', percent:0};
                const extension = file.name.split('.').pop().toLowerCase();
                const mime = {jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',webp:'image/webp',heic:'image/heic',heif:'image/heif'}[extension];
                if (mime && file.size > 0 && file.size <= limit) entry.blob = URL.createObjectURL(new Blob([file], {type:mime}));
                this.entries.push(entry); this.options.dirty(); this.render();
                entry.prepared = (async () => {
                    if (!extensions.test(file.name) || !file.size || file.size > limit) {
                        entry.invalid = true; entry.state = 'failed'; entry.error = 'Use JPG, PNG, WebP, HEIC or HEIF, at most 10 MB per photo.';
                    } else {
                        try {
                            entry.sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), byte => byte.toString(16).padStart(2, '0')).join('');
                            if (entry.cancelled) return;
                            const entries = version === this.version ? this.entries : draftEntries;
                            const duplicate = entries.find(other => other !== entry && !other.cancelled && other.sha256 === entry.sha256);
                            if (duplicate) { entry.cancelled=true; entries.splice(entries.indexOf(entry),1); this.release(entry); }
                            else entry.state = 'queued';
                        } catch (error) { entry.state = 'failed'; entry.invalid = true; entry.error = 'Unable to prepare this photo in the current browser.'; }
                    }
                    if (version === this.version) { this.render(); if (this.owner) this.run(); }
                })();
            }
            this.drafts.set(this.contextKey(), {entries:this.entries, owner:this.owner});
        }
        async plans() {
            await Promise.all(this.entries.map(entry => entry.prepared));
            if (this.entries.some(entry => entry.invalid)) throw Error('Remove invalid photos before saving the color selection.');
            return this.entries.filter(entry => entry.file && !entry.photo).map(entry => {
                entry.reserved = !this.owner;
                return {upload_key:entry.id, sha256:entry.sha256, filename:entry.name, file_size:entry.file.size};
            });
        }
        request(entry, version) {
            const owner = this.owner, vehicle = this.vehicleId;
            return new Promise((resolve, reject) => {
                const xhr = entry.xhr = new XMLHttpRequest();
                xhr.open('POST', `/api/picked-colors/${owner.id}/photos/upload/`); xhr.responseType = 'json'; xhr.timeout = 120000;
                xhr.setRequestHeader('X-CSRFToken', this.options.csrf());
                xhr.upload.onprogress = event => { if (version !== this.version) return; if (event.lengthComputable && event.total > 0) { entry.known = true; entry.percent = Math.min(100, Math.floor(event.loaded / event.total * 100)); } this.progress(entry); };
                xhr.upload.onload = () => { if (version === this.version) { entry.percent = 100; entry.known = true; entry.state = 'processing'; this.progress(entry); } };
                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300 && xhr.response?.status === 'success' && xhr.response.photo?.id) resolve(xhr.response.photo);
                    else reject(Error(xhr.response?.message || 'Photo could not be saved. Retry this upload.'));
                };
                xhr.onerror = xhr.ontimeout = xhr.onabort = () => reject(Error('Upload interrupted. Retry this photo.'));
                const body = new FormData(); body.set('vehicle_id', vehicle); body.set('upload_key', entry.id); body.set('photo', entry.file);
                xhr.send(body);
            });
        }
        async run() {
            if (this.busy || !this.owner || this.scope.signal.aborted) return;
            const version = this.version; this.busy = true; this.options.state();
            try {
                for (let entry; (entry = this.entries.find(item => item.state === 'queued' && item.file));) {
                    if (version !== this.version) return;
                    if (!this.canSend(entry)) { entry.state = 'failed'; entry.error = 'Upload access changed. Your local photo is preserved.'; this.render(); continue; }
                    entry.state = 'uploading'; entry.percent = 0; entry.error = ''; this.render();
                    try {
                        const photo = await this.request(entry, version);
                        if (version !== this.version) return;
                        privateUrl(photo.url);
                        const duplicate = this.entries.find(other => other !== entry && other.photo?.id === photo.id);
                        if (duplicate) this.entries = this.entries.filter(other => other !== entry);
                        else { entry.photo = photo; entry.state = 'saved'; entry.file = null; }
                        this.render(); if (this.viewer.open) this.showPreview(); this.release(entry);
                    } catch (error) {
                        if (version !== this.version) return;
                        entry.state = 'failed'; entry.error = error.message; this.render();
                    } finally { entry.xhr = null; }
                }
            } finally {
                if (version === this.version) { this.busy = false; this.render(); this.options.state(); this.options.complete(); }
            }
        }
        async remove(entry) {
            if (!entry.photo && !entry.xhr && (!entry.reserved || !this.owner)) {
                entry.cancelled=true;
                this.entries = this.entries.filter(other => other !== entry); this.release(entry); this.options.dirty(); this.render(); return;
            }
            if (!this.owner) return;
            if (entry.photo && !entry.photo.can_delete) return;
            if (entry.photo && !confirm('Remove this matching photo? Historical approval media will be retained.')) return;
            entry.xhr?.abort(); entry.removing = true; this.render();
            const owner = this.owner, vehicle = this.vehicleId, version = this.version;
            try {
                const body = new FormData(); body.set('vehicle_id', vehicle);
                const path = entry.photo ? `photos/${entry.photo.id}/remove/` : 'photos/cancel/';
                if (!entry.photo) body.set('upload_key', entry.id);
                const response = await fetch(`/api/picked-colors/${owner.id}/${path}`, {method:'POST', headers:{'X-CSRFToken':this.options.csrf()}, body, signal:this.scope.signal});
                if (!response.ok) throw Error('Removing this photo is not permitted or unavailable.');
                const data = await response.json();
                if (version !== this.version) return;
                this.closePreview(); this.entries = this.entries.filter(other => other !== entry); this.release(entry); this.merge(data.photos); this.render(); this.options.complete();
            } catch (error) { if (version === this.version) { entry.removing = false; entry.state = entry.photo ? 'saved' : 'failed'; entry.error = error.message; this.options.feedback(error.message); this.render(); } }
        }
        progress(entry) {
            const tile = this.grid.querySelector(`[data-upload-key="${entry.id}"]`); if (!tile) return;
            const label = tile.querySelector('[data-progress-label]'), bar = tile.querySelector('[role=progressbar]');
            if (label) label.textContent = entry.state === 'processing' ? '100% · Processing…' : entry.known ? `${entry.percent}%` : 'Uploading…';
            if (bar) { bar.style.width = `${entry.percent}%`; if (entry.known) bar.setAttribute('aria-valuenow', entry.percent); }
        }
        render() {
            if (this.vehicleId) this.drafts.set(this.contextKey(), {entries:this.entries, owner:this.owner});
            this.root.hidden = !this.readAllowed || window.fabroActivityAllowed?.('picked_colors.view') !== true;
            if (this.root.hidden) this.closePreview();
            this.grid.replaceChildren(); this.add.disabled = !this.vehicleId || !this.allowed();
            this.status.textContent = this.owner ? `Photos for saved selection #${this.owner.id}` : this.entries.length ? 'Photos stay on this device until you save the color selection.' : 'JPG, PNG, WebP, HEIC, HEIF · 10 MB each';
            for (const entry of this.entries) {
                const tile = node('article', `swatch-photo-tile ${entry.state === 'saved' ? '' : 'is-pending'} ${entry.state === 'failed' ? 'is-failed' : ''}`);
                tile.dataset.uploadKey = entry.id; if (entry.photo) tile.dataset.photoId = entry.photo.id;
                const preview = node('button', 'swatch-photo-open'); preview.type = 'button'; preview.title = entry.name; preview.setAttribute('aria-label', `Enlarge ${entry.name}`);
                preview.disabled = entry.invalid === true;
                const fallback = node('span', 'swatch-photo-fallback', /\.hei[cf]$/i.test(entry.name) ? 'HEIC / HEIF' : 'Photo');
                const image = node('img'); image.alt = entry.name; image.loading = 'lazy';
                if (entry.photo || entry.blob) image.src = entry.photo ? privateUrl(entry.photo.url) : entry.blob;
                image.onerror = () => { image.hidden = true; fallback.hidden = false; };
                fallback.hidden = true; preview.append(image, fallback); preview.onclick = () => this.openPreview(entry, preview); tile.append(preview);
                if (entry.state !== 'saved') {
                    const overlay = node('div', `swatch-photo-overlay ${['preparing','queued','processing','uploading'].includes(entry.state) ? 'has-skeleton' : ''}`);
                    const label = node('span', '', entry.state === 'preparing' ? 'Preparing…' : entry.state === 'queued' ? this.owner ? 'Queued' : 'Save color to upload' : entry.error || 'Uploading…'); label.dataset.progressLabel = '';
                    overlay.append(label);
                    if (['uploading','processing'].includes(entry.state)) { const track = node('div','swatch-photo-progress-track'), bar = node('div','swatch-photo-progress'); bar.setAttribute('role','progressbar'); bar.setAttribute('aria-label',`Upload ${entry.name}`); bar.setAttribute('aria-valuemin','0'); bar.setAttribute('aria-valuemax','100'); track.append(bar); overlay.append(track); }
                    if (entry.state === 'failed' && !entry.invalid) { const retry = node('button','swatch-photo-retry','Retry'); retry.type='button'; retry.title=entry.error; retry.disabled = this.busy || !this.canSend(entry); retry.onclick=()=>{ entry.state='queued'; this.render(); this.run(); }; overlay.append(retry); }
                    tile.append(overlay);
                }
                if (!entry.photo || entry.photo.can_delete && this.allowed()) { const remove = node('button','swatch-photo-remove','×'); remove.type='button'; remove.title=`Remove ${entry.name}`; remove.setAttribute('aria-label',remove.title); remove.disabled=entry.removing === true; remove.onclick=event=>{event.stopPropagation();this.remove(entry);};tile.append(remove); }
                this.grid.append(tile); if (['uploading','processing'].includes(entry.state)) this.progress(entry);
            }
        }
        openPreview(entry, trigger) {
            this.viewerIndex = this.previewEntries().indexOf(entry); if (this.viewerIndex < 0) return;
            this.previewEntryKey = entry.id;
            this.trigger = trigger; this.showPreview();
            this.scrollStyles = [document.body, document.documentElement].map(el=>[el, el.style.getPropertyValue('overflow'), el.style.getPropertyPriority('overflow')]);
            this.scrollStyles.forEach(([el])=>el.style.setProperty('overflow','hidden','important'));
            this.viewer.showModal(); this.viewer.querySelector('[data-swatch-close]').focus();
        }
        showPreview() {
            const entries = this.previewEntries();
            if (!entries.length) { this.closePreview(); return; }
            this.viewerIndex = (this.viewerIndex + entries.length) % entries.length;
            const entry = entries[this.viewerIndex], host = this.viewer.querySelector('[data-swatch-media]'); host.replaceChildren();
            const image=node('img'); image.alt=entry.name; image.src=entry.photo ? privateUrl(entry.photo.url) : entry.blob;
            image.onerror=()=>{ image.hidden=true; const text=node('p','','Preview unavailable in this browser. '), link=node('a','','Open original photo');link.href=image.src;link.target='_blank';link.rel='noopener';text.append(link);host.append(text); };
            host.append(image); this.viewer.querySelector('[data-swatch-caption]').textContent = `${this.viewerIndex+1} / ${entries.length} · ${entry.name}`;
            this.viewer.querySelectorAll('[data-swatch-prev],[data-swatch-next]').forEach(button=>{button.disabled=entries.length<2;});
        }
        previewEntries() { return this.entries.filter(entry=>!entry.invalid && (entry.photo || entry.blob)); }
        navigate(offset) { this.viewerIndex += offset; this.showPreview(); }
        closePreview() {
            if (this.viewer.open) this.viewer.close();
            this.scrollStyles?.forEach(([el,value,priority])=>{if(value)el.style.setProperty('overflow',value,priority);else el.style.removeProperty('overflow');});
            this.scrollStyles=null; this.viewer.querySelector('[data-swatch-media]').replaceChildren();
            const focus = this.trigger?.isConnected ? this.trigger : this.grid.querySelector(`[data-upload-key="${this.previewEntryKey}"] .swatch-photo-open`);
            if (focus?.isConnected && !this.root.hidden && this.readAllowed) focus.focus();
            this.trigger=null; this.previewEntryKey=null;
        }
    }
    window.FabroMatchingSwatchGallery = MatchingSwatchGallery;
})();
