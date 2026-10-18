// FABRO - Color Approval Slide-In Drawer Controller
(function() {
    let activeSelectionId = null;
    let lastApprovalDrawerTrigger = null;
    let isRemarksDirty = false;

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el && el.value) return el.value;
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function openColorApprovalDrawer(selectionId, triggerEl) {
        if (!selectionId) return;
        activeSelectionId = selectionId;
        lastApprovalDrawerTrigger = triggerEl || document.activeElement;
        isRemarksDirty = false;

        const backdrop = document.getElementById('fabroColorApprovalBackdrop');
        const drawer = document.getElementById('fabroColorApprovalDrawer');
        const loading = document.getElementById('drawerLoadingState');
        const content = document.getElementById('drawerContent');

        if (!drawer || !backdrop) return;

        // Reset drawer form state
        const remarksInput = document.getElementById('drawerDecisionRemarks');
        if (remarksInput) {
            remarksInput.value = '';
            remarksInput.style.borderColor = '';
        }
        const decisionInput = document.getElementById('drawerSelectedDecision');
        if (decisionInput) decisionInput.value = '';
        const errorBox = document.getElementById('drawerDecisionError');
        if (errorBox) { errorBox.style.display = 'none'; errorBox.textContent = ''; }
        const btnApprove = document.getElementById('btnDecisionApprove');
        const btnReject = document.getElementById('btnDecisionReject');
        if (btnApprove) btnApprove.style.boxShadow = '';
        if (btnReject) btnReject.style.boxShadow = '';

        if (loading) loading.style.display = 'block';
        if (content) content.style.display = 'none';

        // Open drawer with GPU transform
        backdrop.classList.add('is-open');
        backdrop.setAttribute('aria-hidden', 'false');
        drawer.classList.add('is-open');
        drawer.setAttribute('aria-hidden', 'false');
        document.body.classList.add('fabro-drawer-open');

        // Focus trap initial focus
        drawer.focus();

        // Fetch details
        fetch(`/api/pattern-color-selection/details/?selection_id=${selectionId}`)
            .then(r => r.json())
            .then(res => {
                if (res.status === 'success' && res.selection) {
                    renderDrawerData(res.selection);
                    if (loading) loading.style.display = 'none';
                    if (content) content.style.display = 'flex';
                } else {
                    if (loading) loading.innerHTML = `<div style="color:#ef4444;"><i class="fas fa-exclamation-triangle"></i> ${res.message || 'Error loading details.'}</div>`;
                }
            })
            .catch(err => {
                if (loading) loading.innerHTML = `<div style="color:#ef4444;"><i class="fas fa-exclamation-triangle"></i> Network error loading details.</div>`;
            });
    }

    function renderDrawerData(data) {
        // Vehicle header
        const serialPill = document.getElementById('drawerSerialPill');
        if (serialPill) {
            const sn = data.vehicle ? (data.vehicle.serial_number || '') : '';
            serialPill.textContent = sn.startsWith('#') ? sn : (sn ? `#${sn}` : '#');
        }
        const vehicleName = document.getElementById('drawerVehicleName');
        if (vehicleName) {
            const v = data.vehicle || {};
            const parts = [v.brand, v.model, v.sub_model, v.year_range].filter(Boolean);
            vehicleName.textContent = parts.join(' ') || 'Vehicle Details';
        }

        // Status banner
        const statusText = document.getElementById('drawerStatusText');
        const statusBadge = document.getElementById('drawerStatusBadge');
        if (statusText) statusText.textContent = data.status_display || data.status;
        if (statusBadge) {
            const st = data.status || 'pending';
            statusBadge.className = 'stepper-badge ' + (st === 'approved' ? 'approved' : (st === 'rejected' ? 'rejected' : 'pending'));
            statusBadge.innerHTML = st === 'approved' ? '<i class="fas fa-check"></i> Approved' : (st === 'rejected' ? '<i class="fas fa-times"></i> Rejected' : '<i class="fas fa-clock"></i> Pending Approval');
        }

        // Tone type
        const toneBadge = document.getElementById('drawerToneTypeBadge');
        if (toneBadge) {
            toneBadge.textContent = data.is_dual ? 'Dual Tone' : 'Single Tone';
        }

        // Inner color
        const inner = data.inner_color || {};
        const innerSwatch = document.getElementById('drawerInnerSwatch');
        if (innerSwatch) innerSwatch.style.backgroundColor = inner.hex || '#000000';
        const innerName = document.getElementById('drawerInnerName');
        if (innerName) innerName.textContent = inner.name || 'Inner Color';
        const innerHex = document.getElementById('drawerInnerHex');
        if (innerHex) innerHex.textContent = inner.hex || '—';
        const innerPantone = document.getElementById('drawerInnerPantone');
        const innerPantoneWrap = document.getElementById('drawerInnerPantoneWrap');
        if (innerPantone) {
            if (inner.pantone) {
                innerPantone.textContent = inner.pantone;
                if (innerPantoneWrap) innerPantoneWrap.style.display = 'block';
            } else {
                if (innerPantoneWrap) innerPantoneWrap.style.display = 'none';
            }
        }

        // Outer color (dual tone)
        const outerBlock = document.getElementById('drawerOuterColorBlock');
        if (outerBlock) {
            if (data.is_dual && data.outer_color) {
                outerBlock.style.display = 'flex';
                const outer = data.outer_color;
                const outerSwatch = document.getElementById('drawerOuterSwatch');
                if (outerSwatch) outerSwatch.style.backgroundColor = outer.hex || '#000000';
                const outerName = document.getElementById('drawerOuterName');
                if (outerName) outerName.textContent = outer.name || 'Outer Color';
                const outerHex = document.getElementById('drawerOuterHex');
                if (outerHex) outerHex.textContent = outer.hex || '—';
                const outerPantone = document.getElementById('drawerOuterPantone');
                const outerPantoneWrap = document.getElementById('drawerOuterPantoneWrap');
                if (outerPantone) {
                    if (outer.pantone) {
                        outerPantone.textContent = outer.pantone;
                        if (outerPantoneWrap) outerPantoneWrap.style.display = 'block';
                    } else {
                        if (outerPantoneWrap) outerPantoneWrap.style.display = 'none';
                    }
                }
            } else {
                outerBlock.style.display = 'none';
            }
        }

        // Swatch photo
        const swatchSec = document.getElementById('drawerSwatchPhotoSection');
        const swatchImg = document.getElementById('drawerSwatchPhotoImg');
        const swatchLink = document.getElementById('drawerSwatchPhotoLink');
        if (swatchSec && swatchImg && swatchLink) {
            if (data.swatch_url) {
                swatchSec.style.display = 'block';
                swatchImg.src = data.swatch_url;
                swatchLink.href = data.swatch_url;
            } else {
                swatchSec.style.display = 'none';
            }
        }

        // Meta info
        const submittedBy = document.getElementById('drawerSubmittedBy');
        if (submittedBy) submittedBy.textContent = (data.submitted_by || 'Unknown') + ' (Measurements)';
        const submittedAt = document.getElementById('drawerSubmittedAt');
        if (submittedAt) submittedAt.textContent = data.submitted_at || '';

        // Decision matrix for MD, ED, CAD (stepper timeline)
        const depts = ['MD', 'ED', 'CAD'];
        let userCanDecideDept = null;

        depts.forEach(dept => {
            const dec = (data.decisions && data.decisions[dept]) || {};
            const statusEl = document.getElementById(`drawerDeptStatus_${dept}`);
            const dotEl = document.getElementById(`drawerDeptDot_${dept}`);
            const dateEl = document.getElementById(`drawerDeptDate_${dept}`);
            const remarksBox = document.getElementById(`drawerDeptRemarksBox_${dept}`);

            const st = dec.status || 'pending';

            if (statusEl) {
                statusEl.className = 'stepper-badge ' + (st === 'approved' ? 'approved' : (st === 'rejected' ? 'rejected' : 'pending'));
                statusEl.innerHTML = st === 'approved' ? '<i class="fas fa-check"></i> Approved' : (st === 'rejected' ? '<i class="fas fa-times"></i> Rejected' : '<i class="fas fa-clock"></i> Pending');
            }
            if (dotEl) {
                dotEl.className = 'stepper-node-dot ' + (st === 'approved' ? 'approved' : (st === 'rejected' ? 'rejected' : 'pending'));
            }
            if (dateEl) {
                dateEl.textContent = dec.decided_at || '—';
            }
            if (remarksBox) {
                if (dec.remarks) {
                    remarksBox.innerHTML = `<span style="color:#e2e8f0;">${escapeHtml(dec.remarks)}</span>`;
                } else {
                    remarksBox.innerHTML = `<span style="color:var(--fabro-text-muted); font-style:italic;">No remarks yet.</span>`;
                }
            }

            if (dec.can_decide) {
                userCanDecideDept = dept;
            }
        });

        // Approver action section
        const actionCard = document.getElementById('drawerApproverActionCard');
        const userDeptLabel = document.getElementById('drawerUserDeptLabel');
        if (actionCard) {
            if (userCanDecideDept && data.status === 'pending') {
                actionCard.style.display = 'block';
                if (userDeptLabel) userDeptLabel.textContent = userCanDecideDept;
            } else {
                actionCard.style.display = 'none';
            }
        }
    }

    function closeColorApprovalDrawer() {
        if (isRemarksDirty) {
            const confirmClose = window.confirm('You have unsaved remarks. Are you sure you want to discard them and close?');
            if (!confirmClose) return;
        }

        const backdrop = document.getElementById('fabroColorApprovalBackdrop');
        const drawer = document.getElementById('fabroColorApprovalDrawer');
        if (!drawer || !backdrop) return;

        backdrop.classList.remove('is-open');
        backdrop.setAttribute('aria-hidden', 'true');
        drawer.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('fabro-drawer-open');

        isRemarksDirty = false;
        activeSelectionId = null;

        if (lastApprovalDrawerTrigger && typeof lastApprovalDrawerTrigger.focus === 'function') {
            lastApprovalDrawerTrigger.focus();
        }
    }

    function handleColorApprovalBackdropClick(e) {
        if (e.target === document.getElementById('fabroColorApprovalBackdrop')) {
            closeColorApprovalDrawer();
        }
    }

    function setDrawerDecisionChoice(choice) {
        const input = document.getElementById('drawerSelectedDecision');
        const btnApprove = document.getElementById('btnDecisionApprove');
        const btnReject = document.getElementById('btnDecisionReject');
        const reqStar = document.getElementById('drawerRemarksReqStar');
        const errorBox = document.getElementById('drawerDecisionError');
        if (errorBox) errorBox.style.display = 'none';

        if (input) input.value = choice;

        if (choice === 'approved') {
            if (btnApprove) btnApprove.style.boxShadow = '0 0 0 2px #22c55e, inset 0 0 8px rgba(34, 197, 94, 0.4)';
            if (btnReject) btnReject.style.boxShadow = '';
            if (reqStar) reqStar.style.display = 'none';
        } else if (choice === 'rejected') {
            if (btnReject) btnReject.style.boxShadow = '0 0 0 2px #ef4444, inset 0 0 8px rgba(239, 68, 68, 0.4)';
            if (btnApprove) btnApprove.style.boxShadow = '';
            if (reqStar) reqStar.style.display = 'inline';
        }
    }

    function handleDrawerRemarksInput(el) {
        isRemarksDirty = (el.value.trim().length > 0);
        const count = document.getElementById('drawerRemarksCharCount');
        if (count) count.textContent = `${el.value.length}/1000`;
        const errorBox = document.getElementById('drawerDecisionError');
        if (errorBox) errorBox.style.display = 'none';
    }

    function submitDrawerDecision() {
        if (!activeSelectionId) return;

        const decision = (document.getElementById('drawerSelectedDecision')?.value || '').trim();
        const remarks = (document.getElementById('drawerDecisionRemarks')?.value || '').trim();
        const errorBox = document.getElementById('drawerDecisionError');
        const btnSubmit = document.getElementById('btnSubmitDrawerDecision');

        if (!decision || (decision !== 'approved' && decision !== 'rejected')) {
            if (errorBox) {
                errorBox.textContent = 'Please choose either Approve or Reject.';
                errorBox.style.display = 'block';
            }
            return;
        }

        if (decision === 'rejected' && !remarks) {
            if (errorBox) {
                errorBox.textContent = 'A remark explaining the reason for rejection is mandatory.';
                errorBox.style.display = 'block';
            }
            const remarksInput = document.getElementById('drawerDecisionRemarks');
            if (remarksInput) {
                remarksInput.style.borderColor = '#ef4444';
                remarksInput.focus();
            }
            return;
        }

        if (btnSubmit) {
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Submitting...';
        }

        fetch('/api/pattern-color-selection/decide/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCsrfToken(),
            },
            body: new URLSearchParams({
                selection_id: activeSelectionId,
                decision: decision,
                remarks: remarks,
            })
        })
        .then(r => r.json())
        .then(res => {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Decision';
            }

            if (res.status === 'success') {
                isRemarksDirty = false;
                // Refresh drawer details
                openColorApprovalDrawer(activeSelectionId, lastApprovalDrawerTrigger);

                // Notify parent view if hooks exist
                if (typeof window.onColorDecisionSubmitted === 'function') {
                    window.onColorDecisionSubmitted(activeSelectionId, res);
                }
            } else {
                if (errorBox) {
                    errorBox.textContent = res.message || 'Error submitting decision.';
                    errorBox.style.display = 'block';
                }
            }
        })
        .catch(err => {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Decision';
            }
            if (errorBox) {
                errorBox.textContent = 'Network error submitting decision.';
                errorBox.style.display = 'block';
            }
        });
    }

    function escapeHtml(text) {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return String(text || '').replace(/[&<>"']/g, m => map[m]);
    }

    // Escape and Tab focus trapping for drawer
    document.addEventListener('keydown', function(e) {
        const drawer = document.getElementById('fabroColorApprovalDrawer');
        if (!drawer || !drawer.classList.contains('is-open')) return;

        if (e.key === 'Escape') {
            e.preventDefault();
            closeColorApprovalDrawer();
            return;
        }

        if (e.key === 'Tab') {
            const focusables = Array.from(drawer.querySelectorAll('button, [href], input, select, textarea, [tabindex="0"]'))
                .filter(el => !el.disabled && el.offsetParent !== null);
            if (focusables.length === 0) return;
            const first = focusables[0];
            const last = focusables[focusables.length - 1];

            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });

    // Expose to window
    window.openColorApprovalDrawer = openColorApprovalDrawer;
    window.closeColorApprovalDrawer = closeColorApprovalDrawer;
    window.handleColorApprovalBackdropClick = handleColorApprovalBackdropClick;
    window.setDrawerDecisionChoice = setDrawerDecisionChoice;
    window.handleDrawerRemarksInput = handleDrawerRemarksInput;
    window.submitDrawerDecision = submitDrawerDecision;
})();
