const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(initial) {
    class Control extends EventTarget {
        constructor(dataset = {}) { super(); this.dataset = dataset; this.attributes = {}; this.hidden = false; }
        setAttribute(key, value) { this.attributes[key] = value; }
        focus() { this.focused = true; }
    }
    const roles = ['cad', 'ed', 'md'];
    const tabs = roles.map(reviewStage => new Control({reviewStage}));
    const panels = roles.map(reviewPanel => new Control({reviewPanel}));
    const prompt = new Control();
    const media = {querySelector: () => null};
    const root = new Control({initialStage: initial});
    root.querySelectorAll = selector => selector === '[data-review-stage]' ? tabs : panels;
    root.querySelector = selector => selector === '[data-review-media]' ? media : selector === '[data-review-select-prompt]' ? prompt : null;
    const controller = new AbortController(), cleanups = [], suspended = [];
    const window = {
        fabroOnPageLoad: callback => callback(),
        fabroCreatePageScope: () => ({
            signal: controller.signal,
            listen: (target, event, callback) => target.addEventListener(event, callback, {signal: controller.signal}),
            onCleanup: callback => cleanups.push(callback),
        }),
        fabroReviewVoice: {suspendWithin: panel => suspended.push(panel.dataset.reviewPanel)},
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../management/static/management/js/design_review.js'), 'utf8'), {
        window, document: {querySelector: () => root, querySelectorAll: () => [], getElementById: () => null},
        cancelAnimationFrame() {},
    });
    function key(role, value) {
        const event = new Event('keydown', {cancelable: true});
        Object.defineProperty(event, 'key', {value});
        tabs[roles.indexOf(role)].dispatchEvent(event);
        return event;
    }
    return {tabs, panels, prompt, suspended, key,
        click: role => tabs[roles.indexOf(role)].dispatchEvent(new Event('click')),
        dispose: () => {controller.abort(); cleanups.forEach(callback => callback());},
    };
}

test('review tabs select the assigned stage and pause hidden-stage recording without resetting drafts', () => {
    const h = harness('ed');
    assert.deepEqual(h.panels.map(panel => panel.hidden), [true, false, true]);
    assert.equal(h.tabs[1].attributes['aria-selected'], 'true');
    h.suspended.length = 0;
    h.panels[1].draft = 'Unsent reviewer text';
    h.click('cad');
    assert.equal(h.panels[1].draft, 'Unsent reviewer text');
    assert.deepEqual(h.suspended, ['ed']);
    assert.deepEqual(h.panels.map(panel => panel.hidden), [false, true, true]);
    h.dispose();
});

test('Admin must explicitly choose a tab; arrow, Home and End navigation move focus and selection', () => {
    const h = harness('');
    assert.ok(h.panels.every(panel => panel.hidden));
    assert.equal(h.prompt.hidden, false);
    h.click('cad');
    assert.equal(h.prompt.hidden, true);
    assert.equal(h.key('cad', 'ArrowLeft').defaultPrevented, true);
    assert.equal(h.tabs[2].attributes['aria-selected'], 'true');
    assert.equal(h.tabs[2].focused, true);
    h.key('md', 'Home');
    assert.equal(h.tabs[0].attributes['aria-selected'], 'true');
    h.key('cad', 'End');
    assert.equal(h.tabs[2].tabIndex, 0);
    assert.equal(h.tabs[0].tabIndex, -1);
    h.dispose();
});

test('leaving the page disposes tab listeners so they cannot affect a later review', () => {
    const h = harness('cad');
    h.dispose(); h.click('md');
    assert.equal(h.tabs[0].attributes['aria-selected'], 'true');
    assert.equal(h.panels[2].hidden, true);
});
