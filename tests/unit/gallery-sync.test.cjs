const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(check, ready = () => true, options = {}) {
    const document = new EventTarget();
    document.hidden = false;
    const root = { isConnected: true, parentElement: null, displayed: true, getClientRects() { return this.displayed ? [{}] : []; } };
    const parent = new AbortController();
    let now = 0, serial = 0, observer;
    const timers = new Map();
    const window = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../management/static/management/js/gallery_sync.js'), 'utf8'), {
        window, document, AbortController,
        MutationObserver: class { constructor(callback) { observer = this; this.callback = callback; } observe() {} disconnect() { this.disconnected = true; } },
        setTimeout(callback, delay) { const id = ++serial; timers.set(id, { callback, at: now + delay }); return id; },
        clearTimeout(id) { timers.delete(id); },
    });
    const sync = window.fabroCreateGallerySync({ root, signal: parent.signal, canCheck: ready, check, ...options });
    const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
    async function advance(milliseconds) {
        const target = now + milliseconds;
        while (true) {
            const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
            if (!next || next[1].at > target) break;
            now = next[1].at;
            timers.delete(next[0]);
            next[1].callback();
            await flush();
        }
        now = target;
        await flush();
    }
    function hidden(value) { document.hidden = value; document.dispatchEvent(new Event('visibilitychange')); }
    return { advance, flush, hidden, sync, root, parent, observer, mutate: () => observer.callback(), timers, now: () => now };
}

test('visible galleries check every ten seconds; hidden tabs pause and resume immediately', async () => {
    let calls = 0;
    const h = harness(async () => { calls++; });
    await h.advance(0); assert.equal(calls, 1);
    await h.advance(9999); assert.equal(calls, 1);
    await h.advance(1); assert.equal(calls, 2);
    h.hidden(true); await h.advance(60000); assert.equal(calls, 2);
    h.hidden(false); await h.advance(0); assert.equal(calls, 3);
    assert.equal(h.timers.size, 1);
    h.parent.abort();
});

test('slow checks cannot overlap, including repeated visibility events', async () => {
    let calls = 0, finish;
    const h = harness(() => { calls++; return new Promise(resolve => { finish = resolve; }); });
    await h.advance(0);
    h.hidden(true); h.hidden(false); h.sync.wake();
    await h.advance(120000); assert.equal(calls, 1);
    finish(); await h.flush();
    await h.advance(10000); assert.equal(calls, 2);
    h.parent.abort();
});

test('temporary failures back off to sixty seconds, then recover to ten seconds', async () => {
    const times = [];
    const h = harness(async () => { times.push(h.now()); if (times.length <= 4) throw new Error('offline'); });
    await h.advance(0); await h.advance(20000); await h.advance(40000); await h.advance(60000);
    await h.advance(60000); await h.advance(10000);
    assert.deepEqual(times, [0, 20000, 60000, 120000, 180000, 190000]);
    h.parent.abort();
});

test('authentication or authorization failure stops the loop permanently', async () => {
    let calls = 0;
    const h = harness(async () => { calls++; return false; });
    await h.advance(0); h.hidden(true); h.hidden(false); await h.advance(120000);
    assert.equal(calls, 1); assert.equal(h.timers.size, 0); assert.equal(h.observer.disconnected, true);
});

test('inactive workspaces do not poll; showing them or completing initial load starts one loop', async () => {
    let ready = false, calls = 0;
    const h = harness(async () => { calls++; }, () => ready);
    await h.advance(30000); assert.equal(calls, 0);
    ready = true; h.sync.wake(); await h.advance(0); assert.equal(calls, 1);
    h.root.displayed = false; h.mutate(); await h.advance(30000); assert.equal(calls, 1);
    h.root.displayed = true; h.mutate(); await h.advance(0); assert.equal(calls, 2);
    h.parent.abort();
});

test('unmount and page disposal cancel in-flight requests and all timers', async () => {
    let requestSignal;
    const h = harness(signal => { requestSignal = signal; return new Promise(() => {}); });
    await h.advance(0); h.parent.abort();
    assert.equal(requestSignal.aborted, true); assert.equal(h.timers.size, 0);
    const other = harness(async () => {});
    other.root.isConnected = false; other.mutate();
    assert.equal(other.observer.disconnected, true); assert.equal(other.timers.size, 0);
});

test('control tower uses thirty seconds, coalesces focus refreshes and owns disposal', async () => {
    let calls = 0, disposals = 0, finish;
    const h = harness(() => { calls++; return new Promise(resolve => { finish = resolve; }); }, () => true,
        { interval: 30000, onDispose: () => { disposals++; } });
    await h.advance(0);
    h.sync.refresh(); h.sync.refresh(); await h.advance(90000);
    assert.equal(calls, 1);
    finish(); await h.flush();
    await h.advance(29999); assert.equal(calls, 1);
    await h.advance(1); assert.equal(calls, 2);
    finish(); await h.flush();
    h.hidden(true); h.sync.refresh(); await h.advance(60000); assert.equal(calls, 2);
    h.hidden(false); await h.advance(0); assert.equal(calls, 3);
    finish(); await h.flush();
    h.sync.refresh(); h.sync.refresh(); await h.advance(0); assert.equal(calls, 4);
    h.root.isConnected = false; h.mutate(); h.sync.dispose();
    assert.equal(disposals, 1); assert.equal(h.timers.size, 0);
});
