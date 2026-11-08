/* Role presentation only. The server resolves every activity and workflow guard. */
(function () {
    'use strict';
    const root = document.getElementById('rolesWorkspace');
    if (!root) return;
    const form = root.querySelector('[data-role-form]'), list = root.querySelector('[data-role-list]');
    const host = root.querySelector('[data-role-tree]'), name = root.querySelector('#roleName'), short = root.querySelector('#roleShortName');
    const state = {data:null, saved:null, draft:null, dirty:false, loading:false, saving:false, sequence:0, nodes:new Map(), actions:new Map()};
    const text = value => window.FabroI18n?.gettext(value) || value;
    const clone = value => JSON.parse(JSON.stringify(value));
    const feedback = (message='', error=false) => { const el=root.querySelector('[data-role-feedback]'); el.textContent=message; el.dataset.error=String(error); };
    const windowOn = key => key in state.draft.windows ? state.draft.windows[key] : Boolean(state.draft.system_code);
    const writable = () => Boolean(state.data?.can[state.draft?.id ? 'edit' : 'create']);
    function busy() {
        root.setAttribute('aria-busy',String(state.loading || state.saving));
        const blocked=state.loading || state.saving;
        root.querySelectorAll('[data-role-action]').forEach(button => {
            const action=button.dataset.roleAction, entry=state.data?.roles.find(role=>role.id===state.draft?.id);
            button.disabled=blocked || (action==='save' && !writable()) || (action==='new' && !state.data?.can.create)
                || (action==='duplicate' && (!state.draft?.id || !state.data?.can.create))
                || (action==='delete' && (!entry || entry.system_code || entry.user_count || !state.data?.can.delete));
            if (action==='delete') button.title=entry?.system_code ? text('System roles cannot be deleted.') : entry?.user_count ? text('Assigned roles cannot be deleted.') : text('Delete role');
        });
        name.disabled=short.disabled=blocked || !writable();
        list.querySelectorAll('button').forEach(button=>{button.disabled=blocked;});
        if (state.draft) updateChecks();
    }
    function renderList() {
        list.replaceChildren();
        for (const role of state.data.roles) {
            const button=document.createElement('button'); button.type='button'; button.className='erp-role-card'; button.dataset.roleId=role.id;
            button.setAttribute('aria-pressed',String(role.id===state.draft?.id));
            const icon=document.createElement('span');icon.className='erp-role-card-icon';const shield=document.createElement('i');shield.className='fas fa-shield-alt';shield.setAttribute('aria-hidden','true');icon.append(shield);
            const details=document.createElement('span'), title=document.createElement('span');title.className='erp-role-card-name';title.textContent=role.name;details.append(title);
            if (role.short_name) {const badge=document.createElement('span');badge.className='erp-role-card-short';badge.textContent=role.short_name;details.append(badge);}
            const count=document.createElement('span');count.className='erp-role-card-count';count.textContent=`${role.user_count} ${text(role.user_count===1?'user':'users')}`;
            button.append(icon,details,count);list.append(button);
        }
    }
    function renderTree() {
        host.replaceChildren();state.nodes.clear();state.actions.clear();
        function branch(items, container, ancestors=[], labels=[]) {
            for (const item of items) {
                const path=ancestors.concat(item.key), words=labels.concat(item.label);
                const details=document.createElement('details');details.className='erp-role-node';details.dataset.roleNode=item.key;
                details.open=ancestors.length<2;
                const summary=document.createElement('summary'), checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.dataset.roleWindow=item.key;checkbox.setAttribute('aria-label',text(item.label));
                const icon=document.createElement('i');icon.className='fas fa-'+item.icon;icon.setAttribute('aria-hidden','true');
                const label=document.createElement('span');label.textContent=text(item.label);const count=document.createElement('small');
                summary.append(checkbox,icon,label,count);details.append(summary);
                const grid=document.createElement('div');grid.className='erp-role-action-grid';
                const keys=[];
                for (const action of item.actions) {
                    const row=document.createElement('label'), input=document.createElement('input'), caption=document.createElement('span');
                    input.type='checkbox';input.dataset.rolePermission=action.key;caption.textContent=text(action.label);row.append(input,caption);grid.append(row);keys.push(action.key);
                    state.actions.set(action.key,{input,row,path,requires:action.requires,search:words.concat(action.label).join(' ').toLocaleLowerCase()});
                }
                if (keys.length) details.append(grid);
                const children=document.createElement('div');children.className='erp-role-children';
                state.nodes.set(item.key,{details,checkbox,count,ancestors,path,keys,search:words.join(' ').toLocaleLowerCase()});
                branch(item.children,children,path,words);if(item.children.length)details.append(children);container.append(details);
            }
        }
        branch(state.data.hierarchy,host);updateChecks();
    }
    function effective(key, seen=new Set()) {
        const action=state.actions.get(key);
        if (!action || seen.has(key) || !state.draft.permissions[key] || !action.path.every(windowOn)) return false;
        const next=new Set(seen);next.add(key);return action.requires.every(dependency=>effective(dependency,next));
    }
    function updateChecks() {
        const blocked=state.loading || state.saving || !state.data.can.permissions;
        const permissionLocks=new Set(state.draft.locked_permissions || []), windowLocks=new Set(state.draft.locked_windows || []);
        for (const [key,node] of state.nodes) {
            node.checkbox.checked=windowOn(key);const disabledParent=!node.ancestors.every(windowOn);
            node.checkbox.disabled=blocked || disabledParent || windowLocks.has(key);node.details.dataset.ancestorDisabled=String(disabledParent);
            node.checkbox.title=windowLocks.has(key)?text('Protected administrative access'):disabledParent?text('Disabled by parent window'):'';
            const descendants=[...state.actions].filter(([,action])=>action.path.includes(key)).map(([name])=>name);
            const stored=descendants.filter(name=>state.draft.permissions[name]).length, active=descendants.filter(name=>effective(name)).length;
            node.count.textContent=`${active} / ${descendants.length}`+(stored>active?` · ${stored} ${text('stored')}`:'');
            node.count.title=`${active} ${text('enabled')}; ${stored} ${text('stored selections')}`;
        }
        for (const [key,action] of state.actions) {
            action.input.checked=Boolean(state.draft.permissions[key]);const disabled=!action.path.every(windowOn);
            action.input.disabled=blocked || disabled || permissionLocks.has(key);action.row.dataset.disabled=String(disabled);
            action.row.title=permissionLocks.has(key)?text('Protected administrative access'):disabled?text('Disabled by parent window'):'';
        }
        root.querySelector('[data-role-counts]').textContent=`${[...state.actions.keys()].filter(key=>effective(key)).length} ${text('enabled')} · ${Object.values(state.draft.permissions).filter(Boolean).length} ${text('stored selections')}`;
    }
    function show(role) {
        state.draft=clone(role || {name:'',short_name:'',permissions:{},windows:{}});state.dirty=false;
        name.value=state.draft.name;short.value=state.draft.short_name;name.setCustomValidity('');
        root.querySelector('[data-role-editor-title]').textContent=text(state.draft.id?'Edit Role':'Create Role');
        renderList();renderTree();busy();feedback();
    }
    function confirmLeave() {
        if (state.saving || state.loading) return false;
        if (!state.dirty) return true;
        if (!window.confirm(text('Discard unsaved role changes?'))) return false;
        show(state.saved);return true;
    }
    async function request(url, body, signal) {
        const response=await fetch(url,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',signal,
            headers:body?{'Content-Type':'application/json','X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value}:{Accept:'application/json'},body:body?JSON.stringify(body):undefined});
        const data=await response.json().catch(()=>({message:text('Role access is unavailable.')}));
        if (!response.ok || response.redirected || (body && data.success!==true)) throw new Error(data.message || text('Unable to save this role.'));
        return data;
    }
    async function load(id='') {
        if (state.saving) return;
        state.request?.abort();const controller=new AbortController(), sequence=++state.sequence;state.request=controller;state.loading=true;busy();feedback(text('Loading roles…'));
        try {
            const url=new URL(root.dataset.configUrl,location.origin);if(id)url.searchParams.set('id',id);
            const data=await request(url,null,controller.signal);if(sequence!==state.sequence)return;
            state.data=data;state.saved=clone(data.selected);show(state.saved);
        } catch(error) {if(error.name!=='AbortError')feedback(error.message,true);}
        finally {if(sequence===state.sequence){state.loading=false;busy();}}
    }
    let toastTimer;
    function success(role, created) {
        clearTimeout(toastTimer);document.getElementById('erpRoleToastHost')?.remove();
        const container=document.createElement('div');container.id='erpRoleToastHost';container.className='erp-toast-container erp-role-toast-host';
        const toast=document.createElement('div');toast.className='erp-toast erp-role-toast';toast.setAttribute('role','status');
        const icon=document.createElement('i');icon.className='fas fa-check-circle';icon.setAttribute('aria-hidden','true');
        const content=document.createElement('div'), title=document.createElement('strong'), description=document.createElement('p');
        title.textContent=text('Saved Successfully');description.textContent=`${text('Role')} "${role.name}" ${text(created?'has been created.':'has been updated.')}`;content.append(title,description);
        const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='erp-toast-close';dismiss.setAttribute('aria-label',text('Dismiss message'));dismiss.textContent='×';dismiss.onclick=()=>container.remove();
        toast.append(icon,content,dismiss);container.append(toast);document.body.append(container);toastTimer=setTimeout(()=>container.remove(),4500);
    }
    form.addEventListener('submit',async event=>{
        event.preventDefault();if(state.saving || state.loading || !writable())return;
        name.setCustomValidity(name.value.trim()?'':text('Role Name is required.'));if(!form.reportValidity())return;
        state.draft.name=name.value.trim();state.draft.short_name=short.value.trim();const created=!state.draft.id;
        clearTimeout(toastTimer);document.getElementById('erpRoleToastHost')?.remove();
        const body={name:state.draft.name,short_name:state.draft.short_name,permissions:state.draft.permissions,windows:state.draft.windows};
        if(!created){body.id=state.draft.id;body.revision=state.draft.revision;}
        state.saving=true;busy();feedback(text('Saving…'));
        try {const data=await request(root.dataset.saveUrl,body);state.data=data;state.saved=clone(data.selected);show(state.saved);success(state.saved,created);window.fabroActivityAccess?.refresh?.();}
        catch(error){feedback(error.message,true);}
        finally{state.saving=false;busy();}
    });
    root.addEventListener('input',event=>{
        if(event.target.matches('#roleName,#roleShortName')){state.dirty=true;name.setCustomValidity('');}
        if(event.target.matches('[data-role-search]')){
            const term=event.target.value.toLocaleLowerCase().trim();
            for(const action of state.actions.values())action.row.hidden=Boolean(term && !action.search.includes(term));
            for(const node of [...state.nodes.values()].reverse()){
                const match=!term || node.search.includes(term) || [...state.actions.values()].some(action=>action.path.includes(node.checkbox.dataset.roleWindow)&&!action.row.hidden);
                node.details.hidden=!match;if(term&&match)node.details.open=true;
            }
        }
    });
    root.addEventListener('change',event=>{
        const key=event.target.dataset.roleWindow, permission=event.target.dataset.rolePermission;
        if(key)state.draft.windows[key]=event.target.checked;
        if(permission){
            state.draft.permissions[permission]=event.target.checked;
            // Dependency edits occur only for an explicit action selection, never a parent toggle.
            if(event.target.checked){
                const enable=(name,seen=new Set())=>{if(seen.has(name))return;seen.add(name);const row=state.actions.get(name);if(!row || row.input.disabled)return;state.draft.permissions[name]=true;row.requires.forEach(dep=>enable(dep,seen));};
                state.actions.get(permission).requires.forEach(dep=>enable(dep));
            }else{
                const disable=(name,seen=new Set())=>{if(seen.has(name))return;seen.add(name);for(const [next,row] of state.actions)if(row.requires.includes(name)&&!row.input.disabled){state.draft.permissions[next]=false;disable(next,seen);}};disable(permission);
            }
        }
        if(key || permission){state.dirty=true;updateChecks();}
    });
    root.addEventListener('click',async event=>{
        if(event.target.matches('input[type=checkbox]'))event.stopPropagation();
        const card=event.target.closest('[data-role-id]');if(card && confirmLeave()){await load(card.dataset.roleId);return;}
        const button=event.target.closest('[data-role-action]');if(!button || button.disabled)return;
        const action=button.dataset.roleAction;
        if(action==='expand' || action==='collapse'){host.querySelectorAll('details').forEach(node=>{node.open=action==='expand';});return;}
        if(action==='save')return;
        if(!confirmLeave())return;
        if(action==='new'){show(null);name.focus();}
        if(action==='cancel')show(state.saved);
        if(action==='duplicate'){
            const copy=clone(state.saved);copy.windows=Object.fromEntries([...state.nodes.keys()].map(key=>[key,windowOn(key)]));
            copy.id=null;copy.system_code=null;copy.locked_permissions=[];copy.locked_windows=[];
            const original=copy.name;let index=1;do{copy.name=original+' '+text('Copy')+(index===1?'':' '+index);index++;}while(state.data.roles.some(role=>role.name.toLocaleLowerCase()===copy.name.toLocaleLowerCase()));
            show(copy);state.dirty=true;name.focus();name.select();
        }
        if(action==='delete' && window.confirm(`${text('Delete role')} "${state.saved.name}"?`)){
            state.saving=true;busy();try{const data=await request(root.dataset.deleteUrl,{id:state.saved.id,revision:state.saved.revision});state.data=data;state.saved=null;state.saving=false;show(null);if(data.roles.length)await load(data.roles[0].id);}
            catch(error){feedback(error.message,true);}finally{state.saving=false;busy();}
        }
    });
    window.addEventListener('beforeunload',event=>{if(state.dirty || state.saving){event.preventDefault();event.returnValue='';}});
    document.addEventListener('fabro:access-changed',event=>{
        if(!state.data)return;
        for(const action of ['create','edit','delete','permissions'])state.data.can[action]=event.detail.permissions['roles.'+action]===true;
        busy();
    });
    document.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(link && root.closest('.erp-tab-pane')?.classList.contains('active') && !confirmLeave())event.preventDefault();});
    window.fabroRoles={open:()=>{if(!state.dirty && !state.saving)return load(state.draft?.id || '');},confirmLeave};
})();
