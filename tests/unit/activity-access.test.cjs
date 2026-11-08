const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(permissions, nodes, fetch, extras = {}) {
    const document = new EventTarget(), window = new EventTarget();
    document.readyState = 'loading'; document.hidden = false; document.documentElement = {};
    document.getElementById = id => ({textContent: JSON.stringify(id === 'fabro-activity-data' ? permissions : {user_id: 7, version: 'original'})});
    document.querySelectorAll = selector => ['[data-approval-file]', '[data-access-fragment]'].includes(selector) ? [] : nodes;
    const timers = new Map(); let sequence = 0;
    let observer;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../management/static/management/js/activity_ui.js'), 'utf8'), {
        window, document, fetch, queueMicrotask, AbortController, URLSearchParams, navigator: {}, ...extras,
        setTimeout: (callback, delay) => {const id = ++sequence; timers.set(id, {callback, delay}); return id;},
        clearTimeout: id => timers.delete(id),
        CustomEvent: class extends Event {constructor(type, options) {super(type); this.detail = options.detail;}},
        MutationObserver: class {constructor(callback) {observer = this; this.callback = callback;} observe() {} disconnect() {this.disconnected = true;}}
    });
    window.fabroActivityAccess.apply();
    return {window, document, observer, timers};
}
function node(key, tagName = 'BUTTON', disabled = false) {
    return {tagName, disabled, hidden: false, dataset: {activity: key}};
}

test('denied navigation and controls hide; existing business-disabled controls stay disabled', () => {
    const link = node('chat.view', 'A'), button = node('chat.send'), completed = node('design_approval.approve', 'BUTTON', true);
    harness({'chat.view': false, 'chat.send': false, 'design_approval.approve': true}, [link, button, completed], () => {});
    assert.equal(link.hidden, true); assert.equal(button.disabled, true); assert.equal(completed.disabled, true);
});

test('own/all download choices cannot expose the all-only control', () => {
    const own = {tagName: 'A', hidden: false, dataset: {activityAny: 'design.download_all design.download_own'}};
    const other = {tagName: 'A', hidden: false, dataset: {activityAny: 'design.download_all'}};
    harness({'design.download_own': true, 'design.download_all': false}, [own, other], () => {});
    assert.equal(own.hidden, false); assert.equal(other.hidden, true);
});

test('shared window gates and own/all gates must all pass together', () => {
    for (const [windowGranted, fileGranted, expected] of [[false,true,true],[true,false,true],[true,true,false]]) {
        const control = node('design_status.view');
        control.dataset.activityAny = 'design.view_own design.view_all';
        harness({'design_status.view':windowGranted,'design.view_own':fileGranted},[control],()=>{});
        assert.equal(control.hidden,expected);
    }
    const control=node('workflow.view');control.dataset.activityAll='approvals.workspace';
    harness({'workflow.view':true,'approvals.workspace':false},[control],()=>{});
    assert.equal(control.hidden,true);
});

test('permission updates restore only controls disabled by the feature gate', async () => {
    const button = node('chat.send');
    const h = harness({'chat.send': false}, [button], async () => ({ok: true, json: async () => ({user_id: 7, version: 'next', permissions: {'chat.send': true}})}));
    assert.equal(button.disabled, true);
    await h.window.fabroActivityAccess.refresh();
    assert.equal(button.hidden, false); assert.equal(button.disabled, false);
    h.window.dispatchEvent(new Event('pagehide')); assert.equal(h.observer.disconnected, true);
});

test('server-rendered hidden gates become visible and lose aria-hidden after grant', async () => {
    const button = node('chat.send'); button.hidden = true;
    button.dataset.activityDenied = 'true'; button.dataset.activityDisabledByGate = 'true';
    const removed = []; button.removeAttribute = value => removed.push(value);
    const h = harness({}, [button], async () => ({ok: true, json: async () => ({user_id: 7, version: 'grant', permissions: {'chat.send': true}})}));
    await h.window.fabroActivityAccess.refresh();
    assert.equal(button.hidden, false); assert.equal(button.disabled, false); assert.ok(removed.includes('aria-hidden'));
});

test('compact checks retain snapshot, send version and notify components only on changes', async () => {
    let url, changeCount = 0, data = {user_id: 7, version: 'original'};
    const button = node('chat.send');
    const h = harness({'chat.send': true}, [button], async input => {url = input; return {ok: true, json: async () => data};});
    h.document.addEventListener('fabro:access-changed', () => changeCount++);
    await h.window.fabroActivityAccess.refresh();
    assert.match(url, /version=original/); assert.equal(changeCount, 0); assert.equal(button.hidden, false);
    data = {user_id: 7, version: 'revoked', permissions: {'chat.send': false}};
    await h.window.fabroActivityAccess.refresh();
    assert.equal(changeCount, 1); assert.equal(button.hidden, true);
    await h.window.fabroActivityAccess.refresh(); assert.equal(changeCount, 1);
});

test('visible polling schedules at two seconds, pauses in background and cleans up', async () => {
    let calls = 0;
    const h = harness({}, [], async () => {calls++; return {ok: true, json: async () => ({user_id: 7, version: 'original'})};});
    h.window.dispatchEvent(new Event('focus')); await new Promise(resolve => setImmediate(resolve));
    const tick = Array.from(h.timers.values()).find(item => item.delay === 2000); assert.ok(tick);
    await tick.callback(); assert.equal(calls, 2);
    h.document.hidden = true; h.document.dispatchEvent(new Event('visibilitychange')); assert.equal(h.timers.size, 0);
    h.document.hidden = false; h.document.dispatchEvent(new Event('visibilitychange')); await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls, 3); h.window.dispatchEvent(new Event('pagehide')); assert.equal(h.timers.size, 0);
});

test('network failures back off and online recovery revalidates immediately', async () => {
    let fail = true, calls = 0;
    const h = harness({}, [], async () => {calls++; if(fail)throw Error('offline');return {ok: true, json: async () => ({user_id: 7, version: 'original'})};});
    h.window.dispatchEvent(new Event('focus')); await new Promise(resolve => setImmediate(resolve));
    assert.ok(Array.from(h.timers.values()).some(item => item.delay === 4000));
    fail = false; h.window.dispatchEvent(new Event('online')); await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls, 2); assert.ok(Array.from(h.timers.values()).some(item => item.delay === 2000));
});

test('focus bursts share one request, hidden pages pause and failures keep denied state', async () => {
    let calls = 0, release;
    const button = node('chat.send');
    const h = harness({'chat.send': false}, [button], () => {calls++; return new Promise(resolve => {release = resolve;});});
    const pending = h.window.fabroActivityAccess.refresh();
    for(let i = 0; i < 5; i++) h.window.dispatchEvent(new Event('focus'));
    assert.equal(calls, 1);
    release({ok: false}); await pending;
    assert.equal(button.hidden, true);
    h.document.hidden = true;
    await h.window.fabroActivityAccess.refresh(); assert.equal(calls, 1);
});

test('cross-tab invalidations contain no permission details and each tab fetches its own snapshot', async () => {
    const peers = [], messages = [];
    class Channel {
        constructor() { peers.push(this); }
        postMessage(data) { messages.push(data); peers.filter(peer => peer !== this).forEach(peer => queueMicrotask(() => peer.onmessage({data}))); }
        close() {}
    }
    const response = async () => ({ok: true, json: async () => ({user_id: 7, version: 'new', permissions: {'chat.send': true}})});
    const first = harness({}, [], response, {BroadcastChannel: Channel});
    let secondCalls = 0;
    const button = node('chat.send');
    const second = harness({}, [button], async () => {secondCalls++; return response();}, {BroadcastChannel: Channel});
    await first.window.fabroActivityAccess.refresh(); await new Promise(resolve => setImmediate(resolve));
    assert.equal(secondCalls, 1); assert.equal(button.hidden, false);
    assert.ok(messages.every(message => !('permissions' in message) && message.type === 'activity_access'));
    assert.equal(second.window.fabroActivityAccess.version, 'new');
});

test('a different-account snapshot or expired session cannot preserve stale grants', async () => {
    for (const result of [{ok: true, json: async () => ({user_id: 99, version: 'other', permissions: {'chat.send': true}})}, {ok: false, redirected: true}]) {
        const button = node('chat.send');
        const h = harness({'chat.send': true}, [button], async () => result);
        await h.window.fabroActivityAccess.refresh();
        assert.equal(button.hidden, true); assert.equal(button.disabled, true);
    }
});
