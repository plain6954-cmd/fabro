const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(permissions, nodes, fetch) {
    const document = new EventTarget(), window = new EventTarget();
    document.readyState = 'complete'; document.hidden = false; document.documentElement = {};
    document.getElementById = () => ({textContent: JSON.stringify(permissions)});
    document.querySelectorAll = () => nodes;
    let observer;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../management/static/management/js/activity_ui.js'), 'utf8'), {
        window, document, fetch, queueMicrotask,
        MutationObserver: class {constructor(callback) {observer = this; this.callback = callback;} observe() {} disconnect() {this.disconnected = true;}}
    });
    return {window, document, observer};
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

test('permission updates restore only controls disabled by the feature gate', async () => {
    const button = node('chat.send');
    const h = harness({'chat.send': false}, [button], async () => ({ok: true, json: async () => ({permissions: {'chat.send': true}})}));
    assert.equal(button.disabled, true);
    await h.window.fabroActivityAccess.refresh();
    assert.equal(button.hidden, false); assert.equal(button.disabled, false);
    h.window.dispatchEvent(new Event('pagehide')); assert.equal(h.observer.disconnected, true);
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
