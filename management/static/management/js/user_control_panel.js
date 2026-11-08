/* One Add/Edit workspace; roles remain workflow metadata, not Django groups. */
(function () {
    'use strict';
    const modal = document.getElementById('editUserModal');
    if (!modal) return;
    const form = modal.querySelector('form'), byId = id => document.getElementById(id);
    const text = value => window.FabroI18n?.gettext(value) || value;
    const state = {open: false, dirty: false, manual: false, data: null, rows: new Map(), previousRole: '', request: null};
    state.permissionTouched = new Set();
    let returnFocus, inertNodes = [], oldOverflow;
    const securityValues = () => ({is_staff: byId('editIsStaff')?.checked || false, is_superuser: byId('editIsSuperuser')?.checked || false, groups: [...byId('ucpGroups').selectedOptions].map(option => option.value)});
    function restoreSecurity(value) { for (const [id, flag] of [['editIsStaff', 'is_staff'], ['editIsSuperuser', 'is_superuser']]) if (byId(id)) byId(id).checked = value[flag]; for (const option of byId('ucpGroups').options) option.selected = value.groups.includes(option.value); }
    function feedback(message, error = false) {
        const host = byId('editUserFeedback');
        host.textContent = message; host.classList.toggle('error', error);
    }
    function busy(value) {
        modal.setAttribute('aria-busy', String(value));
        modal.querySelectorAll('.erp-modal-footer button').forEach(button => { button.disabled = value; });
        byId('resetUserPasswordButton').disabled = value || Boolean(state.data?.recovery_only);
        modal.querySelector('.erp-modal-close').disabled = Boolean(value && state.saving);
    }
    function tab(name) {
        modal.querySelector('.ucp-columns').dataset.active = name;
        byId('ucpDetailsTab').setAttribute('aria-selected', String(name === 'details'));
        byId('ucpPermissionsTab').setAttribute('aria-selected', String(name === 'permissions'));
    }
    function currentRole() { return state.data.role_maps[byId('editRole').value]; }
    function counts() {
        let selected = 0;
        for (const row of state.rows.values()) {
            if (row.input.checked) selected++;
            const inherited = row.input.checked === row.default;
            row.label.dataset.override = String(!inherited && !row.input.disabled);
            row.status.textContent = text(row.parentDisabled ? 'Disabled by role window' : !inherited && row.input.disabled ? (row.input.checked ? 'Superuser-managed: Allow' : 'Superuser-managed: Deny') : row.protected && !state.data.can_override_all_activities ? 'Protected administrative access' : inherited ? 'Inherited from role' : row.input.checked ? 'Override: Allow — business rules still apply' : 'Override: Deny');
        }
        for (const category of modal.querySelectorAll('.ucp-category')) {
            const inputs = [...category.querySelectorAll('input')];
            category.querySelector('[data-count]').textContent = `${inputs.filter(input => input.checked).length} / ${inputs.length}`;
        }
        modal.querySelector('[data-ucp-total]').textContent = `${selected} ${text('selected')}`;
    }
    function setPermissions(overrides = {}) {
        const role = currentRole();
        for (const [key, row] of state.rows) {
            row.default = Boolean(role.defaults[key]); row.eligible = Boolean(role.eligible[key]);
            row.protected = role.protected && row.mandatory;
            row.parentDisabled = role.parents_enabled?.[key] === false;
            row.securityDisabled = !state.data.can_manage_permissions || (!state.data.can_override_all_activities && (!row.eligible || row.protected));
            row.input.disabled = row.parentDisabled || row.securityDisabled;
            const selections = row.securityDisabled ? state.data.overrides : overrides;
            row.input.checked = key in selections ? selections[key] === 'allow' : row.default;
        }
        counts();
    }
    function renderCategories() {
        const host = modal.querySelector('[data-ucp-categories]'); host.replaceChildren(); state.rows.clear();
        for (const category of state.data.categories) {
            const details = document.createElement('details'); details.className = 'ucp-category'; details.open = true;
            details.dataset.category = category.key;
            const summary = document.createElement('summary'); summary.append(document.createTextNode(category.label));
            const count = document.createElement('span'); count.dataset.count = ''; summary.append(count); details.append(summary);
            const checklist = document.createElement('div'); checklist.className = 'ucp-checklist';
            for (const item of category.actions) {
                const label = document.createElement('label'); label.className = 'ucp-activity'; label.dataset.search = `${category.label} ${item.label}`.toLocaleLowerCase();
                const input = document.createElement('input'); input.type = 'checkbox'; input.dataset.permission = item.key;
                const content = document.createElement('span'); content.textContent = item.label;
                const status = document.createElement('small'); content.append(status); label.append(input, content); checklist.append(label);
                state.rows.set(item.key, {input, label, status, mandatory: item.protected, dependencies: item.requires});
                input.addEventListener('change', () => {
                    state.permissionTouched.add(item.key);
                    state.manual = state.dirty = true;
                    // Enable required activities when selecting a dependent action.
                    if (input.checked) for (const dependency of item.requires) {
                        const required = state.rows.get(dependency);
                        if (required && !required.input.checked && !required.input.disabled) {
                            required.input.checked = true;
                            required.input.dispatchEvent(new Event('change'));
                        }
                        if (!required?.input.checked) { input.checked = false; feedback(text('A required permission is locked or unavailable.'), true); break; }
                    }
                    // Deselect dependent actions together instead of silently leaving unusable grants.
                    if (!input.checked) for (const row of state.rows.values()) {
                        if (row.dependencies.includes(item.key) && !row.input.disabled) {
                            row.input.checked = false;
                            row.input.dispatchEvent(new Event('change'));
                        }
                    }
                    counts();
                });
            }
            details.append(checklist); host.append(details);
        }
    }
    async function open(userId = '') {
        if (state.open && state.dirty && !window.confirm(text('Discard unsaved user changes?'))) return;
        state.request?.abort(); state.request = new AbortController();
        returnFocus = document.activeElement;
        if (!state.open) {
            oldOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
            inertNodes = [...document.body.children].filter(node => node !== modal && !['SCRIPT', 'STYLE', 'LINK'].includes(node.tagName)).map(node => [node, node.inert]);
            inertNodes.forEach(([node]) => { node.inert = true; });
        }
        state.open = true; state.dirty = state.manual = false;
        state.permissionTouched.clear(); state.resetDefaults = false;
        form.reset(); modal.style.display = 'flex'; busy(true); tab('details'); feedback(text('Loading user controls…'));
        modal.querySelectorAll('.ucp-details input, .ucp-details select, .ucp-details button').forEach(input => { input.disabled = false; });
        modal.querySelector('.erp-modal-close').focus();
        try {
            const url = new URL(modal.dataset.configUrl, location.origin); if (userId) url.searchParams.set('user_id', userId);
            const response = await fetch(url, {signal: state.request.signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
            if (!response.ok || response.redirected) throw new Error(text('Unable to load user controls.'));
            const data = await response.json(); if (!state.open) return;
            state.data = data;
            const user = data.user || {};
            byId('editRole').replaceChildren(...data.role_options.map(([value,label]) => new Option(label,value)));
            const fields = {editUserId: 'id', editUsername: 'username', editEmail: 'email', editFirstName: 'first_name', editLastName: 'last_name', editPhone: 'phone', editCountry: 'country_id', editDepartment: 'department'};
            for (const [id, key] of Object.entries(fields)) byId(id).value = user[key] || '';
            byId('editRole').value = user.role || 'factory_viewer'; state.previousRole = byId('editRole').value;
            for (const [id, key] of [['editCanFactory', 'can_factory'], ['editIsStaff', 'is_staff'], ['editIsSuperuser', 'is_superuser']]) if (byId(id)) byId(id).checked = Boolean(user[key]);
            byId('ucpActive').checked = user.is_active !== false;
            byId('editRole').disabled = !data.can_manage_permissions;
            byId('editUserPassword').name = user.id ? 'new_password' : 'password';
            byId('editUserPassword').required = !user.id; byId('editUserPasswordConfirm').required = !user.id;
            byId('editEmail').required = !user.id;
            byId('resetUserPasswordButton').hidden = !user.id;
            byId('removeUserPhotoButton').hidden = !user.id || !user.photo_url;
            modal.querySelector('[data-ucp-delete]').hidden = !user.id || !data.can_delete_user;
            const groups = byId('ucpGroups'); groups.replaceChildren(); groups.disabled = !data.can_manage_permissions;
            for (const group of data.groups) { const option = new Option(group.name, group.id, false, (user.groups || []).includes(group.id)); groups.append(option); }
            byId('ucpOverrides').disabled = !data.can_manage_permissions;
            modal.querySelector('[data-ucp-reset]').disabled = !data.can_manage_permissions;
            modal.querySelector('[data-ucp-readonly]').hidden = data.can_manage_permissions;
            modal.querySelector('[data-ucp-recovery]').hidden = !data.recovery_only;
            if (data.recovery_only) {
                modal.querySelectorAll('.ucp-details input, .ucp-details select, .ucp-details button').forEach(input => { input.disabled = true; });
                byId('resetUserPasswordButton').hidden = byId('removeUserPhotoButton').hidden = modal.querySelector('[data-ucp-delete]').hidden = true;
                tab('permissions');
            }
            state.security = securityValues(); renderCategories(); setPermissions(data.overrides);
            modal.querySelector('.ucp-details').scrollTop = modal.querySelector('.ucp-permissions').scrollTop = 0;
            busy(false); feedback(''); byId('editUsername').focus();
        } catch (error) {
            if (error.name !== 'AbortError') feedback(error.message, true);
        }
    }
    function close() {
        if (!state.open || state.saving) return;
        if (state.dirty && !window.confirm(text('Discard unsaved user changes?'))) return;
        state.request?.abort(); state.policyRequest?.abort(); state.open = false; state.data = null; state.rows.clear();
        form.reset(); modal.querySelector('[data-ucp-categories]').replaceChildren(); modal.style.display = 'none';
        inertNodes.forEach(([node, value]) => { node.inert = value; }); inertNodes = [];
        document.body.style.overflow = oldOverflow;
        if (returnFocus?.isConnected) returnFocus.focus(); else document.querySelector('#tab-users button[onclick="openCreateUserModal()"]')?.focus();
        const url = new URL(location.href);
        if (url.searchParams.has('edit_user')) { url.searchParams.delete('edit_user'); history.replaceState({}, '', url.pathname + url.search + url.hash); }
    }
    byId('editRole').addEventListener('change', () => {
        if (!state.data) return;
        if (state.manual && !window.confirm(text('Switching roles will replace unsaved permission selections with the new role defaults. Continue?'))) {
            byId('editRole').value = state.previousRole; return;
        }
        state.previousRole = byId('editRole').value; state.manual = false; state.dirty = true; state.resetDefaults = true; state.permissionTouched.clear(); setPermissions();
    });
    function permissionOverrides() {
        const role = currentRole(), overrides = state.resetDefaults ? {} : {...state.data.overrides};
        for (const [key, row] of state.rows) {
            if (row.securityDisabled && key in state.data.overrides) overrides[key] = state.data.overrides[key];
            else if (!row.securityDisabled && (state.resetDefaults || state.permissionTouched.has(key))) {
                if (row.input.checked !== Boolean(role.defaults[key])) overrides[key] = row.input.checked ? 'allow' : 'deny';
                else delete overrides[key];
            }
        }
        return overrides;
    }
    async function securityChanged() {
        if (!state.data) return;
        if (state.manual && !window.confirm(text('Changing account authority recalculates eligibility and keeps your permission overrides. Continue?'))) { restoreSecurity(state.security); return; }
        state.policyRequest?.abort(); const request = new AbortController(); state.policyRequest = request;
        const overrides = permissionOverrides();
        const values = securityValues(); const url = new URL(modal.dataset.configUrl, location.origin);
        if (byId('editUserId').value) url.searchParams.set('user_id', byId('editUserId').value);
        url.searchParams.set('is_staff', values.is_staff ? '1' : '0'); url.searchParams.set('is_superuser', values.is_superuser ? '1' : '0'); url.searchParams.set('groups', values.groups.join(','));
        busy(true);
        try {
            const response = await fetch(url, {signal: request.signal, cache: 'no-store', headers: {Accept: 'application/json'}});
            if (!response.ok) throw new Error(text('Unable to update role defaults.'));
            const data = await response.json();
            if (!state.open || request.signal.aborted) return;
            state.data.role_maps = data.role_maps; state.security = values;
            setPermissions(overrides); state.manual = false; state.dirty = true; feedback('');
        } catch (error) { if (error.name !== 'AbortError') { restoreSecurity(state.security); feedback(error.message, true); } }
        finally { if (state.open && state.policyRequest === request) busy(false); }
    }
    for (const id of ['editIsStaff', 'editIsSuperuser', 'ucpGroups']) byId(id)?.addEventListener('change', securityChanged);
    form.addEventListener('input', event => { if (state.data && event.target.id !== 'ucpSearch') state.dirty = true; });
    form.addEventListener('change', event => { if (state.data && event.target.id !== 'ucpSearch') state.dirty = true; });
    byId('ucpDetailsTab').addEventListener('click', () => tab('details'));
    byId('ucpPermissionsTab').addEventListener('click', () => tab('permissions'));
    for (const [attribute, expanded] of [['expand', true], ['collapse', false]]) modal.querySelector(`[data-ucp-${attribute}]`).addEventListener('click', () => {
        modal.querySelectorAll('.ucp-category').forEach(category => { category.open = expanded; });
    });
    modal.querySelector('[data-ucp-reset]').addEventListener('click', () => {
        if (window.confirm(text('Replace current permission selections with role defaults?'))) { state.resetDefaults = true; state.permissionTouched.clear(); setPermissions(); state.manual = false; state.dirty = true; }
    });
    byId('ucpSearch').addEventListener('input', event => {
        const needle = event.target.value.toLocaleLowerCase().trim();
        for (const category of modal.querySelectorAll('.ucp-category')) {
            const rows = [...category.querySelectorAll('.ucp-activity')];
            rows.forEach(row => { row.hidden = !row.dataset.search.includes(needle); });
            category.hidden = rows.every(row => row.hidden); if (needle) category.open = true;
        }
        modal.querySelector('[data-ucp-empty]').hidden = [...modal.querySelectorAll('.ucp-category')].some(category => !category.hidden);
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!state.data || byId('saveEditUserButton').disabled) return;
        tab('details'); if (!form.reportValidity()) return;
        const overrides = permissionOverrides();
        byId('ucpOverrides').value = JSON.stringify(overrides);
        const data = new FormData(form);
        // Disabled role field is read-only for MD administrators, not omitted from profile validation.
        if (!state.data.recovery_only) data.set('role', byId('editRole').value);
        state.saving = true; busy(true); feedback(text('Saving…'));
        try {
            const response = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin', headers: {Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest'}});
            const result = await response.json();
            feedback((result.messages || []).join(' '), !result.success);
            if (result.success) {
                const created = !byId('editUserId').value;
                byId('editUserId').value = result.user.id; byId('editUserPassword').value = byId('editUserPasswordConfirm').value = '';
                byId('editUserPassword').name = 'new_password'; byId('editUserPassword').required = false; byId('editUserPasswordConfirm').required = false;
                byId('resetUserPasswordButton').hidden = false; modal.querySelector('[data-ucp-delete]').hidden = false;
                state.dirty = state.manual = false; state.data.user = result.user;
                window.updateUserCardInDOM?.(result.user);
                const actorId = JSON.parse(document.getElementById('fabro-activity-sync')?.textContent || '{}').user_id;
                if (result.user.id === actorId && (state.data.recovery_only || ['users.manage', 'users.permissions', 'erp.view'].some(key => overrides[key] === 'deny'))) {
                    await open(result.user.id); feedback((result.messages || []).join(' '));
                }
                if (created) { window.erpLoadedSections?.delete('users'); await window.switchErpTab?.('users', {historyMode: 'replace', preservePage: true}); }
            }
        } catch (_error) { feedback(text('Unable to save. Check your connection and try again.'), true); }
        finally { state.saving = false; busy(false); }
    });
    document.addEventListener('keydown', event => {
        if (!state.open) return;
        if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close(); return; }
        if (event.key === 'Tab') {
            const items = [...modal.querySelectorAll('button, input, select, textarea, summary, [href]')].filter(node => !node.disabled && node.getClientRects().length);
            const first = items[0], last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
    }, true);
    window.addEventListener('beforeunload', event => { if (state.open && state.dirty) { event.preventDefault(); event.returnValue = ''; } });
    const resetPassword = window.resetUserPassword;
    window.resetUserPassword = async () => {
        if (state.saving) return;
        state.saving = true; busy(true);
        try { await resetPassword(); } finally { state.saving = false; busy(false); }
    };
    for (const [id, name] of [['ucpDetailsTab', 'details'], ['ucpPermissionsTab', 'permissions']]) byId(id).addEventListener('keydown', event => {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
            event.preventDefault(); const target = event.key === 'Home' ? 'details' : event.key === 'End' ? 'permissions' : name === 'details' ? 'permissions' : 'details';
            tab(target); byId(target === 'details' ? 'ucpDetailsTab' : 'ucpPermissionsTab').focus();
        }
    });
    window.openCreateUserModal = () => open();
    window.openEditUserCard = card => open(card.dataset.userId);
    window.openEditUserCardById = open;
    window.closeCreateUserModal = window.closeEditUserModal = close;
    window.fabroUserControl = {open, close};
})();
